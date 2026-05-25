#!/usr/bin/env python3
"""
KineticPulse - YOLOv8 fall-posture detector training.

Loads hyperparameters from configs/train.yaml and trains a YOLOv8 model on
the unified 3-class merged dataset at dataset/_merged/data.yaml.

Typical usage:
    python scripts/train.py
    python scripts/train.py --model yolov8n.pt --epochs 50
    python scripts/train.py --config configs/train.yaml --name kp_v2
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Any, Dict

# Force UTF-8 stdout/stderr on Windows consoles (cp949 / cp1252 default).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "configs" / "train.yaml"


def load_config(path: Path) -> Dict[str, Any]:
    import yaml
    if not path.exists():
        raise FileNotFoundError(f"Training config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Train a YOLOv8 fall-posture detector for KineticPulse.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                   help="Path to training YAML config.")
    p.add_argument("--model", type=str, default=None,
                   help="Base weights override (e.g. yolov8n.pt, yolov8s.pt, yolov8m.pt).")
    p.add_argument("--data", type=Path, default=None,
                   help="Dataset YAML override.")
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--batch", type=int, default=None,
                   help="Batch size. Use 0 for Ultralytics auto-batch.")
    p.add_argument("--imgsz", type=int, default=None)
    p.add_argument("--device", type=str, default=None,
                   help='Device override: "cpu", "0", "0,1", or "" for auto.')
    p.add_argument("--name", type=str, default=None, help="Run name.")
    p.add_argument("--project", type=str, default=None, help="Output parent dir.")
    p.add_argument("--resume", action="store_true",
                   help="Resume the latest run with the same name.")
    return p.parse_args()


def merge_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    overrides = {
        "model": args.model,
        "data": str(args.data) if args.data else None,
        "epochs": args.epochs,
        "batch": args.batch,
        "imgsz": args.imgsz,
        "device": args.device,
        "name": args.name,
        "project": args.project,
    }
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v
    if args.resume:
        cfg["resume"] = True
    return cfg


def resolve_paths(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve relative paths against the repo root so train.py works from any CWD."""
    for key in ("data", "project"):
        if key in cfg and cfg[key]:
            p = Path(cfg[key])
            if not p.is_absolute():
                cfg[key] = str((REPO_ROOT / p).resolve())
    return cfg


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    cfg = merge_overrides(cfg, args)
    cfg = resolve_paths(cfg)

    model_name = cfg.pop("model", "yolov8s.pt")

    print("=" * 64)
    print("KineticPulse - YOLOv8 training")
    print("=" * 64)
    print(f"Config       : {args.config}")
    print(f"Base model   : {model_name}")
    print(f"Dataset      : {cfg.get('data')}")
    print(f"Epochs       : {cfg.get('epochs')}")
    print(f"Image size   : {cfg.get('imgsz')}")
    print(f"Batch        : {cfg.get('batch')}")
    print(f"Device       : {cfg.get('device') or 'auto'}")
    print(f"Project/name : {cfg.get('project')}/{cfg.get('name')}")
    print("=" * 64)

    try:
        from ultralytics import YOLO
    except ImportError as e:
        print("[error] ultralytics not installed. Run: pip install -r requirements.txt",
              file=sys.stderr)
        raise SystemExit(2) from e

    model = YOLO(model_name)
    results = model.train(**cfg)

    save_dir = getattr(results, "save_dir", None)
    if save_dir:
        best = Path(save_dir) / "weights" / "best.pt"
        print()
        print("=" * 64)
        print("Training complete.")
        print(f"  Best weights : {best}")
        print(f"  Run folder   : {save_dir}")
        print()
        print("Next steps:")
        print(f"  python scripts/eval.py --weights {best}")
        print(f"  python scripts/export.py --weights {best} --format onnx")
        print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
