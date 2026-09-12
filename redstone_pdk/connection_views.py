"""Portable, instance-exact EDA and placement views for admitted networks."""
import json

from .project import ROOT
from .model_validation import digest, sha

PREFIX = "views/buffer-network/"
CELL_NAMES = [f"RNETBUF{d}" for d in (2, 4, 6, 8)] + ["RNETCMP2"]
EXAMPLE = "net_fanout3_d4_q1"


def cell_name(node):
    return "RNETCMP2" if node["kind"] == "comparator" else f"RNETBUF{node['delay']}"


def top_name(record):
    return "conn_" + record["fixture"]


GUARD = r'''`timescale 1ns/1ps
`default_nettype none
// Instantiate at the EXTERNAL network input. Internal cells settle in stages.
module rnet_input_guard #(parameter integer MIN_DWELL=9, INITIAL_SETTLE=44) (input wire A);
  realtime last_change = 0.0;
  initial begin
    #0.001;
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RNET_PROTOCOL: initial input must be binary");
  end
  always @(A) if ($realtime > 0.0) begin
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RNET_PROTOCOL: X/Z input outside admitted network envelope");
    if ($realtime < INITIAL_SETTLE)
      $fatal(1, "RNET_PROTOCOL: initial settling interval incomplete");
    if ($realtime != $floor($realtime))
      $fatal(1, "RNET_PROTOCOL: edges require integer game ticks");
    if ($realtime-last_change < MIN_DWELL)
      $fatal(1, "RNET_PROTOCOL: high/low dwell too short");
    last_change = $realtime;
  end
endmodule
`default_nettype wire
'''


def model(mode):
    lines = ["// Generated. Abstract scale: 1 ns = 1 game tick; binary legal histories only.",
             "// Timing models are simulation-only. Synthesis links the Liberty cell symbols.",
             "`timescale 1ns/1ps", "`default_nettype none"]
    for name in CELL_NAMES:
        d = int(name[-1])
        lines += [f"module {name}(input wire A, output wire Y);"]
        if mode == "portable":
            # Startup of delayed continuous assignments is unreliable in the
            # installed Verilator. Explicitly seed during the unobserved hold.
            # Under dwell >= D+1, transport and inertial delays coincide.
            lines += ["  reg delayed;", f"  initial begin #0.001; delayed <= #{d} A; end",
                      f"  always @(A) delayed <= #{d} A;", "  assign Y = delayed;"]
        else:
            lines += ["  buf (Y, A);"]
        if mode == "specify":
            lines += ["  reg timing_notifier=0;", "  always @(timing_notifier) if ($realtime > 0)",
                      '    $fatal(1, "RNET_TIMING_WIDTH: annotated cell pulse-width violation");',
                      "  specify", "`ifdef RNET_SDF_ONLY", "    specparam TPD=0, WMIN=0;", "`else",
                      f"    specparam TPD={d}, WMIN={d+1};", "`endif", "    (A => Y) = (TPD, TPD);",
                      "    $width(posedge A, WMIN, 0, timing_notifier);", "    $width(negedge A, WMIN, 0, timing_notifier);", "  endspecify"]
        lines += ["endmodule", ""]
    return "\n".join(lines+["`default_nettype wire", ""])


def liberty():
    lines = ["/* Logical redstone library; 1 ns means 1 game tick.",
             " * area counts diode blocks; excludes routed dust/support/reserved air.",
             " * fanout_load counts receiving diodes. No electrical capacitance/slew/PVT.",
             " * dont_use prevents unqualified Boolean remapping of physical delay cells. */",
             "library (java_1_21_1_buffer_network) {", '  time_unit : "1ns";', "  delay_model : table_lookup;"]
    for name in CELL_NAMES:
        d = int(name[-1])
        lines += [f"  cell ({name}) {{", "    area : 1;", "    dont_use : true;",
                  "    pin (A) {", "      direction : input;", "      fanout_load : 1;",
                  f"      min_pulse_width_high : {d+1};", f"      min_pulse_width_low : {d+1};", "    }",
                  "    pin (Y) {", "      direction : output;", '      function : "A";', "      max_fanout : 3;",
                  "      timing () {", '        related_pin : "A";', "        timing_sense : positive_unate;",
                  "        timing_type : combinational;", f'        cell_rise (scalar) {{ values ("{d}"); }}',
                  f'        cell_fall (scalar) {{ values ("{d}"); }}', "      }", "    }", "  }"]
    return "\n".join(lines+["}", ""])


def netlist(record):
    nodes = record["graph"]["nodes"]
    lines = ["// Generated physical instances. Keep names/types/connectivity for SDF and placement.",
             "// Q bits observe diode outputs without adding physical loads.", "`default_nettype none",
             f"module {top_name(record)}(input wire A, output wire [{len(nodes)-1}:0] Q);"]
    for node in nodes:
        i = int(node["id"][1:])
        source = "A" if node["parent"] == "source" else "Q["+node["parent"][1:]+"]"
        lines.append(f"  (* keep = 1, dont_touch = 1 *) {cell_name(node)} {node['id']} (.A({source}), .Y(Q[{i}]));")
    return "\n".join(lines+["endmodule", "`default_nettype wire", ""])


