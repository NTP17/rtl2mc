"""Read Liberty in Yosys and compare real HDL/SDF simulation to Minecraft traces."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redstone_pdk.cells import LIBRARY, ADMISSION, validate_cells
from redstone_pdk.cell_views import PREFIX, render_sdf
from redstone_pdk.project import read_json
from eda_tools import runtime

WORK = ROOT / ".local/eda/checks"
OUT = ROOT / "validation/cell-eda"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(argv, env, *, expected_failure=None, allowed_warnings=(), timeout=180):
    result = subprocess.run(list(map(str, argv)), cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    output = result.stdout + result.stderr
    if expected_failure:
        if result.returncode == 0 or expected_failure not in output:
            raise ValueError(f"Expected rejection {expected_failure!r} not observed: {output}")
    elif result.returncode:
        raise ValueError(f"EDA command failed ({result.returncode}): {output}")
    elif any(re.search(r"\b(?:warning|error)\s*(?::|-?\[)|^%Warning|^%Error", line, re.I) and not line.endswith(allowed_warnings)
             for line in output.splitlines()):
        raise ValueError("EDA command emitted an unreviewed diagnostic: " + output)
    return output


def trace_bench(fixtures, observations):
    lines = ["`timescale 1ns/1ps", "module trace_tb;", f"  integer remaining = {len(fixtures)};",
             "`ifndef NO_ANNOTATE", '  initial $sdf_annotate("validation/cell-eda/traces.sdf", trace_tb);', "`endif"]
    instances = {}
    comparisons = 0
    for index, f in enumerate(fixtures):
        name = f"u{index}"
        rows = observations[f["id"]]
        instances[name] = f["experiment"]["cell"]
        a0 = rows[0]["values"]["input"] // 15
        lines += [f"  reg a{index} = 1'b{a0};", f"  wire y{index};", f"  {instances[name]} {name} (.A(a{index}), .Y(y{index}));", "  initial begin", "    #19.999;"]
        def check(row):
            nonlocal comparisons
            comparisons += 2
            a, y = row["values"]["input"] // 15, row["values"]["out"] // 15
            return (f"    if (a{index} !== 1'b{a} || y{index} !== 1'b{y}) "
                    f'$fatal(1, "RS_TRACE: {f["id"]} sample {row["sample_index"]} A=%b Y=%b", a{index}, y{index});')
        lines += [check(rows[0]), "    #0.001;"]
        by_tick = {}
        for row in rows[1:]:
            by_tick.setdefault(row["relative_game_tick"], []).append(row)
        for tick in range(f["ticks"] + 1):
            # #0 waits for current-time path updates before the command phase.
            lines.append("    #0;")
            before = [r for r in by_tick[tick] if r["phase"] == "before_action"]
            if before:
                lines.append(check(before[0]))
            after = by_tick[tick][-1]
            if str(tick) in f["actions"]:
                a = after["values"]["input"] // 15
                lines.append(f"    a{index} = 1'b{a};")
            lines += ["    #0.001;", check(after), "    #0.999;"]
        lines += ["    remaining = remaining - 1;", '    if (remaining == 0) begin $display("RS_TRACE_PASS"); $finish; end', "  end"]
    lines += ['  initial begin #1000; $fatal(1, "RS_TRACE: timeout"); end', "endmodule", ""]
    return "\n".join(lines), instances, comparisons


def main():
    errors = validate_cells(include_eda=False)
    if errors:
        raise ValueError("\n".join(errors))
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    toolset = runtime()
    env, ivl, vvp = toolset["env"], toolset["iverilog"], toolset["vvp"]
    if os.name == "nt":
        ctypes.windll.kernel32.SetErrorMode(0x8003)
    yosys = toolset["yosys"]
    versions = {"yosys": command([*yosys, "-V"], env).strip(), "iverilog": command([ivl, "-V"], env).splitlines()[0]}
    lib = read_json(ROOT / LIBRARY)
    admission = read_json(ROOT / ADMISSION)
    run = ROOT / admission["evidence"]["run"]
    fixtures = read_json(run / "fixtures.json")
    observations = {}
    for line in (run / "observations.jsonl").read_text().splitlines():
        row = json.loads(line)
        observations.setdefault(row["case"], []).append(row)
    bench, instances, comparisons = trace_bench(fixtures, observations)
    (OUT / "traces.sv").write_text(bench, encoding="utf-8")
    (OUT / "traces.sdf").write_text(render_sdf(lib, instances, "trace_tb"), encoding="utf-8")
    logs = {}
    yp = toolset["yosys_path_prefix"]
    ys = f"read_liberty {yp}{PREFIX}repeater-buffers.lib; write_json {yp}validation/cell-eda/yosys-library.json; write_verilog -noattr {yp}validation/cell-eda/yosys-library.v"
    logs["yosys-liberty.log"] = command([*yosys, "-Q", "-T", "-p", ys], env)
    imported = read_json(OUT / "yosys-library.json")["modules"]
    if set(imported) != {c["name"] for c in lib["cells"]}:
        raise ValueError("Yosys did not import exactly the four cells")
    for c in imported.values():
        if set(c["ports"]) != {"A", "Y"} or c["ports"]["A"]["direction"] != "input" or c["ports"]["Y"]["direction"] != "output":
            raise ValueError("Yosys Liberty port interface differs")
    def simulate(label, sources, defines=(), failure=None):
        target = WORK / (label + ".vvp")
        build = command([ivl, "-g2012", "-gspecify", "-s", "trace_tb", *["-D" + d for d in defines], "-o", target, *sources], env,
                        allowed_warnings=("warning: Timing checks are not supported.",))
        output = command([vvp, target], env, expected_failure=failure,
                         allowed_warnings=("TIMINGCHECK not supported.",))
        if not failure and "RS_TRACE_PASS" not in output:
            raise ValueError("Simulation ended without a success marker")
        logs[label + ".log"] = build + output
    model = ROOT / PREFIX / "repeater-buffers.sv"
    simulate("default-timing", [model, OUT / "traces.sv"], ["NO_ANNOTATE"])
    simulate("sdf-timing", [model, OUT / "traces.sv"], ["RS_SDF_ONLY"])
    simulate("missing-sdf-rejected", [model, OUT / "traces.sv"], ["RS_SDF_ONLY", "NO_ANNOTATE"], "RS_TRACE:")
    # Exhaustive Boolean inputs through the cells imported FROM Liberty.
    logic = ["`timescale 1ns/1ps", "module trace_tb;", "  reg [3:0] A; wire [3:0] Y; integer i;",
             "  buffer_bank dut(.A(A), .Y(Y));", "  initial begin",
             "    for (i=0; i<16; i=i+1) begin A=i; #1; if (Y !== A) $fatal(1, \"RS_LOGIC\"); end",
             '    $display("RS_TRACE_PASS"); $finish; end', "endmodule", ""]
    (OUT / "logic.sv").write_text("\n".join(logic), encoding="utf-8")
    simulate("liberty-logic", [OUT / "yosys-library.v", ROOT / PREFIX / "buffer-bank.v", OUT / "logic.sv"])
    simulate("functional-logic", [ROOT / PREFIX / "repeater-buffers-functional.v", ROOT / PREFIX / "buffer-bank.v", OUT / "logic.sv"])
    # Confirm instance scoping of the shipped example SDF, not just traces.sdf.
    bank_tb = ["`timescale 1ns/1ps", "module trace_tb; reg [3:0] A=0; wire [3:0] Y;", "buffer_bank dut(.A(A),.Y(Y));",
               f'initial $sdf_annotate("{PREFIX}buffer-bank.sdf", dut);', "initial begin #20; A=15;"]
    previous = 0
    for tick, y in ((2, 1), (4, 3), (6, 7), (8, 15)):
        bank_tb += [f"#{tick - previous}; #0; if (Y !== 4'd{y}) $fatal(1, \"RS_BANK\");"]
        previous = tick
    bank_tb += ['#1; $display("RS_TRACE_PASS"); $finish; end endmodule', ""]
    (OUT / "bank.sv").write_text("\n".join(bank_tb), encoding="utf-8")
    simulate("example-sdf", [model, ROOT / PREFIX / "buffer-bank.v", OUT / "bank.sv"], ["RS_SDF_ONLY"])
    negatives = {"short-high": "#20; A=1; #8; A=0;", "short-low": "#20; A=1; #9; A=0; #8; A=1;",
                 "fractional-tick": "#20.5; A=1;", "unknown-input": "#20; A=1'bx;",
                 "missing-settle": "#19; A=1;", "early-edge": "#0.001; A=1;",
                 "same-tick": "#20; A=1; #0; A=0;"}
    for label, stimulus in negatives.items():
        tb = f"`timescale 1ns/1ps\nmodule trace_tb; reg A=0; wire Y; RSBUF8 dut(.A(A),.Y(Y)); initial begin {stimulus} #20; $fatal(1, \"GUARD_DID_NOT_REJECT\"); end endmodule\n"
        file = OUT / (label + ".sv")
        file.write_text(tb, encoding="utf-8")
        simulate(label, [model, file], failure="RS_PROTOCOL:")
    for name, content in logs.items():
        (OUT / name).write_text(content, encoding="utf-8")
    inputs = [LIBRARY, ADMISSION, "tools/check_cell_eda.py", "tools/eda_tools.py", "tools/cell-eda-packages.json", "tools/cell-eda-requirements.txt"]
    inputs += [p.relative_to(ROOT).as_posix() for p in (ROOT / PREFIX).rglob("*") if p.is_file()]
    outputs = [p.relative_to(ROOT).as_posix() for p in OUT.iterdir() if p.is_file() and p.name != "report.json"]
    report = {"schema_version": 1, "pass": True, "tools": versions, "minecraft_run": admission["evidence"]["run"],
              "trace_cases": len(fixtures), "port_value_comparisons_per_timing_mode": comparisons,
              "timing_modes": ["default_specify", "SDF_only_zero_defaults"], "liberty_cells": len(imported),
              "boolean_vectors_per_functional_view": 16, "shipped_example_sdf": "pass",
              "expected_rejections": ["missing-sdf", *negatives],
              "inputs_sha256": {p: sha(ROOT / p) for p in inputs}, "evidence_sha256": {p: sha(ROOT / p) for p in outputs},
              "limitations": ["Yosys checks logical Liberty import; it is not a static timing analyzer",
                              "Icarus explicitly warns that specify timing checks and SDF TIMINGCHECK are unsupported; warnings are retained in logs",
                              "IOPATH delays are exercised; SDF WIDTH enforcement is not claimed for Icarus",
                              "The procedural guard independently enforces the fixed admitted timing protocol",
                              "No interconnect, electrical slew/load, PVT, or physical composition validation"]}
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    text = ["# Cell EDA validation", "", "All checks passed for the generated guarded buffer views.", "",
            f"- {versions['yosys']}", f"- {versions['iverilog']}",
            f"- Default specify timing and SDF with zero path defaults each match **{len(fixtures)} Minecraft traces / {comparisons:,} A/Y value comparisons**.",
            "- Yosys imports all four Liberty cells; the imported logic and the functional Verilog each pass all 16 input vectors.",
            "- The shipped four-instance example SDF produces output transitions at 2, 4, 6 and 8 scaled time units.",
            "- Missing SDF fails the trace comparison. Short high/low intervals, fractional ticks, X input, insufficient settling and same-tick changes are rejected by the input guard.", "",
            "Yosys import validates logical compatibility, not full STA or timing-table semantics. Icarus executes the IOPATH delays in this test; its SDF WIDTH/timing-check enforcement is not relied on. The separate procedural guard enforces the fixed native input protocol. No electrical or routed-circuit characterization is implied.", "",
            "[Machine-readable report and evidence hashes](../validation/cell-eda/report.json). Test sources, annotated SDF, Yosys-imported logic and logs are alongside it. Re-run with `python tools/check_cell_eda.py` after installing the pinned tools below.", "", "```powershell",
            "python -m pip install --target .local/eda/python --require-hashes -r tools/cell-eda-requirements.txt",
            "python tools/fetch_cell_eda.py", "python tools/check_cell_eda.py", "```", "",
            "Native tools in C:/msys64/ucrt64 are preferred (override with SV2RT_UCRT_ROOT). The project-local downloads above are fallbacks; no global installation is modified. Versions used for this run appear above.", ""]
    (ROOT / "docs/repeater-cells-eda.md").write_text("\n".join(text), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("inputs_sha256", "evidence_sha256")}, indent=2))


if __name__ == "__main__":
    main()
