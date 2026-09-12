"""Check commercial handoff packaging locally without launching licensed tools."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tkinter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redstone_pdk.project import read_json
from redstone_pdk.model_validation import sha
from redstone_pdk.connection_views import PREFIX, EXAMPLE
import run_commercial


def main():
    out = ROOT / "validation/commercial-adapters"
    out.mkdir(parents=True, exist_ok=True)
    tcl = tkinter.Tcl()
    scripts = sorted((ROOT / "eda/commercial").glob("*.tcl"))+sorted((ROOT / PREFIX / "constraints").glob("*.sdc"))
    for p in scripts:
        if tcl.call("info", "complete", p.read_text()) != 1:
            raise ValueError("Incomplete Tcl syntax: "+str(p))
    plans = []
    for tool in run_commercial.TOOLS:
        with contextlib.redirect_stdout(io.StringIO()):
            run_commercial.main([tool, "--dry-run"])
        plan = read_json(ROOT / f".local/eda/commercial/{tool}/plan.json")
        for item in plan["commands"]:
            for filename in item["files"]:
                if not (ROOT / filename).is_file():
                    raise ValueError("Missing file-list source: "+filename)
        plans.append(plan)
    with contextlib.redirect_stdout(io.StringIO()):
        run_commercial.main(["vcs", "--dry-run", "--suite", "networks", "--fixture", EXAMPLE,
                             "--netlist", PREFIX+f"netlists/{EXAMPLE}.v"])
    replacement = read_json(ROOT / ".local/eda/commercial/vcs/plan.json")
    if "post_synthesis_netlist" not in replacement:
        raise ValueError("Post-synthesis substitution path was not exercised")
    plans.append(replacement)
    (out / "plans.json").write_text(json.dumps(plans, indent=2)+"\n", encoding="utf-8")
    inputs = ["tools/check_commercial_adapters.py", "tools/run_commercial.py", "tools/check_linked_netlist.py",
              "validation/network-eda/report.json", "validation/cell-eda/report.json", PREFIX+"manifest.json"]
    inputs += [p.relative_to(ROOT).as_posix() for p in (ROOT / "eda/commercial").rglob("*") if p.is_file()]
    executables = ("vcs", "vlog", "vsim", "xrun", "lc_shell", "dc_shell", "genus")
    report = {"schema_version": 1, "pass": True, "scope": "Local package checks only; no licensed commercial tool execution",
              "commercial_execution": "not_run", "tools_with_valid_dry_run": list(run_commercial.TOOLS),
              "complete_tcl_commands": len(scripts), "tcl_version": tcl.call("info", "patchlevel"),
              "post_synthesis_substitution_checked": True, "post_synthesis_test_input": "unmodified reference export; actual vendor export pending",
              "commercial_executables_on_path": {exe: shutil.which(exe) for exe in executables},
              "inputs_sha256": {p: sha(ROOT / p) for p in inputs},
              "evidence_sha256": {"validation/commercial-adapters/plans.json": sha(out / "plans.json")},
              "limits": ["Tcl completeness does not validate vendor commands, flags, or Liberty import",
                         "Dry-run generation does not validate licensed execution or WIDTH enforcement",
                         "The actual synthesis export must still pass topology checking and commercial GLS"]}
    (out / "report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("pass", "scope", "tools_with_valid_dry_run", "complete_tcl_commands", "post_synthesis_substitution_checked")}, indent=2))


if __name__ == "__main__":
    main()
