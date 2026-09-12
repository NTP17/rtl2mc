"""Export the canonical synthesis library and exact logic macro geometry."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.logic_cells import macro
from redstone_pdk.mapping_views import liberty,cells_verilog
from redstone_pdk.rtl import dump
from redstone_pdk.project import technology
ROOT = Path(__file__).resolve().parents[1]

def definition():
    cells = []
    for kind,function in (("NOR2","!(A | B)"),("INV","!A"),("DFF","Q captures D on rising CLK")):
        m = macro(kind)
        cells.append({"name":"RMAP_"+kind,"kind":kind,"function":function,
                      "ports":{n:{"position":p,"access_direction":"south","direction":"output" if n in ("Y","Q") else "input"} for n,p in m["ports"].items()},
                      "blocks":[{"position":p,"state":s} for p,s in sorted(m["blocks"].items())],
                      "support":"rigid stone under every body block; preserve generated guard air",
                      "delay_game_ticks":m["delay_hypothesis"]})
    return {"schema_version":1,"id":"mapping_logic_v1","technology":technology()["id"],"cells":cells,
            "route_buffers":[{"name":f"RMAP_BUF{d}","delay_game_ticks":d,"repeater_setting":d//2} for d in (2,4,6,8)],
            "admission":"characterizations/mapping-cells-v1.json","units":"1 simulation ns = 1 game tick",
            "scope":"Supported binary synchronous mapping; a new routed design requires its own qualification",
            "protocol_reference":"docs/rtl-mapping.md"}

def main():
    folder = ROOT/"views/rtl-mapping"; folder.mkdir(parents=True,exist_ok=True)
    dump(ROOT/"cells/mapping-logic.json",definition())
    (folder/"mapping.lib").write_text(liberty(),encoding="utf-8",newline="\n")
    for mode in ("functional","timing","portable"):
        (folder/f"cells-{mode}.sv").write_text(cells_verilog(mode),encoding="utf-8",newline="\n")
    print("Canonical mapping library exported")

if __name__ == "__main__": main()
