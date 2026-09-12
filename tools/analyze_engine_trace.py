"""Recheck observed engine events and vanilla comparisons from a saved run."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from redstone_pdk.trace_analysis import write_report

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("run", type=Path)
args = parser.parse_args()
write_report(args.run)