def sdf(record, *, route_delay=0):
    nodes = record["graph"]["nodes"]
    lines = ["// 1 ns = 1 game tick. Route delay 0 at completed-tick resolution only.",
             "(DELAYFILE", '  (SDFVERSION "3.0")', f'  (DESIGN "{top_name(record)}")',
             '  (VENDOR "sv2rt")', '  (PROGRAM "checked network exporter")', '  (VERSION "1")',
             "  (DIVIDER /)", "  (TIMESCALE 1ns)", "  (CELL", f'    (CELLTYPE "{top_name(record)}")',
             "    (INSTANCE)", "    (DELAY (ABSOLUTE"]
    for node in nodes:
        src = "A" if node["parent"] == "source" else node["parent"]+"/Y"
        d = route_delay
        lines.append(f"      (INTERCONNECT {src} {node['id']}/A ({d}:{d}:{d}) ({d}:{d}:{d}))")
    lines += ["    ))", "  )"]
    for node in nodes:
        d, w = node["delay"], node["delay"]+1
        lines += ["  (CELL", f'    (CELLTYPE "{cell_name(node)}")', f"    (INSTANCE {node['id']})",
                  f"    (DELAY (ABSOLUTE (IOPATH A Y ({d}:{d}:{d}) ({d}:{d}:{d}))))",
                  f"    (TIMINGCHECK (WIDTH (posedge A) ({w}:{w}:{w})) (WIDTH (negedge A) ({w}:{w}:{w})))", "  )"]
    return "\n".join(lines+[")", ""])


def constraints(record):
    lines = ["# Abstract timing budget in ns, where 1 ns = 1 game tick.",
             "# Dwell/initialization and physical guards require the native checker + GLS monitor.",
             "# No electrical load, clock frequency, wire capacitance, or PVT is asserted here."]
    for node in record["graph"]["nodes"]:
        lines.append(f"set_max_delay {node['arrival_delay']} -from [get_ports A] -to [get_ports {{Q[{node['id'][1:]}]}}]")
    return "\n".join(lines)+"\n"


def render_views(contract):
    from .connection_fixtures import connection_cases
    from .fixtures import compile_functions
    admitted = [r for r in contract["cases"] if r["admitted"]]
    fixtures = {f["id"]: f for f in connection_cases()}
    compiled = compile_functions()
    result = {PREFIX+"cells.lib": liberty(), PREFIX+"cells-functional.v": model("functional"),
              PREFIX+"cells-timing.sv": model("specify"), PREFIX+"cells-portable.sv": model("portable"),
              PREFIX+"input-guard.sv": GUARD}
    for record in admitted:
        name = record["fixture"]
        result[PREFIX+f"netlists/{name}.v"] = netlist(record)
        result[PREFIX+f"sdf/{name}.sdf"] = sdf(record)
        result[PREFIX+f"constraints/{name}.sdc"] = constraints(record)
        result[PREFIX+f"layouts/{name}.json"] = json.dumps({"fixture": name, "graph": record["graph"],
            "contract": "connections/buffer-network-v1.json", "contract_content_sha256": digest(contract)}, indent=2)+"\n"
        # Exact measured placements. Absolute commands clear ONLY the reserved lab.
        result[PREFIX+f"layouts/{name}.mcfunction"] = ("# Exact lab placement, not a relocatable template. Clears the reserved lab volume.\n"
            +compiled[name+"/setup"]+"\n# Initialize separately and hold for the declared interval.\n")
        result[PREFIX+f"layouts/{name}-initialize.mcfunction"] = "\n".join(fixtures[name]["prepare"][0]["commands"])+"\n"
    for mode, cellfile in (("functional", "cells-functional.v"), ("timing", "cells-timing.sv"), ("portable", "cells-portable.sv")):
        result[PREFIX+mode+".f"] = PREFIX+cellfile+"\n"+"\n".join(PREFIX+f"netlists/{r['fixture']}.v" for r in admitted)+"\n"
    result[PREFIX+"synthesis.f"] = "\n".join(PREFIX+f"netlists/{r['fixture']}.v" for r in admitted)+"\n"
    result[PREFIX+"manifest.json"] = json.dumps({"schema_version": 1, "technology": contract["technology"],
        "contract_content_sha256": digest(contract), "generator_sha256": sha(ROOT / "redstone_pdk/connection_views.py"),
        "cells": CELL_NAMES, "admitted_networks": [r["fixture"] for r in admitted], "example": EXAMPLE,
        "files": {k: __import__("hashlib").sha256(v.encode()).hexdigest() for k, v in result.items()},
        "time_scale": "1 ns represents 1 game tick; equal min/typ/max are one deterministic build",
        "synthesis": "Link Liberty symbols only; do not synthesize the functional/timing simulation bodies; preserve cells and recheck exported topology",
        "qualification": "Commercial simulator/synthesis tool execution must be recorded per installed release; source compatibility alone is not vendor qualification"}, indent=2)+"\n"
    return result


