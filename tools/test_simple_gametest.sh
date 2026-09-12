#!/usr/bin/env bash
# Four fresh exports followed by native GameTest and a broken-output control.
set -euo pipefail
cd "$(dirname "$0")/.."
run_root="${1:-builds/gametest-$(date -u +%Y%m%dT%H%M%SZ)}"
test ! -e "$run_root"
for design in adder mux2 counter shift2; do
    "${RTL2MC_PYTHON:-python3}" rtl2mc.py run -f "examples/rtl/$design.f" \
        --synth "${RTL2MC_TEST_SYNTH:-yosys}" --sim "${RTL2MC_TEST_SIM:-icarus}" \
        --minecraft-version 1.21.1 --out "$run_root/$design"
done
"${RTL2MC_PYTHON:-python3}" tools/check_gametest.py "$run_root/adder" "$run_root/mux2" \
    "$run_root/counter" "$run_root/shift2" --out "$run_root/gametest" --negative-control
