#!/usr/bin/env bash
# One-time Jetson / Linux bootstrap after git clone.
set -euo pipefail

_script_dir() {
  cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd
}

_repo_root() {
  local script_dir="$1"
  if git -C "$script_dir" rev-parse --show-toplevel &>/dev/null; then
    git -C "$script_dir" rev-parse --show-toplevel
  else
    cd "$script_dir/../.." && pwd
  fi
}

SCRIPT_DIR="$(_script_dir)"
ROOT="$(_repo_root "$SCRIPT_DIR")"
cd "$ROOT"

is_jetson() {
  [[ -f /etc/nv_tegra_release ]]
}

echo "==> KineticPulse install (root: $ROOT)"

if command -v apt-get &>/dev/null; then
  echo "==> Installing system packages (sudo)..."
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    libportaudio2 libasound2 \
    git curl \
    || true
  # aiortc / PyAV build/runtime helpers on Ubuntu
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
    libswscale-dev libavfilter-dev pkg-config \
    || true
fi

VENV="$ROOT/.venv"
VENV_FLAGS=()
if is_jetson; then
  # ponytail: inherit JetPack PyTorch from system site-packages when present
  VENV_FLAGS+=(--system-site-packages)
  echo "==> Jetson detected — venv will use --system-site-packages for PyTorch"
fi

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "${VENV_FLAGS[@]}" "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -U pip setuptools wheel

REQ="$ROOT/requirements.txt"
if is_jetson && [[ -f "$ROOT/requirements-jetson-runtime.txt" ]]; then
  REQ="$ROOT/requirements-jetson-runtime.txt"
fi

echo "==> Installing Python deps from $(basename "$REQ")..."
python -m pip install -r "$REQ"

if ! python -c "import torch" 2>/dev/null; then
  echo ""
  echo "WARNING: PyTorch not importable in this venv."
  if is_jetson; then
    echo "  Install NVIDIA's Jetson PyTorch wheel, then re-run ./install.sh"
    echo "  https://docs.nvidia.com/deep-learning/frameworks/install-pytorch-jetson-platform/index.html"
  else
    echo "  pip install torch  # or use full requirements.txt on a dev machine"
  fi
  echo ""
fi

if [[ ! -f "$ROOT/config.yaml" ]]; then
  cp "$ROOT/config.example.yaml" "$ROOT/config.yaml"
  echo "==> Created config.yaml — edit wristband TCP, webhooks, WebRTC before production."
fi

chmod +x "$ROOT/install.sh" "$ROOT/deploy/jetson/install.sh" "$ROOT/deploy/jetson/run"
ln -sf deploy/jetson/run "$ROOT/kineticpulse"

echo "==> Shipped model weights:"
for w in \
  "$ROOT/runs/detect/kp_v2_4cls/weights/best.pt" \
  "$ROOT/models/tsstg/tsstg-model.pth"; do
  if [[ -f "$w" ]]; then
    echo "    OK $(basename "$w") ($(du -h "$w" | cut -f1))"
  else
    echo "    MISSING $w" >&2
  fi
done

echo ""
echo "==> Install complete."
echo ""
echo "  One-shot full deploy (runtime + signaling + systemd):"
echo "    ./bootstrap.sh"
echo ""
echo "  Quick test (no camera / wristband):"
echo "    ./kineticpulse --mock-ble --mock-stt --no-camera --max-runtime-s 5"
echo ""
echo "  Production run (real hardware):"
echo "    ./kineticpulse"
echo ""
echo "  Optional — start on boot (edit User/WorkingDirectory in the unit file first):"
echo "    sudo cp deploy/jetson/kineticpulse.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload && sudo systemctl enable --now kineticpulse"
