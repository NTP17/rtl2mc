"""Compile synthesizable binary RTL into the measured redstone mapping library."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from redstone_pdk.rtl import synthesize
from redstone_pdk.router import route
from redstone_pdk.mapping_views import export

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="+")
    p.add_argument("--top", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-cells", type=int, default=64)
    args = p.parse_args()
    graph = synthesize(args.sources, args.top, args.out, args.max_cells)
    layout = route(graph)
    budget = export(graph,layout,args.out)
    print(f"Lowered, proved, placed and routed {args.top}: {len(graph['cells'])} logic/register cells, {layout['drc']['route_repeaters']} route buffers, {len(layout['blocks'])} blocks; settle {budget['settle']} gt")

if __name__ == "__main__":
    main()
