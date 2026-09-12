#!/usr/bin/env python3
"""Audit a completed tool matrix and optionally retain a compact evidence copy."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rtl2mc.common import dump, read, sha
from rtl2mc.gametest import audit_samples
from rtl2mc.verification import annotation_report, diagnostic_text, DIAGNOSTICS
from run_tool_matrix import DESIGNS, SIMS, SYNTHS, reusable


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hashes(folder, manifest):
    for name, expected in manifest.items():
        require(sha(folder / name) == expected, "Evidence changed: " + str(folder / name))


def audit(root):
    report = read(root / "report.json")
    # The original archived 36-run report predates explicit matrix axes.
    axes = report.get("matrix") or {"synthesis": list(SYNTHS), "simulation": ["vcs", "icarus", "xcelium"], "designs": list(DESIGNS)}
    for key, allowed in (("synthesis", SYNTHS), ("simulation", SIMS), ("designs", DESIGNS)):
        values = axes[key]
        require(values and len(values) == len(set(values)) and set(values) <= set(allowed), "Invalid matrix axis: " + key)
    expected = {(s, m, d) for s in axes["synthesis"] for m in axes["simulation"] for d in axes["designs"]}
    results = report["results"]
    require(report["pass"] and report["passed_runs"] == report["expected_runs"] == len(expected), "Matrix is incomplete")
    require(len(results) == len(expected) and {(r["synthesis"], r["simulation"], r["top"]) for r in results} == expected,
            "Missing or duplicate tool/design combination")
    annotations, warnings = {}, set()
    for result in results:
        label = f"{result['synthesis']}+{result['simulation']}/{result['top']}"
        require(reusable(result), "Stale implementation or invalid archive: " + label)
        export, game = ROOT / result["export"], ROOT / result["gametest"]
        flow, native = read(export / "run.json"), read(game / "report.json")
        require(flow["pass"] and (flow["synthesis"], flow["simulation"]) ==
                (result["synthesis"], result["simulation"]), "Wrong flow backend: " + label)
        require(native["pass"] and native["exit_code"] == native["gametest_failures"] == 0 and
                native["gametest_tests"] == 1, "Native GameTest failed: " + label)
        hashes(game, native["evidence_sha256"])
        case = read(game / "case.json")
        require(sha(game / "case.json") == native["case_sha256"], "GameTest case changed: " + label)
        xml = ET.parse(game / "gametest.xml")
        tests = xml.findall(".//testcase")
        require(len(tests) == 1 and tests[0].get("name") == case["name"] and
                not xml.findall(".//failure") and not xml.findall(".//skipped"), "Invalid native XML: " + label)
        samples = [json.loads(line) for line in (game / "observations.jsonl").read_text().splitlines()]
        audit_samples(case, samples)
        physical = read(export / "verification/minecraft.json")
        require(physical["pass"] and physical["reopen_pass"], "Physical/reopen failure: " + label)
        hashes(export / "verification", physical["evidence_sha256"])
        hashes(export / "world", read(export / "world-manifest.json")["files_sha256"])
        build = export / "build"
        for key, name in (("layout", "layout.json"), ("vectors", "vectors.json"), ("golden", "golden.json")):
            require(sha(build / name) == result[key + "_sha256"], "Changed " + key + ": " + label)
        eda = read(build / "eda-report.json")
        require(eda["pass"] and eda["backend"] == result["simulation"], "Wrong simulator evidence: " + label)
        for control in eda["controls"]:
            if "log_sha256" in control:
                require(sha(build / f"{result['simulation']}-{control['name']}.log") == control["log_sha256"],
                        "Control log changed: " + label)
        for mode in ("golden", "sdf", "portable", "arcs"):
            log = (build / f"{result['simulation']}-{mode}.log").read_text()
            log = diagnostic_text(log, result["simulation"] + "-" + mode)
            require(not re.search(DIAGNOSTICS, log) and not re.search(r"timing violation", log, re.I),
                    "Unexpected positive simulation diagnostic: " + label + "/" + mode)
            warnings.update(line.strip() for line in log.splitlines() if re.search(r"Warning|WARNING|\*W,", line))
        if result["simulation"] in ("xcelium", "questa"):
            counts = {}
            for mode, sdf, key in (("sdf", "mapped.sdf", "routed"), ("arcs", "arc.sdf", "arcs"),
                                   ("width", "arc.sdf", "width")):
                counts[key] = annotation_report(result["simulation"], build, result["simulation"] + "-" + mode, sdf)
            require(counts == eda["sdf_annotation"], "Annotation report differs: " + label)
            annotations[label] = counts
        if result["simulation"] == "questa":
            require(not re.search(DIAGNOSTICS, diagnostic_text((build / "questa-width.log").read_text(), "questa-width")),
                    "Unexpected error in native width control: " + label)
    consistency = []
    for synth in axes["synthesis"]:
        for top in axes["designs"]:
            group = [r for r in results if r["synthesis"] == synth and r["top"] == top]
            for key in ("layout_sha256", "vectors_sha256", "golden_sha256"):
                require(len({r[key] for r in group}) == 1, f"Cross-simulator difference: {synth}/{top}/{key}")
            consistency.append(f"{synth}/{top}")
    negative = ROOT / report["negative_control"]["evidence"]
    control = read(negative / "report.json")
    hashes(negative, control["evidence_sha256"])
    failures = ET.parse(negative / "gametest.xml").findall(".//failure")
    require(control["pass"] and control["exit_code"] == 1 and len(failures) == 1 and
            "RMAP_GAMETEST_OUTPUT_BLOCK" in failures[0].get("message", "") and
            "RMAP_GAMETEST_PASS" not in (negative / "server.log").read_text(), "Broken-output control invalid")
    return report, {"pass": True, "runs_audited": len(results), "current_implementation": True,
                    "runner_sources_sha256": {"tools/" + name: sha(ROOT / "tools" / name) for name in
                                              ("run_tool_matrix.py", "test_tool_matrix.sh", "check_tool_matrix.py")},
                    "matching_layout_vectors_and_source_results": consistency, "sdf_annotation": annotations,
                    "remaining_positive_simulator_warnings": sorted(warnings),
                    "negative_control": "Native assertion detected removed output wire, exit 1",
                    "checks": "Implementation and evidence hashes, ZIP CRC, native XML, every GameTest observation, positive simulator diagnostics and SDF annotation counts"}


def snapshot(destination, root, report, checks):
    require(not destination.exists(), "Snapshot destination must be new")
    destination.mkdir(parents=True)
    dump(destination / "report.json", report)
    dump(destination / "audit.json", checks)
    rows = ["# Cross-tool Minecraft results", "", f"All {len(report['results'])} exports passed. Paths in JSON reports are relative to the workspace root unless absolute.",
            "Full synthesis, simulation and world evidence remains under the linked export folders.", "",
            "| Synthesis | Simulator | Design | Exported world ZIP | Native GameTest |",
            "| --- | --- | --- | --- | --- |"]
    def copy(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for result in report["results"]:
        pair, top = result["synthesis"] + "-" + result["simulation"], result["top"]
        target = destination / pair / top
        target.mkdir(parents=True)
        export, game = ROOT / result["export"], ROOT / result["gametest"]
        dump(target / "result.json", result)
        for name in ("run.json", "implementation-manifest.json", "world-manifest.json", "project.json"):
            copy(export / name, target / name)
        for name in ("report.json", "gametest.xml", "observations.jsonl", "server.log"):
            copy(game / name, target / "gametest" / name)
        for name in ("minecraft.json", "observations.jsonl"):
            copy(export / "verification" / name, target / "verification" / name)
        build = export / "build"
        names = ["eda-report.json", "graph.json", "vectors.json", "golden.json", "timing.json", "equivalence.log", "logical.v"]
        names += [f"{result['simulation']}-{mode}.log" for mode in ("golden", "sdf", "portable", "arcs", "missing-sdf", "width")]
        names += ["dc-synthesis.log", "genus-synthesis.log", "synthesis.log", "vendor-netlist.v", "references.rpt"]
        names += [f"questa-{mode}-sdf.rpt" for mode in ("sdf", "arcs", "width", "missing-sdf")]
        for name in names:
            if (build / name).is_file():
                copy(build / name, target / "build" / name)
        archive = Path(os.path.relpath(ROOT / result["archive"], destination)).as_posix()
        rows.append(f"| {result['synthesis']} | {result['simulation']} | {top} | [ZIP]({archive}) | [Passed]({pair}/{top}/gametest/gametest.xml) |")
    negative = ROOT / report["negative_control"]["evidence"]
    for name in ("report.json", "gametest.xml", "observations.jsonl", "server.log"):
        copy(negative / name, destination / "negative-control" / name)
    for name in ("python-tests.log", "matrix-final.log"):
        if (root / name).is_file():
            copy(root / name, destination / name)
    (destination / "README.md").write_text("\n".join(rows) + "\n")
    dump(destination / "files-sha256.json", {p.relative_to(destination).as_posix(): sha(p)
         for p in sorted(destination.rglob("*")) if p.is_file()})


def compare_baseline(report, path):
    """Compare new results to an intact, previously audited evidence snapshot."""
    baseline = read(path)
    previous_audit = read(path.parent / "audit.json")
    require(baseline["pass"] and previous_audit["pass"], "Baseline did not pass")
    hashes(path.parent, read(path.parent / "files-sha256.json"))
    matches = []
    for result in report["results"]:
        prior = [r for r in baseline["results"] if r["synthesis"] == result["synthesis"] and r["top"] == result["top"]]
        require(prior, "No corresponding baseline design")
        for old in prior:
            require(old["pass"], "Corresponding baseline design did not pass")
            for key, name in (("layout", "layout.json"), ("vectors", "vectors.json"), ("golden", "golden.json")):
                digest = sha(ROOT / old["export"] / "build" / name)
                require(digest == old[key + "_sha256"] == result[key + "_sha256"], "Difference from baseline: " + key)
            for name in ("project.json",):
                require(read(ROOT / old["export"] / name) == read(ROOT / result["export"] / name), "Changed test configuration")
            before = read(ROOT / old["export"] / "build/inputs.json")
            after = read(ROOT / result["export"] / "build/inputs.json")
            require(before == after, "Changed source inputs")
            matches.append({"synthesis": result["synthesis"], "design": result["top"],
                            "new_simulator": result["simulation"], "previous_simulator": old["simulation"]})
    return {"pass": True, "baseline_report": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "baseline_report_sha256": sha(path), "matches": matches,
            "scope": "Same source inputs, test configuration, layout, vectors and golden simulation results; previous simulator runs were not repeated"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--compare", type=Path, help="compare with a previously audited snapshot's report.json")
    args = parser.parse_args()
    report, checks = audit(args.root.resolve())
    if args.compare:
        checks["previous_matrix"] = compare_baseline(report, args.compare.resolve())
    dump(args.root / "audit.json", checks)
    if args.snapshot:
        snapshot(args.snapshot.resolve(), args.root.resolve(), report, checks)
    print(f"TOOL_MATRIX_AUDIT_PASS runs={len(report['results'])}")


if __name__ == "__main__":
    main()
