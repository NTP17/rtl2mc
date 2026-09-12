"""Require exact named cell/port connectivity before reusing physical SDF."""
import argparse
import json
from pathlib import Path
import shutil
import sys
from collections import defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.rtl import yosys,dump,sha


def topology(module):
    nets = defaultdict(list)
    types = {}
    for name,c in module["cells"].items():
        types[name] = c["type"]
        for pin,bits in c["connections"].items():
            if len(bits) != 1: raise ValueError("Library pins must be scalar")
            nets[bits[0]].append(("cell",name,pin))
    ports = {}
    for name,p in module["ports"].items():
        ports[name] = {k:v for k,v in p.items() if k != "bits"}
        ports[name]["width"] = len(p["bits"])
        for i,b in enumerate(p["bits"]): nets[b].append(("port",name,str(i)))
    groups = []
    for bit,endpoints in nets.items():
        if isinstance(bit,str): endpoints.append(("constant",bit,""))
        groups.append(sorted(endpoints))
    return {"cells":types,"ports":ports,"nets":sorted(groups)}


def check(build,netlist):
    folder = Path(build).resolve()
    work = folder/"topology-check"; work.mkdir(exist_ok=True)
    g = json.loads((folder/"graph.json").read_text()); top = g["top"]+"_mapped"
    shutil.copy2(folder/"cells-functional.sv",work/"cells.sv")
    shutil.copy2(folder/"mapped.v",work/"reference.v")
    shutil.copy2(netlist,work/"candidate.v")
    records = []
    for name in ("reference","candidate"):
        yosys(work,name,f"read_verilog -lib cells.sv\nread_verilog {name}.v\nhierarchy -check -top {top}\nproc\ncheck -assert\nwrite_json {name}.json\n")
        m = json.loads((work/f"{name}.json").read_text())["modules"][top]
        records.append(topology(m))
    if records[0] != records[1]:
        raise ValueError("Named physical topology changed; reroute and requalify before using SDF")
    report = {"pass":True,"instances":len(records[0]["cells"]),"net_groups":len(records[0]["nets"]),
              "reference_sha256":sha(folder/"mapped.v"),"candidate_sha256":sha(netlist)}
    dump(work/"report.json",report)
    return report

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("build"); p.add_argument("netlist")
    a = p.parse_args(); print(check(a.build,a.netlist))
