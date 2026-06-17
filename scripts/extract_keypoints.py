"""Extract COCO-17 keypoint sequences from videos -> labelled .npz clips.

This is the offline counterpart to ``live_predict.py --record``: it lets
you turn pre-recorded fall / sitting / stand-up footage into the same
clip format the temporal trainer consumes, without sitting in front of
a webcam.

Output layout (compatible with ``--record`` and ``train_temporal.py``)::

    <out_dir>/<label>/<source-stem>__<chunk_idx>.npz

Each ``.npz`` payload mirrors the live recorder:

* ``keypoints``   - float32, shape ``(T, 17, 3)`` (raw COCO-17 + score)
* ``label``       - 0-d unicode array, one of ``fallen / falling / stand / sitting``
* ``fps``         - float32 scalar (source video FPS, post-stride)
* ``image_size``  - int32 ``(W, H)``
* ``video_path``  - 0-d unicode array (provenance)

Two ways to label your videos
=============================

1. **Folder convention** (recommended) - the *immediate parent folder*
   of each video file is the label. Drop your clips into a tree like::

       data/raw_clips/
         fallen/   *.mp4
         falling/  *.mp4
         stand/    *.mp4
         sitting/  *.mp4

   then run ``python scripts/extract_keypoints.py --input data/raw_clips``.

2. **Single label override** - pass ``--label sitting`` to apply that
   label to every video discovered under ``--input`` (a single file or
   a flat folder of clips that all show the same posture).

Examples
========

::

    # Folder-of-folders, auto label:
    python scripts/extract_keypoints.py \
        --input data/raw_clips \
        --out   dataset/temporal_clips

    # Single file with explicit label:
    python scripts/extract_keypoints.py \
        --input data/raw_clips/sit_demo.mp4 \
        --label sitting

    # Long video chopped into 30-frame, 15-frame-overlap clips:
    python scripts/extract_keypoints.py \
        --input data/raw_clips/long_session.mp4 \
        --label stand --clip-window 30 --clip-overlap 15
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
VALID_LABELS = ("fallen", "falling", "stand", "sitting")


def _is_video(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in VIDEO_EXTS


def enumerate_videos(input_path: Path,
                     forced_label: Optional[str]) -> List[Tuple[Path, str]]:
    """Discover videos under ``input_path`` and pair each with its label.

    Returns ``[(video_path, label), ...]``. Raises ``ValueError`` for
    unlabelable files (e.g. video sitting at the root of a directory
    without ``--label``).
    """
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    pairs: List[Tuple[Path, str]] = []

    if input_path.is_file():
        if not _is_video(input_path):
            raise ValueError(f"{input_path} does not look like a video file")
        if forced_label is None:
            raise ValueError(
                "Single-file input requires --label. "
                "Pass e.g. --label sitting."
            )
        pairs.append((input_path, forced_label))
        return pairs

    # Directory mode.
    if forced_label is not None:
        for vid in sorted(input_path.rglob("*")):
            if _is_video(vid):
                pairs.append((vid, forced_label))
        return pairs

    # Folder convention: <input>/<label>/<file>.mp4
    for label_dir in sorted(p for p in input_path.iterdir() if p.is_dir()):
        label = label_dir.name.lower()
        if label not in VALID_LABELS:
            print(f"[skip] '{label_dir.name}' is not in {VALID_LABELS}; "
                  f"pass --label to override.")
            continue
        for vid in sorted(label_dir.rglob("*")):
            if _is_video(vid):
                pairs.append((vid, label))
    return pairs


def extract_keypoint_sequence(pose_model, video_path: Path, *, imgsz: int,
                              conf: float, stride: int,
                              max_frames: Optional[int]
                              ) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """Run YOLOv8-pose over ``video_path`` and return ``(seq, fps, (w, h))``.

    Frames where pose detection fails produce a zero-confidence row so
    that downstream length / windowing logic stays predictable. The
    consumer (``train_temporal.py``) drops zero-confidence rows when
    needed.
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video {video_path}")

    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width == 0 or height == 0:
        # Some containers report 0 until the first read.
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            raise RuntimeError(f"empty video {video_path}")
        height, width = frame.shape[:2]
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    seq: List[np.ndarray] = []
    frame_idx = -1
    kept = 0
    missed = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame_idx += 1
            if stride > 1 and (frame_idx % stride) != 0:
                continue
            if max_frames is not None and kept >= max_frames:
                break

            res = pose_model.predict(
                source=frame, imgsz=imgsz, conf=conf, verbose=False,
            )
            r0 = res[0] if res else None
            if (r0 is not None and r0.keypoints is not None
                    and r0.keypoints.data is not None
                    and len(r0.keypoints.data) > 0):
                kp_data = r0.keypoints.data.cpu().numpy()  # (P, 17, 3)
                if r0.boxes is not None and r0.boxes.conf is not None:
                    confs = r0.boxes.conf.cpu().numpy()
                    idx = int(confs.argmax())
                else:
                    idx = 0
                seq.append(kp_data[idx].astype(np.float32))
            else:
                seq.append(np.zeros((17, 3), dtype=np.float32))
                missed += 1
            kept += 1
    finally:
        cap.release()

    if not seq:
        raise RuntimeError(f"no frames decoded from {video_path}")

    seq_arr = np.stack(seq, axis=0)
    effective_fps = src_fps / max(1, stride)
    print(f"  -> {kept} frames kept, {missed} with no pose "
          f"(src fps={src_fps:.1f}, eff fps={effective_fps:.1f})")
    return seq_arr, effective_fps, (width, height)


