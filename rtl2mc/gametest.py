"""Check exported example circuits with the unmodified Java 1.21.1 GameTest server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

from .common import CACHE, ROOT, dump, read, sha, write
from .toolchain import discover
from .world import accepted_eula, server_jar

MAPPINGS_SHA1 = "03f8985492bda0afc0898465341eb0acef35f570"


def reference(top, inputs, q):
    """Independent integer functions; never evaluate the mapped graph/netlist."""
    if top == "adder":
        total = inputs["a"] + inputs["b"] + inputs["cin"]
        return {"sum": total % 2, "cout": total // 2}
    if top == "mux2":
        return {"y": inputs["b"] if inputs["select_b"] else inputs["a"]}
    if top in ("counter", "shift2") and q is not None:
        return {"q": q}
    raise ValueError("Reference model requires a supported example and initialized state: " + top)


def oracle(top, vectors):
    if top not in ("adder", "mux2", "counter", "shift2"):
        raise ValueError("No independent reference model for example: " + top)
    state = dict(vectors["initial"])
    q, rising_count = None, 0
    events = {e["tick"]: e["inputs"] for e in vectors["events"]}
    checks = set(vectors["checks"])
    low_checks = set()
    # Also check retention at the end of each low phase, after two boot edges.
    if top in ("counter", "shift2"):
        clk, edges = state["clk"], 0
        for event in vectors["events"]:
            new = event["inputs"].get("clk", clk)
            if new and not clk:
                if edges >= 2:
                    low_checks.add(event["tick"] - 1)
                edges += 1
            clk = new
    rows = []
    reached = set()
    for tick in sorted(set(events) | checks | low_checks):
        previous_clock = state.get("clk", 0)
        state.update(events.get(tick, {}))
        if state.get("clk", 0) and not previous_clock:
            rising_count += 1
            if state["reset"]:
                q = 0
            elif state["enable"]:
                if q is None:
                    raise ValueError("Reference state used before synchronous reset")
                q = ((q + 1) if top == "counter" else ((q << 1) | state["serial_in"])) & 3
        if tick in checks | low_checks:
            outputs = reference(top, state, q)
            reached.add(q if q is not None else tuple(sorted(state.items())))
            rows.append({"tick": tick, "phase": "low_hold" if tick in low_checks else "settled",
                         "outputs": outputs})
    return rows, {"reference": "independent Python integer model", "distinct_states_or_inputs": len(reached),
                  "clock_rising_edges": rising_count, "low_hold_checks": len(low_checks),
                  "settled_checks": len(checks)}


def runtime(java):
    """Extract only entries whose hashes match the official server bundle."""
    folder = CACHE / "gametest/runtime"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    with zipfile.ZipFile(server_jar()) as bundle:
        for listing, prefix in (("versions.list", "versions"), ("libraries.list", "libraries")):
            for line in bundle.read("META-INF/" + listing).decode().splitlines():
                digest, _, name = line.split("\t")
                target = folder / prefix / name
                if not target.resolve().is_relative_to(folder.resolve()):
                    raise ValueError("Unsafe server bundle path")
                if not target.exists() or sha(target) != digest:
                    data = bundle.read("META-INF/" + prefix + "/" + name)
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError("Server bundle member hash mismatch")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                paths.append(target)
    compiler = ROOT / ".local/instrumentation/dependencies/ecj-3.39.0.jar"
    pin = read(ROOT / "instrumentation/dependencies.json")[compiler.name]
    if not compiler.is_file() or sha(compiler) != pin["sha256"]:
        raise ValueError("Pinned ECJ compiler missing or changed; run python tools/setup_gametest.py --install")
    mapping_path = ROOT / ".local/investigation/server-mappings.txt"
    if not mapping_path.is_file() or hashlib.sha1(mapping_path.read_bytes()).hexdigest() != MAPPINGS_SHA1:
        raise ValueError("Mojang mappings missing or changed; run python tools/setup_gametest.py --install")
    build = CACHE / "gametest/harness"
    build.mkdir(parents=True, exist_ok=True)
    sources = sorted((ROOT / "gametest").glob("*.java"))
    classpath = os.pathsep.join(map(str, paths))
    command = [java, "-jar", str(compiler), "-21", "-proc:none", "-encoding", "UTF-8",
               "-classpath", classpath, "-d", str(build), *map(str, sources)]
    p = subprocess.run(command, capture_output=True, text=True, timeout=120)
    write(build / "compile.log", p.stdout + p.stderr)
    if p.returncode:
        raise ValueError("GameTest harness compilation failed: " + str(build / "compile.log"))
    return os.pathsep.join([str(build), classpath]), {
        "minecraft_version": "1.21.1", "server_sha1": hashlib.sha1(server_jar().read_bytes()).hexdigest(),
        "mappings_sha1": MAPPINGS_SHA1, "compiler_sha256": sha(compiler),
        "runner_sha256": sha(Path(__file__)),
        "source_sha256": {p.name: sha(p) for p in sources},
        "class_sha256": {p.name: sha(p) for p in (build / "rtl2mc/gametest").glob("*.class")},
        "runtime_sha256": {str(p.relative_to(folder)): sha(p) for p in paths},
        "engine_modifications": "No class changes or mods; native GameTestServer, TestFunction and GameTestHelper",
        "gametest_development_flag": "SharedConstants.IS_RUNNING_IN_IDE=true enables the native GameTestTicker",
    }


def prepare(output, destination, negative=False):
    output, destination = Path(output).resolve(), Path(destination).resolve()
    run = read(output / "run.json")
    if not run["pass"] or run["minecraft_version"] != "1.21.1":
        raise ValueError("GameTest requires a completed 1.21.1 world export")
    if destination.exists():
        raise ValueError("GameTest output must be new: " + str(destination))
    build = output / "build"
    layout, vectors, budget, golden = [read(build / n) for n in ("layout.json", "vectors.json", "timing.json", "golden.json")]
    top = run["top"]
    checks, coverage = oracle(top, vectors)
    for row in checks:
        if row["phase"] == "settled":
            for port, value in row["outputs"].items():
                if golden[str(row["tick"])]["out_" + port] != value:
                    raise ValueError(f"Independent reference disagrees with source RTL: {top} tick={row['tick']} {port}")
    manifest = read(output / "world-manifest.json")
    for name, digest in manifest["files_sha256"].items():
        if sha(output / "world" / name) != digest:
            raise ValueError("Exported world changed since packaging: " + name)
    destination.mkdir(parents=True)
    shutil.copytree(output / "world", destination / "world", ignore=shutil.ignore_patterns("session.lock"))
    # A tiny native template anchors GameTest far from the exported circuit.
    # The circuit is read from copied region files and is never reconstructed.
    from .nbt import encode
    import gzip
    template = {b"DataVersion": (3, 3955), b"size": (9, (3, [1, 1, 1])),
                b"palette": (9, (10, [{b"Name": (8, b"minecraft:air")}])),
                b"blocks": (9, (10, [])), b"entities": (9, (10, []))}
    structure = destination / "world/generated/rtl2mc/structures/empty.nbt"
    structure.parent.mkdir(parents=True)
    structure.write_bytes(gzip.compress(b"\x0a" + encode(8, b"") + encode(10, template), mtime=0))
    drivers = {tuple(s["position"]) for s in layout["sources"] if "port" in s}
    blocks = []
    for block in layout["blocks"]:
        if tuple(block["position"]) in drivers:
            continue
        name, _, props = block["state"].partition("[")
        properties = dict(p.split("=") for p in props.rstrip("]").split(",") if p)
        blocks.append({"position": block["position"], "id": "minecraft:" + name,
                       "properties": {k: v for k, v in properties.items() if k in ("facing", "delay", "mode")}})
    low, high = layout["bounds"]
    chunks = [(x, z) for x in range(low[0] // 16, high[0] // 16 + 1)
              for z in range(low[2] // 16, high[2] // 16 + 1)]
    expected_samples = len(checks) + 1
    case = {"top": top, "name": "rtl2mc." + top + (".broken_output" if negative else ".exported_world"),
            "negative_control": negative, "settle": budget["settle"], "initial": vectors["initial"],
            "events": vectors["events"], "checks": checks, "saved_outputs": checks[-1]["outputs"],
            "last_tick": checks[-1]["tick"], "timeout_ticks": checks[-1]["tick"] + 2 * budget["settle"] + 5000,
            "expected_samples": expected_samples, "expected_output_bits": expected_samples * len(layout["outputs"]),
            "blocks": blocks, "sources": [s for s in layout["sources"] if "port" in s],
            "outputs": layout["outputs"], "chunks": chunks, "coverage": coverage}
    dump(destination / "case.json", case)
    dump(destination / "export-manifest.json", manifest)
    write(destination / "eula.txt", "eula=true\n")
    return case


def audit_samples(case, samples):
    """Recheck every recorded game reading against the independent oracle."""
    expected = [{"tick": -1, "phase": "saved_world", "outputs": case["saved_outputs"]}, *case["checks"]]
    if len(samples) != len(expected):
        raise ValueError("Incomplete recorded GameTest observations")
    names = {o["name"] for o in case["outputs"]}
    prior_game_tick = -1
    for actual, want in zip(samples, expected):
        if (actual["tick"], actual["phase"]) != (want["tick"], want["phase"]) or set(actual["outputs"]) != names:
            raise ValueError("Missing, duplicate or reordered GameTest observation")
        if actual["gametest_tick"] <= prior_game_tick:
            raise ValueError("GameTest observation clock did not advance")
        prior_game_tick = actual["gametest_tick"]
        for output in case["outputs"]:
            reading = actual["outputs"][output["name"]]
            value = (want["outputs"][output["port"]] >> output["bit_index"]) & 1
            power = reading["power"]
            if type(power) is not int or not 0 <= power <= 15 or reading["expected"] != value or int(power > 0) != value:
                raise ValueError("Recorded GameTest output differs from independent reference")


def check(output, destination, java, classpath, pins, negative=False, timeout=1800):
    case = prepare(output, destination, negative)
    destination = Path(destination).resolve()
    report = {"pass": False, "status": "running", "test": case["name"], "runtime": pins,
              "case_sha256": sha(destination / "case.json"), "coverage": case["coverage"],
              "export": str(Path(output).resolve()), "negative_control": negative}
    dump(destination / "report.json", report)
    command = [java, "-Xms512M", "-Xmx2048M", "-Djava.awt.headless=true", "-cp", classpath,
               "rtl2mc.gametest.VanillaGameTests", "case.json"]
    dump(destination / "command.json", command)
    start = time.monotonic()
    try:
        with (destination / "server.log").open("w") as log:
            p = subprocess.run(command, cwd=destination, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        text = (destination / "server.log").read_text()
        if not (destination / "gametest.xml").is_file():
            raise ValueError(f"GameTest produced no XML report (exit {p.returncode}); inspect server.log")
        xml = ET.parse(destination / "gametest.xml")
        tests = xml.findall(".//testcase")
        failures = xml.findall(".//failure")
        if len(tests) != 1 or tests[0].get("name") != case["name"]:
            raise ValueError("GameTest did not report exactly the requested test")
        if negative:
            if p.returncode != 1 or len(failures) != 1 or "RMAP_GAMETEST_OUTPUT_BLOCK" not in failures[0].get("message", ""):
                raise ValueError("Broken-output control did not fail through the expected native GameTest assertion")
            if "RMAP_GAMETEST_PASS" in text:
                raise ValueError("Negative GameTest emitted a contradictory pass marker")
            samples = []
        else:
            if p.returncode or failures or xml.findall(".//skipped") or "All 1 required tests passed" not in text:
                raise ValueError("Native GameTest failure; inspect gametest.xml and server.log")
            marker = f"RMAP_GAMETEST_PASS {case['top']} samples={case['expected_samples']} output_bits={case['expected_output_bits']}"
            if marker not in text:
                raise ValueError("GameTest completed without the required comparison marker")
            samples = [json.loads(line) for line in (destination / "observations.jsonl").read_text().splitlines()]
            audit_samples(case, samples)
        report.update({"pass": True, "status": "expected_failure" if negative else "passed",
                       "exit_code": p.returncode, "gametest_tests": len(tests), "gametest_failures": len(failures),
                       "samples": len(samples), "output_bit_comparisons": 0 if negative else case["expected_output_bits"],
                       "layout_blocks_checked": len(case["blocks"]), "seconds": round(time.monotonic() - start, 3),
                       "evidence_sha256": {n: sha(destination / n) for n in ("gametest.xml", "server.log", "observations.jsonl")}})
    except Exception as exc:
        report.update(status="failed", error=str(exc), seconds=round(time.monotonic() - start, 3))
        dump(destination / "report.json", report)
        raise
    dump(destination / "report.json", report)
    print("GAMETEST " + report["status"] + ": " + str(destination), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", nargs="+", type=Path, help="completed RTL2MC output directories")
    parser.add_argument("--out", type=Path, required=True, help="new evidence directory")
    parser.add_argument("--negative-control", action="store_true", help="also remove one output in a separate copy of the first export")
    args = parser.parse_args(argv)
    if not accepted_eula():
        raise PermissionError("Existing Minecraft EULA acceptance required")
    if args.out.exists():
        raise ValueError("Evidence output must be new")
    found, _ = discover()
    if not found["java"]["available"]:
        raise ValueError("Java 21 or newer required")
    java = found["java"]["argv"][0]
    classpath, pins = runtime(java)
    reports = []
    for output in args.exports:
        top = read(output / "run.json")["top"]
        reports.append(check(output, args.out / top, java, classpath, pins))
    if args.negative_control:
        reports.append(check(args.exports[0], args.out / "negative-control", java, classpath, pins, negative=True))
    dump(args.out / "report.json", {"pass": True, "results": reports,
         "limitations": ["Four declared example reference models only", "Settled outputs and captured/held state; no transient-equivalence claim",
                         "Finite sequences, not exhaustive physical state-space proof", "GameTest opens isolated copies of exported region files"]})
