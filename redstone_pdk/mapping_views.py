"""Consistent structural, Liberty, SDF and Minecraft placement views."""
from pathlib import Path
from .rtl import dump

KINDS = ("NOR2","INV","DFF","BUF2","BUF4","BUF6","BUF8")
DELAYS = {"NOR2":8,"INV":8,"DFF":14,"BUF2":2,"BUF4":4,"BUF6":6,"BUF8":8}


def cells_verilog(mode):
    lines = ["`timescale 1ns/1ps", "// One simulation ns represents one completed Minecraft game tick.",
             "// Startup state is unconstrained. Apply the documented clocked reset protocol.", "`default_nettype none"]
    for kind in KINDS:
        d = DELAYS[kind]
        pins = "input D, CLK, output Q" if kind == "DFF" else "input A, "+("B, " if kind == "NOR2" else "")+"output Y"
        lines.append(f"module RMAP_{kind}({pins});")
        expr = "~(A | B)" if kind == "NOR2" else "~A" if kind == "INV" else "A"
        if kind == "DFF":
            lines += ["  reg state;", f"  always @(posedge CLK) state <= {'#14 ' if mode == 'portable' else ''}D;", "  assign Q = state;"]
            if mode == "timing":
                lines += ["  reg notifier = 0;", "  always @(notifier) state <= 1'bx;"]
        elif mode == "portable":
            lines += ["  reg state;", f"  initial begin #0.001; state <= #{d} {expr}; end",
                      f"  always @({'A or B' if kind == 'NOR2' else 'A'}) state <= #{d} {expr};", "  assign Y = state;"]
        else:
            lines.append(f"  assign Y = {expr};")
        if mode == "timing":
            lines += ["  specify", "`ifdef RMAP_SDF_ONLY", "    specparam T = 0;", "`else", f"    specparam T = {d};", "`endif"]
            if kind == "DFF":
                lines += ["`ifdef RMAP_SDF_ONLY", "    specparam TS = 0, TH = 0, TW = 0;", "`else",
                          "    specparam TS = 11, TH = 3, TW = 17;", "`endif",
                          "    (posedge CLK => (Q +: D)) = (T, T);", "    $setuphold(posedge CLK, D, TS, TH, notifier);",
                          "    $width(posedge CLK, TW, 0, notifier);", "    $width(negedge CLK, TW, 0, notifier);"]
            else:
                lines += ["    (A => Y) = (T, T);"]
                if kind == "NOR2": lines.append("    (B => Y) = (T, T);")
            lines.append("  endspecify")
        lines += ["endmodule", ""]
    return "\n".join(lines+["`default_nettype wire", ""])


def liberty():
    lines = ['library (redstone_mapping) {', '  delay_model : table_lookup;', '  time_unit : "1ns";',
             '  voltage_unit : "1V";', '  current_unit : "1mA";', '  pulling_resistance_unit : "1kohm";',
             '  leakage_power_unit : "1nW";', '  capacitive_load_unit (1,pf);', '  nom_process : 1;',
             '  nom_temperature : 25;', '  nom_voltage : 1;', '  default_cell_leakage_power : 0;',
             '  input_threshold_pct_rise : 50;', '  input_threshold_pct_fall : 50;',
             '  output_threshold_pct_rise : 50;', '  output_threshold_pct_fall : 50;',
             '  slew_lower_threshold_pct_rise : 20;', '  slew_upper_threshold_pct_rise : 80;',
             '  slew_lower_threshold_pct_fall : 20;', '  slew_upper_threshold_pct_fall : 80;',
             '  default_input_pin_cap : 1;', '  default_output_pin_cap : 0;',
             '  default_max_transition : 1;', '  operating_conditions (game_tick) { process : 1; voltage : 1; temperature : 25; }',
             '  default_operating_conditions : game_tick;',
             '  /* Abstract binary timing units; capacitance/voltage are placeholders, not Minecraft electrical quantities. */']
    for k in KINDS:
        area = 17*13 if k == "DFF" else 17*6 if k in ("NOR2","INV") else 3
        lines += [f'  cell (RMAP_{k}) {{', f'    area : {area};']
        if k == "DFF": lines.append('    ff (IQ, IQN) { clocked_on : "CLK"; next_state : "D"; }')
        inputs = ("D","CLK") if k == "DFF" else ("A","B") if k == "NOR2" else ("A",)
        for pin in inputs:
            lines += [f'    pin ({pin}) {{ direction : input; capacitance : 1;']
            if pin == "CLK": lines.append('      clock : true; min_pulse_width_high : 17; min_pulse_width_low : 17;')
            if pin == "D":
                for typ,value in (("setup_rising",11),("hold_rising",3)):
                    lines.append(f'      timing () {{ related_pin : "CLK"; timing_type : {typ}; rise_constraint (scalar) {{ values ("{value}"); }} fall_constraint (scalar) {{ values ("{value}"); }} }}')
            lines.append('    }')
        output = "Q" if k == "DFF" else "Y"
        fun = "IQ" if k == "DFF" else "!(A | B)" if k == "NOR2" else "!A" if k == "INV" else "A"
        lines += [f'    pin ({output}) {{ direction : output; function : "{fun}"; max_capacitance : 100000;']
        for pin in (("CLK",) if k == "DFF" else inputs):
            typ = "rising_edge" if k == "DFF" else "combinational"
            sense = "non_unate" if k == "DFF" else "negative_unate" if k in ("NOR2","INV") else "positive_unate"
            lines += [f'      timing () {{ related_pin : "{pin}"; timing_type : {typ}; timing_sense : {sense};',
                      f'        cell_rise (scalar) {{ values ("{DELAYS[k]}"); }} cell_fall (scalar) {{ values ("{DELAYS[k]}"); }}',
                      '        rise_transition (scalar) { values ("0"); } fall_transition (scalar) { values ("0"); }', '      }']
        lines += ['    }', '  }']
    return "\n".join(lines+['}', ''])


