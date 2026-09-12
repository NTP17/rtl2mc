"""Generate source-RTL oracles and replay sparse, explicit observation schedules."""
import json
from pathlib import Path
import re
import subprocess

from tools.eda_tools import runtime
from .rtl import dump, bit_expr, sha
from .mapping_views import public_bit


def example_vectors(graph,budget):
    h = budget["settle"]+2
    if graph["top"] == "adder":
        return {"initial":{"a":0,"b":0,"cin":0},
                "events":[{"tick":i*(h+1),"inputs":{"a":v&1,"b":(v>>1)&1,"cin":(v>>2)&1}}
                          for i,v in enumerate([0,1,2,3,4,5,6,7,0,7,3,5,1,6,2,4])],
                "checks":[i*(h+1)+h for i in range(16)]}
    if graph["top"] == "counter":
        events = [{"tick":0,"inputs":{"clk":0,"reset":1,"enable":0}}]
        for phase in range(1,29):
            values = {"clk":phase%2}
            if phase%2 == 0:
                values["reset"] = int(phase<4 or phase in (18,20))
                values["enable"] = int(phase not in (0,2,12,14,20))
            events.append({"tick":phase*h,"inputs":values})
        return {"initial":{"clk":0,"reset":1,"enable":0},"events":events,
                "checks":[phase*h+h-1 for phase in range(3,29)]}
    raise ValueError("Provide --vectors for this top; an explicit boot and observation schedule is required")


def validate_vectors(graph,budget,vectors):
    inputs = {n:p for n,p in graph["ports"].items() if p["direction"] == "input"}
    def values(v,all_inputs=False):
        if not set(v)<=set(inputs) or (all_inputs and set(v)!=set(inputs)):
            raise ValueError("Vector input names differ from the RTL ports")
        for n,value in v.items():
            if type(value) is not int or not 0 <= value < 2**len(inputs[n]["bits"]):
                raise ValueError("Vectors require width-bounded binary integer values")
    values(vectors["initial"],True)
    times = [v["tick"] for v in vectors["events"]]
    if any(type(t) is not int or t<0 for t in times) or times != sorted(set(times)):
        raise ValueError("Events must have unique increasing nonnegative integer ticks")
    checks = vectors["checks"]
    if not checks or checks != sorted(set(checks)) or any(type(t) is not int or t<0 for t in checks):
        raise ValueError("Need increasing nonnegative integer check times")
    state = dict(vectors["initial"])
    clk = None
    if graph["clock_bit"] is not None:
        clk = next(n for n,p in inputs.items() if graph["clock_bit"] in p["bits"])
        if len(inputs[clk]["bits"]) != 1 or state[clk] != 0:
            raise ValueError("The transaction driver requires a scalar clock initially low")
    last_edge,edges,changes,rising = None,[],[],[]
    for e in vectors["events"]:
        values(e["inputs"])
        next_state = {**state,**e["inputs"]}
        changed = [n for n in state if state[n] != next_state[n]]
        if clk:
            if clk in changed:
                if last_edge is None and e["tick"] < budget["clock_half_period"]:
                    raise ValueError("First clock edge precedes input/route initialization")
                if last_edge is not None and e["tick"]-last_edge < budget["clock_half_period"]:
                    raise ValueError("Clock interval below generated route/capture budget")
                edges.append(e["tick"]); last_edge = e["tick"]
                if next_state[clk] == 1: rising.append(e["tick"])
            if any(n != clk for n in changed) and e["tick"] != 0 and not (clk in changed and next_state[clk] == 0):
                raise ValueError("Change data only on an external falling clock edge")
        if changed: changes.append(e["tick"])
        state = next_state
    # Check points must be after the worst settling budget of the last change.
    for t in checks:
        previous = max([v for v in changes if v<=t],default=0)
        if t-previous < budget["settle"]:
            raise ValueError("Observation precedes the generated settling deadline")
        if clk and sum(edge<t for edge in rising) < 2:
            raise ValueError("Observe registers only after at least two initialization clocks")
    return True


