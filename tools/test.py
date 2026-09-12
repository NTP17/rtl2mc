#!/usr/bin/env python3
"""Run self-contained tests, optionally including archived PDK evidence audits."""
import argparse
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-evidence", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or newer is required")
    if args.with_evidence and not (ROOT / "validation/mapping/release.json").is_file():
        parser.error("Restore the optional lab evidence bundle first; see docs/testing.md")
    suite = unittest.TestLoader().discover(str(ROOT / "tests"))
    if args.with_evidence:
        suite.addTests(unittest.TestLoader().discover(str(ROOT / "tests/evidence")))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
