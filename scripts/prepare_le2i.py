#!/usr/bin/env python3
"""
Turn the Le2i / ImViA fall dataset into YOLO frames in the KineticPulse schema.

Why: our detector's weak class is `falling` (val recall ~0.69) because the
merged dataset has few mid-fall frames. Le2i annotates, per video, the frame
the fall starts and the frame it ends, plus a bounding box on every frame - so
the mid-fall window can be cut out and labelled automatically.

Source (dataset/FallDataset.zip -> nested per-scene zips):

    <scene>/Annotation_files/video (i).txt
        line 1          : first frame of the fall  (0 = no fall in this video)
        line 2          : last frame of the fall
        rest, per frame : frame,code,x1,y1,x2,y2   (absolute px, 1-based frame)
    <scene>/Videos/video (i).avi   (or <scene>/video (i).avi)

Labelling:

    frame <  start                      -> stand
    inside the fall window, 10%..60%    -> falling
    end   <  frame <= end+W             -> fallen

Le2i's fall window runs from "starts to lose balance" to "has come to rest",
so only its first part is a real mid-fall transition. Filmstrips of
Coffee_room_01 video (6) and video (19) show the subject already flat on the
floor from ~60% of the window onward, and still upright at 0%. Labelling the
whole window `falling` would feed the detector `fallen`-looking frames under
the `falling` class - the exact noise this dataset is meant to fix. The
ambiguous 60..100% tail is dropped rather than guessed.

Videos with no fall (0/0) are skipped entirely: their ADL content includes
sitting down and lying on furniture, which is exactly the label noise the
merge policy drops elsewhere (see dataset/README.md).

Output (already in the unified 4-class schema, so merge_datasets.py uses an
identity remap):

    dataset/le2i fall detection/train/{images,labels}/

Usage:
    python scripts/prepare_le2i.py dataset/FallDataset.zip --dry-run
    python scripts/prepare_le2i.py dataset/FallDataset.zip
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2

OUT_DIR_NAME = "le2i fall detection"
# Must match UNIFIED_CLASSES in scripts/merge_datasets.py.
CLS = {"fallen": 0, "falling": 1, "stand": 2}
# Only these scenes ship Annotation_files; Office / Lecture_room / Coffee_room_02
# are videos only and would need manual labelling.
SCENES = ("Home_01.zip", "Home_02.zip", "Coffee_room_01.zip", "Coffee_room_02.zip")


def parse_annotation(text: str) -> Optional[Tuple[int, int, Dict[int, Tuple[int, int, int, int]]]]:
    """Return (fall_start, fall_end, {frame: (x1, y1, x2, y2)}) or None if unusable."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return None
    try:
        start, end = int(lines[0]), int(lines[1])
    except ValueError:
        return None      # a few files ship without the 2-line header
    boxes: Dict[int, Tuple[int, int, int, int]] = {}
    for ln in lines[2:]:
        parts = ln.split(",")
        if len(parts) != 6:
            continue
        try:
            frame, _code, x1, y1, x2, y2 = (int(p) for p in parts)
        except ValueError:
            continue
        if x2 <= x1 or y2 <= y1:
            continue     # person not in frame
        boxes[frame] = (x1, y1, x2, y2)
    return start, end, boxes


def wanted_frames(
    start: int, end: int, boxes: Dict[int, Tuple[int, int, int, int]], args: argparse.Namespace
) -> Dict[int, str]:
    """Map frame number -> class name for the frames worth extracting."""
    picks: Dict[int, str] = {}
    span = max(1, end - start)
    lo = start + round(args.falling_lo * span)
    hi = start + round(args.falling_hi * span)
    for f in range(lo, hi + 1):
        if f in boxes and (f - lo) % args.falling_stride == 0:
            picks[f] = "falling"
    for f in range(end + 1, end + 1 + args.fallen_window):
        if f in boxes and (f - end) % args.fallen_stride == 0:
            picks[f] = "fallen"
    stand = [f for f in range(1, start) if f in boxes and f % args.stand_stride == 0]
    for f in stand[: args.max_stand_per_video]:
        picks[f] = "stand"
    return picks


