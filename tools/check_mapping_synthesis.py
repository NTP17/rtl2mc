"""Exercise Liberty technology mapping, logical import, and topology failure controls."""
import json
from pathlib import Path
import sys
import tkinter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.rtl import yosys,dump,sha
from redstone_pdk.mapping_commercial import scripts,plan
from redstone_pdk.mapping_admission import audit_build
from tools.import_synth import import_netlist
from tools.check_mapped_netlist import check
ROOT = Path(__file__).resolve().parents[1]

def main():
    records = []; tcl = tkinter.Tcl()
    for name in ("adder","counter"):
        folder = ROOT/"builds"/name
        script = f"read_liberty -lib mapping.lib\nread_verilog -sv source_0.sv\nsynth -top {name} -noabc\ndffunmap\ndfflibmap -liberty mapping.lib\nabc -liberty mapping.lib\nclean\ncheck -assert\nwrite_verilog -noattr liberty-mapped.v\n"
        yosys(folder,"library_mapping",script)
        work = ROOT/".local"/("mapping_liberty_import_"+name)
        imported = import_netlist(folder,folder/"liberty-mapped.v",name,work)
        topology = check(folder,folder/"mapped.v")
        mutated = work/"mutated.v"
        content = (folder/"mapped.v").read_text()
        content = content.replace("RMAP_NOR2 u","RMAP_INV u",1)
        mutated.write_text(content,encoding="utf-8",newline="\n")
        try: check(folder,mutated)
        except ValueError: negative = True
        else: raise ValueError("Topology mutation was accepted")
        # Restore the saved checker evidence to the successful reference case.
        check(folder,folder/"mapped.v")
        graph = json.loads((folder/"graph.json").read_text())
        budget = json.loads((folder/"timing.json").read_text())
        for filename,expected in scripts(graph,budget).items():
            if (folder/filename).read_text() != expected: raise ValueError("Stale commercial artifact "+filename)
            if filename.endswith((".tcl",".sdc")) and tcl.call("info","complete",expected) != 1:
                raise ValueError("Incomplete Tcl: "+filename)
        import_evidence = json.loads((work/"import-report.json").read_text())
        # Keep portable proof evidence with the build, without duplicating another layout.
        proof_dir = folder/"liberty-import-proof"; proof_dir.mkdir(exist_ok=True)
        import shutil
        for p in (work/"import").iterdir():
            if p.is_file(): shutil.copy2(p,proof_dir/p.name)
        dump(proof_dir/"report.json",import_evidence)
        records.append({"top":name,"pass":True,"liberty_mapping":"actual Yosys dfflibmap and ABC -liberty",
                        "imported_logic_cells":len(imported["cells"]),"reference_topology":topology,
                        "changed_topology_rejected":negative,"vendor_plans":{t:plan(t)[0] for t in ("lc","dc","genus","vcs","questa","xcelium")}})
    out = ROOT/"validation/mapping"; out.mkdir(parents=True,exist_ok=True)
    dump(out/"synthesis.json",{"pass":True,"commercial_execution":"not_run","records":records})
    print("Liberty synthesis/import, topology controls and commercial Tcl checks passed")

if __name__ == "__main__": main()
