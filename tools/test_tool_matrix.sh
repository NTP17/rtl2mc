#!/usr/bin/env bash
# Configure tools on PATH or with RTL2MC_* overrides; see docs/toolchains.md.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${RTL2MC_PYTHON:-python3}" tools/run_tool_matrix.py "$@"
