#!/usr/bin/env python3
"""Offline checks of repository source, data, local documentation links and views."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    errors = []
    archive = json.loads((ROOT / "tests/fixtures/lab-evidence.json").read_text(encoding="utf-8"))
    optional_files = set(archive["files_sha256"])
    optional_links = 0
    excluded = {".git", ".local", ".venv", "__pycache__", "builds", "results", "validation", "dist"}
    files = [p for p in ROOT.rglob("*") if p.is_file() and
             not set(p.relative_to(ROOT).parts) & excluded]
    for path in files:
        try:
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            elif path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8-sig"))
            elif path.suffix == ".md":
                content = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
                for link in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", content):
                    link = link.split(' "', 1)[0].strip("<>")
                    parsed = urlsplit(link)
                    if not parsed.scheme and not parsed.netloc and parsed.path:
                        target = path.parent / unquote(parsed.path)
                        if not target.exists():
                            relative = target.resolve().relative_to(ROOT).as_posix()
                            if relative in optional_files:
                                optional_links += 1
                            else:
                                errors.append(f"{path.relative_to(ROOT)}: missing link {link}")
        except (OSError, ValueError, SyntaxError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    for name in ("views/buffer-network/manifest.json", "views/repeater-buffers/manifest.json"):
        manifest = json.loads((ROOT / name).read_text(encoding="utf-8"))
        for relative, digest in manifest["files"].items():
            path = ROOT / relative
            # The early repeater view generator hashed LF text before Windows
            # wrote CRLF files. Later network manifests hash actual file bytes.
            content = (path.read_text(encoding="utf-8").encode("utf-8")
                       if name.startswith("views/repeater-buffers/") else path.read_bytes()) if path.is_file() else b""
            if not path.is_file() or hashlib.sha256(content).hexdigest() != digest:
                errors.append("Canonical view changed: " + relative)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Repository checks passed: {len(files)} files; Python/JSON, local Markdown links and canonical view hashes.")
    if optional_links:
        print(f"{optional_links} link(s) refer to explicitly cataloged optional lab evidence; see docs/testing.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