def render_report(contract):
    c = contract["coverage"]
    return f'''# Checked driver–cell–receiver networks

**{c['cases']}/{c['cases']} Minecraft cases match the compositional prediction.**
{c['admitted']} cases are admitted; {c['negative_controls']} deliberate overlength routes are rejected.
The run contains {c['samples']:,} observation boundaries, {c['probe_readings']:,} block-property readings,
and {c['source_transitions']} source transitions. All raw probe/time replies and executed function sequences were audited.
Evidence: [{contract['evidence']['run']}](../{contract['evidence']['run']}/summary.json).

| Coverage | Cases |
|---|---:|
| All driver/DUT/receiver repeater settings (4 × 4 × 4) | 64 |
| First route lengths 2–16 × four DUT settings | 60 |
| Binary comparator driver × DUT/receiver settings × both initial states | 32 |
| Elbow, dangling stub, two/three receivers × DUT settings × both initial states | 32 |
| Four rotations, chunk boundaries, both initial states, two delay triples | 16 |

This is not the full cross product of route, fanout, orientation, initial state and timing.
The admitted catalog lists exact measured geometries; the extractor's broader tree model is not permission to use arbitrary new layouts.
The older native event model independently agrees on {c['native_model_matches']} cases.
Its v1 geometry rules exclude the 32 bent/branched cases; those are checked directly against Minecraft using the independent compositional law.

## What the route measurements establish

The first driven dust block has strength 15. Each further dust block reduces HIGH by one.
A 15-block straight route reaches its receiver at strength 1 and works. All four 16-block controls reach 0 and fail to convey HIGH;
the checker rejects them before HDL export. Repeaters restore the output to 15.
Elbows and the measured stubs/fanouts add no delay at completed-game-tick resolution. Receiving repeaters retain their 2/4/6/8-tick delay.
This zero route delay does not mean that dust has no internal update sequence.

`RNETBUF2/4/6/8` describe connected repeaters receiving 0 versus 1..15.
`RNETCMP2` is only the measured binary source driver (compare mode, rear 0/15, empty sides).
These new symbols have a separate connection contract; the older `RSBUF` symbols remain isolated cells.

Every admitted net has one driver, a planar tree of at most 15 dust blocks, and at most three receiving diodes.
Every diode has rear/output dust, empty locking sides and empty space above. The support is an unpowered stone plane.
The lab reserve is x=0..63, y=79..84, z=-16..47, with at least two empty horizontal blocks around the body/source.
Only the declared source changes. No feedback, shared drivers, vertical routes, pistons, moving blocks, locks, external power or tick backlog is allowed.
All chunks stay loaded. Reflections, relocation and larger designs require further admission.

Hold the initial binary input for at least **20 + longest path delay** game ticks.
Then use integer tick boundaries and hold both HIGH and LOW for at least **max(cell delay) + 1** ticks.
For each cell, its input is still stable when its scheduled event executes, and its queue drains before the next edge.
Induction along this acyclic graph preserves pulse widths and adds delays. This is an engineering extension from finite evidence, not a formal proof of Minecraft.

## Synthesis and gate-level simulation handoff

The [manifest](../views/buffer-network/manifest.json) pins all views to this admission:

- [Liberty](../views/buffer-network/cells.lib), separate functional/specify/portable timed models, and an external input guard.
- 200 structural netlists, matching instance SDF (IOPATH and explicit INTERCONNECT), path-budget SDC, and exact lab placement/initialization functions.
- [EDA integration guide](eda-integration.md): Design Compiler/Library Compiler, Genus, VCS, Questa and Xcelium adapters, import/export checks, and local qualification results.

Synthesis reads the Liberty symbols and structural netlist. Preserve all diode instances: a Boolean optimizer can remove a physically necessary buffer.
The exported netlist must pass the instance/type/connectivity checker before its SDF or placement certificate can be reused.
The `.lib` remains `dont_use` for unconstrained mapping. A buffer-only library cannot map arbitrary RTL; general logic and state cells are still needed.
SDC path budgets do not encode the input dwell rule, geometry or wire strength.

**1 simulation ns = 1 game tick.** Equal SDF min/typ/max describe one build, not PVT corners.
Liberty area counts diode blocks and fanout_load counts receiving diodes; neither is an electrical quantity.
No capacitance, voltage, analog slew, power, ASIC layout or electrical STA qualification is supplied.
The native route certificate remains authoritative over a synthesis tool's inferred wire model or SDF.

## Reproduce

```powershell
python pdk.py admit-connections {contract['evidence']['run']}
python tools/check_network_eda.py
python pdk.py validate
```

Fresh evidence: `python pdk.py start`, `python pdk.py run --suite connections`, `python pdk.py stop`.
Placement functions clear the full reserved lab and are inspectable artifacts; they are not automatically executed by synthesis or simulation.
'''
