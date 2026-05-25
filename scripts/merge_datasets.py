#!/usr/bin/env python3
"""
KineticPulse — Merge fall-detection datasets into a unified 3-class schema.

Unified classes (Option A, safe remap):
    0 = fallen
    1 = falling
    2 = stand

Sources:
    Primary    : dataset/fall detection.v1i.yolov8        (train + valid + test, CC BY 4.0)
    Secondary 1: dataset/Fall Detection.yolov8            (train only)
    Secondary 2: dataset/fallen detection.yolov8          (train only)

Remap policy (decided in chat with rationale documented in dataset/README.md):

    Primary (['fallen', 'falling', 'stand'])
        fallen     -> fallen
        falling    -> falling
        stand      -> stand

    Secondary 1 (['bending', 'fallen', 'falling', 'standing'])
        bending    -> DROP   (label + image)
        fallen     -> fallen
        falling    -> falling
        standing   -> stand

    Secondary 2 (['fall_down', 'lying_down', 'sitting', 'standing'])
        fall_down  -> fallen     (sample paths printed for spot-check)
        lying_down -> DROP       (couch/bed contamination risk)
        sitting    -> DROP
        standing   -> stand

Output:
    dataset/_merged/
        train/{images,labels}/
        valid/{images,labels}/    (primary only)
        test/{images,labels}/     (primary only)
        data.yaml

Usage:
    python scripts/merge_datasets.py            # write merged dataset
    python scripts/merge_datasets.py --dry-run  # report only, no writes
    python scripts/merge_datasets.py --no-dedupe

Optional dependency:
    pip install pillow      # enables dHash near-duplicate removal across train set
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys

# Force UTF-8 stdout/stderr on Windows consoles where the default codepage
# (e.g. cp949) can't render report characters.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
elif isinstance(getattr(sys, "stdout", None), io.TextIOWrapper):  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


UNIFIED_CLASSES: List[str] = ["fallen", "falling", "stand"]
UNIFIED_IDX: Dict[str, int] = {name: i for i, name in enumerate(UNIFIED_CLASSES)}

# None in the remap value = DROP this label.
# If, after remapping, an image has zero surviving labels, the image is also dropped.
REMAPS: Dict[str, Dict[int, Optional[str]]] = {
    "fall detection.v1i.yolov8": {
        0: "fallen",
        1: "falling",
        2: "stand",
    },
    "Fall Detection.yolov8": {
        0: None,        # bending
        1: "fallen",
        2: "falling",
        3: "stand",
    },
    "fallen detection.yolov8": {
        0: "fallen",    # fall_down (spot-check; flip to "falling" if mid-air)
        1: None,        # lying_down
        2: None,        # sitting
        3: "stand",
    },
}

DATASET_TAGS: Dict[str, str] = {
    "fall detection.v1i.yolov8": "p1",
    "Fall Detection.yolov8":     "s1",
    "fallen detection.yolov8":   "s2",
}

DATASETS: List[Tuple[str, str]] = [
    ("fall detection.v1i.yolov8", "primary"),
    ("Fall Detection.yolov8",     "secondary"),
    ("fallen detection.yolov8",   "secondary"),
]

FALL_DOWN_DATASET = "fallen detection.yolov8"
FALL_DOWN_LOCAL_IDX = 0

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


@dataclass
class MergeStats:
    images_seen: int = 0
    images_kept: int = 0
    images_dropped_no_labels: int = 0
    duplicates_removed: int = 0
    labels_remapped: int = 0
    labels_dropped: int = 0
    per_class_count: Counter = field(default_factory=Counter)
    per_split_image_count: Counter = field(default_factory=Counter)
    per_dataset_image_count: Counter = field(default_factory=Counter)


def find_image_for_label(label_path: Path, images_dir: Path) -> Optional[Path]:
    stem = label_path.stem
    for ext in IMG_EXTS:
        cand = images_dir / f"{stem}{ext}"
        if cand.exists():
            return cand
    return None


def parse_and_remap(
    src_label: Path,
    remap: Dict[int, Optional[str]],
) -> Tuple[List[Tuple[int, str, List[str]]], int, bool]:
    """
    Parse a YOLO label file and apply the remap.

    Returns:
        survivors          : list of (new_idx, target_name, rest_parts)
        dropped_label_count: number of label lines dropped by the remap
        has_fall_down      : True if any line referenced FALL_DOWN_LOCAL_IDX
                             (caller decides whether this is meaningful)
    """
    survivors: List[Tuple[int, str, List[str]]] = []
    dropped = 0
    has_fall_down = False
    with src_label.open("r", encoding="utf-8") as f:
        for raw in f:
            parts = raw.strip().split()
            if not parts:
                continue
            try:
                local_idx = int(parts[0])
            except ValueError:
                continue
            target = remap.get(local_idx, None)
            if local_idx == FALL_DOWN_LOCAL_IDX:
                has_fall_down = True
            if target is None:
                dropped += 1
                continue
            survivors.append((UNIFIED_IDX[target], target, parts[1:]))
    return survivors, dropped, has_fall_down


def dhash_hex(image_path: Path, size: int = 8) -> Optional[str]:
    if not PIL_AVAILABLE:
        return None
    try:
        with Image.open(image_path) as im:
            small = im.convert("L").resize((size + 1, size))
        px = small.load()
        bits = 0
        for y in range(size):
            for x in range(size):
                bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
        return f"{bits:0{(size * size) // 4}x}"
    except Exception:
        return None


def process_split(
    *,
    dataset_dir: Path,
    dataset_name: str,
    split: str,
    out_root: Path,
    remap: Dict[int, Optional[str]],
    tag: str,
    stats: MergeStats,
    seen_hashes: Dict[str, Path],
    fall_down_samples: List[Path],
    dedupe: bool,
    dry_run: bool,
) -> None:
    img_dir = dataset_dir / split / "images"
    lbl_dir = dataset_dir / split / "labels"
    if not img_dir.exists() or not lbl_dir.exists():
        return

    out_img_dir = out_root / split / "images"
    out_lbl_dir = out_root / split / "labels"

    for lbl_path in sorted(lbl_dir.glob("*.txt")):
        img_path = find_image_for_label(lbl_path, img_dir)
        if img_path is None:
            continue
        stats.images_seen += 1

        survivors, dropped_count, has_fall_down = parse_and_remap(lbl_path, remap)
        stats.labels_dropped += dropped_count

        if not survivors:
            stats.images_dropped_no_labels += 1
            continue

        # Only dedupe inside the train split to keep valid/test untouched
        if dedupe and split == "train":
            h = dhash_hex(img_path)
            if h is not None:
                if h in seen_hashes:
                    stats.duplicates_removed += 1
                    continue
                seen_hashes[h] = img_path

        # Commit: count labels and (if not dry-run) write outputs
        for _, target, _ in survivors:
            stats.labels_remapped += 1
            stats.per_class_count[target] += 1

        stats.images_kept += 1
        stats.per_split_image_count[split] += 1
        stats.per_dataset_image_count[dataset_name] += 1

        if has_fall_down and dataset_name == FALL_DOWN_DATASET:
            fall_down_samples.append(img_path)

        if dry_run:
            continue

        new_stem = f"{tag}__{img_path.stem}"
        dst_lbl = out_lbl_dir / f"{new_stem}.txt"
        dst_img = out_img_dir / f"{new_stem}{img_path.suffix}"
        dst_lbl.parent.mkdir(parents=True, exist_ok=True)
        dst_img.parent.mkdir(parents=True, exist_ok=True)

        with dst_lbl.open("w", encoding="utf-8") as f:
            for new_idx, _, rest in survivors:
                f.write(" ".join([str(new_idx)] + rest) + "\n")
        shutil.copy2(img_path, dst_img)


def write_data_yaml(out_root: Path) -> None:
    data_yaml = out_root / "data.yaml"
    names_list = "[" + ", ".join(f"'{n}'" for n in UNIFIED_CLASSES) + "]"
    data_yaml.write_text(
        "train: ./train/images\n"
        "val: ./valid/images\n"
        "test: ./test/images\n"
        "\n"
        f"nc: {len(UNIFIED_CLASSES)}\n"
        f"names: {names_list}\n"
        "\n"
        "# Generated by scripts/merge_datasets.py\n"
        "# Unified schema: 0=fallen, 1=falling, 2=stand\n",
        encoding="utf-8",
    )


def print_report(
    args: argparse.Namespace,
    out_root: Path,
    stats: MergeStats,
    fall_down_samples: List[Path],
) -> None:
    line = "=" * 64
    print()
    print(line)
    print("KineticPulse dataset merge - report")
    print(line)
    print(f"Mode                   : {'DRY RUN' if args.dry_run else 'WRITE'}")
    dedupe_state = "enabled" if (not args.no_dedupe and PIL_AVAILABLE) else "disabled"
    if not args.no_dedupe and not PIL_AVAILABLE:
        dedupe_state += " (install pillow to enable)"
    print(f"Dedupe (dHash, train)  : {dedupe_state}")
    print(f"Output                 : {out_root}")
    print()
    print(f"Images seen            : {stats.images_seen}")
    print(f"Images kept            : {stats.images_kept}")
    print(f"  (all labels dropped) : {stats.images_dropped_no_labels}")
    print(f"  (deduplicated)       : {stats.duplicates_removed}")
    print(f"Labels remapped        : {stats.labels_remapped}")
    print(f"Labels dropped         : {stats.labels_dropped}")
    print()
    print("Per-split image counts:")
    for split in ("train", "valid", "test"):
        print(f"  {split:<6s} {stats.per_split_image_count.get(split, 0)}")
    print()
    print("Per-dataset image contribution:")
    for ds_name, _ in DATASETS:
        print(f"  {ds_name:<35s} {stats.per_dataset_image_count.get(ds_name, 0)}")
    print()
    print("Per-class label counts (all splits combined):")
    total = sum(stats.per_class_count.values()) or 1
    for name in UNIFIED_CLASSES:
        n = stats.per_class_count.get(name, 0)
        pct = 100.0 * n / total
        print(f"  {name:<10s} {n:>6d}  ({pct:5.1f}%)")
    print()
    if fall_down_samples:
        n_show = min(args.fall_down_samples, len(fall_down_samples))
        print(f"`fall_down` spot-check — first {n_show} of {len(fall_down_samples)} sample paths:")
        for p in fall_down_samples[:n_show]:
            print(f"  {p}")
        print()
        print("  Open a few of these. If they look mid-air / mid-collapse,")
        print("  edit REMAPS['fallen detection.yolov8'][0] from 'fallen' to 'falling'")
        print("  and re-run this script.")
        print()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge KineticPulse fall-detection datasets into a unified 3-class schema.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent,
        help="Repository root (default: parent of scripts/).",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Output directory (default: <root>/dataset/_merged).",
    )
    parser.add_argument(
        "--no-dedupe", action="store_true",
        help="Disable dHash near-duplicate removal across the merged train set.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would happen without writing files.",
    )
    parser.add_argument(
        "--fall-down-samples", type=int, default=20,
        help="Number of `fall_down` sample paths to print for spot-checking (default: 20).",
    )
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    dataset_root = root / "dataset"
    out_root = (args.out or (dataset_root / "_merged")).resolve()

    if not dataset_root.exists():
        print(f"[error] dataset root not found: {dataset_root}", file=sys.stderr)
        return 2

    if not args.dry_run:
        if out_root.exists():
            shutil.rmtree(out_root)
        for split in ("train", "valid", "test"):
            (out_root / split / "images").mkdir(parents=True, exist_ok=True)
            (out_root / split / "labels").mkdir(parents=True, exist_ok=True)

    stats = MergeStats()
    seen_hashes: Dict[str, Path] = {}
    fall_down_samples: List[Path] = []
    dedupe = (not args.no_dedupe) and PIL_AVAILABLE

    if not args.no_dedupe and not PIL_AVAILABLE:
        print("[warn] Pillow not installed; dHash dedupe disabled. "
              "Install with: pip install pillow", file=sys.stderr)

    for ds_name, role in DATASETS:
        ds_dir = dataset_root / ds_name
        if not ds_dir.exists():
            print(f"[warn] dataset missing, skipping: {ds_name}", file=sys.stderr)
            continue
        if ds_name not in REMAPS:
            print(f"[warn] no remap defined for: {ds_name}", file=sys.stderr)
            continue
        remap = REMAPS[ds_name]
        tag = DATASET_TAGS[ds_name]
        splits = ("train", "valid", "test") if role == "primary" else ("train",)
        for split in splits:
            process_split(
                dataset_dir=ds_dir,
                dataset_name=ds_name,
                split=split,
                out_root=out_root,
                remap=remap,
                tag=tag,
                stats=stats,
                seen_hashes=seen_hashes,
                fall_down_samples=fall_down_samples,
                dedupe=dedupe,
                dry_run=args.dry_run,
            )

    if not args.dry_run:
        write_data_yaml(out_root)

    print_report(args, out_root, stats, fall_down_samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
