#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(realpath -- "$0")")/.."
# System Python is a host prerequisite, not downloaded or built by this script.
python -m venv .build
.build/bin/python -m pip --isolated install --index-url https://pypi.org/simple \
  --require-hashes --only-binary=:all: --no-deps --force-reinstall -r sayit/locks/build.txt
.build/bin/python -m build --no-isolation
