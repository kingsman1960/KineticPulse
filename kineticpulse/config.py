"""Runtime configuration loader.

Loads YAML config and validates into a tree of dataclasses. The example
template lives at the repository root as ``config.example.yaml``; copy it
to ``config.yaml`` and edit before running ``python -m kineticpulse.main``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from kineticpulse.webrtc.types import IceServerConfig


@dataclass
class CameraConfig:
    source: str = "usb"               # one of: usb, csi, rtsp, file
    device: str = "0"                 # USB index, CSI sensor id, RTSP URI, or file path
    width: int = 1280
    height: int = 720
    fps: int = 30


@dataclass
class DetectorConfig:
    # Default points at the 4-class checkpoint produced by scripts/train.py
    # with configs/train.yaml (name: kp_v2_4cls). Accepts .pt / .onnx / .engine
    # transparently via Ultralytics.
    weights: str = "runs/detect/kp_v2_4cls/weights/best.pt"
    conf: float = 0.5
    iou: float = 0.45
    imgsz: int = 640
    device: str = "auto"              # auto | cpu | 0 | 0,1 ...


@dataclass
class PoseConfig:
    enabled: bool = True
    # YOLOv8s-pose: 13 MB, COCO val AP ~60 (vs ~50 for the n-variant).
    # Live testing showed the per-frame keypoint quality of the n-variant
    # was the secondary contributor to action-classifier oscillation; the
    # s-variant is a one-line upgrade that is byte-compatible with our
    # ultralytics wrapper and the COCO-17 -> coco_cut adapter.
    weights: str = "yolov8s-pose.pt"  # auto-downloaded pretrained COCO weights
    conf: float = 0.5
    imgsz: int = 640
    device: str = "auto"


@dataclass
class TemporalConfig:
    """Temporal action-classifier (TSSTG / two-stream ST-GCN) settings.

    Holds both the keypoint ring-buffer parameters and the inference-
    side knobs that ``TsstgClassifier`` needs (weights path, device,
    sequence length, source image size for coordinate normalisation).
    The default ``weights`` path is where ``docs/MANUAL.md`` instructs
    operators to drop the released ``tsstg-model.pth`` checkpoint.
    """

    enabled: bool = True
    window_size: int = 60             # frames in the keypoint ring buffer (~2 s @ 30 FPS)
    stride: int = 5                   # run temporal head every N frames
    weights: str = "models/tsstg/tsstg-model.pth"
    device: str = "auto"              # auto | cpu | cuda | cuda:0 ...
    sequence_length: int = 30         # TSSTG checkpoint was trained on 30-frame clips
    image_width: int = 1280           # used to normalise keypoint coords; matches CameraConfig
    image_height: int = 720

    # --- Output stabilisation (Phase 2 -- live spot check showed 1-2 s
    # oscillation between sitting and falling around posture transitions).
    # `smoothing_alpha` is the EMA weight on the new prediction (0.0 =
    # ignore new, 1.0 = no smoothing); `hysteresis_min_consecutive` is the
    # number of stride-spaced predictions a candidate label must hold
    # before it becomes the published `stable_label` consumed by the
    # fusion engine.
    smoothing_alpha: float = 0.4
    hysteresis_min_consecutive: int = 3
    action_confidence_threshold: float = 0.55  # min prob to override the static detector


@dataclass
class WristbandConfig:
    """Wristband telemetry source.

    The hardware team pivoted from BLE to TCP/Wi-Fi for stability, so
    ``transport`` defaults to ``"tcp"``. The Jetson runs a TCP server and
    the ESP32 connects to it; payloads are newline-delimited JSON. The
    BLE fields below are kept so future wearables / a fallback path can
    flip ``transport: ble`` without code changes.
    """

    transport: str = "tcp"            # tcp | ble

    # --- TCP transport (current direction; Jetson is the server) ------------
    tcp_host: str = "0.0.0.0"         # interface to bind on the Jetson
    tcp_port: int = 5555              # ESP32 connects here; firmware default
    tcp_idle_timeout_s: float = 10.0  # drop a silent connection after this
    tcp_max_line_bytes: int = 65_536  # safety cap on a single JSON line

    # --- BLE transport (legacy / fallback) ----------------------------------
    mac: Optional[str] = None         # BLE MAC of the wristband, e.g. "AA:BB:CC:..."
    reconnect_delay_s: float = 2.0
    accel_service_uuid: Optional[str] = None
    hr_service_uuid: Optional[str] = None
    ppg_service_uuid: Optional[str] = None   # set when firmware lands; defaults to vendor UUID.

    # --- Capability flags (transport-agnostic) ------------------------------
    has_accelerometer: bool = False   # IMU not yet ordered as of v0.1; True once installed.
    has_ppg_raw: bool = True          # ESP32 streams raw MAX30102 samples (vs. pre-computed BPM).
    ppg_sample_rate_hz: int = 100     # MAX30102 default sample rate.


@dataclass
class ThresholdsConfig:
    """Heart-rate + accelerometer thresholds (PRD section 5)."""
    hr_resting_low: int = 50           # below this = bradycardia (Scenario C)
    hr_resting_high: int = 100         # above this counts as elevated
    hr_panic_low: int = 100            # standard fall spike band low
    hr_panic_high: int = 130           # standard fall spike band high
    hr_seizure_low: int = 130          # Scenario B (extreme spike)
    hr_seizure_high: int = 160
    pulse_loss_timeout_s: float = 3.0  # no pulse for this long -> cardiac arrest
    impact_g_threshold: float = 3.0    # accelerometer impact magnitude (g)
    tremor_band_hz: List[float] = field(default_factory=lambda: [3.0, 8.0])
    tremor_min_duration_s: float = 2.0


@dataclass
class VoiceConfig:
    enabled: bool = True
    verify_timeout_s: float = 10.0
    prompt_text: str = "A fall has been detected. Are you okay?"
    distress_words: List[str] = field(
        default_factory=lambda: ["help", "emergency", "save me", "hurt", "pain"]
    )
    safe_words: List[str] = field(
        default_factory=lambda: ["i am fine", "i'm fine", "im fine", "okay", "ok", "all good"]
    )
    stt_model: str = "small.en"        # CTranslate2 / faster-whisper model name
    stt_device: str = "auto"


@dataclass
class WebhookConfig:
    name: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class AlertsConfig:
    subject_id: str = "subject-001"
    location: str = "Unknown"
    webhooks: List[WebhookConfig] = field(default_factory=list)


@dataclass
class WebrtcConfig:
    enabled: bool = False
    signaling_url: Optional[str] = None
    always_on: bool = False            # if True, stream a continuous low-bitrate preview
    auth_token: Optional[str] = None
    session_id_prefix: str = "kp"
    connect_timeout_s: float = 8.0
    reconnect_backoff_s: float = 3.0
    max_session_s: float = 120.0
    enable_audio: bool = False
    video_bitrate_kbps: int = 1200
    ice_servers: List[IceServerConfig] = field(default_factory=lambda: [
        IceServerConfig(urls=["stun:stun.l.google.com:19302"]),
    ])


@dataclass
class LoggingConfig:
    level: str = "INFO"
    json: bool = False


@dataclass
class RuntimeConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    pose: PoseConfig = field(default_factory=PoseConfig)
    temporal: TemporalConfig = field(default_factory=TemporalConfig)
    wristband: WristbandConfig = field(default_factory=WristbandConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    webrtc: WebrtcConfig = field(default_factory=WebrtcConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _from_dict(cls, data: Optional[Dict[str, Any]]):
    """Minimal dict -> dataclass loader. Drops unknown keys with a warning."""
    if data is None:
        return cls()
    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    kwargs: Dict[str, Any] = {}
    for key, value in data.items():
        if key not in field_types:
            continue
        kwargs[key] = value
    return cls(**kwargs)


def load_config(path: Path) -> RuntimeConfig:
    """Load and parse a YAML config file into a :class:`RuntimeConfig`."""
    import yaml
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

    webhooks_raw = (raw.get("alerts") or {}).get("webhooks") or []
    webhooks = [WebhookConfig(**w) for w in webhooks_raw]

    alerts = AlertsConfig(
        subject_id=(raw.get("alerts") or {}).get("subject_id", "subject-001"),
        location=(raw.get("alerts") or {}).get("location", "Unknown"),
        webhooks=webhooks,
    )

    webrtc_raw = raw.get("webrtc") or {}
    ice_servers_raw = webrtc_raw.get("ice_servers") or []
    ice_servers = []
    for entry in ice_servers_raw:
        if not isinstance(entry, dict):
            continue
        urls = entry.get("urls")
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list) or not urls:
            continue
        ice_servers.append(IceServerConfig(
            urls=[str(u) for u in urls],
            username=entry.get("username"),
            credential=entry.get("credential"),
        ))
    if not ice_servers:
        ice_servers = [IceServerConfig(urls=["stun:stun.l.google.com:19302"])]

    cfg = RuntimeConfig(
        camera=_from_dict(CameraConfig, raw.get("camera")),
        detector=_from_dict(DetectorConfig, raw.get("detector")),
        pose=_from_dict(PoseConfig, raw.get("pose")),
        temporal=_from_dict(TemporalConfig, raw.get("temporal")),
        wristband=_from_dict(WristbandConfig, raw.get("wristband")),
        thresholds=_from_dict(ThresholdsConfig, raw.get("thresholds")),
        voice=_from_dict(VoiceConfig, raw.get("voice")),
        alerts=alerts,
        webrtc=WebrtcConfig(
            **{
                **_from_dict(WebrtcConfig, webrtc_raw).__dict__,
                "ice_servers": ice_servers,
            }
        ),
        logging=_from_dict(LoggingConfig, raw.get("logging")),
    )
    return cfg
