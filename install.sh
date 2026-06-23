#!/usr/bin/env bash
# Repo-root entry point — delegates to deploy/jetson/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec bash "$ROOT/deploy/jetson/install.sh" "$@"
