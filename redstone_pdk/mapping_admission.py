"""Audit measured cell evidence and mapped-design artifacts before handoff."""
import json
from pathlib import Path

from .project import ROOT,technology
from .rtl import dump,sha,graph_from_json,logical_verilog
from .logic_fixtures import logic_cases,external_prediction
from .route_fixtures import route_cases
from .fixtures import compile_functions
from .characterize import load_run,restore_case
from .cells import audit_commands
from .router import route,check_layout
from .mapping_views import structural,sdf,timing_budget,cells_verilog,liberty
from .mapping_lab import functions,expected_values
from .mapping_validation import validate_vectors,testbench
from .results import parse_probe_response
from .lab import score

ADMISSION = ROOT/"characterizations/mapping-cells-v1.json"


def normalized(value):
    return json.loads(json.dumps(value))


def admit_cells(run):
    cases = [restore_case(normalized(c)) for c in logic_cases()+route_cases()]
    analyses,observed,evidence = load_run(run,{c["id"]:c for c in cases},compile_functions(cases))
    if set(observed) != {c["id"] for c in cases}: raise ValueError("Incomplete cell/route sweep")
    commands = [json.loads(l) for l in (ROOT/evidence["run"]/"commands.jsonl").read_text().splitlines()]
    audit_commands(commands,cases,observed)
    comparisons = 0
    for c in logic_cases():
        predicted = {r["tick"]:r["values"] for r in external_prediction(c)}
        for row in observed[c["id"]]:
            t = row["relative_game_tick"]
            # Before-action rows have the preceding input state; output pending
            # events at this tick already executed. Only input pins use t-1.
            for pin,value in predicted[t].items():
                if row["phase"] == "before_action" and pin not in ("y","q"):
                    value = predicted[t-1][pin]
                if row["values"][pin] != value: raise ValueError("Primitive prediction mismatch")
                comparisons += 1
    return {"schema_version":1,"id":"mapping_cells_v1","technology":technology()["id"],
            "status":"measured cells and route motifs; generated designs require their own qualification",
            "coverage":{"cases":len(cases),"logic_and_register_cases":len(logic_cases()),"route_cases":len(route_cases()),
                        "independent_port_comparisons":comparisons},"evidence":evidence,
            "cell_protocol":{"NOR2_INV":{"delay":8,"minimum_measured_dwell":9,"input_high_strengths":[1,8,15]},
                             "DFF":{"clock_to_q":14,"clock_high_low_minimum":17,"setup":11,"hold":3,
                                    "initialization":"clock desired state through the cell; passive settling is insufficient"}},
            "implementation_sha256":{n:sha(ROOT/n) for n in ("redstone_pdk/logic_cells.py","redstone_pdk/logic_fixtures.py","redstone_pdk/route_fixtures.py")},
            "limits":["No general event model for comparator/glitch behavior is claimed",
                      "Routing motifs are compositional evidence, not exhaustive validation of arbitrary layouts",
                      "Use only the generated static geometry, rigid support and reserved air; all chunks loaded"]}


def audit_minecraft(folder,graph,layout,budget,vectors,golden):
    reference = json.loads((folder/"minecraft-report.json").read_text())
    run = (ROOT/reference["run"]).resolve()
    if not run.is_relative_to(ROOT/"results") or reference["report_sha256"] != sha(run/"report.json"):
        raise ValueError("Invalid Minecraft evidence reference")
    report = json.loads((run/"report.json").read_text())
    metadata = json.loads((run/"metadata.json").read_text())
    if report["pass"] is not True or report["metadata"] != metadata or metadata["server_sha1"] != technology()["server"]["sha1"]:
        raise ValueError("Unqualified physical run")
    for name,digest in report["files_sha256"].items():
        if Path(name).name != name or sha(run/name) != digest: raise ValueError("Modified physical run")
    for name,digest in metadata["harness_sha256"].items():
        if Path(name).name != name or sha(run/"harness-source"/name) != digest: raise ValueError("Modified saved harness")
    for name,digest in metadata["build_sha256"].items():
        if Path(name).name != name or sha(run/"build"/name) != digest: raise ValueError("Modified saved build")
    for name in ("graph.json","layout.json","timing.json","vectors.json","golden.json","mapped.v","mapped.sdf"):
        if sha(folder/name) != sha(run/"build"/name): raise ValueError("Build differs from measured physical run: "+name)
    compiled,probes,chunks = functions(graph,layout,vectors,metadata["clear_bounds"])
    if json.loads((run/"compiled-functions.json").read_text()) != compiled:
        raise ValueError("Recorded placement or stimuli differ")
    rows = [json.loads(l) for l in (run/"observations.jsonl").read_text().splitlines()]
    commands = [json.loads(l) for l in (run/"commands.jsonl").read_text().splitlines()]
    prefix = "function pdk_lab:mapped_"+graph["top"]+"/"
    order = [prefix+"setup",prefix+"initial",prefix+"sample"]
    phases = [(-1,"baseline")]
    events = {e["tick"] for e in vectors["events"]}
    for t in sorted(events|set(golden)):
        if t in events:
            phases += [(t,"before_action"),(t,"after_action")]
            order += [prefix+"sample",prefix+f"action_{t}",prefix+"sample"]
        if t in golden:
            phases.append((t,"settled_check")); order.append(prefix+"sample")
    actual_order = [c["command"] for c in commands if c["command"].startswith("function ") and not c["command"].endswith("/loaded")]
    if actual_order != order or [(r["tick"],r["phase"]) for r in rows] != phases:
        raise ValueError("Missing, reordered or extra physical boundaries")
    replies = [(i,c) for i,c in enumerate(commands) if c["command"] == "data get storage pdk_lab:sample values"]
    if len(replies) != len(rows): raise ValueError("Probe reply count mismatch")
    comparisons = 0
    for (i,c),r in zip(replies,rows):
        if parse_probe_response(c["response"],[p["name"] for p in probes]) != r["values"]:
            raise ValueError("Probe reply differs from saved observation")
        following = commands[i+1:i+3]
        if [v["command"] for v in following] != ["execute store result score #time pdk_lab run time query gametime","scoreboard players get #time pdk_lab"]:
            raise ValueError("Missing sample timestamp query")
        if score(following[1]["response"]) != r["game_time"] or r["game_time"] != rows[0]["game_time"]+max(0,r["tick"]):
            raise ValueError("Physical timestamps differ")
        if r["phase"] == "settled_check":
            for name,value in expected_values(layout,golden[r["tick"]]).items():
                if int(r["values"][name]>0) != value: raise ValueError("Physical result does not match RTL")
                comparisons += 1
    if report["observations"] != len(rows) or report["comparisons"] != comparisons or report["checks"] != len(golden) or report["failures"]:
        raise ValueError("Physical report totals differ from raw evidence")
    return {"run":reference["run"],"report_sha256":reference["report_sha256"],"comparisons":comparisons}


