#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(realpath -- "$0")")/.."
python -m venv .tools
.tools/bin/python -m pip --isolated install --index-url https://pypi.org/simple \
  --require-hashes --only-binary=:all: --no-deps --force-reinstall -r sayit/locks/bootstrap.txt
echo "Ready. Run ./bin/sayit setup kokoro, then ./bin/sayit download kokoro-bf16."

