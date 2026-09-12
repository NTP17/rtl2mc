#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
module load synopsys/libraryCompiler/V-2023.12
module load synopsys/syn/V-2023.12
module load synopsys/vcs/X-2025.06
python3.13 tools/check_synopsys.py "$@"
