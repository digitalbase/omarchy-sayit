#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(realpath -- "$0")")/.."
python -m venv .tools
.tools/bin/pip install 'uv==0.12.10'
echo "Ready. Run ./bin/sayit setup kokoro, then ./bin/sayit download kokoro-bf16."

