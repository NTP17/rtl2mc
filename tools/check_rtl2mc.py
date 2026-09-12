"""Repeat file-list/synthesis/import/GLS integration without starting Minecraft."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from redstone_pdk.router import route
from redstone_pdk.mapping_views import export
from rtl2mc.cli import config_for
from rtl2mc.common import ROOT, dump
from rtl2mc.filelist import parse, snapshot
from rtl2mc.frontend import synthesize
from rtl2mc.toolchain import discover, select
from rtl2mc.verification import vectors, verify


def main():
    tools, env = discover()
    selection = select(tools, simulation="icarus", imported=True)
    results = []
    for top in ("adder", "mux2", "counter", "shift2"):
        folder = ROOT / "builds/rtl2mc-dc-adapters" / top
        folder.mkdir(parents=True, exist_ok=True)
        listing = ROOT / "examples/rtl" / (top + ".f")
        config = config_for(listing)
        inputs = snapshot(parse(listing), folder)
        graph = synthesize(folder, inputs, top, selection, tools, env, config,
                           imported=ROOT / "validation/synopsys-simple" / top / "netlist.v", imported_top=top+"_gate")
        layout = route(graph)
        budget = export(graph, layout, folder)
        vector_set = vectors(graph, budget, config)
        dump(folder / "vectors.json", vector_set)
        _, report = verify(folder, graph, layout, vector_set, selection, tools, env)
        results.append({"top": top, "pass": report["pass"], "preserved_logic_instances": len(graph["cells"]),
                        "route_repeaters": layout["drc"]["route_repeaters"], "observations": report["observations"]})
        print(top + ": topology-preserving import, equivalence, routing and Icarus GLS passed", flush=True)
    destination = ROOT / "validation/rtl2mc"
    destination.mkdir(exist_ok=True)
    dump(destination / "dc-import.json", {"pass": True, "results": results,
                                          "scope": "Imported existing native DC artifacts; no new commercial tool execution or Minecraft measurement in this check"})


if __name__ == "__main__":
    main()
