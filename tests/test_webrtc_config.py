from __future__ import annotations

from pathlib import Path

from kineticpulse.config import load_config


def test_webrtc_config_parses_ice_servers_and_defaults(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        """
alerts:
  subject_id: subject-123
  location: Lab A
webrtc:
  enabled: true
  signaling_url: wss://signal.example/ws
  auth_token: secret-token
  session_id_prefix: kp
  connect_timeout_s: 9.5
  ice_servers:
    - urls: "stun:stun.l.google.com:19302"
    - urls:
        - "turn:turn.example:3478?transport=udp"
      username: user1
      credential: pass1
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)
    assert cfg.webrtc.enabled is True
    assert cfg.webrtc.signaling_url == "wss://signal.example/ws"
    assert cfg.webrtc.auth_token == "secret-token"
    assert cfg.webrtc.connect_timeout_s == 9.5
    assert len(cfg.webrtc.ice_servers) == 2
    assert cfg.webrtc.ice_servers[0].urls == ["stun:stun.l.google.com:19302"]
    assert cfg.webrtc.ice_servers[1].username == "user1"
    assert cfg.webrtc.ice_servers[1].credential == "pass1"


def test_webrtc_config_falls_back_to_default_stun_when_missing(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = load_config(cfg_path)
    assert len(cfg.webrtc.ice_servers) == 1
    assert cfg.webrtc.ice_servers[0].urls == ["stun:stun.l.google.com:19302"]