def public_bit(name, port, i):
    index = port.get("offset",0)+(len(port["bits"])-1-i if port.get("upto",0) else i)
    return name if len(port["bits"]) == 1 and not port.get("offset",0) else f"{name}[{index}]"


def structural(graph, layout):
    lines = ["`default_nettype none", f"module {graph['top']}_mapped("+", ".join(graph["ports"])+");"]
    for name,p in graph["ports"].items():
        n,off = len(p["bits"]),p.get("offset",0)
        a,b = (off,off+n-1) if p.get("upto",0) else (off+n-1,off)
        lines.append(f"  {p['direction']}"+(f" [{a}:{b}]" if n>1 or off else "")+f" {name};")
    nets = sorted({v for c in layout["components"] for v in c["pins"].values()})
    lines += ["  wire "+n+";" for n in nets]
    for s in layout["sources"]:
        expr = "1'b"+str(s["constant"]) if "constant" in s else public_bit(s["port"],graph["ports"][s["port"]],s["bit_index"])
        lines.append(f"  assign {s['wire']} = {expr};")
    for o in layout["outputs"]:
        lines.append(f"  assign {public_bit(o['port'],graph['ports'][o['port']],o['bit_index'])} = {o['wire']};")
    for c in layout["components"]:
        ports = ", ".join(f".{p}({n})" for p,n in c["pins"].items())
        lines.append(f"  RMAP_{c['kind']} {c['name']}({ports});")
    return "\n".join(lines+["endmodule", "`default_nettype wire", ""])


def timing_budget(graph, layout):
    # Three times the sum along each path leaves room for pending/stretched
    # transient pulses. Only settled observations are claimed for reconvergence.
    arrival = {s["wire"]:0 for s in layout["sources"]}
    arrival.update({c["pins"]["Q"]:14 for c in layout["components"] if c["kind"] == "DFF"})
    todo = [c for c in layout["components"] if c["kind"] != "DFF"]
    while todo:
        ready = [c for c in todo if all(n in arrival for p,n in c["pins"].items() if p != "Y")]
        if not ready: raise ValueError("Routing graph has a cycle or an undriven net")
        for c in ready:
            arrival[c["pins"]["Y"]] = max(arrival[n] for p,n in c["pins"].items() if p != "Y")+c["delay"]
            todo.remove(c)
    depth = max(arrival.values(), default=0)
    half = 3*(depth+layout["clock_delay"])+40
    return {"time_unit":"game_tick","nominal_longest_path":depth,"clock_tree_delay":layout["clock_delay"],
            "settle":half,"clock_half_period":half,"minimum_clock_period":2*half,
            "protocol":"Change data only with the falling external clock; hold data through the next rising edge. Observe after settle. For combinational transactions, hold all inputs for settle before observing.",
            "initialization":"No power-up value is promised. Apply a synchronous reset/boot sequence for at least two full clocks, then release reset at a falling edge.",
            "accuracy":"Cell arc delays are measured under their pin protocol. Reconvergent transient waveforms are not qualified; RTL equivalence and physical regression compare settled outputs and captured state."}


