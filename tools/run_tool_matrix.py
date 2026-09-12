#!/usr/bin/env python3
"""Run every selected synthesis/simulator pair through export and native GameTest."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rtl2mc.common import dump, read, sha
from rtl2mc.gametest import check as gametest, runtime as gametest_runtime
from rtl2mc.toolchain import discover, select

SYNTHS = ("dc", "yosys", "genus")
SIMS = ("vcs", "icarus", "xcelium", "questa")
DESIGNS = ("adder", "mux2", "counter", "shift2")


def relative(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def archive_check(export):
    run, manifest = read(export / "run.json"), read(export / "world-manifest.json")
    archive = export / run["archive"]
    if sha(archive) != manifest["zip_sha256"]:
        raise ValueError("World ZIP hash differs from the manifest")
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("Corrupt exported ZIP")
    return relative(archive)


def reusable(result):
    if not result.get("pass"):
        return False
    export = ROOT / result["export"]
    try:
        pins = read(export / "implementation-manifest.json")
        if any(sha(ROOT / path) != digest for path, digest in pins.items()):
            return False
        inputs = read(export / "build/inputs.json")
        for row in inputs["snapshots"]:
            if sha(Path(row["original"])) != row["sha256"] or sha(export / "build" / row["file"]) != row["sha256"]:
                return False
        if any(sha(Path(row["path"])) != row["sha256"] for row in inputs["filelists"]):
            return False
        from rtl2mc.cli import config_for
        if config_for(ROOT / "examples/rtl" / (result["top"] + ".f")) != read(export / "project.json"):
            return False
        game = read(ROOT / result["gametest"] / "report.json")
        if any(sha(ROOT / "gametest" / path) != digest for path, digest in game["runtime"]["source_sha256"].items()):
            return False
        archive_check(export)
        return True
    except (OSError, KeyError, ValueError):
        return False


def execute_job(root, synth, sim, top, env, java, classpath, pins):
    job = root / (synth + "-" + sim) / top
    job.mkdir(parents=True, exist_ok=True)
    index = 1
    while (job / f"attempt-{index}").exists():
        index += 1
    attempt = job / f"attempt-{index}"
    attempt.mkdir()
    export = attempt / "export"
    game = attempt / "gametest"
    result = {"synthesis": synth, "simulation": sim, "top": top, "pass": False,
              "status": "running", "attempt": index, "export": relative(export), "gametest": relative(game)}
    dump(job / "result.json", result)
    command = [sys.executable, str(ROOT / "rtl2mc.py"), "run", "-f", str(ROOT / "examples/rtl" / (top + ".f")),
               "--synth", synth, "--sim", sim, "--minecraft-version", "1.21.1", "--out", str(export)]
    dump(attempt / "command.json", command)
    start = time.monotonic()
    print(f"START {synth}+{sim} {top} attempt={index}", flush=True)
    try:
        with (attempt / "flow.log").open("w") as log:
            process = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        if process.returncode:
            flow = read(export / "run.json") if (export / "run.json").exists() else {}
            result["failed_stage"] = flow.get("active_stage", "tool preflight")
            raise ValueError(flow.get("error", "RTL2MC failed; inspect flow.log"))
        flow = read(export / "run.json")
        if not flow["pass"] or (flow["synthesis"], flow["simulation"]) != (synth, sim):
            raise ValueError("Requested synthesis/simulator pair was not qualified")
        result["failed_stage"] = "native GameTest"
        native = gametest(export, game, java, classpath, pins)
        result["failed_stage"] = "archive verification"
        archive = archive_check(export)
        eda = read(export / "build/eda-report.json")
        result.update({"pass": True, "status": "passed", "archive": archive,
                       "logic_cells": flow["logic_cells"], "route_repeaters": flow["route_repeaters"],
                       "blocks": flow["blocks"], "physical_comparisons": flow["physical_comparisons"],
                       "reopen_comparisons": flow["reopen_comparisons"], "gametest_samples": native["samples"],
                       "gametest_output_bit_comparisons": native["output_bit_comparisons"],
                       "sdf_timing_checks": eda["sdf_timing_checks"], "sdf_annotation": eda["sdf_annotation"],
                       "layout_sha256": sha(export / "build/layout.json"),
                       "vectors_sha256": sha(export / "build/vectors.json"),
                       "golden_sha256": sha(export / "build/golden.json"),
                       "controls": eda["controls"]})
        result.pop("failed_stage", None)
    except Exception as exc:
        result.update(status="failed", error=str(exc))
    result["seconds"] = round(time.monotonic() - start, 3)
    dump(attempt / "result.json", result)
    dump(job / "result.json", result)
    print(f"{result['status'].upper()} {synth}+{sim} {top} {result['seconds']}s" +
          (" " + result["error"] if "error" in result else ""), flush=True)
    return result


def summary(root, expected, results, tools, negative=None, matrix=None):
    results = sorted(results, key=lambda r: (SYNTHS.index(r["synthesis"]), SIMS.index(r["simulation"]), DESIGNS.index(r["top"])))
    positive = [r for r in results if r["pass"]]
    report = {"schema_version": 1, "pass": len(positive) == expected and bool(negative and negative["pass"]),
              "status": "running" if len(results) < expected else "passed" if len(positive) == expected and negative and negative["pass"] else "incomplete_or_failed",
              "updated_utc": datetime.now(timezone.utc).isoformat(), "expected_runs": expected,
              "completed_runs": len(results), "passed_runs": len(positive), "results": results, "tools": tools,
              "negative_control": negative, "matrix": matrix,
              "totals": {key: sum(r[key] for r in positive) for key in
                         ("physical_comparisons", "reopen_comparisons", "gametest_samples", "gametest_output_bit_comparisons", "blocks")},
              "scope": "Fresh synthesis, source/routed simulation, vanilla measurement, save/reopen, ZIP and native GameTest for each run",
              "limitations": ["Four example designs and their declared finite vectors", "Icarus uses procedural timing guards; native SDF TIMINGCHECK unsupported",
                              "Settled and captured/held behavior only; no universal physical or transient proof"]}
    groups = []
    for synth in SYNTHS:
        for top in DESIGNS:
            members = [r for r in positive if r["synthesis"] == synth and r["top"] == top]
            if members:
                groups.append({"synthesis": synth, "top": top, "simulators": [r["simulation"] for r in members],
                               "unique_layouts": len({r["layout_sha256"] for r in members}),
                               "unique_vectors": len({r["vectors_sha256"] for r in members}),
                               "unique_source_oracles": len({r["golden_sha256"] for r in members})})
    report["cross_simulator_consistency"] = groups
    dump(root / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--resume", action="store_true", help="reuse current passing evidence; repeat failed/stale jobs in new attempt directories")
    parser.add_argument("--synth", nargs="+", choices=SYNTHS, default=list(SYNTHS))
    parser.add_argument("--sim", nargs="+", choices=SIMS, default=list(SIMS))
    parser.add_argument("--designs", nargs="+", choices=DESIGNS, default=list(DESIGNS))
    args = parser.parse_args(argv)
    matrix = {"synthesis": args.synth, "simulation": args.sim, "designs": args.designs}
    if any(len(values) != len(set(values)) for values in matrix.values()):
        raise ValueError("Matrix axes cannot contain duplicates")
    if not 1 <= args.jobs <= 4:
        raise ValueError("Use between one and four isolated workers")
    root = args.out.resolve()
    if root.exists() and not args.resume:
        raise ValueError("Choose a new output directory or use --resume")
    root.mkdir(parents=True, exist_ok=True)
    found, env = discover()
    for synth in args.synth:
        for sim in args.sim:
            selected = select(found, synth, sim)
            if selected["missing"]:
                raise ValueError(f"{synth}+{sim}: " + ", ".join(selected["missing"]))
    dump(root / "toolchain.json", found)
    java = found["java"]["argv"][0]
    classpath, pins = gametest_runtime(java)
    pairs = [(s, m) for s in args.synth for m in args.sim]
    preferred = [("dc", "icarus"), ("yosys", "xcelium"), ("genus", "vcs")]
    pairs.sort(key=lambda pair: preferred.index(pair) if pair in preferred else len(preferred) + SYNTHS.index(pair[0]) * len(SIMS) + SIMS.index(pair[1]))
    jobs = [(s, m, top) for top in args.designs for s, m in pairs]
    results, pending = [], []
    for synth, sim, top in jobs:
        record = root / (synth + "-" + sim) / top / "result.json"
        previous = read(record) if args.resume and record.exists() else None
        if previous and reusable(previous):
            results.append(previous)
            print(f"REUSE {synth}+{sim} {top}", flush=True)
        else:
            pending.append((synth, sim, top))
    summary(root, len(jobs), results, found, matrix=matrix)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(execute_job, root, s, m, top, env, java, classpath, pins) for s, m, top in pending]
        for future in as_completed(futures):
            results.append(future.result())
            summary(root, len(jobs), results, found, matrix=matrix)
    negative = None
    passed = [r for r in results if r["pass"]]
    if passed:
        n = 1
        while (root / f"negative-control-{n}").exists():
            n += 1
        location = root / f"negative-control-{n}"
        native = gametest(ROOT / passed[0]["export"], location, java, classpath, pins, negative=True)
        negative = {"pass": native["pass"], "evidence": relative(location), "exit_code": native["exit_code"]}
    report = summary(root, len(jobs), results, found, negative, matrix)
    print(f"MATRIX {report['passed_runs']}/{len(jobs)} passed: {root / 'report.json'}", flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
