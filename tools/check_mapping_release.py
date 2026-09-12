"""Reanalyze the complete supported RTL-mapping release without launching Minecraft."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.mapping_admission import ADMISSION,admit_cells,audit_build
from redstone_pdk.rtl import dump,sha
ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT/"validation/mapping/release.json"


def build_report():
    admission = json.loads(ADMISSION.read_text())
    if admit_cells(admission["evidence"]["run"]) != admission: raise ValueError("Cell admission differs from raw evidence")
    records = [audit_build(ROOT/"builds"/name) for name in ("adder","counter")]
    synthesis = json.loads((ROOT/"validation/mapping/synthesis.json").read_text())
    if synthesis["pass"] is not True or {r["top"] for r in synthesis["records"]} != {"adder","counter"}:
        raise ValueError("Missing synthesis qualification")
    from tools.export_mapping_library import definition
    from redstone_pdk.mapping_admission import normalized
    from redstone_pdk.mapping_views import liberty,cells_verilog
    if json.loads((ROOT/"cells/mapping-logic.json").read_text()) != normalized(definition()):
        raise ValueError("Canonical cell definitions differ")
    canonical = {"mapping.lib":liberty(),**{f"cells-{m}.sv":cells_verilog(m) for m in ("functional","timing","portable")}}
    for name,text in canonical.items():
        if (ROOT/"views/rtl-mapping"/name).read_text() != text: raise ValueError("Canonical EDA view differs")
    for name in ("adder","counter"):
        folder = ROOT/"builds"/name
        v = json.loads((folder/"verilator-report.json").read_text())
        if v["pass"] is not True or sha(folder/"verilator.log") != v["log_sha256"] or sha(folder/"verilator-build.log") != v["build_log_sha256"]:
            raise ValueError("Verilator evidence differs")
        if "RMAP_RTL_PASS" not in (folder/"verilator.log").read_text(): raise ValueError("Missing Verilator marker")
    implementation = [*sorted((ROOT/"redstone_pdk").glob("mapping*.py")),ROOT/"redstone_pdk/rtl.py",ROOT/"redstone_pdk/router.py",
                      ROOT/"redstone_pdk/logic_cells.py",ROOT/"redstone_pdk/logic_fixtures.py",ROOT/"redstone_pdk/route_fixtures.py",
                      ROOT/"redstone_pdk/lab.py",ROOT/"redstone_pdk/fixtures.py",ROOT/"tools/eda_tools.py"]
    implementation += [p for p in sorted((ROOT/"tools").glob("*.py")) if any(s in p.name for s in ("mapping","mapped","map_rtl","import_synth"))]
    artifacts = [ADMISSION,ROOT/"validation/mapping/synthesis.json",ROOT/"cells/mapping-logic.json",*sorted((ROOT/"views/rtl-mapping").glob("*"))]
    for name in ("adder","counter"):
        folder = ROOT/"builds"/name
        artifacts += [p for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix in (".json",".sv",".v",".sdf",".sdc",".lib",".tcl",".f",".mcfunction",".ys",".il",".log")
                      and not any(s.startswith("commercial-") or s=="topology-check" for s in p.relative_to(folder).parts)]
    return {"schema_version":1,"id":"rtl_mapping_v1","pass":True,"commercial_execution":"not_run",
            "status":"local release candidate for the supported synchronous binary subset; licensed-tool qualification pending",
            "cells":admission["coverage"],"designs":records,
            "implementation_sha256":{p.relative_to(ROOT).as_posix():sha(p) for p in implementation},
            "artifacts_sha256":{p.relative_to(ROOT).as_posix():sha(p) for p in artifacts}}


def validate():
    try:
        actual = build_report()
        if not RELEASE.exists() or json.loads(RELEASE.read_text()) != actual:
            raise ValueError("Release manifest differs; rerun qualification before rebuilding it")
        return []
    except (OSError,ValueError,KeyError,TypeError) as error:
        return ["Invalid RTL mapping release: "+str(error)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--record",action="store_true",help="Record the release after all checks have been rerun")
    args = p.parse_args()
    if args.record:
        record = build_report(); RELEASE.parent.mkdir(parents=True,exist_ok=True); dump(RELEASE,record)
    errors = validate()
    if errors: raise ValueError("\n".join(errors))
    print("RTL mapping release passes: 228 primitive/route cases, two physical RTL builds, local GLS and Liberty synthesis")

if __name__ == "__main__": main()
