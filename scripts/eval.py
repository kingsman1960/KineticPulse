#!/usr/bin/env python3
"""
KineticPulse - YOLOv8 fall-posture detector evaluation.

Loads trained weights and runs validation on the test split (or any split)
of the merged dataset. Prints per-class P / R / mAP50 / mAP50-95 and writes
a JSON report alongside the confusion matrix PNG produced by Ultralytics.

Typical usage:
    python scripts/eval.py --weights runs/detect/kp_v1/weights/best.pt
    python scripts/eval.py --weights ... --split val
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO_ROOT / "dataset" / "_merged" / "data.yaml"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate a trained KineticPulse YOLOv8 detector.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--weights", type=Path, required=True,
                   help="Trained weights (.pt). Usually runs/detect/<name>/weights/best.pt")
    p.add_argument("--data", type=Path, default=DEFAULT_DATA,
                   help="Dataset YAML.")
    p.add_argument("--split", choices=["train", "val", "test"], default="test",
                   help="Which split to evaluate against.")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", type=str, default="",
                   help='Device override: "cpu", "0", or "" for auto.')
    p.add_argument("--conf", type=float, default=0.001,
                   help="Confidence threshold for mAP (Ultralytics default).")
    p.add_argument("--iou", type=float, default=0.6,
                   help="IoU threshold for NMS during eval.")
    p.add_argument("--project", type=str, default="runs/detect",
                   help="Output parent dir.")
    p.add_argument("--name", type=str, default=None,
                   help="Eval run name (default: <weights_parent>/eval/<split>).")
    return p.parse_args()


def metrics_to_dict(results: Any, class_names: Dict[int, str]) -> Dict[str, Any]:
    """Extract a JSON-serialisable summary from an Ultralytics DetMetrics object."""
    out: Dict[str, Any] = {}
    try:
        box = results.box
        out["overall"] = {
            "precision_mean": float(box.mp),
            "recall_mean": float(box.mr),
            "mAP50": float(box.map50),
            "mAP50-95": float(box.map),
        }
        per_class = {}
        ap50 = box.ap50 if hasattr(box, "ap50") else None
        ap = box.ap if hasattr(box, "ap") else None
        # Per-class precision / recall: Ultralytics 8.x stores them on .p and .r
        p_arr = getattr(box, "p", None)
        r_arr = getattr(box, "r", None)
        for i, cls_id in enumerate(getattr(box, "ap_class_index", [])):
            name = class_names.get(int(cls_id), str(cls_id))
            per_class[name] = {
                "precision": float(p_arr[i]) if p_arr is not None else None,
                "recall": float(r_arr[i]) if r_arr is not None else None,
                "mAP50": float(ap50[i]) if ap50 is not None else None,
                "mAP50-95": float(ap[i].mean()) if ap is not None else None,
            }
        out["per_class"] = per_class
    except Exception as exc:
        out["error_extracting_metrics"] = repr(exc)
    return out


def main() -> int:
    args = parse_args()
    if not args.weights.exists():
        print(f"[error] weights not found: {args.weights}", file=sys.stderr)
        return 2

    eval_name = args.name or f"eval_{args.split}"
    print("=" * 64)
    print("KineticPulse - evaluation")
    print("=" * 64)
    print(f"Weights : {args.weights}")
    print(f"Data    : {args.data}")
    print(f"Split   : {args.split}")
    print(f"Imgsz   : {args.imgsz}")
    print(f"Device  : {args.device or 'auto'}")
    print("=" * 64)

    try:
        from ultralytics import YOLO
    except ImportError as e:
        print("[error] ultralytics not installed. Run: pip install -r requirements.txt",
              file=sys.stderr)
        raise SystemExit(2) from e

    model = YOLO(str(args.weights))
    results = model.val(
        data=str(args.data),
        split=args.split,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        conf=args.conf,
        iou=args.iou,
        project=args.project,
        name=eval_name,
        plots=True,
        save_json=True,
        exist_ok=True,
    )

    class_names = getattr(model, "names", {}) or {}
    summary = metrics_to_dict(results, class_names)
    save_dir = Path(getattr(results, "save_dir", Path(args.project) / eval_name))
    report_path = save_dir / "report.json"
    save_dir.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print()
    print("=" * 64)
    print("Per-class results:")
    print("=" * 64)
    print(f"{'class':<12s} {'P':>8s} {'R':>8s} {'mAP50':>8s} {'mAP50-95':>10s}")
    for name, m in summary.get("per_class", {}).items():
        print(f"{name:<12s} "
              f"{(m['precision'] or 0):>8.3f} "
              f"{(m['recall'] or 0):>8.3f} "
              f"{(m['mAP50'] or 0):>8.3f} "
              f"{(m['mAP50-95'] or 0):>10.3f}")
    o = summary.get("overall", {})
    print("-" * 50)
    print(f"{'overall':<12s} "
          f"{o.get('precision_mean', 0):>8.3f} "
          f"{o.get('recall_mean', 0):>8.3f} "
          f"{o.get('mAP50', 0):>8.3f} "
          f"{o.get('mAP50-95', 0):>10.3f}")
    print()
    print(f"Report  : {report_path}")
    cm_png = save_dir / "confusion_matrix.png"
    if cm_png.exists():
        print(f"CM PNG  : {cm_png}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
