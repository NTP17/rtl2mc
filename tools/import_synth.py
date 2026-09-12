"""Import a library-mapped vendor/Yosys netlist, prove against a reference build, and reroute."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.rtl import synthesize,yosys,dump,sha,identifier
from redstone_pdk.mapping_views import cells_verilog,export
from redstone_pdk.router import route

def import_netlist(reference,netlist,top,out):
    reference,out = Path(reference).resolve(),Path(out).resolve()
    identifier(top); out.mkdir(parents=True,exist_ok=True)
    prep = out/"import"; prep.mkdir(exist_ok=True)
    shutil.copy2(netlist,prep/"input.v")
    shutil.copy2(reference/"golden.il",prep/"reference.il")
    (prep/"cells.sv").write_text(cells_verilog("functional"),encoding="utf-8",newline="\n")
    yosys(prep,"normalize",f"read_verilog -sv cells.sv input.v\nhierarchy -check -top {top}\nflatten\nsynth -top {top} -noabc\nwrite_verilog -noattr normalized.v\n")
    ref = json.loads((reference/"graph.json").read_text())
    proof = (f"read_rtlil reference.il\nrename {ref['top']} gold\nread_verilog normalized.v\nrename {top} gate\n"
             "proc\ntechmap\nopt\nequiv_make gold gate equiv\nhierarchy -top equiv\nequiv_simple\nequiv_induct -seq 4\nequiv_status -assert\n")
    yosys(prep,"reference_equivalence",proof)
    graph = synthesize([prep/"normalized.v"],top,out)
    layout = route(graph); export(graph,layout,out)
    dump(out/"import-report.json",{"pass":True,"reference":str(reference),"reference_graph_sha256":sha(reference/"graph.json"),
                                   "scope":"Logical library functions checked against reference RTL; new layout requires new vectors/GLS/Minecraft qualification",
                                   "files_sha256":{p.name:sha(p) for p in prep.iterdir() if p.is_file()}})
    return graph

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reference_build"); p.add_argument("netlist"); p.add_argument("--top",required=True); p.add_argument("--out",required=True)
    a = p.parse_args(); g = import_netlist(a.reference_build,a.netlist,a.top,a.out)
    print(f"Imported, proved and rerouted {g['top']}: {len(g['cells'])} cells; qualification still required")
