"""Run/dry-run mapped-build commercial synthesis or SDF GLS from a licensed host."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.mapping_admission import audit_build
from redstone_pdk.mapping_commercial import plan,control_plans
from redstone_pdk.rtl import dump,sha

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("tool",choices=("lc","dc","genus","vcs","questa","xcelium"))
    p.add_argument("build")
    p.add_argument("--mode",choices=("rtl","preserve"),default="rtl")
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--netlist",help="Preserved post-synthesis netlist; exact named topology is checked before replacing mapped.v")
    args = p.parse_args(argv)
    folder = Path(args.build).resolve()
    audit_build(folder)
    if args.netlist:
        if args.tool in ("dc","genus","lc"): raise ValueError("--netlist applies to GLS")
        from check_mapped_netlist import check
        check(folder,args.netlist)
        shutil.copy2(args.netlist,folder/"commercial_imported.v")
        listing = (folder/"commercial.f").read_text().splitlines()
        listing[listing.index("mapped.v")] = "commercial_imported.v"
        (folder/"commercial-post.f").write_text("\n".join(listing)+"\n",encoding="utf-8",newline="\n")
    commands,marker = plan(args.tool,args.mode)
    if args.netlist:
        commands = [["commercial-post.f" if a=="commercial.f" else a for a in c] for c in commands]
    (folder/"arc-commercial.f").write_text("cells-timing.sv\narc-bench.sv\n",encoding="utf-8",newline="\n")
    checks = [{"label":"design","commands":commands,"marker":marker,"expected_failure":False}]+control_plans(args.tool)
    record = {"tool":args.tool,"mode":args.mode,"working_directory":str(folder),"checks":checks,
              "dry_run":args.dry_run,"commercial_execution":"not_run"}
    dump(folder/f"commercial-{args.tool}-plan.json",record)
    if args.dry_run:
        print(json.dumps(record,indent=2)); return 0
    outcomes = []
    for check in checks:
        logs = []
        for command in check["commands"]:
            if not command[0].startswith("./") and not shutil.which(command[0]):
                raise ValueError("Licensed executable is unavailable: "+command[0])
            r = subprocess.run(command,cwd=folder,capture_output=True,text=True,timeout=1800,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            logs.append(r.stdout+r.stderr)
            log = "\n".join(logs)
            path = folder/f"commercial-{args.tool}-{check['label']}.log"
            path.write_text(log,encoding="utf-8",newline="\n")
            if r.returncode and not (check["expected_failure"] and check["marker"] in log):
                raise ValueError("Commercial execution failed; inspect "+str(path))
        diagnostics = [l for l in log.splitlines() if re.search(r"\b(error|fatal|warning)\b|\*[WEF],",l,re.I)]
        remaining = diagnostics
        if check["expected_failure"]: remaining = []  # Required mismatch marker still checked below.
        if check["label"] == "width": remaining = [l for l in diagnostics if not re.search(r"width|timing",l,re.I)]
        if check["marker"] not in log or remaining:
            raise ValueError("Commercial diagnostics require review; no qualification recorded: "+str(path))
        outcomes.append({"label":check["label"],"pass":True,"log_sha256":sha(path),"diagnostics":diagnostics})
    record.update(commercial_execution="executed",pass_checks=True,outcomes=outcomes)
    if args.tool in ("dc","genus"):
        record["next_gate"] = "import_synth.py and requalification" if args.mode == "rtl" else "check_mapped_netlist.py before SDF GLS"
    dump(folder/f"commercial-{args.tool}-report.json",record)
    print("Commercial execution completed; "+record.get("next_gate","inspect SDF coverage and timing-check controls before signoff"))
    return 0

if __name__ == "__main__": raise SystemExit(main())
