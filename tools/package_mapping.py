"""Build a portable, locally verified source/evidence archive; exclude runtimes and credentials."""
from pathlib import Path
import json
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.check_mapping_release import validate
from redstone_pdk.rtl import sha
ROOT = Path(__file__).resolve().parents[1]

def main():
    errors = validate()
    if errors: raise ValueError("\n".join(errors))
    prefixes = ("redstone_pdk","tools","technology","schema","components","characterizations","cells","connections",
                "models","docs","eda","views","validation","examples","tests","builds")
    paths = {ROOT/name for name in ("README.md","pdk.py",".gitattributes",".gitignore")}
    for name in prefixes:
        paths.update(p for p in (ROOT/name).rglob("*") if p.is_file())
    for line in (ROOT/".gitignore").read_text().splitlines():
        if line.startswith("!results/") and line.endswith("/"):
            directory = ROOT/line[1:-1]
            if not directory.resolve().is_relative_to(ROOT/"results"): raise ValueError("Invalid evidence path")
            paths.update(p for p in directory.rglob("*") if p.is_file())
    selected = []
    for p in sorted(paths):
        if not p.resolve().is_relative_to(ROOT): raise ValueError("Package input escapes workspace")
        relative = p.relative_to(ROOT)
        if any(part in ("__pycache__","topology-check") or part.startswith("commercial_") for part in relative.parts): continue
        if p.suffix in (".pyc",".vvp",".exe",".db",".ddc") or p.name == "progress.json": continue
        if p.name.startswith("commercial-"): continue
        selected.append(p)
    out = ROOT/"dist"; out.mkdir(exist_ok=True)
    archive = out/"sv2rt-rtl-mapping-v1.zip"
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in selected: z.write(p,p.relative_to(ROOT).as_posix())
    (out/(archive.name+".sha256")).write_text(sha(archive)+"  "+archive.name+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"archive":str(archive),"files":len(selected),"bytes":archive.stat().st_size,"sha256":sha(archive)},indent=2))

if __name__ == "__main__": main()
