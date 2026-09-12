"""Deterministic abstract EDA views; native game ticks remain authoritative."""
import hashlib
import json
import re

PREFIX = "views/repeater-buffers/"


def render_liberty(lib):
    lines = ["/* Abstract redstone timing: 1 ns in this file means 1 game tick.",
             "   No physical voltage, capacitance, slew, power, or PVT characterization.",
             "   Explicit instances only; honor the native layout and input protocol. */",
             "library (java_1_21_1_guarded_buffers) {", "  delay_model : table_lookup;", '  time_unit : "1ns";']
    for c in lib["cells"]:
        d = c["timing"]["arcs"][0]["rise"]
        lines += [f"  cell ({c['name']}) {{", "    dont_use : true;", "    pin (A) {", "      direction : input;",
                  f"      min_pulse_width_high : {d + 1};", f"      min_pulse_width_low : {d + 1};", "    }",
                  "    pin (Y) {", "      direction : output;", '      function : "A";', "      timing () {",
                  '        related_pin : "A";', "        timing_sense : positive_unate;", "        timing_type : combinational;",
                  f'        cell_rise (scalar) {{ values ("{d}"); }}', f'        cell_fall (scalar) {{ values ("{d}"); }}',
                  "      }", "    }", "  }"]
    return "\n".join(lines + ["}", ""])


GUARD = r"""// The procedural guard is authoritative even when a simulator omits $width.
// It checks temporal inputs only; physical placement needs the native contract.
module rs_input_guard #(parameter integer MIN_DWELL = 3) (input wire A);
  realtime last_change = 0.0;
  initial begin
    #0;
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RS_PROTOCOL: initial input must be binary");
  end
  always @(A) if ($realtime > 0.0) begin
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RS_PROTOCOL: X/Z input outside cell envelope");
    if ($realtime < 20.0)
      $fatal(1, "RS_PROTOCOL: initial input must settle for 20 game ticks");
    if ($realtime != $floor($realtime))
      $fatal(1, "RS_PROTOCOL: input edges require integer game ticks");
    if ($realtime - last_change < MIN_DWELL)
      $fatal(1, "RS_PROTOCOL: input dwell too short");
    last_change = $realtime;
  end
endmodule
"""


def render_sv(lib, functional=False):
    lines = ["// Generated; 1 simulation ns = 1 game tick. See docs/repeater-cells.md.",
             "`timescale 1ns/1ps", "`default_nettype none"]
    if not functional:
        lines += ["// Enable specify paths (Icarus: -gspecify).",
                  "// RS_SDF_ONLY sets path defaults to zero: delays must then come from SDF.", GUARD]
    for c in lib["cells"]:
        d = c["timing"]["arcs"][0]["rise"]
        lines += [f"module {c['name']} (input wire A, output wire Y);", "  buf (Y, A);"]
        if not functional:
            lines += [f"  rs_input_guard #(.MIN_DWELL({d + 1})) protocol_guard (.A(A));", "  specify",
                      "`ifdef RS_SDF_ONLY", "    specparam TPD = 0;", "`else", f"    specparam TPD = {d};", "`endif",
                      "    (A => Y) = (TPD, TPD);", f"    $width(posedge A, {d + 1}, 0);",
                      f"    $width(negedge A, {d + 1}, 0);", "  endspecify"]
        lines += ["endmodule", ""]
    return "\n".join(lines + ["`default_nettype wire", ""])


def render_sdf(lib, instances, design):
    cells = {c["name"]: c for c in lib["cells"]}
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    if not re.fullmatch(identifier, design) or not instances:
        raise ValueError("SDF requires a simple design identifier and explicit instances")
    lines = ["// Abstract scale: 1 ns = 1 game tick, not elapsed nanoseconds.", "(DELAYFILE", '  (SDFVERSION "3.0")',
             f'  (DESIGN "{design}")', '  (VENDOR "sv2rt")', '  (PROGRAM "guarded buffer exporter")',
             '  (VERSION "1")', "  (DIVIDER /)", "  (TIMESCALE 1ns)"]
    for instance, name in instances.items():
        if name not in cells or not re.fullmatch(identifier + r"(?:/" + identifier + ")*", instance):
            raise ValueError("Unknown cell or unsupported SDF instance path")
        d = cells[name]["timing"]["arcs"][0]["rise"]
        w = d + 1
        lines += ["  (CELL", f'    (CELLTYPE "{name}")', f"    (INSTANCE {instance})",
                  f"    (DELAY (ABSOLUTE (IOPATH A Y ({d}:{d}:{d}) ({d}:{d}:{d}))))", "    (TIMINGCHECK",
                  f"      (WIDTH (posedge A) ({w}:{w}:{w}))", f"      (WIDTH (negedge A) ({w}:{w}:{w})))", "  )"]
    return "\n".join(lines + [")", ""])


