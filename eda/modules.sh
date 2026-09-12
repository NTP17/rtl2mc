#!/usr/bin/env bash
# Optional site profile matching the recorded Linux qualification environment.
# Source this file in a shell where Environment Modules is initialized.
module load synopsys/vcs/X-2025.06 || return
module load synopsys/syn/V-2023.12 || return
module load synopsys/libraryCompiler/V-2023.12 || return
module load cadence/xcelium/23.03 || return
module load cadence/ddi/23.10 || return
module load siemens/questasim/2024.1 || return
