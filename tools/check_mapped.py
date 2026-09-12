"""Check a mapped build in source RTL and three local GLS modes."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.mapping_validation import prepare

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("build")
    p.add_argument("--vectors")
    args = p.parse_args()
    prepare(args.build,json.loads(Path(args.vectors).read_text()) if args.vectors else None)
    print("Mapped RTL/GLS checks passed: "+args.build)
