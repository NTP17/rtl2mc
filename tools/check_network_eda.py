"""Exercise checked routed networks in real synthesis import and timed HDL tools."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redstone_pdk.project import read_json
from redstone_pdk.connections import CONTRACT, validate_connections
from redstone_pdk.connection_views import PREFIX, CELL_NAMES, top_name, cell_name, sdf
from redstone_pdk.model_validation import sha
from eda_tools import runtime
from check_cell_eda import command

OUT = ROOT / "validation/network-eda"
WORK = ROOT / ".local/eda/network-checks"


def check_topology(module, record):
    """Verify the actual linked graph and names used by SDF and placement."""
    nodes = record["graph"]["nodes"]
    ports = module["ports"]
    if set(ports) != {"A", "Q"} or ports["A"]["direction"] != "input" or ports["Q"]["direction"] != "output":
        raise ValueError("Exported top-level ports differ")
    a, q = ports["A"]["bits"], ports["Q"]["bits"]
    if len(a) != 1 or len(q) != len(nodes) or len(set(a+q)) != len(a+q) or any(type(b) is not int for b in a+q):
        raise ValueError("Exported nets were aliased, folded, or resized")
    cells = module.get("cells", {})
    if set(cells) != {n["id"] for n in nodes}:
        raise ValueError("Exported cell names/count differ; SDF/placement certificate invalid")
    for n in nodes:
        cell = cells[n["id"]]
        parent = a if n["parent"] == "source" else [q[int(n["parent"][1:])]]
        if cell["type"] != cell_name(n) or cell.get("parameters") or cell["connections"] != {"A": parent, "Y": [q[int(n['id'][1:])]]}:
            raise ValueError("Exported cell type or connectivity differs; recharacterize the physical route")
        if cell.get("port_directions") != {"A": "input", "Y": "output"}:
            raise ValueError("Missing linked cell port directions")


def trace_bench(records, observations, fixtures):
    artifacts, comparisons, sample_count = {}, 0, 0
    lines = ["`timescale 1ns/1ps", "`default_nettype none", "module network_tb;",
             f"  wire [{len(records)-1}:0] done;"]
    for index, r in enumerate(records):
        name, graph = r["fixture"], r["graph"]
        nodes = graph["nodes"]
        # Probe lookup is by physical diode position, never fixture-role naming.
        fs = fixtures[name]
        probe = {tuple(p["position"]): p["name"] for p in fs["probes"] if p["property"] == "powered"}
        rows = [row for row in observations[name] if row["phase"] != "before_action"]
        values = []
        for row in rows:
            packed = row["values"]["input"] // 15
            for n in nodes:
                packed |= row["values"][probe[tuple(n["position"])]] << (int(n["id"][1:])+1)
            values.append(f"{packed:x}")
        filename = f"validation/network-eda/vectors/{name}.mem"
        artifacts[filename] = "\n".join(values)+"\n"
        comparisons += len(rows)*(len(nodes)+1)
        sample_count += len(rows)
        lines += [f"  if (1) begin:g{index}", f"    reg a=1'b{graph['initial']};",
                  f"    wire [{len(nodes)-1}:0] q;", "    reg finished=0;", f"    assign done[{index}]=finished;",
                  f"    {top_name(r)} dut(.A(a),.Q(q));",
                  f"    rnet_input_guard #(.MIN_DWELL({graph['minimum_dwell']}), .INITIAL_SETTLE({graph['initial_settle']})) guard(.A(a));",
                  "`ifndef NO_ANNOTATE", f'    initial $sdf_annotate("{PREFIX}sdf/{name}.sdf", dut);', "`endif",
                  f"    reg [{len(nodes)}:0] expected[0:{len(rows)-1}];", "    integer k;", "    initial begin",
                  f'      $readmemh("{filename}",expected);', "      #63.999;",
                  f'      if ({{q,a}} !== expected[0]) $fatal(1,"RNET_TRACE: {name} initial state got=%b expected=%b",{{q,a}},expected[0]);', "      #0.002;",
                  f"      for (k=1; k<{len(rows)}; k=k+1) begin",
                  f'        if ({{q,a}} !== expected[k]) $fatal(1,"RNET_TRACE: {name} tick=%0d got=%b expected=%b",k-1,{{q,a}},expected[k]);',
                  "        #1;", "      end", "      finished=1;", "    end", "    initial begin"]
        previous = -64
        for tick, value in graph["transitions"]:
            lines += [f"      #{tick-previous}; a=1'b{value};"]
            previous = tick
        lines += ["    end", "  end"]
    lines += [f'  initial begin wait (&done); $display("RNET_TRACE_PASS cases={len(records)} comparisons={comparisons}"); $finish; end',
              '  initial begin #1000; $fatal(1,"RNET_TRACE: timeout"); end', "endmodule", "`default_nettype wire", ""]
    artifacts["validation/network-eda/traces.sv"] = "\n".join(lines)
    return artifacts, comparisons, sample_count


def main():
    errors = validate_connections(include_eda=False)
    if errors:
        raise ValueError("\n".join(errors))
    OUT.mkdir(parents=True, exist_ok=True); WORK.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        ctypes.windll.kernel32.SetErrorMode(0x8003)
    t = runtime(); env = t["env"]
    contract = read_json(ROOT / CONTRACT)
    run = ROOT / contract["evidence"]["run"]
    fixtures = {f["id"]: f for f in read_json(run / "fixtures.json")}
    observed = {}
    for line in (run / "observations.jsonl").read_text().splitlines():
        row = json.loads(line); observed.setdefault(row["case"], []).append(row)
    records = [r for r in contract["cases"] if r["admitted"]]
    artifacts, comparisons, samples = trace_bench(records, observed, fixtures)
    for name, value in artifacts.items():
        p = ROOT / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value, encoding="utf-8")
    logs = {}
    versions = {"yosys": command([*t["yosys"], "-V"], env).strip(),
                "iverilog": command([t["iverilog"], "-V"], env).splitlines()[0]}
    yp = t["yosys_path_prefix"]
    netlist_files = [PREFIX+f"netlists/{r['fixture']}.v" for r in records]
    ys = f"read_liberty -lib {yp}{PREFIX}cells.lib; read_verilog " + " ".join(yp+p for p in netlist_files)
    ys += f"; hierarchy -check; write_json {yp}validation/network-eda/linked.json"
    logs["yosys-link.log"] = command([*t["yosys"], "-Q", "-T", "-p", ys], env)
    linked = read_json(OUT / "linked.json")["modules"]
    for record in records:
        check_topology(linked[top_name(record)], record)
    ys = f"read_liberty {yp}{PREFIX}cells.lib; write_verilog -noattr {yp}validation/network-eda/liberty-functional.v"
    logs["yosys-liberty.log"] = command([*t["yosys"], "-Q", "-T", "-p", ys], env)
    def simulate(label, sourcefile="cells-timing.sv", defines=(), failure=None, bench=None, all_nets=True):
        target = WORK / (label+".vvp")
        sources = [PREFIX+sourcefile, PREFIX+"input-guard.sv"]
        sources += netlist_files if all_nets else []
        sources += [bench or "validation/network-eda/traces.sv"]
        build = command([t["iverilog"], "-g2012", "-gspecify", "-ginterconnect", "-s", "network_tb",
                         *["-D"+s for s in defines], "-o", target, *sources], env,
                         allowed_warnings=("warning: Timing checks are not supported.",))
        output = command([t["vvp"], target], env, expected_failure=failure,
                         allowed_warnings=("TIMINGCHECK not supported.",))
        if not failure and "RNET_TRACE_PASS" not in output:
            raise ValueError("Network simulation ended without a pass marker")
        logs[label+".log"] = build+output
        print(label+": pass", flush=True)
    simulate("default-timing", defines=["NO_ANNOTATE"])
    simulate("sdf-timing", defines=["RNET_SDF_ONLY"])
    simulate("portable-timing", "cells-portable.sv", ["NO_ANNOTATE"])
    simulate("missing-sdf-rejected", defines=["RNET_SDF_ONLY", "NO_ANNOTATE"], failure="RNET_TRACE:")
    negatives = {"short-high": "#44; A=1; #8; A=0;", "short-low": "#44; A=1; #9; A=0; #8; A=1;",
                 "fractional-edge": "#44.5; A=1;", "unknown": "#44; A=1'bx;", "high-impedance": "#44; A=1'bz;",
                 "initial-settle": "#43; A=1;", "early-edge": "#0.001; A=1;", "same-tick": "#44; A=1; #0; A=0;"}
    for label, stimulus in negatives.items():
        bench = f"validation/network-eda/{label}.sv"
        (ROOT / bench).write_text('`timescale 1ns/1ps\nmodule network_tb; reg A=0; rnet_input_guard guard(.A(A));\n'
            +f'initial begin {stimulus} #80; $fatal(1,"GUARD_DID_NOT_REJECT"); end endmodule\n', encoding="utf-8")
        simulate(label, failure="RNET_PROTOCOL:", bench=bench, all_nets=False)
    # A one-tick injected route error must change actual timing. This exercises INTERCONNECT.
    first = records[0]
    bad_sdf = OUT / "route-fault.sdf"; bad_sdf.write_text(sdf(first, route_delay=1), encoding="utf-8")
    one_artifacts, _, _ = trace_bench([first], observed, fixtures)
    fault = one_artifacts["validation/network-eda/traces.sv"].replace(PREFIX+f"sdf/{first['fixture']}.sdf", "validation/network-eda/route-fault.sdf")
    (OUT / "route-fault.sv").write_text(fault, encoding="utf-8")
    simulate("interconnect-fault-rejected", defines=["RNET_SDF_ONLY"], failure="RNET_TRACE:", bench="validation/network-eda/route-fault.sv")
    # Exercise 0, 1, X and Z through both four-state functional views.
    logic = ['`timescale 1ns/1ps', 'module network_tb; reg A=0; wire [4:0] Y;']
    logic += [f'{n} u{i}(.A(A),.Y(Y[{i}]));' for i,n in enumerate(CELL_NAMES)]
    logic += ['initial begin #1; if(Y !== 5\'b00000) $fatal(1,"RNET_LOGIC");',
              'A=1; #1; if(Y !== 5\'b11111) $fatal(1,"RNET_LOGIC");',
              'A=1\'bx; #1; if(Y !== 5\'bxxxxx) $fatal(1,"RNET_LOGIC");',
              'A=1\'bz; #1; if(Y !== 5\'bxxxxx) $fatal(1,"RNET_LOGIC");',
              '$display("RNET_TRACE_PASS"); $finish; end endmodule', '']
    (OUT / "logic.sv").write_text("\n".join(logic), encoding="utf-8")
    simulate("functional-four-state", "cells-functional.v", bench="validation/network-eda/logic.sv", all_nets=False)
    # Yosys imports identity functions as assigns, so Z is preserved there; only binary truth is required for synthesis.
    binary_logic = "\n".join(logic).split("A=1'bx;")[0]+'$display("RNET_TRACE_PASS"); $finish; end endmodule\n'
    (OUT / "binary-logic.sv").write_text(binary_logic, encoding="utf-8")
    simulate("liberty-binary", "../../validation/network-eda/liberty-functional.v", bench="validation/network-eda/binary-logic.sv", all_nets=False)
    if not t["verilator"]:
        raise ValueError("Verilator is required for this qualification; set SV2RT_UCRT_ROOT")
    versions["verilator"] = command([*t["verilator"], "--version"], env).strip()
    args = [*t["verilator"], "--binary", "--timing", "-j", "2", "-Wno-DECLFILENAME", "--top-module", "network_tb",
            "--Mdir", ".local/eda/network-checks/verilator-o0", "--prefix", "Vnetwork", "+define+NO_ANNOTATE",
            "-MAKEFLAGS", "OPT_FAST=-O0 OPT_SLOW=-O0",
            PREFIX+"cells-portable.sv", PREFIX+"input-guard.sv", *netlist_files, "validation/network-eda/traces.sv"]
    print("Verilator timed build started", flush=True)
    logs["verilator-build.log"] = command(args, env, timeout=900)
    binary = WORK / "verilator-o0" / ("Vnetwork.exe" if os.name == "nt" else "Vnetwork")
    logs["verilator-timing.log"] = command([binary], env)
    if "RNET_TRACE_PASS" not in logs["verilator-timing.log"]:
        raise ValueError("Verilator did not complete the Minecraft comparison")
    for name, value in logs.items():
        (OUT / name).write_text(value, encoding="utf-8")
    inputs = [CONTRACT, "redstone_pdk/connection_views.py", "tools/check_network_eda.py", "tools/check_cell_eda.py", "tools/eda_tools.py"]
    inputs += [p.relative_to(ROOT).as_posix() for p in (ROOT / PREFIX).rglob("*") if p.is_file()]
    evidence = [p.relative_to(ROOT).as_posix() for p in OUT.rglob("*") if p.is_file() and p.name != "report.json"]
    report = {"schema_version": 1, "pass": True, "tools": versions, "trace_cases": len(records),
              "minecraft_run": contract["evidence"]["run"], "observation_boundaries_per_mode": samples,
              "port_value_comparisons_per_mode": comparisons,
              "modes": ["Icarus default specify", "Icarus SDF zero defaults", "Icarus portable delays", "Verilator portable delays"],
              "linked_topologies_checked": len(records), "linked_cell_instances": sum(len(r["graph"]["nodes"]) for r in records),
              "liberty_cells": len(CELL_NAMES), "interconnect_fault_rejected": True,
              "expected_rejections": ["missing SDF", "nonzero route fault", *negatives],
              "inputs_sha256": {p: sha(ROOT / p) for p in inputs}, "evidence_sha256": {p: sha(ROOT / p) for p in evidence},
              "commercial_tools": {name: "adapter supplied; execution unverified" for name in ("VCS", "Questa", "Xcelium", "Library Compiler", "Design Compiler", "Genus")},
              "limits": ["EDA compares baseline and post-boundary A/diode-Q values; before-action phases and wire strengths are checked by native admission",
                         "Initial hold normalized to 64 ticks before the recorded stimulus; same settled state",
                         "Icarus does not execute WIDTH timing checks; procedural guards are tested separately",
                         "Verilator ignores specify/SDF timing checks and is mostly two-state; it uses the separate portable delay view",
                         "Synthesis import/link is not unrestricted technology mapping or electrical STA qualification"]}
    (OUT / "report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("pass", "tools", "trace_cases", "port_value_comparisons_per_mode", "linked_cell_instances")}, indent=2))


if __name__ == "__main__":
    main()