def yolo_line(cls_name: str, box: Tuple[int, int, int, int], w: int, h: int) -> Optional[str]:
    x1, y1, x2, y2 = box
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
    bw, bh = (x2 - x1) / w, (y2 - y1) / h
    return f"{CLS[cls_name]} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def extract_video(
    video: Path, picks: Dict[int, str], boxes: Dict[int, Tuple[int, int, int, int]],
    stem: str, out_img: Path, out_lbl: Path, counts: Counter, dry_run: bool,
) -> None:
    """Sequentially decode ``video`` and write the frames named in ``picks``."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"[warn] cannot open {video}", file=sys.stderr)
        return
    last = max(picks) if picks else 0
    frame_no = 0
    try:
        while frame_no < last:
            ok, frame = cap.read()
            if not ok:
                break
            frame_no += 1           # annotations are 1-based
            cls_name = picks.get(frame_no)
            if cls_name is None:
                continue
            h, w = frame.shape[:2]
            line = yolo_line(cls_name, boxes[frame_no], w, h)
            if line is None:
                continue
            counts[cls_name] += 1
            if dry_run:
                continue
            name = f"{stem}_f{frame_no:05d}"
            cv2.imwrite(str(out_img / f"{name}.jpg"), frame)
            (out_lbl / f"{name}.txt").write_text(line + "\n", encoding="utf-8")
    finally:
        cap.release()


def find_video(scene_dir: Path, index_name: str) -> Optional[Path]:
    """Le2i puts videos either in <scene>/Videos/ or directly in <scene>/."""
    for cand in scene_dir.rglob(f"{index_name}.avi"):
        return cand
    return None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("zip_path", type=Path, help="Le2i FallDataset.zip")
    p.add_argument("--out", type=Path, default=None,
                   help=f"Output dir (default: <zip parent>/{OUT_DIR_NAME}).")
    p.add_argument("--falling-stride", type=int, default=2,
                   help="Keep every Nth mid-fall frame (default: 2; this is the scarce class).")
    p.add_argument("--falling-lo", type=float, default=0.10,
                   help="Start of the usable mid-fall window, as a fraction of "
                        "Le2i's fall window (default: 0.10 - before this the subject is upright).")
    p.add_argument("--falling-hi", type=float, default=0.60,
                   help="End of the usable mid-fall window (default: 0.60 - after this the "
                        "subject is already on the floor). Re-check with a filmstrip if changed.")
    p.add_argument("--fallen-stride", type=int, default=8, help="Keep every Nth post-fall frame.")
    p.add_argument("--fallen-window", type=int, default=40,
                   help="Frames after the fall ends to treat as `fallen` (25 fps; default 40).")
    p.add_argument("--stand-stride", type=int, default=30, help="Keep every Nth pre-fall frame.")
    p.add_argument("--max-stand-per-video", type=int, default=4,
                   help="Cap on pre-fall frames per video (we already have plenty of stand).")
    p.add_argument("--dry-run", action="store_true", help="Report counts without writing frames.")
    args = p.parse_args(argv)

    if not args.zip_path.exists():
        print(f"[error] zip not found: {args.zip_path}", file=sys.stderr)
        return 2
    out_root = (args.out or (args.zip_path.parent / OUT_DIR_NAME)) / "train"
    out_img, out_lbl = out_root / "images", out_root / "labels"
    if not args.dry_run:
        out_img.mkdir(parents=True, exist_ok=True)
        out_lbl.mkdir(parents=True, exist_ok=True)

    counts: Counter = Counter()
    videos_used = skipped_nofall = skipped_bad = 0

    with zipfile.ZipFile(args.zip_path) as outer:
        available = set(outer.namelist())
        for scene_zip in SCENES:
            if scene_zip not in available:
                print(f"[warn] {scene_zip} not in archive; skipping", file=sys.stderr)
                continue
            inner = zipfile.ZipFile(io.BytesIO(outer.read(scene_zip)))
            anns = [n for n in inner.namelist()
                    if "Annotation_files/" in n and n.lower().endswith(".txt")]
            if not anns:
                print(f"[warn] {scene_zip} has no Annotation_files; skipping", file=sys.stderr)
                continue

            # cv2 needs real files, so unpack this scene to a temp dir and drop it after.
            tmp = Path(tempfile.mkdtemp(prefix="le2i_"))
            try:
                inner.extractall(tmp)
                scene = scene_zip[:-4]
                for ann in sorted(anns):
                    parsed = parse_annotation(inner.read(ann).decode("latin-1"))
                    if parsed is None:
                        skipped_bad += 1
                        continue
                    start, end, boxes = parsed
                    if start <= 0 or end < start:
                        skipped_nofall += 1
                        continue
                    index_name = Path(ann).stem            # e.g. "video (12)"
                    video = find_video(tmp, index_name)
                    if video is None:
                        skipped_bad += 1
                        continue
                    picks = wanted_frames(start, end, boxes, args)
                    if not picks:
                        continue
                    stem = f"{scene}_{index_name}".replace(" ", "").replace("(", "").replace(")", "")
                    extract_video(video, picks, boxes, stem, out_img, out_lbl, counts, args.dry_run)
                    videos_used += 1
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            print(f"  {scene_zip}: done ({sum(counts.values())} frames so far)")

    print()
    print(f"{'[dry-run] ' if args.dry_run else ''}Le2i -> {out_root}")
    print(f"  videos used      : {videos_used}")
    print(f"  skipped (no fall): {skipped_nofall}")
    print(f"  skipped (bad/missing): {skipped_bad}")
    for name in ("falling", "fallen", "stand"):
        print(f"  {name:<8s} {counts.get(name, 0)}")
    if not counts:
        print("[error] nothing extracted - unexpected archive layout", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
