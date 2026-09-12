"""Commercial EDA adapters with explicit dry-run and qualification records.

Run on a licensed tool host from a copy of this repository and its retained evidence.
No commercial tool result is claimed until the corresponding executable runs.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redstone_pdk.project import read_json
from redstone_pdk.connections import CONTRACT, validate_connections
from redstone_pdk.cells import validate_cells
from redstone_pdk.connection_views import PREFIX, EXAMPLE
from redstone_pdk.model_validation import sha

TOOLS = ("vcs", "questa", "xcelium", "lc", "dc", "genus")


def simulation_plan(tool, suite, label, folder, replacement=None):
    if suite == "networks":
        files = (ROOT / PREFIX / "timing.f").read_text().splitlines()+[PREFIX+"input-guard.sv", "validation/network-eda/traces.sv"]
        top, define, success, mismatch = "network_tb", "RNET_SDF_ONLY", "RNET_TRACE_PASS", "RNET_TRACE:"
    else:
        files = ["views/repeater-buffers/repeater-buffers.sv", "validation/cell-eda/traces.sv"]
        top, define, success, mismatch = "trace_tb", "RS_SDF_ONLY", "RS_TRACE_PASS", "RS_TRACE:"
    failure = mismatch if label == "missing-sdf" else None
    defines = [define]+(["NO_ANNOTATE"] if failure else [])
    if label == "width-check":
        files = [PREFIX+"cells-timing.sv", "eda/commercial/width_probe.sv"]
        top, defines, failure = "network_tb", ["RNET_SDF_ONLY"], "RNET_TIMING_WIDTH:"
    if replacement and suite == "networks" and label != "width-check":
        old, new = replacement
        if old not in files:
            raise ValueError("Post-synthesis replacement did not match a known catalog file")
        files[files.index(old)] = new
    folder.mkdir(parents=True, exist_ok=True)
    listing = folder / "files.f"
    listing.write_text("\n".join(files)+"\n", encoding="utf-8", newline="\n")
    f = folder.relative_to(ROOT).as_posix()
    switches = ["+define+"+d for d in defines]
    if tool == "vcs":
        commands = [["vcs", "-full64", "-sverilog", "-timescale=1ns/1ps", "-top", top,
                     "-Mdir="+f+"/csrc", "-o", f+"/simv", *switches, "+sdfverbose", "-f", f+"/files.f"],
                    [str(folder / "simv"), "+sdfverbose"]]
    elif tool == "questa":
        commands = [["vlib", f+"/work"], ["vlog", "-sv", "-work", f+"/work", *switches, "-f", f+"/files.f"],
                    ["vsim", "-c", "-t", "1ps", "-lib", f+"/work", top,
                     "-do", "onerror {quit -code 1}; run -all; quit -code 0"]]
    else:
        commands = [["xrun", "-64bit", "-sv", "-timescale", "1ns/1ps", "-top", top,
                     "-xmlibdirname", f+"/xcelium.d", *switches, "-f", f+"/files.f"]]
    return {"suite": suite, "label": label, "commands": commands, "success": success, "expected_failure": failure,
            "files": files, "directory": f}


def diagnostic_lines(log):
    # Fail closed on SDF mapping failures and tool errors. Retain all warnings for review.
    return [line for line in log.splitlines() if re.search(r"\b(?:error|fatal)(?:-\[|\s*[:\[])|\*\*\s+(?:error|fatal)|\*[EF],", line, re.I)
            or ("sdf" in line.lower() and re.search(r"warn|not found|cannot|failed|unmatched|ignored", line, re.I))]


def preflight():
    errors = validate_connections(include_eda=False)+validate_cells(include_eda=False)
    if errors:
        raise ValueError("\n".join(errors))
    # Golden benches must still be those actually exercised by local qualification.
    for name in ("validation/cell-eda/report.json", "validation/network-eda/report.json"):
        report = read_json(ROOT / name)
        if report["pass"] is not True:
            raise ValueError("Missing local qualification: "+name)
        for field in ("inputs_sha256", "evidence_sha256"):
            for path, expected in report[field].items():
                p = (ROOT / path).resolve()
                if not p.is_relative_to(ROOT) or sha(p) != expected:
                    raise ValueError("Stale qualification input/evidence: "+path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=TOOLS)
    parser.add_argument("--suite", choices=("all", "cells", "networks"), default="all")
    parser.add_argument("--fixture", default=EXAMPLE)
    parser.add_argument("--netlist", help="Post-synthesis export for --fixture; requires Yosys topology check before GLS")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    preflight()
    base = ROOT / ".local/eda/commercial" / args.tool
    base.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    replacement = None
    if args.netlist:
        if args.tool in ("lc", "dc", "genus") or args.suite == "cells":
            raise ValueError("--netlist applies to connected-network GLS")
        from check_linked_netlist import check
        check(args.fixture, args.netlist)
        imported = base / "imported-netlist.v"
        imported.write_bytes(Path(args.netlist).read_bytes())
        replacement = (PREFIX+f"netlists/{args.fixture}.v", imported.relative_to(ROOT).as_posix())
    if args.tool in ("lc", "dc", "genus"):
        records = {r["fixture"]: r for r in read_json(ROOT / CONTRACT)["cases"] if r["admitted"]}
        if args.fixture not in records:
            raise ValueError("Synthesis fixture must be an admitted catalog entry")
        exe, script = {"lc": ("lc_shell", "library_compiler.tcl"), "dc": ("dc_shell", "design_compiler.tcl"), "genus": ("genus", "genus.tcl")}[args.tool]
        commands = [[exe, "-f", "eda/commercial/"+script]]
        if args.tool == "genus":
            commands[0].insert(1, "-no_gui")
        env["SV2RT_FIXTURE"] = args.fixture
        plan = [{"suite": "synthesis", "label": args.fixture, "commands": commands,
                 "success": "RNET_LIBRARY_COMPILE_DONE" if args.tool == "lc" else "RNET_SYNTHESIS_EXPORT_DONE",
                 "expected_failure": None, "files": ["eda/commercial/"+script],
                 "directory": base.relative_to(ROOT).as_posix()}]
    else:
        suites = ["cells", "networks"] if args.suite == "all" else [args.suite]
        plan = [simulation_plan(args.tool, suite, label, base / suite / label, replacement)
                for suite in suites for label in ("annotated", "missing-sdf")]
        if "networks" in suites:
            plan.append(simulation_plan(args.tool, "networks", "width-check", base / "networks/width-check"))
    document = {"tool": args.tool, "dry_run": args.dry_run, "commands": plan,
                "commercial_execution": "not_run", "working_directory": str(ROOT), "fixture": args.fixture}
    if replacement:
        document["post_synthesis_netlist"] = {"path": replacement[1], "sha256": sha(ROOT / replacement[1])}
    (base / "plan.json").write_text(json.dumps(document, indent=2)+"\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps(document, indent=2))
        return 0
    results = []
    for item in plan:
        parts = []
        failure = item["expected_failure"]
        for i, command in enumerate(item["commands"]):
            if i == 0 and shutil.which(command[0]) is None:
                raise ValueError("Licensed tool executable is not on PATH: "+command[0])
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            output = result.stdout+result.stderr; parts.append(output)
            is_simulation = i == len(item["commands"])-1
            if result.returncode and not (failure and is_simulation and failure in output):
                (ROOT / item["directory"] / "failed.log").write_text("\n".join(parts), encoding="utf-8")
                raise ValueError("Commercial command failed; see "+item["directory"]+"/failed.log")
        log = "\n".join(parts)
        logpath = ROOT / item["directory"] / "qualification.log"
        logpath.write_text(log, encoding="utf-8")
        expected_marker = failure or item["success"]
        if expected_marker not in log:
            raise ValueError("Missing qualification marker "+expected_marker+"; inspect "+str(logpath))
        diagnostics = diagnostic_lines(log)
        # Expected failure runs must have the intended marker. All diagnostics remain visible.
        if not failure and diagnostics:
            raise ValueError("Commercial diagnostics require review: "+str(logpath))
        results.append({"suite": item["suite"], "label": item["label"], "pass": True,
                        "expected_failure": failure, "log": logpath.relative_to(ROOT).as_posix(), "log_sha256": sha(logpath),
                        "warnings": [line for line in log.splitlines() if "warn" in line.lower()]})
    if args.tool in ("dc", "genus"):
        from check_linked_netlist import check
        exported = base / args.fixture / "netlist.v"
        topology = check(args.fixture, exported, base / "topology.json")
        results.append(topology)
    document.update({"commercial_execution": "completed", "pass": True, "results": results,
                     "scope": "These exact tools/logs and artifacts only; not electrical timing or unrestricted RTL mapping"})
    # Hash the source views, scripts and reference reports so later results are attributable.
    paths = ["tools/run_commercial.py", "tools/check_linked_netlist.py", "validation/cell-eda/report.json", "validation/network-eda/report.json"]
    paths += [p.relative_to(ROOT).as_posix() for directory in ("eda/commercial", "views/repeater-buffers", PREFIX)
              for p in (ROOT / directory).rglob("*") if p.is_file()]
    document["inputs_sha256"] = {p: sha(ROOT / p) for p in paths}
    (base / "qualification.json").write_text(json.dumps(document, indent=2)+"\n", encoding="utf-8")
    print("Commercial qualification completed: "+str(base / "qualification.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
