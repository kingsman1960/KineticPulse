"""Live webcam fall-posture detection - manual / spot-check helper.

Why this script and not `yolo predict source=0`?
=================================================
Plain `yolo predict source=0` opens the camera through OpenCV's MSMF
backend on Windows and that is fragile (frequent ``Failed to read
images from 0`` even when the camera is fine). This wrapper:

* Probes camera indices 0..N-1 and reports which ones actually open
  (using DirectShow first, then MSMF, then the auto backend).
* Lets you pick an index explicitly with ``--camera``.
* Runs the trained 4-class detector and overlays the bounding boxes,
  class label, and a per-frame FPS counter.
* Prints the **dominant posture class** and its confidence to the
  console roughly once per second so the live behaviour of the
  ``sitting`` class (which is not present in val/test splits) can be
  spot-checked without staring at the OSD.

Usage::

    set KMP_DUPLICATE_LIB_OK=TRUE
    python scripts/live_predict.py                # auto-detect camera
    python scripts/live_predict.py --camera 1     # force index 1
    python scripts/live_predict.py --probe        # only list cameras

Press ``q`` or ``ESC`` in the preview window to quit.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from collections import Counter
from pathlib import Path
from typing import List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


REPO_ROOT = Path(__file__).resolve().parent.parent
# Allow ``python scripts/live_predict.py`` to import the kineticpulse package
# without the user having to set PYTHONPATH first.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_WEIGHTS = REPO_ROOT / "runs" / "detect" / "kp_v2_4cls" / "weights" / "best.pt"


# Order matters: try the most reliable backend on Windows first.
_BACKENDS_WIN = ("DSHOW", "MSMF", "ANY")
_BACKENDS_OTHER = ("ANY",)


def _backend_const(cv2, name: str) -> int:
    return {
        "DSHOW": cv2.CAP_DSHOW,
        "MSMF":  cv2.CAP_MSMF,
        "ANY":   cv2.CAP_ANY,
    }[name]


def _backends_to_try() -> Tuple[str, ...]:
    return _BACKENDS_WIN if sys.platform.startswith("win") else _BACKENDS_OTHER


def probe_cameras(max_index: int = 4) -> List[Tuple[int, str]]:
    """Return ``[(index, backend_name), ...]`` for cameras that opened and
    delivered at least one frame within a short timeout."""
    import cv2

    found: List[Tuple[int, str]] = []
    for idx in range(max_index + 1):
        for be in _backends_to_try():
            cap = cv2.VideoCapture(idx, _backend_const(cv2, be))
            if not cap.isOpened():
                cap.release()
                continue
            # Some webcams need a couple of frames before they hand one out.
            ok = False
            for _ in range(5):
                ret, frame = cap.read()
                if ret and frame is not None:
                    ok = True
                    break
                time.sleep(0.05)
            cap.release()
            if ok:
                found.append((idx, be))
                break  # one working backend per index is enough
    return found


def open_camera(cv2, index: int, prefer_backend: Optional[str] = None,
                retries: int = 5, retry_delay_s: float = 0.4):
    """Open camera ``index`` with the most reliable available backend.

    On Windows, releasing a capture from ``probe_cameras`` and immediately
    re-opening the same index sometimes races and ``VideoCapture.isOpened()``
    returns False. A few short retries make this rock-solid in practice.
    """
    backends = (prefer_backend,) if prefer_backend else _backends_to_try()
    last_err = None
    for attempt in range(1, retries + 1):
        for be in backends:
            cap = cv2.VideoCapture(index, _backend_const(cv2, be))
            if cap.isOpened():
                # Some webcams need a couple of warm-up reads.
                ret = False
                for _ in range(5):
                    ret, _frame = cap.read()
                    if ret:
                        break
                    time.sleep(0.05)
                if ret:
                    print(f"[camera] index={index} backend={be} OK "
                          f"(attempt {attempt})")
                    return cap
                cap.release()
                last_err = f"{be}: opened but read() returned False"
            else:
                last_err = f"{be}: VideoCapture.isOpened()==False"
        if attempt < retries:
            time.sleep(retry_delay_s)
    raise RuntimeError(
        f"Could not open camera index {index} after {retries} tries. "
        f"Last error: {last_err}. Run with --probe to see what is "
        f"actually available, and close any other app (Zoom/OBS/browser) "
        f"that may be holding the camera."
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Live spot-check helper for the trained 4-class detector.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS,
                   help="Path to the trained .pt / .onnx / .engine.")
    p.add_argument("--camera", type=int, default=None,
                   help="Camera index. Default: auto-pick the first one that works.")
    p.add_argument("--backend", choices=("DSHOW", "MSMF", "ANY"), default=None,
                   help="Force a specific OpenCV backend (Windows: DSHOW recommended).")
    p.add_argument("--probe", action="store_true",
                   help="Only probe camera indices 0..4 and exit.")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--iou", type=float, default=0.45)
    p.add_argument("--device", type=str, default="",
                   help='Device override: "cpu", "0", or "" for auto.')
    p.add_argument("--max-cameras", type=int, default=4,
                   help="Highest camera index to probe.")
    p.add_argument("--debug-classes", action="store_true",
                   help="Print the per-class max confidence each second. Forces "
                        "conf=0.01 and iou=0.95 so even non-dominant classes "
                        "(e.g. sitting) survive NMS for diagnosis.")
    p.add_argument("--apply-priority", action="store_true",
                   help="Apply the posture_postprocess priority rules so "
                        "sitting / fallen / falling are rescued from the noisy "
                        "argmax. Forces conf=0.01 and iou=0.95 to expose the "
                        "raw class scores the rules need.")
    p.add_argument("--show-rule", action="store_true",
                   help="When --apply-priority is on, draw which rule fired "
                        "(argmax / sitting-rescue / ...) on each box.")
    p.add_argument("--use-action-classifier", action="store_true",
                   help="Run the TSSTG two-stream ST-GCN action classifier on "
                        "top of YOLOv8n-pose. Bypasses the 4-class detector "
                        "and reports the dominant action from a 30-frame "
                        "skeleton clip - much more robust to camera angle / "
                        "distance than the per-frame detector. Requires "
                        "models/tsstg/tsstg-model.pth (see docs/MANUAL.md).")
    p.add_argument("--pose-weights", type=str, default="yolov8n-pose.pt",
                   help="YOLOv8 pose checkpoint to use with "
                        "--use-action-classifier. The COCO-pretrained "
                        "default auto-downloads on first run.")
    p.add_argument("--tsstg-weights", type=str,
                   default="models/tsstg/tsstg-model.pth",
                   help="Path to the released TSSTG checkpoint.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import cv2
    except ImportError as exc:
        print("[error] OpenCV (cv2) not installed. `pip install opencv-python`.",
              file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"OpenCV : {cv2.__version__}")
    print(f"Probing cameras 0..{args.max_cameras} ...")
    available = probe_cameras(max_index=args.max_cameras)
    if not available:
        print("[error] No working camera detected.")
        print("Likely causes:")
        print("  - Another app (Zoom, Teams, OBS, browser) is holding the camera.")
        print("  - Windows Settings -> Privacy & security -> Camera -> 'Let apps access' is OFF.")
        print("  - Anti-virus / endpoint manager is blocking webcam access for python.exe.")
        return 1

    print("Available cameras:")
    for idx, be in available:
        print(f"  - index={idx} (via {be})")

    if args.probe:
        return 0

    chosen = args.camera if args.camera is not None else available[0][0]
    print(f"Using camera index {chosen}.")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        print("[error] ultralytics not installed.", file=sys.stderr)
        raise SystemExit(2) from exc

    # In action-classifier mode the 4-class detector is bypassed; only the
    # pose model + ST-GCN run.
    model = None
    pose_model = None
    temporal_head = None
    keypoint_buffer = None
    last_action_logits = None
    last_action_label = "..."
    last_action_conf = 0.0
    last_action_dist = (0.0, 0.0, 0.0, 0.0)  # (fallen, falling, stand, sitting)

    if args.use_action_classifier:
        from kineticpulse.config import TemporalConfig
        from kineticpulse.temporal.stgcn import (
            KeypointRingBuffer, TemporalHead,
        )

        tsstg_path = Path(args.tsstg_weights)
        print(f"Loading pose model: {args.pose_weights}")
        pose_model = YOLO(args.pose_weights)
        if args.device:
            try:
                pose_model.to(args.device)
            except Exception as exc:
                print(f"[warn] could not move pose model to "
                      f"{args.device!r}: {exc}")

        # Image size for normalisation - filled in once we have a frame.
        temporal_cfg = TemporalConfig(
            enabled=True,
            window_size=30,
            stride=1,                  # predict every frame; cheap
            weights=str(tsstg_path),
            device=args.device or "auto",
            sequence_length=30,
            image_width=640,           # placeholder; fixed once we read a frame
            image_height=480,
        )
        temporal_head = TemporalHead(temporal_cfg)
        keypoint_buffer = KeypointRingBuffer(maxlen=temporal_cfg.window_size)

        if not tsstg_path.exists():
            print(f"[warn] TSSTG weights not found at {tsstg_path}. "
                  "TemporalHead will use the heuristic fallback.")
        else:
            print(f"TSSTG weights: {tsstg_path}")
    else:
        if not args.weights.exists():
            print(f"[error] weights not found: {args.weights}", file=sys.stderr)
            return 2
        print(f"Loading detector: {args.weights}")
        model = YOLO(str(args.weights))
        if args.device:
            try:
                model.to(args.device)
            except Exception as exc:
                print(f"[warn] could not move model to {args.device!r}: {exc}")

    # In debug mode we want to see *every* class' score per frame, even when
    # one class wins the dominant box. Use very low conf + very high iou so
    # NMS does not erase the runner-up classes. The priority post-process
    # needs the same raw view, hence the shared eff_conf / eff_iou.
    raw_mode = args.debug_classes or args.apply_priority
    eff_conf = 0.01 if raw_mode else args.conf
    eff_iou = 0.95 if raw_mode else args.iou
    if raw_mode:
        why = []
        if args.debug_classes: why.append("debug-classes")
        if args.apply_priority: why.append("apply-priority")
        print(f"[{'+'.join(why)}] forcing conf={eff_conf} iou={eff_iou} "
              "to expose per-class scores")

    # Priority rules (only loaded when needed so a plain run stays light).
    if args.apply_priority:
        from kineticpulse.vision.posture_postprocess import (
            reweight_postures, PriorityConfig,
        )
        priority_cfg = PriorityConfig(output_min_conf=args.conf)
        rule_counter: Counter = Counter()  # which rule fired this second
    else:
        reweight_postures = None  # type: ignore[assignment]
        priority_cfg = None
        rule_counter = Counter()

    cap = open_camera(cv2, chosen, prefer_backend=args.backend)

    win = "KineticPulse - live spot-check (press q or ESC to quit)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    fps_alpha = 0.9
    fps_ema: Optional[float] = None
    last_fps_t = time.monotonic()

    print_every_s = 1.0
    last_print_t = time.monotonic()
    class_counter: Counter = Counter()
    conf_sum: dict = {}
    # Per-class running max for debug-classes mode (reset every print interval).
    per_class_max: dict = {}

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("[warn] frame read failed; retrying.")
                time.sleep(0.05)
                continue

            # ----- Action-classifier branch ---------------------------- #
            if args.use_action_classifier:
                # Sync the temporal head's image size to the actual frame.
                h, w = frame.shape[:2]
                if (temporal_head.cfg.image_width != w
                        or temporal_head.cfg.image_height != h):
                    temporal_head.cfg.image_width = w
                    temporal_head.cfg.image_height = h

                pose_results = pose_model.predict(
                    source=frame, imgsz=args.imgsz, conf=args.conf,
                    verbose=False,
                )
                pr0 = pose_results[0] if pose_results else None

                # Pick the most confident person and push their keypoints.
                main_kpts = None
                main_box = None
                if (pr0 is not None and pr0.keypoints is not None
                        and pr0.keypoints.data is not None
                        and len(pr0.keypoints.data) > 0):
                    import numpy as np
                    kp_data = pr0.keypoints.data.cpu().numpy()  # (P, 17, 3)
                    if pr0.boxes is not None and pr0.boxes.conf is not None:
                        confs = pr0.boxes.conf.cpu().numpy()
                        idx = int(confs.argmax())
                    else:
                        idx = 0
                    main_kpts = kp_data[idx].astype(np.float32)
                    if pr0.boxes is not None and pr0.boxes.xyxy is not None:
                        main_box = pr0.boxes.xyxy.cpu().numpy()[idx]

                if main_kpts is not None:
                    keypoint_buffer.push(main_kpts)

                logits = temporal_head.maybe_predict(
                    keypoint_buffer, latest_features=None,
                    timestamp_ms=int(time.monotonic() * 1000),
                )
                if logits is not None:
                    last_action_logits = logits
                    last_action_label = logits.argmax_label
                    last_action_conf = getattr(logits, last_action_label)
                    last_action_dist = (logits.fallen, logits.falling,
                                        logits.stand, logits.sitting)

                annotated = frame.copy()
                color_map = {
                    "fallen":  (0,   0,   255),
                    "falling": (0,   140, 255),
                    "stand":   (0,   200, 0),
                    "sitting": (255, 180, 0),
                }
                osd_color = color_map.get(last_action_label, (255, 255, 255))
                if main_box is not None:
                    x1, y1, x2, y2 = (int(v) for v in main_box)
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), osd_color, 2)
                    cv2.putText(
                        annotated,
                        f"{last_action_label} {last_action_conf:.2f}",
                        (x1, max(20, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, osd_color, 2,
                        cv2.LINE_AA,
                    )
                # Distribution OSD in the corner.
                f, fl, st, si = last_action_dist
                fill_pct = int(100 * len(keypoint_buffer)
                               / max(1, keypoint_buffer.maxlen))
                cv2.putText(
                    annotated,
                    f"buf {fill_pct:3d}%  fallen={f:.2f}  falling={fl:.2f}  "
                    f"stand={st:.2f}  sitting={si:.2f}",
                    (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA,
                )
                # Skip the detector / priority branches below.
                results = None
                r0 = None
                names_map = {}
                priority_preds = []

                # Run common FPS overlay / console summary code via fall-through
                # to the standard sections below by setting best_label here.
                _ac_best_label = (
                    last_action_label if last_action_logits is not None
                    else None
                )
                _ac_best_conf = (
                    last_action_conf if last_action_logits is not None
                    else 0.0
                )
            else:
                _ac_best_label = None
                _ac_best_conf = 0.0

            if not args.use_action_classifier:
                results = model.predict(
                    source=frame, imgsz=args.imgsz, conf=eff_conf,
                    iou=eff_iou, verbose=False,
                )
                r0 = results[0] if results else None
                # Names map for both modes below.
                names_map = {}
                if r0 is not None:
                    names_map = (r0.names if isinstance(r0.names, dict)
                                 else dict(enumerate(r0.names)))

            # `priority_preds` is populated in apply-priority mode and drives
            # both the OSD and the per-second console summary. Skipped in
            # action-classifier mode (which already produced its own annotated).
            priority_preds = []
            if not args.use_action_classifier:
                if (args.apply_priority and r0 is not None
                        and r0.boxes is not None and len(r0.boxes) > 0):
                    import numpy as np
                    xyxy = r0.boxes.xyxy.cpu().numpy()
                    cls_ids = r0.boxes.cls.cpu().numpy().astype(int)
                    confs_all = r0.boxes.conf.cpu().numpy()
                    priority_preds = reweight_postures(
                        xyxy, cls_ids, confs_all, priority_cfg)

                if args.apply_priority:
                    annotated = frame.copy()
                    for pred in priority_preds:
                        x1, y1, x2, y2 = (int(v) for v in pred.bbox_xyxy)
                        label = names_map.get(pred.cls_idx, str(pred.cls_idx))
                        color = {
                            "fallen":  (0,   0,   255),
                            "falling": (0,   140, 255),
                            "stand":   (0,   200, 0),
                            "sitting": (255, 180, 0),
                        }.get(label, (255, 255, 255))
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                        txt = f"{label} {pred.confidence:.2f}"
                        if args.show_rule:
                            txt += f" [{pred.rule_fired}]"
                        cv2.putText(annotated, txt, (x1, max(20, y1 - 6)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
                                    cv2.LINE_AA)
                        rule_counter[pred.rule_fired] += 1
                elif (args.debug_classes and r0 is not None
                      and r0.boxes is not None):
                    try:
                        import numpy as np
                        confs = r0.boxes.conf.cpu().numpy()
                        keep = np.where(confs >= args.conf)[0]
                        annotated = (r0[keep].plot()
                                     if len(keep) else frame.copy())
                    except Exception:
                        annotated = frame.copy()
                else:
                    annotated = r0.plot() if r0 is not None else frame

            now = time.monotonic()
            dt = now - last_fps_t
            last_fps_t = now
            inst_fps = 1.0 / dt if dt > 0 else 0.0
            fps_ema = inst_fps if fps_ema is None else fps_alpha * fps_ema + (1 - fps_alpha) * inst_fps
            cv2.putText(annotated, f"FPS {fps_ema:5.1f}", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)

            # Dominant class summary on the console (helps confirm `sitting`).
            best_label = None
            best_conf = 0.0
            try:
                if args.use_action_classifier:
                    best_label = _ac_best_label
                    best_conf = _ac_best_conf
                elif args.apply_priority and priority_preds:
                    # Pick the most confident *re-weighted* box.
                    pred = max(priority_preds, key=lambda p: p.confidence)
                    best_label = names_map.get(pred.cls_idx, str(pred.cls_idx))
                    best_conf = pred.confidence
                elif r0 is not None and r0.boxes is not None and len(r0.boxes) > 0:
                    confs = r0.boxes.conf.cpu().numpy()
                    cls_ids = r0.boxes.cls.cpu().numpy().astype(int)
                    i_best = int(confs.argmax())
                    best_label = names_map.get(int(cls_ids[i_best]), str(cls_ids[i_best]))
                    best_conf = float(confs[i_best])
                    # Track per-class max for the diagnosis mode.
                    if args.debug_classes:
                        for c, cf in zip(cls_ids, confs):
                            lbl = names_map.get(int(c), str(int(c)))
                            if cf > per_class_max.get(lbl, 0.0):
                                per_class_max[lbl] = float(cf)
            except Exception:
                pass

            if best_label is not None:
                class_counter[best_label] += 1
                conf_sum[best_label] = conf_sum.get(best_label, 0.0) + best_conf

            if now - last_print_t >= print_every_s:
                last_print_t = now
                if args.apply_priority:
                    # Report which rules fired and the resulting class share.
                    rule_summary = ", ".join(
                        f"{r}:{c}" for r, c in rule_counter.most_common()
                    ) or "(no boxes)"
                    if class_counter:
                        parts = []
                        for lbl, cnt in class_counter.most_common():
                            avg_conf = conf_sum[lbl] / cnt
                            parts.append(f"{lbl} x{cnt} (avg conf {avg_conf:.2f})")
                        cls_summary = ", ".join(parts)
                    else:
                        cls_summary = "(no detection)"
                    print(f"[{time.strftime('%H:%M:%S')}] FPS {fps_ema:5.1f}  "
                          f"-> {cls_summary}    rules: {rule_summary}")
                    rule_counter.clear()
                elif args.debug_classes:
                    all_classes = ("fallen", "falling", "stand", "sitting")
                    parts = [f"{c}={per_class_max.get(c, 0.0):.2f}"
                             for c in all_classes]
                    print(f"[{time.strftime('%H:%M:%S')}] FPS {fps_ema:5.1f}  "
                          f"max-conf  " + "  ".join(parts))
                    per_class_max.clear()
                elif class_counter:
                    parts = []
                    for lbl, cnt in class_counter.most_common():
                        avg_conf = conf_sum[lbl] / cnt
                        parts.append(f"{lbl} x{cnt} (avg conf {avg_conf:.2f})")
                    print(f"[{time.strftime('%H:%M:%S')}] FPS {fps_ema:5.1f}  -> "
                          + ", ".join(parts))
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] FPS {fps_ema:5.1f}  -> "
                          "(no detection)")
                class_counter.clear()
                conf_sum.clear()

            cv2.imshow(win, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):    # q or ESC
                break
            # Bail out as soon as the user closes the window with the X button.
            try:
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    print("Live spot-check exited cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
