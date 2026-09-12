"""Synthesize four small designs into RMAP cells and check them with licensed VCS.

Run with the modules in eda/synopsys/run.sh loaded. No Yosys, Icarus or Minecraft
server is required. Every run uses a new directory so stale outputs cannot pass.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redstone_pdk.mapping_controls import artifacts

DESIGNS = {
    "adder": {"inputs": ["a", "b", "cin"], "outputs": [("cout", 1), ("sum", 1)]},
    "mux2": {"inputs": ["a", "b", "select_b"], "outputs": [("y", 1)]},
    "counter": {"inputs": ["reset", "enable"], "outputs": [("q", 2)]},
    "shift2": {"inputs": ["reset", "enable", "serial_in"], "outputs": [("q", 2)]},
}
RMAP_CELLS = {"RMAP_" + k for k in ("NOR2", "INV", "DFF", "BUF2", "BUF4", "BUF6", "BUF8")}
REVIEWED_WARNINGS = (
    (r"^Warning: Line 1, The 'default_(?:fanout_load|inout_pin_cap)' attribute is not specified\. Using 1\.00\. \(LBDB-172\)$",
     "Library Compiler uses documented placeholder defaults; neither represents Minecraft electrical loading."),
    (r"^Warning: In design 'counter', cell '[^']+' does not drive any nets\. \(LINT-1\)$",
     "Unused intermediate logic before optimization; the post-synthesis check must be clean."),
)


def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def dump(path, value):
    write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vectors(top):
    """Independent integer truth/transition models; no simulator-derived oracle."""
    spec = DESIGNS[top]
    rows = []
    if top in ("adder", "mux2"):
        for before, after in itertools.product(range(8), repeat=2):
            for value in (before, after):
                inputs = {name: (value >> i) & 1 for i, name in enumerate(spec["inputs"])}
                expected = sum(inputs.values()) if top == "adder" else inputs["b"] if inputs["select_b"] else inputs["a"]
                rows.append({"inputs": inputs, "expected": expected})
        return rows, {"input_combinations": 8, "ordered_input_pairs": 64}

    state = 0
    transitions = set()

    def add(reset=0, enable=0, serial_in=0):
        nonlocal state
        inputs = {"reset": reset, "enable": enable}
        if top == "shift2":
            inputs["serial_in"] = serial_in
        transitions.add((state, *inputs.values()))
        if reset:
            state = 0
        elif enable:
            state = (state + 1) % 4 if top == "counter" else (state * 2 + serial_in) % 4
        rows.append({"inputs": inputs, "expected": state})

    # Reset reaches a known state through the hardware; no force/init on flops.
    add(reset=1)
    add(reset=1)
    for start in range(4):
        for control in itertools.product(range(2), repeat=len(spec["inputs"])):
            add(reset=1)
            if top == "counter":
                for _ in range(start):
                    add(enable=1)
            else:
                add(enable=1, serial_in=start >> 1)
                add(enable=1, serial_in=start & 1)
            assert state == start
            add(**dict(zip(spec["inputs"], control)))
    # Sustained operation, wraparound, hold, and reset priority sequences.
    for _ in range(16):
        add(enable=1, serial_in=1)
    for _ in range(8):
        add(enable=0)
    rng = random.Random(0x5A2)
    for _ in range(256):
        add(reset=int(rng.randrange(16) == 0), enable=rng.randrange(2), serial_in=rng.randrange(2))
    expected_coverage = set(itertools.product(range(4), *([range(2)] * len(spec["inputs"]))))
    assert transitions == expected_coverage
    return rows, {"states": 4, "state_control_combinations": len(transitions), "random_cycles": 256, "seed": 0x5A2}


def bench(top, rows):
    spec = DESIGNS[top]
    sequential = top in ("counter", "shift2")
    iw, ow = len(spec["inputs"]), sum(w for _, w in spec["outputs"])
    lines = ["`timescale 1ns/1ps", "module simple_tb;"]
    if sequential:
        lines.append("  reg clk = 0;")
    lines.extend(f"  reg {n} = 0;" for n in spec["inputs"])
    for name, width in spec["outputs"]:
        lines.append(f"  wire [{width-1}:0] gold_{name}, gate_{name};")
    for suffix, inst in (("", "gold"), ("_gate", "dut")):
        pins = ([".clk(clk)"] if sequential else []) + [f".{n}({n})" for n in spec["inputs"]]
        prefix = "gold" if inst == "gold" else "gate"
        pins.extend(f".{n}({prefix}_{n})" for n, _ in spec["outputs"])
        lines.append(f"  {top}{suffix} {inst}({', '.join(pins)});")
    lines += [f"  reg [{iw+ow-1}:0] vector_mem [0:{len(rows)-1}];", f"  reg [{ow-1}:0] previous;"]
    for prefix in ("gold", "gate"):
        expr = ", ".join(prefix + "_" + n for n, _ in spec["outputs"])
        lines.append(f"  wire [{ow-1}:0] {prefix}_value = {{{expr}}};")
    lines += [
        "  integer i, observations = 0;",
        "  initial begin",
        "`ifdef USE_SDF",
        '    $sdf_annotate("netlist.sdf", dut, , "sdf.log", "MAXIMUM");',
        "`endif",
        "  end",
        f"  task automatic check_value(input logic [{ow-1}:0] expected);",
        "    if (gold_value !== expected || gate_value !== expected)",
        f'      $fatal(1, "RMAP_DESIGN_MISMATCH {top} row=%0d t=%0t expected=%h rtl=%h gate=%h", i, $time, expected, gold_value, gate_value);',
        "    observations++;",
        "  endtask",
        "  initial begin",
        '    $dumpfile("wave.vcd"); $dumpvars(0, simple_tb);',
        '    $readmemh("vectors.hex", vector_mem);',
        f"    for (i = 0; i < {len(rows)}; i++) begin",
        f"      {{{', '.join(spec['inputs'])}}} = vector_mem[i][{iw+ow-1}:{ow}];",
    ]
    if sequential:
        lines += ["      #1000;", "      if (i > 0) check_value(previous);", "      clk = 1;", "      #999.999;"]
    else:
        lines.append("      #1000;")
    lines += [f"      check_value(vector_mem[i][{ow-1}:0]);", f"      previous = vector_mem[i][{ow-1}:0];"]
    if sequential:
        lines.append("      #0.001; clk = 0;")
    lines += ["    end", f'    $display("RMAP_DESIGN_PASS {top} vectors={len(rows)} observations=%0d", observations);', "    $finish;", "  end",
              f'  initial begin #{len(rows)*2000+10000}; $fatal(1, "RMAP_TIMEOUT"); end', "endmodule", ""]
    return "\n".join(lines)


def execute(folder, name, command, *, marker=None, env=None, failure=False, timing=False, allowed_returncodes=(0,)):
    print(f"{folder.name}: {name}", flush=True)
    logpath = folder / (name + ".log")
    with logpath.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, text=True, timeout=1800)
    log = logpath.read_text()
    # Tcl echoes commands containing the marker; only a printed marker counts.
    found = marker is None or re.search(r"^" + re.escape(marker) + r"(?:\s|$)", log, re.M)
    errors = re.findall(r"^(?:Error(?:-|:)|Fatal:|FATAL:).*$", log, re.M)
    warnings = re.findall(r"^(?:Warning(?:-|:)).*$", log, re.M)
    if failure:
        # VCS can return zero after $fatal. Require the intended failure itself.
        found = (marker in log and len(errors) == 1 and errors[0].startswith("Fatal:")
                 and "RMAP_DESIGN_PASS" not in log and "RMAP_ARCS_PASS" not in log)
    elif result.returncode not in allowed_returncodes:
        found = False
    reviews = []
    for warning in warnings:
        reason = next((why for pattern, why in REVIEWED_WARNINGS if re.fullmatch(pattern, warning)), None)
        if reason is None:
            raise RuntimeError(f"Unreviewed warning in {logpath}: {warning}")
        reviews.append({"diagnostic": warning, "review": reason})
    if not found or (errors and not failure) or (bool(re.search("timing violation", log, re.I)) != timing):
        raise RuntimeError(f"{name} failed; inspect {logpath}\n{log[-1800:]}")
    return {"pass": True, "returncode": result.returncode, "expected_failure": failure,
            "command": command, "log": logpath.name, "log_sha256": digest(logpath),
            "warnings": reviews, "expected_diagnostics": errors if failure else []}


def annotation_coverage(work, sdf_name):
    sdf_text = (work / sdf_name).read_text()
    coverage_path = work / "sdfAnnotateInfo"
    coverage = coverage_path.read_text()
    annotated, static = coverage.split("# Annotated entries in elaborated design:")[1].split("# Static entries in elaborated design:")

    def count(text, label):
        found = re.findall(re.escape(label) + r"\s*=\s*(\d+)", text)
        return int(found[0]) if len(found) == 1 else 0

    paths = len(re.findall(r"\(IOPATH\s", sdf_text))
    wires = len(re.findall(r"\(INTERCONNECT\s", sdf_text))
    timing = len(re.findall(r"\((?:SETUP|HOLD|WIDTH)\s", sdf_text))
    # VCS reports the two internal halves of SETUPHOLD separately.
    timing += 2 * len(re.findall(r"\(SETUPHOLD\s", sdf_text))
    if paths == 0 or paths != count(annotated, "IOPATH Delays") or paths != count(static, "IOPATH Delays"):
        raise RuntimeError(f"Incomplete IOPATH annotation: {coverage_path}")
    if wires != count(annotated, "INTERCONNECT(MSID)"):
        raise RuntimeError(f"Incomplete interconnect annotation: {coverage_path}")
    if timing != count(annotated, "Timing Checks") or timing != count(static, "Timing Checks"):
        raise RuntimeError(f"Incomplete timing-check annotation: {coverage_path}")
    return {"annotated_iopaths": paths, "annotated_interconnects": wires, "annotated_timing_checks": timing,
            "coverage_log": coverage_path.name, "coverage_log_sha256": digest(coverage_path)}


def simulate(folder, mode, *, top="simple_tb", bench_file="tb.sv", cells="cells-timing.sv", netlist="netlist.v", marker=None, defines=(), failure=False, timing=False):
    work = folder / mode
    work.mkdir()
    for name in (bench_file, cells, netlist, "source.sv", "vectors.hex", "netlist.sdf", "arc.sdf"):
        if name and (folder / name).is_file():
            shutil.copy2(folder / name, work / name)
    sources = [cells, bench_file]
    if netlist:
        sources += [netlist, "source.sv"]
    command = ["vcs", "-full64", "-sverilog", "-timescale=1ns/1ps", "-top", top,
               *["+define+" + d for d in defines], "+sdfverbose", *sources, "-o", "simv"]
    compiled = execute(work, "compile", command)
    ran = execute(work, "simulate", ["./simv", "+sdfverbose"], marker=marker, failure=failure, timing=timing)
    result = {"compile": compiled, "simulation": ran}
    if "RMAP_SDF_ONLY" in defines and "NO_ANNOTATE" not in defines:
        logfile = work / "sdf.log"
        log = logfile.read_text()
        for label in ("errors", "warnings"):
            totals = re.findall(r"Total " + label + r":\s+(\d+)", log)
            if totals != ["0"]:
                raise RuntimeError(f"Missing or nonzero SDF {label} summary: {logfile}")
        if "SDF annotation completed" not in log:
            raise RuntimeError(f"SDF annotation did not complete: {logfile}")
        result["annotation"] = {
            "pass": True, "errors": 0, "warnings": 0,
            "log": logfile.name, "log_sha256": digest(logfile),
            **annotation_coverage(work, "netlist.sdf" if netlist else "arc.sdf"),
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "builds" / datetime.now(timezone.utc).strftime("synopsys-%Y%m%dT%H%M%SZ"))
    args = parser.parse_args(argv)
    out = args.out.resolve()
    if out.exists():
        raise ValueError(f"Use a fresh output directory: {out}")
    for name in ("lc_shell", "dc_shell", "vcs"):
        if not shutil.which(name):
            raise ValueError(f"Missing {name}; load the modules using eda/synopsys/run.sh")
    out.mkdir(parents=True)
    report = {"pass": False, "started_utc": datetime.now(timezone.utc).isoformat(), "designs": {},
              "scope": "Fresh DC RTL synthesis into RMAP cells; VCS RTL/reference comparison and functional/SDF gate-level simulation. DC interconnect delays are zero; no new Minecraft placement or measurement.",
              "time_unit": "1 simulation ns = 1 Minecraft game tick", "formal_equivalence": "not_run",
              "modules": ["synopsys/libraryCompiler/V-2023.12", "synopsys/syn/V-2023.12", "synopsys/vcs/X-2025.06"],
              "python": sys.version, "tools": {}, "controls": {},
              "implementation_sha256": {name: digest(ROOT / name) for name in (
                  "tools/check_synopsys.py", "eda/synopsys/run.sh", "eda/synopsys/simple_designs.tcl",
                  "eda/synopsys/library_compiler.tcl", "redstone_pdk/mapping_controls.py")}}
    try:
        for name, option in (("dc_shell", "-version"), ("lc_shell", "-version"), ("vcs", "-ID")):
            # This DC release returns 1 for a successful -version query.
            execute(out, name + "-version", [name, option],
                    marker="vcs script version" if name == "vcs" else name + " version",
                    allowed_returncodes=(0, 1) if name == "dc_shell" else (0,))
            report["tools"][name] = {"path": shutil.which(name), "version_log": name + "-version.log"}
        lib = out / "library"
        lib.mkdir()
        shutil.copy2(ROOT / "views/rtl-mapping/mapping.lib", lib / "mapping.lib")
        shutil.copy2(ROOT / "eda/synopsys/library_compiler.tcl", lib / "library_compiler.tcl")
        report["library"] = execute(lib, "lc", ["lc_shell", "-f", "library_compiler.tcl"], marker="RMAP_LIBRARY_COMPILE_DONE")
        if not (lib / "mapping.db").is_file():
            raise RuntimeError("LC did not write mapping.db")
        report["library"]["liberty_sha256"] = digest(lib / "mapping.lib")
        report["library"]["db_sha256"] = digest(lib / "mapping.db")

        for top, spec in DESIGNS.items():
            folder = out / top
            folder.mkdir()
            shutil.copy2(ROOT / "examples/rtl" / (top + ".sv"), folder / "source.sv")
            shutil.copy2(ROOT / "eda/synopsys/simple_designs.tcl", folder / "synthesis.tcl")
            for mode in ("functional", "timing"):
                shutil.copy2(ROOT / "views/rtl-mapping" / f"cells-{mode}.sv", folder / f"cells-{mode}.sv")
            rows, coverage = vectors(top)
            dump(folder / "vectors.json", {"coverage": coverage, "vectors": rows})
            ow = sum(w for _, w in spec["outputs"])
            packed = []
            for row in rows:
                value = 0
                for name in spec["inputs"]:
                    value = (value << 1) | row["inputs"][name]
                packed.append(f"{(value << ow) | row['expected']:x}")
            write(folder / "vectors.hex", "\n".join(packed) + "\n")
            write(folder / "tb.sv", bench(top, rows))
            observations = 2 * len(rows) - 1 if top in ("counter", "shift2") else len(rows)
            result = {"source": f"examples/rtl/{top}.sv", "vectors": len(rows), "coverage": coverage,
                      "observations_per_mode": observations, "comparisons_per_mode": 2 * observations}
            report["designs"][top] = result
            result["synthesis"] = execute(folder, "dc", ["dc_shell", "-f", "synthesis.tcl"], marker="RMAP_SYNTHESIS_EXPORT_DONE", env={**os.environ, "RMAP_TOP": top})
            cell_counts = Counter(line.split()[0] for line in (folder / "cells.tsv").read_text().splitlines())
            if not cell_counts or not set(cell_counts) <= RMAP_CELLS:
                raise RuntimeError("Empty or unsupported mapped cell inventory")
            if cell_counts.get("RMAP_DFF", 0) != (2 if top in ("counter", "shift2") else 0):
                raise RuntimeError("Unexpected register count")
            result["cells"] = dict(sorted(cell_counts.items()))
            result["cell_count"] = sum(cell_counts.values())
            if (folder / "check_design.rpt").read_text().strip() != "1":
                raise RuntimeError("Post-synthesis check_design report is not clean")
            if "This design has no violated constraints." not in (folder / "constraints.rpt").read_text():
                raise RuntimeError("Synthesis constraint violations require review")
            for name in ("netlist.v", "netlist.sdf", "source.sv", "tb.sv", "vectors.json", "cells-functional.sv", "cells-timing.sv"):
                result[name + "_sha256"] = digest(folder / name)
            marker = f"RMAP_DESIGN_PASS {top} vectors={len(rows)} observations={observations}"
            result["functional"] = simulate(folder, "functional", cells="cells-functional.sv", marker=marker)
            result["sdf"] = simulate(folder, "sdf", defines=("RMAP_SDF_ONLY", "USE_SDF"), marker=marker)
            result["pass"] = True
            dump(out / "report.json", report)

        controls = out / "controls"
        controls.mkdir()
        shutil.copy2(ROOT / "views/rtl-mapping/cells-timing.sv", controls / "cells-timing.sv")
        for name, content in artifacts().items():
            # Keep the annotation diagnostic log separate from VCS's coverage table.
            if name.endswith(".sv"):
                content = content.replace('$sdf_annotate("arc.sdf",dut);',
                                          '$sdf_annotate("arc.sdf",dut, ,"sdf.log","MAXIMUM");')
            write(controls / name, content)
        for mode, top, marker, defs, failure, timing in (
            ("arcs", "arc_tb", "RMAP_ARCS_PASS", ("RMAP_SDF_ONLY",), False, False),
            ("missing_sdf", "arc_tb", "RMAP_ARC_MISMATCH", ("RMAP_SDF_ONLY", "NO_ANNOTATE"), True, False),
            ("width", "width_tb", "RMAP_WIDTH_CAUGHT", ("RMAP_SDF_ONLY",), False, True),
        ):
            report["controls"][mode] = simulate(controls, mode, top=top, bench_file="arc-bench.sv", netlist=None,
                                                     marker=marker, defines=defs, failure=failure, timing=timing)
        report["pass"] = True
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        dump(out / "report.json", report)
    print(f"RMAP_SYNOPSYS_PASS: {out / 'report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