def testbench(graph,layout,vectors,mode):
    lines = ["`timescale 1ns/1ps", "module mapping_tb;"]
    for name,p in graph["ports"].items():
        n,off = len(p["bits"]),p.get("offset",0)
        a,b = (off,off+n-1) if p.get("upto",0) else (off+n-1,off)
        size = f" [{a}:{b}]" if n>1 or off else ""
        if p["direction"] == "input":
            lines.append(f"  reg{size} {name};")
        else:
            lines += [f"  wire{size} gold_{name}, logical_{name};"]
            if mode != "golden": lines.append(f"  wire{size} mapped_{name};")
    def ports(prefix):
        return ", ".join(f".{n}({n if p['direction']=='input' else prefix+n})" for n,p in graph["ports"].items())
    lines += [f"  {graph['top']} gold({ports('gold_')});",f"  gate logic_ref({ports('logical_')});"]
    if mode != "golden":
        lines += [f"  {graph['top']}_mapped dut({ports('mapped_')});", "  initial begin", "`ifndef NO_ANNOTATE",
                  '    $sdf_annotate("mapped.sdf", dut);',"`endif", "  end"]
        # Procedural checks supplement tools that ignore specify timing checks.
        # They observe actual routed D/CLK pins, after the startup interval.
        for c in graph["cells"]:
            if c["kind"] != "DFF": continue
            n = c["name"]
            enable_at = min(vectors["checks"])
            lines += [f"  realtime {n}_data=-100000, {n}_rise=-100000, {n}_edge=-100000;",
                      f"  always @(dut.{n}.D) begin",
                      f'    if ($realtime>{enable_at} && $realtime-{n}_rise<3) $fatal(1,"RMAP_HOLD {n}");',
                      f"    {n}_data=$realtime;", "  end",
                      f"  always @(dut.{n}.CLK) begin",
                      f'    if ($realtime>{enable_at} && $realtime-{n}_edge<17) $fatal(1,"RMAP_CLOCK_WIDTH {n}");',
                      f"    {n}_edge=$realtime;", "  end",
                      f"  always @(posedge dut.{n}.CLK) begin",
                      f'    if ($realtime>{enable_at} && $realtime-{n}_data<11) $fatal(1,"RMAP_SETUP {n}");',
                      f"    {n}_rise=$realtime;", "  end"]
    # Stimulus and observations share a single process; samples are after the
    # current time slot's NBA/delta work, at one precision step beyond a tick.
    lines.append("  initial begin")
    for n,v in sorted(vectors["initial"].items()): lines.append(f"    {n} = {len(graph['ports'][n]['bits'])}'d{v};")
    events = {e["tick"]:e["inputs"] for e in vectors["events"]}
    prev = 0
    for t in sorted(set(events)|set(vectors["checks"])):
        delay = t-prev
        if delay: lines.append(f"    #{delay:.3f};")
        for n,v in sorted(events.get(t,{}).items()): lines.append(f"    {n} = {len(graph['ports'][n]['bits'])}'d{v};")
        prev = t
        if t in vectors["checks"]:
            lines.append("    #0.001;"); prev += 0.001
            for n,p in graph["ports"].items():
                if p["direction"] == "output":
                    lines.append(f'    if (gold_{n} !== logical_{n}) $fatal(1, "RTL_LOGIC_MISMATCH {n} {t}");')
                    if mode != "golden": lines.append(f'    if (gold_{n} !== mapped_{n}) $fatal(1, "RTL_MAPPED_MISMATCH {n} {t}: %b != %b", gold_{n}, mapped_{n});')
                    lines.append(f'    $display("GOLD {t} out_{n} %h", gold_{n});')
            for c in graph["cells"]:
                for p,b in c["pins"].items():
                    expr = "logic_ref."+bit_expr(b) if isinstance(b,int) else bit_expr(b)
                    lines.append(f'    $display("GOLD {t} {c["name"]}_{p} %b", {expr});')
    lines += ['    $display("RMAP_RTL_PASS"); $finish;', "  end", "endmodule", ""]
    return "\n".join(lines)


def simulate(folder,graph,layout,vectors,mode):
    folder = Path(folder)
    rt = runtime()
    tb = folder/f"tb-{mode}.sv"
    tb.write_text(testbench(graph,layout,vectors,mode),encoding="utf-8",newline="\n")
    sources = [s["file"] for s in graph["provenance"]["sources"]]
    files = [*sources,"logical.v",tb.name]
    flags = ["-g2012","-s","mapping_tb"]
    if mode != "golden":
        files += ["mapped.v",f"cells-{'portable' if mode=='portable' else 'timing'}.sv"]
        if mode == "portable": flags += ["-DNO_ANNOTATE"]
        else:
            flags += ["-gspecify"]
            if mode == "sdf": flags += ["-DRMAP_SDF_ONLY"]
            else: flags += ["-DNO_ANNOTATE"]
    commands = [[str(rt["iverilog"]),*flags,"-o",f"{mode}.vvp",*files],
                [str(rt["vvp"]),f"{mode}.vvp"]]
    logs = []
    for command in commands:
        p = subprocess.run(command,cwd=folder,env=rt["env"],capture_output=True,text=True,timeout=180)
        logs.append(p.stdout+p.stderr)
        if p.returncode:
            (folder/f"{mode}.log").write_text("\n".join(logs),encoding="utf-8",newline="\n")
            raise ValueError(f"{mode} simulation failed: {folder / (mode+'.log')}")
    log = "\n".join(logs)
    (folder/f"{mode}.log").write_text(log,encoding="utf-8",newline="\n")
    if "RMAP_RTL_PASS" not in log: raise ValueError("Missing simulation success marker")
    rows = {}
    for t,n,value in re.findall(r"^GOLD (\d+) (\w+) ([0-9a-fxXzZ]+)$",log,re.M):
        if any(c in value.lower() for c in "xz"):
            raise ValueError("The reset/boot sequence did not establish a known RTL state")
        rows.setdefault(int(t),{})[n] = int(value,16 if n.startswith("out_") else 2)
    if set(rows) != set(vectors["checks"]): raise ValueError("Missing golden observation")
    return rows


def prepare(folder,vectors=None):
    folder = Path(folder).resolve()
    dump(folder/"eda-report.json",{"pass":False,"status":"qualification_in_progress"})
    graph,layout,budget = [json.loads((folder/n).read_text()) for n in ("graph.json","layout.json","timing.json")]
    vectors = vectors or example_vectors(graph,budget)
    validate_vectors(graph,budget,vectors)
    dump(folder/"vectors.json",vectors)
    golden = simulate(folder,graph,layout,vectors,"golden")
    for mode in ("specify","sdf","portable"):
        if simulate(folder,graph,layout,vectors,mode) != golden:
            raise ValueError("Mode-dependent golden outputs")
    dump(folder/"golden.json",golden)
    from .mapping_controls import check
    check(folder)
    report = {"pass":True,"modes":["source RTL + logical graph","specify","SDF","portable"],
              "observations":len(golden),"source_probes":sum(map(len,golden.values())),
              "scope":"Settled top-level outputs compared to source RTL; logical internal oracle proven equivalent by Yosys",
              "commercial_execution":"not_run"}
    dump(folder/"eda-report.json",report)
    return graph,layout,budget,vectors,golden
