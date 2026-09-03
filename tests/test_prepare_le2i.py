"""Le2i -> YOLO conversion rules (scripts/prepare_le2i.py)."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "prepare_le2i", REPO / "scripts" / "prepare_le2i.py"
)
prepare_le2i = importlib.util.module_from_spec(_spec)
sys.modules["prepare_le2i"] = prepare_le2i
_spec.loader.exec_module(prepare_le2i)


def _args(**over) -> argparse.Namespace:
    base = dict(falling_stride=1, falling_lo=0.10, falling_hi=0.60,
                fallen_stride=1, fallen_window=10,
                stand_stride=1, max_stand_per_video=2)
    base.update(over)
    return argparse.Namespace(**base)


def test_parse_annotation_reads_header_and_skips_empty_boxes():
    text = "144\n164\n1,1,10,20,30,40\n2,1,0,0,0,0\n3,1,11,21,31,41\n"
    start, end, boxes = prepare_le2i.parse_annotation(text)
    assert (start, end) == (144, 164)
    assert boxes == {1: (10, 20, 30, 40), 3: (11, 21, 31, 41)}


def test_parse_annotation_rejects_missing_header():
    # A few Le2i files start straight at the frame rows with no fall window.
    assert prepare_le2i.parse_annotation("1,1,10,20,30,40\n2,1,10,20,30,40\n") is None


def test_falling_uses_only_the_early_part_of_the_fall_window():
    """Le2i's window ends once the body is at rest; the tail looks `fallen`.

    Labelling the whole window `falling` is the noise this converter exists to
    avoid, so frames outside 10..60% must not be emitted as `falling`.
    """
    start, end = 100, 120                      # span 20 -> falling frames 102..112
    boxes = {f: (10, 20, 30, 40) for f in range(1, 200)}
    picks = prepare_le2i.wanted_frames(start, end, boxes, _args())
    falling = sorted(f for f, c in picks.items() if c == "falling")
    assert falling[0] == 102 and falling[-1] == 112
    assert picks.get(start) != "falling"       # still upright at 0%
    assert picks.get(end) != "falling"         # already on the floor at 100%
    assert all(picks[f] == "fallen" for f in range(end + 1, end + 11))


def test_yolo_line_normalizes_and_clamps_to_frame():
    line = prepare_le2i.yolo_line("falling", (10, 20, 110, 120), 200, 200)
    cls, cx, cy, bw, bh = line.split()
    assert cls == str(prepare_le2i.CLS["falling"])
    assert (float(cx), float(cy), float(bw), float(bh)) == (0.3, 0.35, 0.5, 0.5)
    # Boxes that run past the frame edge are clipped, not emitted raw.
    clamped = prepare_le2i.yolo_line("fallen", (-50, -50, 100, 100), 200, 200)
    assert all(0.0 <= float(v) <= 1.0 for v in clamped.split()[1:])
    assert prepare_le2i.yolo_line("stand", (50, 50, 50, 60), 200, 200) is None
