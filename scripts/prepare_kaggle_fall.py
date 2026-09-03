#!/usr/bin/env python3
"""
Restructure the Kaggle fall-detection dataset into the layout merge_datasets.py expects.

Source (Kaggle "uttejkumarkandagatla/fall-detection-dataset", downloaded as a zip):

    fall_dataset/images/{train,val}/*.jpg|png
    fall_dataset/labels/{train,val}/*.txt      # 0=Fall Detected, 1=Walking, 2=Sitting

Target:

    dataset/kaggle fall detection/train/images/
    dataset/kaggle fall detection/train/labels/

Only ``train`` is extracted: every one of the 111 ``val`` stems also appears in
``train``, so the val split is redundant. This dataset feeds the merged train
split only - Primary owns valid/test (see dataset/README.md).

Usage:
    python scripts/prepare_kaggle_fall.py "dataset/archive (1).zip"
    python scripts/prepare_kaggle_fall.py "dataset/archive (1).zip" --dry-run
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections import Counter
from pathlib import Path

OUT_DIR_NAME = "kaggle fall detection"
SRC_CLASSES = {0: "Fall Detected", 1: "Walking", 2: "Sitting"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("zip_path", type=Path, help="Kaggle fall-detection zip.")
    p.add_argument("--out", type=Path, default=None,
                   help=f"Output dir (default: <zip parent>/{OUT_DIR_NAME}).")
    p.add_argument("--dry-run", action="store_true", help="Report only, no writes.")
    args = p.parse_args(argv)

    if not args.zip_path.exists():
        print(f"[error] zip not found: {args.zip_path}", file=sys.stderr)
        return 2
    out_root = (args.out or (args.zip_path.parent / OUT_DIR_NAME)) / "train"

    counts: Counter[str] = Counter()
    written = 0
    with zipfile.ZipFile(args.zip_path) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            parts = name.split("/")
            # fall_dataset/<images|labels>/<split>/<file>
            if len(parts) != 4 or parts[1] not in ("images", "labels") or parts[2] != "train":
                continue
            kind, filename = parts[1], parts[3]
            data = zf.read(name)
            if kind == "labels":
                for line in data.decode("utf-8").splitlines():
                    tok = line.split()
                    if tok and tok[0].isdigit():
                        counts[SRC_CLASSES.get(int(tok[0]), tok[0])] += 1
            written += 1
            if args.dry_run:
                continue
            dst = out_root / kind / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)

    print(f"{'[dry-run] ' if args.dry_run else ''}{written} files -> {out_root}")
    for cls, n in sorted(counts.items()):
        print(f"  {cls:<15s} {n}")
    if not counts:
        print("[error] no train labels found - unexpected zip layout", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