def render_layout(cell, rotation):
    from .cells import placement
    world = placement(cell, rotation)
    def pos(p):
        return " ".join("~" + str(v) if v else "~" for v in p)
    lo = tuple(min(p[k] for p in world) for k in range(3))
    hi = tuple(max(p[k] for p in world) for k in range(3))
    # These are relative placement templates, never automatically executed.
    lines = [f"# {cell['name']} rotation {rotation}; origin is the repeater block.",
             "# Clears the declared reserved volume; place only in a reserved lab area.",
             "# Keep A stable for 20 game ticks before use; external wiring is not admitted.",
             f"fill {pos(lo)} {pos(hi)} minecraft:air",
             f"fill {pos((lo[0], -1, lo[2]))} {pos((hi[0], -1, hi[2]))} minecraft:stone"]
    lines += [f"setblock {pos(p)} {state}" for p, state in world.items() if state not in ("minecraft:air", "minecraft:stone")]
    return "\n".join(lines) + "\n"


def render_views(lib):
    instances = {f"u{2 * i}": f"RSBUF{2 * i}" for i in range(1, 5)}
    bank = ["// Four independent cells. This is not a connected physical circuit.",
            "module buffer_bank(input wire [3:0] A, output wire [3:0] Y);"]
    bank += [f"  {name} {instance} (.A(A[{i}]), .Y(Y[{i}]));" for i, (instance, name) in enumerate(instances.items())]
    bank += ["endmodule", ""]
    result = {PREFIX + "repeater-buffers.lib": render_liberty(lib), PREFIX + "repeater-buffers.sv": render_sv(lib),
              PREFIX + "repeater-buffers-functional.v": render_sv(lib, True), PREFIX + "buffer-bank.v": "\n".join(bank),
              PREFIX + "buffer-bank.sdf": render_sdf(lib, instances, "buffer_bank")}
    for c in lib["cells"]:
        for r in c["physical"]["rotations_quarter_turns"]:
            result[PREFIX + f"layouts/{c['name']}_r{r}.mcfunction"] = render_layout(c, r)
    from .project import ROOT
    manifest = {"schema_version": 1, "library": lib["id"], "admission": lib["admission"], "time_scale": lib["eda_time_scale"],
                "generator_sha256": hashlib.sha256((ROOT / "redstone_pdk/cell_views.py").read_bytes()).hexdigest(),
                "files": {name: hashlib.sha256(content.encode()).hexdigest() for name, content in result.items()},
                "notes": ["Liberty is a logical timing interchange view, not an electrical or full STA library",
                          "Scalar rise/fall delays have no characterized slew, capacitance, fanout, or PVT dependence",
                          "Equal min/typ/max values describe one deterministic game build, not three corners",
                          "SDF instances match buffer-bank.v; no route/interconnect delays are admitted",
                          "Minimum pulse widths do not encode geometry, initialization, or all stimulus restrictions"]}
    result[PREFIX + "manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    return result


def render_report(lib, admission):
    count = admission["coverage"]
    lines = ["# First admitted redstone cells", "",
             "Four guarded repeater buffers are admitted for **explicit isolated instances** in vanilla Java Edition 1.21.1, under the physical and temporal envelope below. General synthesis mapping remains disabled (`mapping_eligible: false`, Liberty `dont_use: true`).", "",
             f"Fresh Minecraft evidence: **{count['cases']}/{count['cases']} fixtures, {count['input_edges']} input transitions, {count['samples']:,} sample points, {count['probe_readings']:,} probe readings**. Every sample matches both the independent delayed-Boolean cell law and the native event model, including before-action observations.", "",
             "| Cell | Repeater setting | Rise / fall delay | Minimum HIGH | Minimum LOW |",
             "|---|---:|---:|---:|---:|"]
    for c in lib["cells"]:
        d = c["timing"]["arcs"][0]["rise"]
        lines.append(f"| {c['name']} | {c['setting']} | {d} gt | {d + 1} gt | {d + 1} gt |")
    lines += ["", "## Physical contract", "",
              "Local coordinates place the repeater at (0,0,0); +x points toward its output. Rotation turns this entire volume, ports included, around the vertical axis.", "",
              "```text", "Top view at y=0; all unmarked reserved positions are air", "",
              "          x=-3   -2       -1       0        +1      +2   +3",
              "z=-2      .      .        .        .        .       .    .",
              "z=-1      .      .        .        .        .       .    .",
              "z= 0      .    source -> A dust -> repeater -> Y dust .    .",
              "z=+1      .      .        .        .        .       .    .",
              "z=+2      .      .        .        .        .       .    .", "```", "",
              "The reserved volume is 7 × 5 × 4 blocks: x=-3..3, z=-2..2, y=-1..2. Its bottom layer is stone with no external power applied; the remaining positions are air except the three body blocks and the source port. Both locking sides and the space above stay empty. The input access face is west, at dust (-1,0,0), driven by air or a redstone block at (-2,0,0). The output access face is east, at dust (+1,0,0). The only output load is this included dust, observed without a connected receiver.", "",
              "All four horizontal rotations were measured with both initial states and both stimulus patterns. Reflections and vertical layouts are not admitted. All affected chunks must stay loaded, the queue must have no backlog, and outside mechanisms must not power the support or alter the reserved volume. Fresh fixtures use an otherwise empty lab on a stone plane; the air margin is an integration rule, not evidence of immunity to arbitrary external circuits.", "",
              "## Input protocol and why it gives a fixed delay", "",
              "Initialize A to 0 or 1 and hold it for at least 20 game ticks. A means dust strength 0 or 15, respectively. Thereafter, change only the declared source, after a completed game tick, at integer game-tick boundaries. Both high and low intervals must be at least D+1 ticks, where D is the cell delay. Hold the final input indefinitely or until the next legal transition. Sample after scheduled work and source updates finish.", "",
              "With no lock and a settled initial state, an input transition schedules one output event at t+D. The input is still stable when that event executes. The output reaches the new input value and the queue is empty before another transition is permitted at t+D+1. This restores the same condition for the next transition. This induction is the engineering argument for extending the measured finite histories to the stated protocol; it is not a formal proof of the entire Minecraft engine.", "",
              "D+1 is a conservative admission boundary, not a claim that every shorter pulse fails. Short pulses, locks, alternate drivers and order-sensitive cases must use the native event model. The simpler cell timing view does not emulate their behavior.", "",
              "## Generated views", "",
              "- [Native cell definitions](../cells/repeater-buffers.json): ports, body blocks, support, air, transforms, protocol and timing arcs.",
              "- [Liberty](../views/repeater-buffers/repeater-buffers.lib): function, scalar rise/fall timing, minimum pulse widths and mapping exclusion.",
              "- [Timing SystemVerilog](../views/repeater-buffers/repeater-buffers.sv): specify paths, width checks and a procedural input guard that rejects illegal timing or X/Z inputs.",
              "- [Functional Verilog](../views/repeater-buffers/repeater-buffers-functional.v): zero-delay logical view only; no timing or envelope enforcement.",
              "- [Example netlist](../views/repeater-buffers/buffer-bank.v) and [SDF](../views/repeater-buffers/buffer-bank.sdf): four independent instances with matching instance names.",
              "- [View manifest](../views/repeater-buffers/manifest.json): hashes and scale; layouts/ contains sixteen relative Minecraft placement functions.", "",
              "**1 simulation ns = 1 game tick.** This is a numerical interchange scale, never elapsed wall-clock time. Native JSON keeps game ticks. Equal SDF min/typ/max values describe one deterministic build and envelope; they are not PVT corners. Liberty supplies no invented capacitance, slew, voltage, power or electrical load tables. It is an initial logical timing view, not a complete electrical/STA library.", "",
              "Specify paths use IEEE 1800-2023 §30.4.2 (pp.873–874), rise/fall delays §30.5.1 (pp.882–883), pulse checks §31.4.4 (pp.911–912), and `$sdf_annotate` §32.9 (pp.932–933). The standard maps SDF IOPATH to module paths (§32.4.1, p.925) and WIDTH to `$width` (§32.4.2, p.926). The procedural guard is also necessary for tools that do not execute all timing checks. Enable specify support; compile with `RS_SDF_ONLY` when the SDF should supply all path delays.", "",
              "Liberty representation was cross-checked against the primary [OpenSTA reader](https://github.com/The-OpenROAD-Project/OpenSTA/blob/master/liberty/LibertyReader.cc). Tool setup follows [YoWASP](https://yowasp.org/) and [Icarus documentation](https://steveicarus.github.io/iverilog/usage/installation.html); the [MSYS2 package](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-iverilog) supplies the portable simulator. See [EDA validation](repeater-cells-eda.md) for the actual tested versions, results and limitations.", "",
              "## Reproduce and next integration gate", "", "```powershell",
              f"python pdk.py admit-buffer-cells {admission['evidence']['run']}", "python tools/check_cell_eda.py",
              "python pdk.py validate", "```", "",
              "Rebuild rechecks the complete raw run, saved commands, source hashes, probe domains and coverage before writing any admitted view. Fresh measurements can be repeated with `python pdk.py start`, `python pdk.py run --suite cells`, then `python pdk.py stop`.", "",
              "The next admission gate is a **driver–cell–receiver connection contract**: characterize actual routed input drivers and receiving loads, dust joins/strength/fanout, guard compatibility, and chains. Only then can a mapper compose these into a circuit. This milestone does not yet admit arbitrary input waveforms, cell chaining, branching, clocks, state cells, or unrestricted mapping.", ""]
    return "\n".join(lines)
