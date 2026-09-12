"""Run placed RTL in the identified local lab; record sparse boundaries explicitly."""
import json
from datetime import datetime, timezone
from pathlib import Path
import secrets
import shutil

from . import lab
from .project import ROOT,technology
from .rtl import dump,sha
from .router import check_layout
from .mapping_views import clear_commands
from .mapping_validation import validate_vectors
from .results import parse_probe_response


def check_bounds(bounds):
    low,high = bounds
    if any(type(v) is not int for p in bounds for v in p) or not all(a<=b for a,b in zip(low,high)):
        raise ValueError("Invalid layout bounds")
    if not all(a<=x<=b for p in bounds for a,x,b in zip((256,79,0),p,(2047,85,2047))):
        raise ValueError("Mapping measurement escapes its reserved lab region")


def functions(graph,layout,vectors,clear_bounds):
    check_bounds(clear_bounds)
    prefix = "mapped_"+graph["top"]
    compiled = {}
    cmds = list(clear_commands(clear_bounds))
    cmds += ["setblock "+" ".join(map(str,b["position"]))+" minecraft:"+b["state"]
             for b in sorted(layout["blocks"],key=lambda b:(b["position"][1],b["position"][0],b["position"][2]))]
    if len(cmds)>60000: raise ValueError("Placement exceeds vanilla command budget")
    compiled[prefix+"/setup"] = "\n".join(cmds)+"\n"
    def source_commands(values):
        return ["setblock "+" ".join(map(str,s["position"]))+" minecraft:"+
                ("redstone_block" if (values[s["port"]]>>s["bit_index"])&1 else "air")
                for s in layout["sources"] if "port" in s and s["port"] in values]
    compiled[prefix+"/initial"] = "\n".join(source_commands(vectors["initial"]))+"\n"
    for e in vectors["events"]:
        compiled[prefix+f"/action_{e['tick']}"] = "\n".join(source_commands(e["inputs"]))+"\n"
    probes = [{"name":o["name"],"position":o["position"]} for o in layout["outputs"]]
    probes += [{"name":m["name"]+"_"+p,"position":pos} for m in layout["macros"] for p,pos in m["ports"].items()]
    probes += [{"name":s["name"],"position":s["probe"]} for s in layout["sources"]]
    sample = ["data modify storage pdk_lab:sample values set value {}"]
    for p in probes:
        sample += ["scoreboard players set #probe pdk_lab -1"]
        pos = " ".join(map(str,p["position"]))
        for v in range(16):
            sample.append(f"execute if block {pos} minecraft:redstone_wire[power={v}] run scoreboard players set #probe pdk_lab {v}")
        sample.append(f"execute store result storage pdk_lab:sample values.{p['name']} int 1 run scoreboard players get #probe pdk_lab")
    if len(probes)>200: raise ValueError("Probe response exceeds the short RCON transport budget")
    compiled[prefix+"/sample"] = "\n".join(sample)+"\n"
    low,high = clear_bounds
    chunks = [(x,z) for x in range(low[0]//16,high[0]//16+1) for z in range(low[2]//16,high[2]//16+1)]
    compiled[prefix+"/loaded"] = "scoreboard players set #loaded pdk_lab 0\n"+"\n".join(
        f"execute if loaded {x*16} 80 {z*16} run scoreboard players add #loaded pdk_lab 1" for x,z in chunks)+"\n"
    return compiled,probes,chunks


def expected_values(layout,golden):
    result = {n:v for n,v in golden.items() if not n.startswith("out_")}
    result.update({o["name"]:(golden["out_"+o["port"]]>>o["bit_index"])&1 for o in layout["outputs"]})
    return result


def run(folder):
    folder = Path(folder).resolve()
    graph,layout,budget,vectors,golden = [json.loads((folder/n).read_text()) for n in
                                          ("graph.json","layout.json","timing.json","vectors.json","golden.json")]
    golden = {int(k):v for k,v in golden.items()}
    validate_vectors(graph,budget,vectors); check_layout(layout); check_bounds(layout["bounds"])
    if lab.file_hash(lab.SERVER/"server.jar","sha1") != technology()["server"]["sha1"]:
        raise ValueError("The lab server differs from the pinned vanilla build")
    bounds = layout["bounds"]
    previous = lab.LOCAL/"mapping-bounds.json"
    if previous.exists():
        old = json.loads(previous.read_text()); check_bounds(old)
        bounds = [[min(a,b) for a,b in zip(old[0],bounds[0])],[max(a,b) for a,b in zip(old[1],bounds[1])]]
    compiled,probes,chunks = functions(graph,layout,vectors,bounds)
    run_dir = ROOT/"results"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-mapped-"+secrets.token_hex(3))
    run_dir.mkdir(parents=True)
    dump(folder/"minecraft-report.json",{"run":run_dir.relative_to(ROOT).as_posix(),"pass":False,"status":"measurement_in_progress"})
    dump(run_dir/"compiled-functions.json",compiled)
    build_copy = run_dir/"build"; build_copy.mkdir()
    for p in folder.iterdir():
        if p.is_file() and p.suffix not in (".vvp",): shutil.copy2(p,build_copy/p.name)
    harness = run_dir/"harness-source"; harness.mkdir()
    for p in (ROOT/"redstone_pdk").glob("*.py"): shutil.copy2(p,harness/p.name)
    metadata = {"technology":technology()["id"],"server_sha1":technology()["server"]["sha1"],
                "build":folder.relative_to(ROOT).as_posix(),"resolution":"sparse: before/after each stimulus and explicitly scheduled settled checks; integer game ticks",
                "requested_tick_rate":1000,"clear_bounds":bounds,"chunks":len(chunks),
                "build_sha256":{p.name:sha(p) for p in build_copy.iterdir()},
                "harness_sha256":{p.name:sha(p) for p in harness.iterdir()}}
    dump(run_dir/"metadata.json",metadata)
    prefix = "mapped_"+graph["top"]
    events = {e["tick"]:e for e in vectors["events"]}
    boundaries = sorted(set(events)|set(golden))
    rows,failures = [],[]
    forced = []
    with (run_dir/"commands.jsonl").open("w",encoding="utf-8") as command_log, (run_dir/"observations.jsonl").open("w",encoding="utf-8") as observations:
        def log(entry):
            command_log.write(json.dumps(entry)+"\n"); command_log.flush()
        with lab.connect(log) as client:
            lab.assert_identity(client)
            lab.install_datapack(compiled); lab.checked(client,"reload")
            lab.checked(client,"tick freeze"); lab.checked(client,"tick rate 1000")
            for name,value in (("randomTickSpeed","0"),("doMobSpawning","false"),("doTileDrops","false"),("maxCommandChainLength","65536")):
                lab.checked(client,f"gamerule {name} {value}")
            low,high = bounds
            try:
                for x in range(low[0]//16,high[0]//16+1,16):
                    for z in range(low[2]//16,high[2]//16+1,16):
                        rect = f"{x*16} {z*16} {min(x+15,high[0]//16)*16} {min(z+15,high[2]//16)*16}"
                        lab.checked(client,"forceload add "+rect); forced.append(rect)
                for _ in range(200):
                    lab.checked(client,f"function pdk_lab:{prefix}/loaded")
                    loaded = lab.score(client.command("scoreboard players get #loaded pdk_lab"))
                    if loaded == len(chunks): break
                    lab.step(client,10)
                else: raise ValueError("Mapped layout chunks did not load")
                print(f"Loaded {len(chunks)} chunks; placing {len(layout['blocks'])} blocks",flush=True)
                lab.checked(client,"kill @e[type=minecraft:item,x=256,y=79,z=0,dx=1791,dy=10,dz=2047]")
                lab.checked(client,f"function pdk_lab:{prefix}/setup")
                dump(previous,bounds)
                lab.step(client,budget["settle"])
                lab.checked(client,f"function pdk_lab:{prefix}/initial")
                lab.step(client,budget["settle"])
                start = lab.game_time(client)
                def sample(t,phase):
                    lab.checked(client,f"function pdk_lab:{prefix}/sample")
                    actual = parse_probe_response(client.command("data get storage pdk_lab:sample values"),[p["name"] for p in probes])
                    current = lab.game_time(client)
                    if current != start+max(t,0): raise ValueError("Unexpected tick advance")
                    row = {"tick":t,"phase":phase,"game_time":current,"values":actual}
                    observations.write(json.dumps(row)+"\n"); observations.flush(); rows.append(row)
                    if t in golden and phase == "settled_check":
                        expected = expected_values(layout,golden[t])
                        for name,value in expected.items():
                            if int(actual[name]>0) != value:
                                failures.append({"tick":t,"probe":name,"expected":value,"actual_strength":actual[name]})
                        print(f"{graph['top']} t={t}: {'FAIL' if any(f['tick']==t for f in failures) else 'PASS'}",flush=True)
                    dump(run_dir/"progress.json",{"boundaries":len(rows),"checks_completed":sum(r["phase"]=="settled_check" for r in rows),"checks_total":len(golden),"failures":failures})
                sample(-1,"baseline")
                now = 0
                for t in boundaries:
                    if t>now: lab.step(client,t-now)
                    now = t
                    if t in events:
                        sample(t,"before_action")
                        lab.checked(client,f"function pdk_lab:{prefix}/action_{t}")
                        sample(t,"after_action")
                    if t in golden: sample(t,"settled_check")
                lab.checked(client,"save-all")
            finally:
                for rect in forced:
                    try: lab.checked(client,"forceload remove "+rect)
                    except OSError: break
    report = {"pass":not failures,"metadata":metadata,"observations":len(rows),"checks":len(golden),
              "comparisons":sum(len(expected_values(layout,r)) for r in golden.values()),"failures":failures,
              "files_sha256":{n:sha(run_dir/n) for n in ("metadata.json","compiled-functions.json","commands.jsonl","observations.jsonl")}}
    dump(run_dir/"report.json",report)
    dump(folder/"minecraft-report.json",{"run":run_dir.relative_to(ROOT).as_posix(),"report_sha256":sha(run_dir/"report.json"),"pass":not failures})
    print("Minecraft report: "+str(run_dir/"report.json"),flush=True)
    if failures: raise ValueError(f"{len(failures)} mapped physical comparisons failed")
    return run_dir
