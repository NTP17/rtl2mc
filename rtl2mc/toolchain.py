"""Per-stage commercial-first discovery; executable presence is not a license test."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .common import CACHE, ROOT

TOOLS = {
    "dc": ("dc_shell", "-version"), "lc": ("lc_shell", "-version"),
    "genus": ("genus", "-version"), "vcs": ("vcs", "-ID"),
    "xcelium": ("xrun", "-version"), "yosys": ("yosys", "-V"),
    "questa": ("vsim", "-version"), "vlog": ("vlog", "-version"), "vlib": ("vlib", "-help"),
    "icarus": ("iverilog", "-V"), "vvp": ("vvp", "-V"),
    "verilator": ("verilator", "--version"), "java": ("java", "-version"),
}


def environment(extra=()):
    env = dict(os.environ)
    dirs = [Path(p) for p in extra]
    dirs += [Path(p) for p in env.get("RTL2MC_TOOL_PATH", "").split(os.pathsep) if p]
    for key in ("DC_HOME", "SYNOPSYS", "VCS_HOME", "GENUS_HOME", "XCELIUM_HOME", "CDS_INST_DIR", "QUESTA_HOME", "MODEL_TECH", "JAVA_HOME"):
        if env.get(key):
            dirs += [Path(env[key]) / "bin", Path(env[key]) / "tools/bin"]
    dirs += [Path(env.get("SV2RT_UCRT_ROOT", "C:/msys64/ucrt64")) / "bin"] if os.name == "nt" else []
    # PATH installations take precedence over previously bootstrapped copies.
    dirs += [Path(p) for p in env.get("PATH", "").split(os.pathsep) if p]
    dirs += [CACHE / "msys/ucrt64/bin", CACHE / "conda/bin", ROOT / ".local/eda/msys/ucrt64/bin"]
    exe = "java.exe" if os.name == "nt" else "java"
    dirs += [p.parent for root in (ROOT / ".local/java", CACHE / "java") for p in root.glob("*/bin/" + exe)]
    usable = []
    for path in dirs:
        try:
            if path.is_dir():
                usable.append(str(path.resolve()))
        except OSError:
            # PATH can contain stale junctions or directories this user cannot read.
            continue
    env["PATH"] = os.pathsep.join(dict.fromkeys(usable))
    python_roots = [p for p in (CACHE / "python", ROOT / ".local/eda/python") if (p / "yowasp_yosys").is_dir()]
    if python_roots:
        env["PYTHONPATH"] = os.pathsep.join(map(str, python_roots)) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["YOWASP_CACHE_DIR"] = str(CACHE / "wasm-cache")
        # / is only this run's cwd, not the host filesystem root.
        env["YOWASP_MOUNT"] = "/=."
    return env


def discover(extra=(), java_major=21):
    env = environment(extra)
    found = {}
    for name, (binary, flag) in TOOLS.items():
        override = os.environ.get("RTL2MC_" + name.upper())
        path = shutil.which(override or binary, path=env["PATH"])
        if name == "java" and not override:
            # Keep searching if a PATH runtime is older than this MC target.
            executable = "java.exe" if os.name == "nt" else "java"
            for directory in env["PATH"].split(os.pathsep):
                candidate = Path(directory) / executable
                if not candidate.is_file():
                    continue
                try:
                    p = subprocess.run([str(candidate), "-version"], env=env, capture_output=True, text=True, timeout=15,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    m = re.search(r'version "(\d+)', p.stdout+p.stderr)
                    if p.returncode == 0 and m and int(m[1]) >= java_major:
                        path = str(candidate)
                        break
                except (OSError, subprocess.TimeoutExpired):
                    continue
        wasm = name == "yosys" and (override == "wasm" or (not path and not override)) and any(
            (p / "yowasp_yosys").is_dir() for p in (CACHE / "python", ROOT / ".local/eda/python"))
        if wasm:
            path = sys.executable
        if not path:
            found[name] = {"available": False, "reason": "not found"}
            continue
        argv = [path]
        if wasm:
            argv = [sys.executable, "-c", "import sys,yowasp_yosys; raise SystemExit(yowasp_yosys.run_yosys(sys.argv[1:]))"]
        if name == "verilator" and os.name == "nt":
            ucrt = Path(path).parent.parent
            perl = ucrt.parent / "usr/bin/perl.exe"
            if (ucrt / "bin/verilator").is_file() and perl.is_file():
                argv = [str(perl), "/" + ucrt.name + "/bin/verilator"]
        try:
            p = subprocess.run([*argv, flag], env=env, capture_output=True, text=True,
                               errors="replace", timeout=180 if wasm else 20,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            text = (p.stdout + p.stderr).strip()
            ok = p.returncode == 0
            # DC V-2023.12-SP3 prints its version successfully but exits 1.
            # Admit only that diagnostic shape; synthesis still checks its
            # own status, error messages, license and positive pass marker.
            if name == "dc" and p.returncode == 1:
                ok = bool(re.search(r"(?m)^dc_shell version\s+-\s+\S+", text)) and not bool(
                    re.search(r"(?im)^\s*(?:error|fatal)\b", text))
            if name == "java":
                m = re.search(r'version "(\d+)', text)
                ok = ok and bool(m) and int(m[1]) >= java_major
            found[name] = {"available": ok, "argv": argv, "version": text[:1800],
                           "version_exit_code": p.returncode,
                           "reason": "version probe passed; license not yet checked" if ok else "version probe failed"}
            if name == "java" and m:
                found[name]["major"] = int(m[1])
            if wasm:
                found[name]["implementation"] = "YoWASP package; upstream release version reported by the engine"
        except (OSError, subprocess.TimeoutExpired) as exc:
            found[name] = {"available": False, "argv": argv, "reason": str(exc)}
    return found, env


def simulation_available(found, name):
    dependencies = {"icarus": ("vvp",), "questa": ("vlog", "vlib")}
    return all(found.get(n, {}).get("available", False) for n in (name, *dependencies.get(name, ())))


def select(found, synthesis="auto", simulation="auto", imported=False):
    have = lambda name: found.get(name, {}).get("available", False)
    synths = [name for name in ("dc", "genus", "yosys") if have(name) and (name != "dc" or have("lc"))]
    sims = [name for name in ("vcs", "xcelium", "questa", "icarus") if simulation_available(found, name)]
    if synthesis != "auto":
        synths = [synthesis] if synthesis in synths else []
    if simulation != "auto":
        sims = [simulation] if simulation in sims else []
    missing = []
    if not have("yosys"):
        missing.append("yosys (structural import / equivalence helper, including commercial flows)")
    if not imported and not synths:
        missing.append("synthesis backend" if synthesis == "auto" else synthesis)
    if not sims:
        missing.append("four-state simulation backend" if simulation == "auto" else simulation)
    if not have("java"):
        missing.append("compatible Java runtime")
    return {"synthesis": "import" if imported else (synths[0] if synths else None),
            "simulation": sims[0] if sims else None, "synthesis_candidates": synths,
            "simulation_candidates": sims, "missing": missing,
            "verilator": "optional portable-timing cross-check; not an SDF/four-state substitute"}


def unavailable_license(log):
    return bool(re.search(r"license.*(?:checkout failed|not available|denied)|"
                          r"unable to (?:check.?out|obtain).*license|"
                          r"cannot (?:check.?out|connect to).*license|"
                          r"no valid license|LM_LICENSE_FILE.*not set", log, re.I))
