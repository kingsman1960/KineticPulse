#!/usr/bin/env python3
"""
KineticPulse - YOLOv8 model export.

Exports trained weights to deployment formats:
  - ONNX  : always available, runs anywhere via onnxruntime.
  - TRT   : only when run on a Jetson with TensorRT installed (JetPack).

Typical usage:
    python scripts/export.py --weights runs/detect/kp_v1/weights/best.pt
    python scripts/export.py --weights ... --format onnx,engine --half
    python scripts/export.py --weights ... --format engine --imgsz 480
"""

from __future__ import annotations

import argparse
import importlib
import io
import sys
from pathlib import Path
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


SUPPORTED = {"onnx", "engine", "torchscript", "openvino", "tflite"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export a KineticPulse YOLOv8 model to deployment formats.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--weights", type=Path, required=True,
                   help="Trained weights (.pt).")
    p.add_argument("--format", type=str, default="onnx",
                   help=f"Comma-separated formats. Supported: {sorted(SUPPORTED)}")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--half", action="store_true",
                   help="FP16 export (recommended for TensorRT engine on Jetson).")
    p.add_argument("--int8", action="store_true",
                   help="INT8 quantisation (TensorRT engine; needs calibration data).")
    p.add_argument("--dynamic", action="store_true",
                   help="Dynamic shape ONNX export (variable batch / imgsz).")
    p.add_argument("--simplify", action="store_true", default=True,
                   help="Simplify ONNX graph after export.")
    p.add_argument("--opset", type=int, default=12,
                   help="ONNX opset version.")
    p.add_argument("--device", type=str, default="",
                   help='Device for export (TRT requires CUDA: "0").')
    return p.parse_args()


def split_formats(spec: str) -> List[str]:
    fmts = [f.strip().lower() for f in spec.split(",") if f.strip()]
    invalid = [f for f in fmts if f not in SUPPORTED]
    if invalid:
        raise SystemExit(f"[error] unsupported export formats: {invalid}. "
                         f"Supported: {sorted(SUPPORTED)}")
    return fmts


def tensorrt_available() -> bool:
    try:
        importlib.import_module("tensorrt")
        return True
    except ImportError:
        return False


def main() -> int:
    args = parse_args()
    if not args.weights.exists():
        print(f"[error] weights not found: {args.weights}", file=sys.stderr)
        return 2

    formats = split_formats(args.format)
    print("=" * 64)
    print("KineticPulse - export")
    print("=" * 64)
    print(f"Weights : {args.weights}")
    print(f"Formats : {formats}")
    print(f"Imgsz   : {args.imgsz}")
    print(f"FP16    : {args.half}")
    print(f"INT8    : {args.int8}")
    print(f"Dynamic : {args.dynamic}")
    print(f"Device  : {args.device or 'auto'}")
    print("=" * 64)

    try:
        from ultralytics import YOLO
    except ImportError as e:
        print("[error] ultralytics not installed. Run: pip install -r requirements.txt",
              file=sys.stderr)
        raise SystemExit(2) from e

    if "engine" in formats and not tensorrt_available():
        print("[warn] `engine` requested but `tensorrt` Python module not found. "
              "Skipping TRT export. This export must be run on the Jetson "
              "(JetPack provides TensorRT).", file=sys.stderr)
        formats = [f for f in formats if f != "engine"]
        if not formats:
            return 1

    model = YOLO(str(args.weights))
    outputs: List[Path] = []
    for fmt in formats:
        print(f"\n--- exporting: {fmt} ---")
        kwargs = dict(format=fmt, imgsz=args.imgsz, device=args.device)
        if fmt == "onnx":
            kwargs.update(opset=args.opset, simplify=args.simplify, dynamic=args.dynamic)
        if args.half:
            kwargs["half"] = True
        if args.int8 and fmt == "engine":
            kwargs["int8"] = True

        out = model.export(**kwargs)
        out_path = Path(out) if out else None
        if out_path:
            outputs.append(out_path)
            print(f"  -> {out_path}")

    print()
    print("=" * 64)
    print("Export complete.")
    for p in outputs:
        print(f"  {p}")
    if "onnx" in formats:
        print()
        print("Tip: run on the Jetson to verify TensorRT engine build:")
        print("  /usr/src/tensorrt/bin/trtexec --onnx=<file>.onnx --fp16")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
