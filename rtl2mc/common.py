"""Small, shared filesystem and process helpers (no shell evaluation)."""
import json
import os
from pathlib import Path
import subprocess

from redstone_pdk.rtl import dump, sha

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".local/rtl2mc"


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def execute(command, folder, label, env=None, timeout=600, allow_failure=False):
    """Record argv and output, never environment variables or credentials."""
    folder = Path(folder)
    dump(folder / (label + ".command.json"), list(map(str, command)))
    try:
        p = subprocess.run(list(map(str, command)), cwd=folder, env=env,
                           capture_output=True, text=True, errors="replace", timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as exc:
        write(folder / (label + ".log"), "Process timed out.\n" + str(exc.stdout or "") + str(exc.stderr or ""))
        raise RuntimeError(f"{label} timed out; see {folder / (label + '.log')}") from exc
    log = p.stdout + p.stderr
    write(folder / (label + ".log"), log)
    if p.returncode and not allow_failure:
        raise RuntimeError(f"{label} failed ({p.returncode}); see {folder / (label + '.log')}")
    return p.returncode, log


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def quote(text):
    """A Yosys string, not a shell string."""
    text = str(text).replace("\\", "/")
    if any(c in text for c in ('"', '\n', '\r', '\x00')):
        raise ValueError("Unsupported character in tool argument")
    return '"' + text + '"'


def tcl_list(items):
    # Braces prevent Tcl substitutions; reject nested brace/escape syntax.
    values = []
    for item in items:
        text = str(item).replace("\\", "/")
        if any(c in text for c in "{}\n\r\x00"):
            raise ValueError("Unsupported character in Tcl argument")
        values.append("{" + text + "}")
    return "[list " + " ".join(values) + "]"
