#!/usr/bin/env python3
"""Show or download the two checksum-pinned native GameTest build dependencies."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rtl2mc.common import read
from rtl2mc.install import fetch
from rtl2mc.gametest import MAPPINGS_SHA1


def dependencies():
    compiler = read(ROOT / "instrumentation/dependencies.json")["ecj-3.39.0.jar"]
    return [
        {"path": ".local/instrumentation/dependencies/ecj-3.39.0.jar",
         "url": compiler["url"], "algorithm": "sha256", "digest": compiler["sha256"]},
        {"path": ".local/investigation/server-mappings.txt",
         "url": f"https://piston-data.mojang.com/v1/objects/{MAPPINGS_SHA1}/server.txt",
         "algorithm": "sha1", "digest": MAPPINGS_SHA1},
    ]


def ensure(item, install=False):
    path = ROOT / item["path"]
    valid = lambda data: hashlib.new(item["algorithm"], data).hexdigest() == item["digest"]
    if path.is_file() and valid(path.read_bytes()):
        return "verified"
    if not install:
        return "missing or changed"
    data = fetch(item["url"])
    if not valid(data):
        raise ValueError("Downloaded dependency checksum mismatch: " + item["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(data)
    partial.replace(path)
    return "installed and verified"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="download missing pinned dependencies")
    args = parser.parse_args()
    for item in dependencies():
        print(item["path"] + ": " + ensure(item, args.install))
        print("  " + item["url"])
        print("  " + item["algorithm"] + ": " + item["digest"])
    if not args.install:
        print("To download missing files, rerun with --install.")
    print("Java 21 and the Minecraft server are provisioned by rtl2mc.py run.")


if __name__ == "__main__":
    main()
