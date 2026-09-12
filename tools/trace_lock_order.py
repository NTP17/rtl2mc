"""Prepare, start, measure, and stop the isolated instrumented Minecraft lab."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from redstone_pdk import engine_trace, lab


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "start", "run", "stop"))
    parser.add_argument("--minimal", action="store_true", help="Measure only the two setting-2 north/rising examples")
    args = parser.parse_args()
    if args.command == "prepare":
        engine_trace.prepare()
    elif args.command == "start":
        engine_trace.start()
    elif args.command == "run":
        engine_trace.run(args.minimal)
    else:
        engine_trace.configure()
        lab.stop()


if __name__ == "__main__":
    main()
