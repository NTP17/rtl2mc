"""Prefer the user's native UCRT tools; preserve project-local fallback tools."""
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def runtime(*, require_iverilog=True):
    env = dict(os.environ)
    ucrt = Path(env.get("SV2RT_UCRT_ROOT", "C:/msys64/ucrt64"))
    local = ROOT / ".local/eda/msys/ucrt64/bin"
    bins = [ucrt / "bin", ucrt.parent / "usr/bin", local]
    env["PATH"] = os.pathsep.join(str(p) for p in bins if p.exists()) + os.pathsep + env.get("PATH", "")
    ivl = next((p / "iverilog.exe" for p in bins if (p / "iverilog.exe").exists()), None)
    if ivl is None and shutil.which("iverilog", path=env["PATH"]):
        ivl = Path(shutil.which("iverilog", path=env["PATH"]))
    if ivl is None and require_iverilog:
        raise ValueError("Install Icarus in the UCRT root or run tools/fetch_cell_eda.py")
    native_yosys = ucrt / "bin/yosys.exe"
    if native_yosys.exists():
        yosys, prefix = [str(native_yosys)], ""
    elif shutil.which("yosys", path=env["PATH"]):
        yosys, prefix = [shutil.which("yosys", path=env["PATH"])], ""
    else:
        env["PYTHONPATH"] = str(ROOT / ".local/eda/python")
        env["YOWASP_CACHE_DIR"] = str(ROOT / ".local/eda/yowasp-cache")
        env["YOWASP_MOUNT"] = "/work=."
        yosys = [sys.executable, "-c", "import sys,yowasp_yosys; raise SystemExit(yowasp_yosys.run_yosys(sys.argv[1:]))"]
        prefix = "/work/"
    verilator = None
    if (ucrt / "bin/verilator").exists():
        # MSYS Perl needs an MSYS path for FindBin/realpath to locate its runtime.
        msys_script = "/" + ucrt.name + "/bin/verilator"
        verilator = [str(ucrt.parent / "usr/bin/perl.exe"), msys_script]
        env.pop("VERILATOR_ROOT", None)
    elif shutil.which("verilator", path=env["PATH"]):
        verilator = [shutil.which("verilator", path=env["PATH"])]
    vvp = ivl.with_name("vvp.exe" if os.name == "nt" else "vvp") if ivl else None
    return {"env": env, "iverilog": ivl, "vvp": vvp, "yosys": yosys,
            "yosys_path_prefix": prefix, "verilator": verilator, "ucrt_root": ucrt}