def audit_build(folder,require_minecraft=True):
    folder = Path(folder).resolve()
    graph,layout,budget,vectors,golden = [json.loads((folder/n).read_text()) for n in
                                         ("graph.json","layout.json","timing.json","vectors.json","golden.json")]
    golden = {int(k):v for k,v in golden.items()}
    rebuilt = graph_from_json(json.loads((folder/"lowered.json").read_text()),graph["top"])
    if {k:v for k,v in graph.items() if k!="provenance"} != rebuilt:
        raise ValueError("Graph differs from the synthesis output")
    for r in graph["provenance"]["sources"]:
        if Path(r["file"]).name != r["file"] or sha(folder/r["file"]) != r["sha256"]: raise ValueError("Source hash differs")
    for n,h in graph["provenance"]["files_sha256"].items():
        if Path(n).name != n or sha(folder/n) != h: raise ValueError("Synthesis/proof artifact differs")
    if (folder/"logical.v").read_text() != logical_verilog(graph,"gate"):
        raise ValueError("Logical oracle differs")
    rebuilt_layout = route(graph)
    if layout != normalized(rebuilt_layout) or layout["drc"] != check_layout(layout):
        raise ValueError("Layout differs from routing/DRC reanalysis")
    if budget != timing_budget(graph,layout): raise ValueError("Timing budget differs")
    validate_vectors(graph,budget,vectors)
    for n,text in {"mapped.v":structural(graph,rebuilt_layout),"mapped.sdf":sdf(graph,rebuilt_layout),"mapping.lib":liberty(),
                   **{f"cells-{m}.sv":cells_verilog(m) for m in ("functional","timing","portable")},
                   **{f"tb-{m}.sv":testbench(graph,layout,vectors,m) for m in ("golden","specify","sdf","portable")}}.items():
        if (folder/n).read_text() != text: raise ValueError("Stale generated view: "+n)
    for mode in ("golden","specify","sdf","portable"):
        log = (folder/f"{mode}.log").read_text()
        if "RMAP_RTL_PASS" not in log or "MISMATCH" in log or "FATAL" in log: raise ValueError("Failed GLS mode "+mode)
        found = {}
        import re
        for t,n,value in re.findall(r"^GOLD (\d+) (\w+) ([0-9a-f]+)$",log,re.M):
            found.setdefault(int(t),{})[n] = int(value,16 if n.startswith("out_") else 2)
        if found != golden: raise ValueError("Golden log differs")
    from .mapping_controls import artifacts
    for name,content in artifacts().items():
        if (folder/name).read_text() != content: raise ValueError("Stale arc or WIDTH control")
    arc_report = json.loads((folder/"arc-report.json").read_text())
    if arc_report["pass"] is not True or [r["mode"] for r in arc_report["checks"]] != ["specify","sdf","missing_sdf","portable"]:
        raise ValueError("Missing arc coverage")
    for r in arc_report["checks"]:
        log = folder/f"arc-{r['mode']}.log"
        if sha(log) != r["log_sha256"] or r["pass"] is not True: raise ValueError("Changed arc evidence")
        marker = "RMAP_ARC_MISMATCH" if r["mode"] == "missing_sdf" else "RMAP_ARCS_PASS"
        if marker not in log.read_text(): raise ValueError("Arc result marker differs")
    from .mapping_commercial import scripts
    for name,content in scripts(graph,budget).items():
        if (folder/name).read_text() != content: raise ValueError("Stale commercial view: "+name)
    result = {"pass":True,"top":graph["top"],"logic_cells":len(graph["cells"]),"drc":layout["drc"],
              "timing":budget,"source_equivalence":"proven by Yosys; sequential equivalence assumes synchronized state",
              "local_gls_modes":["specify","SDF","portable"],"commercial_execution":"not_run"}
    if require_minecraft: result["minecraft"] = audit_minecraft(folder,graph,layout,budget,vectors,golden)
    return result
