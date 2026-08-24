"""Frame-by-frame dump of every feature the fall decision actually depends on.

Why this exists
===============
When the pipeline reports ``stand`` through a real collapse there are several
independent places the signal can die, and the normal logs cannot tell them
apart:

* the detector never produced a box at all,
* the pose estimator produced a box but could not resolve all four
  shoulder/hip landmarks, so ``torso_angle_deg`` is ``None`` and every
  angle-gated rule degrades to UPRIGHT,
* the features were all available but ``centroid_vel_pps`` never crossed the
  ``_FALL_VEL_BLS`` bar,
* ``stillness`` suppressed the promotion.

This writes one CSV row per frame with the raw feature vector *and* the
resulting ``pose_signature``, using the real project functions so the numbers
are exactly what fusion sees. Perform the motion in front of the camera, then
read the CSV to find which gate blocked it.

Usage::

    python scripts/diagnose_fall_features.py --seconds 60
    python scripts/diagnose_fall_features.py --out /tmp/fall.csv --seconds 90

Then inspect the peak descent and the torso-angle availability::

    python scripts/diagnose_fall_features.py --summarise /tmp/fall.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kineticpulse.config import load_config                      # noqa: E402
from kineticpulse.fusion.rules import pose_signature             # noqa: E402
from kineticpulse.vision.detector import FallDetector            # noqa: E402
from kineticpulse.vision.features import extract_features        # noqa: E402
from kineticpulse.vision.pose import PoseEstimator               # noqa: E402

FIELDS = [
    "t_s", "fps", "det_class", "det_conf", "n_boxes",
    "kp_shoulder_conf", "kp_hip_conf", "torso_angle_deg",
    "aspect_ratio", "centroid_vel_bls", "descent_1s_bl", "stillness",
    "pose_signature",
]


def summarise(path: Path) -> int:
    """Print the diagnosis for a recorded run."""
    rows = list(csv.DictReader(path.open()))
    if not rows:
        print(f"[error] {path} has no rows.")
        return 1

    def nums(key: str) -> List[float]:
        out = []
        for r in rows:
            v = r.get(key, "")
            if v not in ("", "None"):
                try:
                    out.append(float(v))
                except ValueError:
                    pass
        return out

    n = len(rows)
    with_box = [r for r in rows if r["det_class"] not in ("", "None")]
    with_angle = nums("torso_angle_deg")
    vels = nums("centroid_vel_bls")
    desc = nums("descent_1s_bl")
    sigs: dict = {}
    for r in rows:
        sigs[r["pose_signature"]] = sigs.get(r["pose_signature"], 0) + 1

    print(f"\n=== {path}  ({n} frames) ===\n")
    print(f"detector produced a box   : {len(with_box)}/{n} frames "
          f"({100.0 * len(with_box) / n:.0f}%)")
    print(f"torso_angle_deg available : {len(with_angle)}/{n} frames "
          f"({100.0 * len(with_angle) / n:.0f}%)"
          "   <- angle-gated rules need this")
    if vels:
        vels_sorted = sorted(vels)
        print(f"centroid_vel (body-len/s) : peak {max(vels):+.2f}   "
              f"p95 {vels_sorted[int(0.95 * (len(vels) - 1))]:+.2f}   "
              f"median {vels_sorted[len(vels) // 2]:+.2f}")
    if desc:
        print(f"descent over 1 s (body-len): peak {max(desc):+.2f}")
    print("\npose_signature distribution:")
    for k, v in sorted(sigs.items(), key=lambda kv: -kv[1]):
        print(f"  {k or '(none)':16s} {v:5d}  ({100.0 * v / n:.0f}%)")

    print("\n--- reading this ---")
    if len(with_box) < n * 0.5:
        print("* The detector rarely saw a person. Framing/lighting problem,")
        print("  not a threshold problem.")
    if with_angle and len(with_angle) < n * 0.5:
        print("* torso_angle_deg was mostly unavailable: hips/shoulders are")
        print("  outside the frame or low-confidence. Angle-gated rules are")
        print("  dead here; only the kinematic fallback can fire.")
    elif not with_angle:
        print("* torso_angle_deg was NEVER available. Every angle-gated rule")
        print("  was inert for this whole run.")
    if vels and max(vels) < 0.9:
        print(f"* Peak descent was {max(vels):+.2f} body-len/s, below the")
        print("  0.9 fallback bar and the 1.0 _FALL_VEL_BLS bar. These")
        print("  thresholds cannot fire on this motion - they need lowering")
        print("  to a data-derived value, or a cumulative-descent feature.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--cap-width", type=int, default=1280)
    p.add_argument("--cap-height", type=int, default=720)
    p.add_argument("--seconds", type=float, default=60.0,
                   help="How long to record. Perform the motion during this.")
    p.add_argument("--out", type=Path, default=ROOT / "logs" / "fall_features.csv")
    p.add_argument("--summarise", type=Path, default=None,
                   help="Skip capture; just analyse an existing CSV.")
    args = p.parse_args(argv)

    if args.summarise is not None:
        return summarise(args.summarise)

    import cv2

    cfg = load_config(args.config)
    detector = FallDetector(cfg.detector)
    pose_est = PoseEstimator(cfg.pose)

    cap = cv2.VideoCapture(args.camera)
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    except Exception:
        pass
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.cap_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.cap_height)
    if not cap.isOpened():
        print(f"[error] could not open camera {args.camera}", file=sys.stderr)
        return 1
    got = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
           int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    print(f"[camera] {got[0]}x{got[1]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fh = args.out.open("w", newline="")
    writer = csv.DictWriter(fh, fieldnames=FIELDS)
    writer.writeheader()

    # (timestamp_ms, centroid_y / bbox_height) for the cumulative-descent window
    centroid_hist: Deque = deque(maxlen=200)
    kp_hist: Deque = deque(maxlen=30)
    prev_pose = None

    # First CUDA inference costs seconds (kernel autotuning). Burn it before
    # the clock starts, or a short --seconds window records almost nothing.
    print("[warmup] priming CUDA kernels ...")
    ok, warm = cap.read()
    if ok:
        detector.infer(warm, int(time.time() * 1000))
        pose_est.infer(warm, int(time.time() * 1000))
    print("[warmup] done")

    t0 = time.time()
    frames = 0
    fps = 0.0
    last_print = 0.0

    print(f"[recording {args.seconds:.0f}s] perform the motion now — "
          "sit, then collapse. Ctrl-C to stop early.")
    try:
        while time.time() - t0 < args.seconds:
            ok, frame = cap.read()
            if not ok:
                continue
            frames += 1
            now = time.time()
            ts_ms = int(now * 1000)
            elapsed = now - t0
            if elapsed > 0:
                fps = frames / elapsed

            dets = detector.infer(frame, ts_ms)
            poses = pose_est.infer(frame, ts_ms)
            pose = poses[0] if poses else None

            det_class = det_conf = None
            if dets:
                best = max(dets, key=lambda d: d.confidence)
                det_class = getattr(best.cls, "value", str(best.cls))
                det_conf = round(float(best.confidence), 3)

            sh_conf = hip_conf = None
            if pose is not None and pose.keypoints is not None \
                    and pose.keypoints.shape[0] >= 17:
                kp = pose.keypoints
                sh_conf = round(float(min(kp[5][2], kp[6][2])), 3)
                hip_conf = round(float(min(kp[11][2], kp[12][2])), 3)
                kp_hist.append(kp)

            feats = extract_features(pose, prev_pose, list(kp_hist), ts_ms)

            # Cumulative descent over the last ~1 s, normalised by body length.
            descent_1s = None
            if pose is not None and pose.bbox_xyxy is not None:
                h = float(pose.bbox_xyxy[3] - pose.bbox_xyxy[1])
                cy = (float(pose.bbox_xyxy[1]) + float(pose.bbox_xyxy[3])) / 2.0
                if h > 1.0:
                    centroid_hist.append((ts_ms, cy / h))
                    window = [c for (t, c) in centroid_hist if ts_ms - t <= 1000]
                    if len(window) >= 2:
                        descent_1s = round(window[-1] - min(window), 3)

            sig = pose_signature(
                detector_class=det_class,
                torso_angle_deg=feats.torso_angle_deg,
                aspect_ratio=feats.aspect_ratio,
                centroid_vel_pps=feats.centroid_vel_pps,
                stillness=feats.stillness,
            )

            writer.writerow({
                "t_s": round(elapsed, 3),
                "fps": round(fps, 1),
                "det_class": det_class,
                "det_conf": det_conf,
                "n_boxes": len(dets),
                "kp_shoulder_conf": sh_conf,
                "kp_hip_conf": hip_conf,
                "torso_angle_deg": (None if feats.torso_angle_deg is None
                                    else round(feats.torso_angle_deg, 1)),
                "aspect_ratio": (None if feats.aspect_ratio is None
                                 else round(feats.aspect_ratio, 3)),
                "centroid_vel_bls": (None if feats.centroid_vel_pps is None
                                     else round(feats.centroid_vel_pps, 3)),
                "descent_1s_bl": descent_1s,
                "stillness": (None if feats.stillness is None
                              else round(feats.stillness, 3)),
                "pose_signature": sig.value,
            })

            if elapsed - last_print >= 1.0:
                last_print = elapsed
                fh.flush()
                print(f"[{elapsed:5.1f}s] fps={fps:4.1f} det={str(det_class):8s} "
                      f"angle={str(feats.torso_angle_deg is not None):5s} "
                      f"vel={feats.centroid_vel_pps if feats.centroid_vel_pps is None else round(feats.centroid_vel_pps, 2)} "
                      f"desc1s={descent_1s} -> {sig.value}")

            if pose is not None:
                prev_pose = pose
    except KeyboardInterrupt:
        print("\n[stopped]")
    finally:
        cap.release()
        fh.close()

    print(f"\n[written] {args.out}")
    return summarise(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