def sdf(graph, layout):
    lines = ['(DELAYFILE (SDFVERSION "3.0")',f'  (DESIGN "{graph["top"]}_mapped")',
             '  (VENDOR "sv2rt") (PROGRAM "sv2rt map") (VERSION "1")', '  (DIVIDER /) (TIMESCALE 1ns)']
    for c in layout["components"]:
        k,d = c["kind"],c["delay"]
        pins = ("CLK",) if k == "DFF" else ("A","B") if k == "NOR2" else ("A",)
        output = "Q" if k == "DFF" else "Y"
        lines += [f'  (CELL (CELLTYPE "RMAP_{k}") (INSTANCE {c["name"]})', '    (DELAY (ABSOLUTE']
        for p in pins:
            edge = "(posedge CLK)" if k == "DFF" else p
            lines.append(f'      (IOPATH {edge} {output} ({d}:{d}:{d}) ({d}:{d}:{d}))')
        lines.append('    ))')
        if k == "DFF":
            lines += ['    (TIMINGCHECK', '      (SETUPHOLD D (posedge CLK) (11:11:11) (3:3:3))',
                      '      (WIDTH (posedge CLK) (17:17:17)) (WIDTH (negedge CLK) (17:17:17))', '    )']
        lines.append('  )')
    return "\n".join(lines+[')', ''])


def clear_commands(bounds):
    low,high = bounds
    # Each fill fits vanilla's 32768-block limit. The entire volume is owned
    # by the generated layout and contains no existing user build.
    # Clear dust before its supports to avoid spawning thousands of dropped
    # items while replacing a previous build.
    for y in range(high[1],low[1]-1,-1):
        for x in range(low[0],high[0]+1,32):
            for z in range(low[2],high[2]+1,32):
                yield f"fill {x} {y} {z} {min(x+31,high[0])} {y} {min(z+31,high[2])} minecraft:air"


def export(graph, layout, folder):
    folder = Path(folder)
    budget = timing_budget(graph,layout)
    dump(folder/"layout.json",layout); dump(folder/"timing.json",budget)
    for mode in ("functional","timing","portable"):
        (folder/f"cells-{mode}.sv").write_text(cells_verilog(mode),encoding="utf-8",newline="\n")
    (folder/"mapping.lib").write_text(liberty(),encoding="utf-8",newline="\n")
    (folder/"mapped.v").write_text(structural(graph,layout),encoding="utf-8",newline="\n")
    (folder/"mapped.sdf").write_text(sdf(graph,layout),encoding="utf-8",newline="\n")
    sdc = ["# One ns represents one game tick. Clock includes the generated route buffers."]
    if graph["clock_bit"] is not None:
        clk = next(s for s in layout["sources"] if s.get("logical_bit") == graph["clock_bit"])
        port = public_bit(clk["port"],graph["ports"][clk["port"]],clk["bit_index"])
        sdc += [f"create_clock -name game_clock -period {budget['minimum_clock_period']} [get_ports {{{port}}}]",
                "set_propagated_clock [all_clocks]"]
    sdc += [f"set_max_delay {budget['settle']} -from [all_inputs] -to [all_outputs]",
            "# No analog RC/parasitic interpretation; placement DRC supplies connectivity/strength checks."]
    (folder/"mapped.sdc").write_text("\n".join(sdc)+"\n",encoding="utf-8",newline="\n")
    commands = list(clear_commands(layout["bounds"]))
    commands += ["setblock "+" ".join(map(str,b["position"]))+" minecraft:"+b["state"]
                 for b in sorted(layout["blocks"],key=lambda b:(b["position"][1],b["position"][0],b["position"][2]))]
    if len(commands)>60000: raise ValueError("Layout exceeds the 60000-command placement budget")
    (folder/"place.mcfunction").write_text("\n".join(commands)+"\n",encoding="utf-8",newline="\n")
    from .mapping_commercial import scripts
    for name,content in scripts(graph,budget).items():
        (folder/name).write_text(content,encoding="utf-8",newline="\n")
    return budget