def chunk_clip(seq: np.ndarray, window: int, overlap: int
               ) -> Iterable[Tuple[int, np.ndarray]]:
    """Yield ``(chunk_idx, sub_clip)`` slices along the time axis."""
    if window <= 0 or seq.shape[0] <= window:
        yield 0, seq
        return
    step = max(1, window - overlap)
    idx = 0
    for start in range(0, seq.shape[0] - window + 1, step):
        yield idx, seq[start:start + window]
        idx += 1


def save_npz(out_root: Path, label: str, source_path: Path, chunk_idx: int,
             seq: np.ndarray, fps: float, image_size: Tuple[int, int]) -> Path:
    out_dir = out_root / label
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{source_path.stem}__{chunk_idx:03d}.npz"
    out_path = out_dir / name
    np.savez_compressed(
        out_path,
        keypoints=np.asarray(seq, dtype=np.float32),
        label=np.asarray(label),
        fps=np.asarray(float(fps), dtype=np.float32),
        image_size=np.asarray(image_size, dtype=np.int32),
        video_path=np.asarray(str(source_path)),
    )
    return out_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", type=Path, required=True,
                   help="Video file, or directory of videos / labelled subdirs.")
    p.add_argument("--out", type=Path,
                   default=REPO_ROOT / "dataset" / "temporal_clips",
                   help="Where to write <label>/*.npz clips.")
    p.add_argument("--label", choices=VALID_LABELS, default=None,
                   help="Force every input video to this label. "
                        "Otherwise the immediate parent-folder name is used.")
    p.add_argument("--pose-weights", type=str, default="yolov8s-pose.pt",
                   help="YOLOv8 pose checkpoint. Auto-downloads on first use.")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--device", type=str, default="",
                   help='Device override: "cpu", "0", or "" for auto.')
    p.add_argument("--stride", type=int, default=1,
                   help="Process every Nth source frame (downsamples FPS).")
    p.add_argument("--max-frames", type=int, default=0,
                   help="Cap per-video frame count (0 = unlimited).")
    p.add_argument("--min-frames", type=int, default=12,
                   help="Skip clips shorter than this many kept frames.")
    p.add_argument("--clip-window", type=int, default=0,
                   help="If > 0, split each sequence into windows of this "
                        "many frames before saving. 0 = save whole clip.")
    p.add_argument("--clip-overlap", type=int, default=0,
                   help="Frames of overlap between successive windows.")
    p.add_argument("--dry-run", action="store_true",
                   help="Discover and process videos but do not write npz.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[error] ultralytics not installed: pip install ultralytics",
              file=sys.stderr)
        return 2

    videos = enumerate_videos(args.input.resolve(), args.label)
    if not videos:
        print(f"[error] no videos discovered under {args.input}", file=sys.stderr)
        return 1

    print(f"Discovered {len(videos)} videos.")
    label_counts: dict = {}
    for _, lbl in videos:
        label_counts[lbl] = label_counts.get(lbl, 0) + 1
    for lbl in VALID_LABELS:
        n = label_counts.get(lbl, 0)
        if n:
            print(f"  {lbl:<8s}  {n:4d}")

    print(f"Loading pose model: {args.pose_weights}")
    pose = YOLO(args.pose_weights)
    if args.device:
        try:
            pose.to(args.device)
        except Exception as exc:
            print(f"[warn] could not move pose model to {args.device!r}: {exc}")

    out_root = args.out.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    saved = 0
    skipped = 0
    t0 = time.monotonic()

    for vp, label in videos:
        print(f"[{label}] {vp}")
        try:
            seq, fps, (w, h) = extract_keypoint_sequence(
                pose, vp,
                imgsz=args.imgsz, conf=args.conf,
                stride=args.stride,
                max_frames=(args.max_frames or None),
            )
        except Exception as exc:
            print(f"  ERROR: {exc}")
            skipped += 1
            continue

        if seq.shape[0] < args.min_frames:
            print(f"  too short ({seq.shape[0]} < {args.min_frames}); skipped.")
            skipped += 1
            continue

        for chunk_idx, sub in chunk_clip(seq, args.clip_window, args.clip_overlap):
            if sub.shape[0] < args.min_frames:
                continue
            if args.dry_run:
                print(f"  [dry] would save chunk {chunk_idx} "
                      f"shape={sub.shape} fps={fps:.1f}")
                continue
            out_path = save_npz(out_root, label, vp, chunk_idx, sub, fps, (w, h))
            try:
                rel = out_path.relative_to(REPO_ROOT)
            except ValueError:
                rel = out_path
            print(f"  saved {rel}")
            saved += 1

    dt = time.monotonic() - t0
    print(f"\nDone in {dt:.1f}s. saved={saved} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
