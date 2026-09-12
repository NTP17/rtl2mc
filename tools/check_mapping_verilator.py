"""Exercise the mapped portable timing view with the installed Verilator."""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.eda_tools import runtime
from redstone_pdk.rtl import dump,sha
ROOT = Path(__file__).resolve().parents[1]

def check(folder):
    folder = Path(folder).resolve(); graph = json.loads((folder/"graph.json").read_text())
    rt = runtime(); exe = rt["verilator"]
    if not exe: raise ValueError("Verilator is unavailable")
    obj = ROOT/".local/eda"/("mapping_"+graph["top"])
    obj.mkdir(parents=True,exist_ok=True)
    command = [*exe,"--binary","--timing","--timescale-override","1ns/1ps","-j","2","-Wno-DECLFILENAME","-Wno-WIDTHEXPAND","-Wno-WIDTHTRUNC",
               "-MAKEFLAGS","OPT_FAST=-O0 OPT_SLOW=-O0","--top-module","mapping_tb","--prefix","Vmapping_tb",
               "--Mdir",obj.as_posix(),"+define+NO_ANNOTATE",*[s["file"] for s in graph["provenance"]["sources"]],
               "logical.v","mapped.v","cells-portable.sv","tb-portable.sv"]
    p = subprocess.run(command,cwd=folder,env=rt["env"],capture_output=True,text=True,timeout=900)
    (folder/"verilator-build.log").write_text(p.stdout+p.stderr,encoding="utf-8",newline="\n")
    if p.returncode: raise ValueError("Verilator build failed: "+str(folder/"verilator-build.log"))
    binary = next(p for p in (obj/"Vmapping_tb.exe",obj/"Vmapping_tb") if p.exists())
    r = subprocess.run([str(binary)],cwd=folder,env=rt["env"],capture_output=True,text=True,timeout=180)
    (folder/"verilator.log").write_text(r.stdout+r.stderr,encoding="utf-8",newline="\n")
    if r.returncode or "RMAP_RTL_PASS" not in r.stdout: raise ValueError("Verilator simulation failed")
    dump(folder/"verilator-report.json",{"pass":True,"mode":"portable timing; specify/SDF not supported by Verilator",
                                         "log_sha256":sha(folder/"verilator.log"),"build_log_sha256":sha(folder/"verilator-build.log")})
    print("Verilator passed: "+graph["top"],flush=True)

if __name__ == "__main__":
    for folder in sys.argv[1:]: check(folder)
