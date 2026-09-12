#!/usr/bin/env python3
"""Restore the optional, byte-pinned historical lab evidence into ignored folders."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def restore(archive):
    manifest = json.loads((ROOT / "tests/fixtures/lab-evidence.json").read_text())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Evidence archive checksum mismatch")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest["files_sha256"]):
            raise ValueError("Archive membership differs from the pinned manifest")
        # Validate all members and existing destinations before writing anything.
        for name, digest in manifest["files_sha256"].items():
            rel = PurePosixPath(name)
            target = (ROOT / name).resolve()
            if (rel.is_absolute() or ".." in rel.parts or "\\" in name or
                    rel.parts[0] not in ("results", "builds", "validation") or
                    not target.is_relative_to(ROOT.resolve())):
                raise ValueError("Unsafe evidence destination: " + name)
            if hashlib.sha256(bundle.read(name)).hexdigest() != digest:
                raise ValueError("Evidence member checksum mismatch: " + name)
            if target.exists() and (not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest):
                raise ValueError("Refusing to replace existing different file: " + name)
        for name in names:
            target = ROOT / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(name))
    print(f"Restored and verified {len(names)} archived files.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        restore(args.archive)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
