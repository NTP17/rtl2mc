"""Install small, project-local EDA tool packages; no system/PATH changes.

MSYS2 archives and their SHA-256 values come from each official package page.
Every resolved version, URL and digest is saved for review and repeat installs.
"""
import hashlib
import json
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".local/eda/msys"
LOCK = ROOT / "tools/cell-eda-packages.json"


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError:
        if not url.startswith("https://mirror.msys2.org/"):
            raise
        with urllib.request.urlopen(url.replace("https://mirror.msys2.org/", "https://repo.msys2.org/", 1), timeout=90) as response:
            return response.read()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    packages = json.loads(LOCK.read_text()) if LOCK.exists() else []
    pending = ["mingw-w64-ucrt-x86_64-iverilog"]
    visited = set()
    while pending:
        name = pending.pop(0)
        # Official MSYS2 virtual package, provided by gcc-libs in UCRT64.
        if name == "mingw-w64-ucrt-x86_64-cc-libs":
            name = "mingw-w64-ucrt-x86_64-gcc-libs"
        if name in visited:
            continue
        visited.add(name)
        item = next((p for p in packages if p["name"] == name), None)
        if item is None:
            page = fetch("https://packages.msys2.org/packages/" + name).decode()
            url = re.search(r'href="(https://mirror.msys2.org/mingw/ucrt64/[^"<>]+\.pkg\.tar\.zst)"', page)[1]
            digest = re.search(r'SHA256:.*?([0-9a-f]{64})', page, re.S)[1]
            item = {"name": name, "url": url, "sha256": digest}
            packages.append(item)
        archive = DEST / item["url"].rsplit("/", 1)[-1]
        if not archive.exists():
            archive.write_bytes(fetch(item["url"]))
        if hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Archive digest mismatch: " + name)
        listing = subprocess.check_output(["tar", "-tf", str(archive)], text=True).splitlines()
        # Extract only regular files. Documentation/timezone aliases are not
        # needed by the simulator; never materialize archive links.
        details = subprocess.check_output(["tar", "-tvf", str(archive)], text=True).splitlines()
        if len(listing) != len(details):
            raise ValueError("Archive listings disagree")
        members = [p for p, detail in zip(listing, details) if p.startswith("ucrt64/") and detail.startswith("-")]
        if any(not (DEST / p).resolve().is_relative_to(DEST.resolve()) for p in members):
            raise ValueError("Unsafe archive member")
        item["omitted_links"] = [p for p, detail in zip(listing, details) if detail.startswith(("l", "h"))]
        for start in range(0, len(members), 100):
            subprocess.run(["tar", "-xf", str(archive), "-C", str(DEST), *members[start:start + 100]], check=True)
        info = subprocess.check_output(["tar", "-xOf", str(archive), ".PKGINFO"], text=True)
        deps = re.findall(r"^depend = ([^\s<>=]+)", info, re.M)
        if any(not d.startswith("mingw-w64-ucrt-x86_64-") for d in deps):
            raise ValueError("Unexpected dependency outside the portable UCRT packages")
        item["dependencies"] = deps
        pending.extend(deps)
        LOCK.write_text(json.dumps(packages, indent=2) + "\n", encoding="utf-8")
        print("Installed", name, flush=True)
    LOCK.write_text(json.dumps(packages, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
