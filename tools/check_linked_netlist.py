"""Reject synthesis exports that invalidate a measured network's SDF/placement."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redstone_pdk.project import read_json
from redstone_pdk.connections import CONTRACT, validate_connections
from redstone_pdk.connection_views import PREFIX, top_name
from eda_tools import runtime
from check_cell_eda import command
from check_network_eda import check_topology


def check(fixture, netlist, output=None):
    # Reproduce the native certificate before trusting its exported topology.
    errors = validate_connections(include_eda=False)
    if errors:
        raise ValueError("\n".join(errors))
    record = next((r for r in read_json(ROOT / CONTRACT)["cases"] if r["fixture"] == fixture and r["admitted"]), None)
    if record is None:
        raise ValueError("Only an admitted connection catalog entry can be linked")
    source = Path(netlist).resolve()
    # Avoid Tcl/Yosys script injection through identifiers or file paths.
    if any(c in str(source) for c in '\n\r";'):
        raise ValueError("Unsupported netlist path characters")
    work = ROOT / ".local/eda/linked-export"
    work.mkdir(parents=True, exist_ok=True)
    t = runtime(require_iverilog=False); yp = t["yosys_path_prefix"]
    # Copy read-only external exports into the project so the YoWASP fallback can read them.
    local_source = work / "input.v"
    local_source.write_bytes(source.read_bytes())
    rel = work.relative_to(ROOT).as_posix()
    script = f"read_liberty -lib {yp}{PREFIX}cells.lib; read_verilog {yp}{rel}/input.v; hierarchy -check -top {top_name(record)}; write_json {yp}{rel}/linked.json"
    log = command([*t["yosys"], "-Q", "-T", "-p", script], t["env"])
    modules = read_json(work / "linked.json")["modules"]
    check_topology(modules[top_name(record)], record)
    (work / "yosys.log").write_text(log, encoding="utf-8")
    report = {"pass": True, "fixture": fixture, "top": top_name(record), "instances": len(record["graph"]["nodes"]),
              "meaning": "Exported instance names, types, ports and connections retain the measured SDF/placement association"}
    if output:
        Path(output).write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixture"); p.add_argument("netlist"); p.add_argument("--output")
    args = p.parse_args()
    print(json.dumps(check(args.fixture, args.netlist, args.output), indent=2))
