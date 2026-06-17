"""TSSTG sanity check.

Feeds four hand-crafted COCO-17 keypoint sequences (a 30-frame window each)
into the trained TSSTG checkpoint and prints the collapsed 4-class
distribution. Useful as a "is this checkpoint at all sane on its
canonical inputs?" smoke test, independent of any camera pipeline.

Synthetic poses are deliberately schematic - this is not a benchmark,
just a directional sanity check. Numbers normalised to a 640x480 frame.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from kineticpulse.temporal.tsstg import TsstgClassifier  # noqa: E402


W, H = 640, 480
T = 30  # sequence length expected by the checkpoint


def _coco17_template(joints_xy: dict) -> np.ndarray:
    """Build a (17, 3) COCO-17 array from a {name: (x, y)} dict.

    Order: nose, l/r eye, l/r ear, l/r shoulder, l/r elbow, l/r wrist,
    l/r hip, l/r knee, l/r ankle.
    """
    order = [
        "nose", "leye", "reye", "lear", "rear",
        "lshoulder", "rshoulder", "lelbow", "relbow",
        "lwrist", "rwrist",
        "lhip", "rhip", "lknee", "rknee", "lankle", "rankle",
    ]
    out = np.zeros((17, 3), dtype=np.float32)
    for i, name in enumerate(order):
        x, y = joints_xy[name]
        out[i, 0] = x
        out[i, 1] = y
        out[i, 2] = 0.95
    return out


def standing(cx: float = W / 2) -> np.ndarray:
    return _coco17_template({
        "nose":      (cx,        80),
        "leye":      (cx - 8,    72),
        "reye":      (cx + 8,    72),
        "lear":      (cx - 16,   76),
        "rear":      (cx + 16,   76),
        "lshoulder": (cx - 40,  120),
        "rshoulder": (cx + 40,  120),
        "lelbow":    (cx - 50,  190),
        "relbow":    (cx + 50,  190),
        "lwrist":    (cx - 55,  260),
        "rwrist":    (cx + 55,  260),
        "lhip":      (cx - 30,  280),
        "rhip":      (cx + 30,  280),
        "lknee":     (cx - 30,  360),
        "rknee":     (cx + 30,  360),
        "lankle":    (cx - 30,  440),
        "rankle":    (cx + 30,  440),
    })


def sitting(cx: float = W / 2) -> np.ndarray:
    """Torso upright, hips and knees roughly at the same height."""
    return _coco17_template({
        "nose":      (cx,       180),
        "leye":      (cx - 8,   172),
        "reye":      (cx + 8,   172),
        "lear":      (cx - 16,  176),
        "rear":      (cx + 16,  176),
        "lshoulder": (cx - 40,  220),
        "rshoulder": (cx + 40,  220),
        "lelbow":    (cx - 60,  290),
        "relbow":    (cx + 60,  290),
        "lwrist":    (cx - 30,  340),
        "rwrist":    (cx + 30,  340),
        "lhip":      (cx - 30,  340),
        "rhip":      (cx + 30,  340),
        "lknee":     (cx - 80,  340),
        "rknee":     (cx + 80,  340),
        "lankle":    (cx - 80,  440),
        "rankle":    (cx + 80,  440),
    })


def lying(cy: float = H / 2) -> np.ndarray:
    """Whole body horizontal -- everything roughly on the same y-line."""
    return _coco17_template({
        "nose":      (120, cy),
        "leye":      (114, cy - 6),
        "reye":      (114, cy + 6),
        "lear":      (108, cy - 10),
        "rear":      (108, cy + 10),
        "lshoulder": (180, cy - 30),
        "rshoulder": (180, cy + 30),
        "lelbow":    (240, cy - 50),
        "relbow":    (240, cy + 50),
        "lwrist":    (300, cy - 60),
        "rwrist":    (300, cy + 60),
        "lhip":      (360, cy - 25),
        "rhip":      (360, cy + 25),
        "lknee":     (450, cy - 25),
        "rknee":     (450, cy + 25),
        "lankle":    (540, cy - 25),
        "rankle":    (540, cy + 25),
    })


def falling_motion() -> np.ndarray:
    """30-frame trajectory: starts standing, ends lying. Used directly,
    not stacked, because we want temporal motion in the sequence."""
    seq = np.zeros((T, 17, 3), dtype=np.float32)
    stand = standing()
    lie = lying()
    for t in range(T):
        a = t / (T - 1)
        seq[t, :, :2] = (1 - a) * stand[:, :2] + a * lie[:, :2]
        seq[t, :, 2] = 0.95
    return seq


def stack(pose: np.ndarray, jitter: float = 1.5) -> np.ndarray:
    """Repeat a single static pose over T frames with tiny random jitter,
    so the motion stream sees something non-zero (mostly noise)."""
    rng = np.random.default_rng(0)
    seq = np.tile(pose[None, ...], (T, 1, 1)).astype(np.float32)
    seq[:, :, :2] += rng.normal(0.0, jitter, size=(T, 17, 2)).astype(np.float32)
    return seq


def report(name: str, p) -> None:
    bars = {
        "fallen":  p.fallen,
        "falling": p.falling,
        "stand":   p.stand,
        "sitting": p.sitting,
    }
    pretty = " ".join(f"{k}={v:.3f}" for k, v in bars.items())
    print(f"  {name:<22s} -> argmax={p.argmax_label:<8s} | {pretty}")


def main() -> int:
    weights = REPO_ROOT / "models" / "tsstg" / "tsstg-model.pth"
    if not weights.exists():
        print(f"[error] missing weights at {weights}")
        return 2

    clf = TsstgClassifier(weights_path=str(weights), device="cuda")
    print(f"loaded {weights.name} ({weights.stat().st_size:,} bytes)\n")

    cases = [
        ("standing  (static)",     stack(standing())),
        ("sitting   (static)",     stack(sitting())),
        ("lying     (static)",     stack(lying())),
        ("falling   (motion)",     falling_motion()),
    ]
    for name, seq in cases:
        pred = clf.predict(seq, image_size=(W, H))
        report(name, pred)

    print("\n(synthetic poses are schematic; this is a directional sanity check, not a benchmark)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
