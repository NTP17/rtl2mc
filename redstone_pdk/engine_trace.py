"""Run the lock-order experiment in an explicitly instrumented, isolated lab."""
import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import lab
from .fixtures import compile_functions
from .project import ROOT, read_json, technology
from .repeater_broad_fixtures import lock_sequence_cases
from .results import analyze, parse_probe_response, write_summary

SERVER = ROOT / ".local/instrumented-server"
BUILD = ROOT / ".local/instrumentation"
BASELINE = ROOT / "results/20260910T151115Z-97846b"


def configure():
    # This module runs in its own CLI process. The ordinary pdk.py configuration
    # and its server files are unaffected by these bindings.
    lab.SERVER = SERVER
    lab.IDENTITY = SERVER / "pdk-lab.json"
    lab.FUNCTIONS = SERVER / "lab-world/datapacks/pdk_lab/data/pdk_lab/function"
    lab.GAME_PORT = 25567
    lab.RCON_PORT = 25587


def prepare():
    original = ROOT / ".local/server"
    if SERVER.exists():
        configure()
        lab.check_config()
        print("Existing isolated instrumented lab verified.")
        return
    if SERVER.resolve().parent != (ROOT / ".local").resolve():
        raise RuntimeError("Unexpected instrumented lab location")
    lab.check_config()
    try:
        with lab.connect() as client:
            lab.assert_identity(client)
            raise RuntimeError("Stop the vanilla lab before copying its saved world")
    except OSError:
        pass
    if not re.search(r"^eula=true\s*$", (original / "eula.txt").read_text(), re.M):
        raise RuntimeError("The existing lab has no recorded EULA acceptance")
    SERVER.mkdir()
    for name in ("server.jar", "eula.txt", "server.properties"):
        shutil.copy2(original / name, SERVER / name)
    for name in ("libraries", "versions", "lab-world"):
        shutil.copytree(original / name, SERVER / name)
    props = lab.properties()
    props.update({"server-port": "25567", "rcon.port": "25587", "rcon.password": secrets.token_urlsafe(32),
                  "motd": "Redstone PDK instrumented laboratory"})
    (SERVER / "server.properties").write_text("\n".join(f"{key}={value}" for key, value in props.items()) + "\n", encoding="utf-8")
    identity = {"schema_version": 1, "technology": technology()["id"], "marker": secrets.randbelow(1_000_000_000) + 1}
    (SERVER / "pdk-lab.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    (SERVER / "lab-copy.json").write_text(json.dumps({
        "source": ".local/server/lab-world", "source_level_dat_sha256": lab.file_hash(original / "lab-world/level.dat", "sha256"),
        "copied_at_utc": datetime.now(timezone.utc).isoformat(), "eula_acceptance": "preserved_from_authorized_local_lab",
    }, indent=2) + "\n", encoding="utf-8")
    configure()
    lab.check_config()
    print("Prepared isolated world on loopback ports 25567 and 25587.")


def trace_rows():
    process = read_json(SERVER / "trace-process.json")
    path = Path(process["event_log"])
    if not path.resolve().is_relative_to(SERVER.resolve()):
        raise RuntimeError("Unexpected engine trace path")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def audit():
    process = read_json(SERVER / "trace-process.json")
    build = read_json(BUILD / "build.json")
    if process["build_sha256"] != lab.file_hash(BUILD / "build.json", "sha256"):
        raise RuntimeError("Agent build changed after this server started")
    for name, digest in build["artifacts"].items():
        if lab.file_hash(BUILD / name, "sha256") != digest:
            raise RuntimeError("Agent artifact changed after build")
    rows = trace_rows()
    errors = [row for row in rows if row["event"] == "logger_error"]
    if errors:
        raise RuntimeError(f"Instrumentation failed: {errors[0]}")
    console = (SERVER / "console.log").read_bytes()[process.get("console_offset", 0):].decode("utf-8", errors="replace")
    if "PDK_TRACE_FATAL" in console:
        raise RuntimeError("Logger reported a fatal write/read error; inspect the local console log")
    transforms = {row["class"]: row for row in rows if row["event"] == "class_transform"}
    if set(transforms) != set(build["class_sha256"]):
        raise RuntimeError(f"Incomplete instrumentation: transformed classes {sorted(transforms)}")
    for name, row in transforms.items():
        if row["original_sha256"] != build["class_sha256"][name] or row["hooks"] != build["expected_hooks"][name]:
            raise RuntimeError(f"Unexpected transformation: {name}")
    return {"build": build, "transforms": transforms, "process": process}


def start():
    configure()
    lab.check_config()
    try:
        with lab.connect() as client:
            lab.assert_identity(client)
            audit()
            print("Verified instrumented lab already running.")
            return
    except OSError:
        pass
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    process = {"event_log": str(SERVER / f"events-{tag}.jsonl"), "audit_dir": str(SERVER / f"transformed-{tag}"),
               "build_sha256": lab.file_hash(BUILD / "build.json", "sha256"),
               "console_offset": (SERVER / "console.log").stat().st_size if (SERVER / "console.log").exists() else 0}
    (SERVER / "trace-process.json").write_text(json.dumps(process, indent=2) + "\n", encoding="utf-8")
    arguments = [f"-javaagent:{BUILD / 'pdk-trace-agent.jar'}", f"-Dpdk.trace.path={process['event_log']}",
                 f"-Dpdk.trace.audit={process['audit_dir']}"]
    lab.start(jvm_args=arguments)
    audit()
    print("All six instrumented classes passed their byte/hash and hook checks.")


def marker(client, text):
    if not re.fullmatch(r"[a-zA-Z0-9_|-]+", text):
        raise ValueError("Invalid trace marker")
    lab.checked(client, f'data modify storage pdk_lab:trace marker set value "{text}"')


def run(minimal=False):
    configure()
    instrumentation = audit()
    chosen = lock_sequence_cases()
    if minimal:
        chosen = [case for case in chosen if case["id"] in {
            "repeater_lockseq_d2_q0_north_repeater_release_at_due",
            "repeater_lockseq_d2_q0_north_comparator_release_at_due"}]
    reference = {f["id"]: f for f in read_json(BASELINE / "fixtures.json")}
    for case in chosen:
        if json.loads(json.dumps(case)) != reference[case["id"]]:
            raise RuntimeError(f"Fixture drift from vanilla reference: {case['id']}")
    now = datetime.now(timezone.utc)
    tag = now.strftime("%Y%m%dT%H%M%SZ") + "-trace-" + secrets.token_hex(3)
    destination = ROOT / "results" / tag
    destination.mkdir()
    metadata = {
        "technology": technology()["id"] + "-instrumented", "minecraft_version": "1.21.1",
        "server_sha1": technology()["server"]["sha1"], "suite": "lock_order_minimal" if minimal else "lock_order_96",
        "started_at_utc": now.isoformat(), "fixtures": [c["id"] for c in chosen],
        "java": read_json(SERVER / "process.json")["java"], "random_tick_speed": 0,
        "resolution": {"samples": "after_command_and_completed_game_tick", "engine_events": "observed_intra_tick_hooks"},
        "instrumentation": instrumentation, "vanilla_reference": BASELINE.relative_to(ROOT).as_posix(),
        "vanilla_observations_sha256": lab.file_hash(BASELINE / "observations.jsonl", "sha256"),
    }
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (destination / "fixtures.json").write_text(json.dumps(chosen, indent=2) + "\n", encoding="utf-8")
    (destination / "compiled-functions.json").write_text(json.dumps(compile_functions(), indent=2) + "\n", encoding="utf-8")
    source = destination / "instrumentation-source"
    source.mkdir()
    for path in (ROOT / "instrumentation/java/pdk/trace").glob("*.java"):
        shutil.copy2(path, source / path.name)
    for path in (ROOT / "tools/build_trace_agent.py", ROOT / "tools/investigate_lock_order.py", Path(__file__)):
        shutil.copy2(path, source / path.name)
    shutil.copy2(ROOT / "instrumentation/dependencies.json", source / "dependencies.json")
    shutil.copy2(ROOT / "instrumentation/THIRD_PARTY_NOTICES.txt", source / "THIRD_PARTY_NOTICES.txt")
    shutil.copy2(BUILD / "build.json", source / "build.json")
    for name in instrumentation["build"]["artifacts"]:
        shutil.copy2(BUILD / name, source / name)
    analyses = []
    error = None
    try:
        with (destination / "commands.jsonl").open("w", encoding="utf-8") as commands, (destination / "observations.jsonl").open("w", encoding="utf-8") as observations:
            def log(row):
                commands.write(json.dumps(row) + "\n")
                commands.flush()
            with lab.connect(log) as client:
                lab.assert_identity(client)
                lab.install_datapack()
                lab.checked(client, "reload")
                lab.prepare_measurement(client)
                for index, case in enumerate(chosen):
                    print(f"[{index + 1}/{len(chosen)}] Recording {case['id']}...", flush=True)
                    marker(client, "end")
                    lab.checked(client, f"function pdk_lab:{case['id']}/setup")
                    lab.step(client, 20)
                    for stage_index, stage in enumerate(case.get("prepare", [])):
                        lab.checked(client, f"function pdk_lab:{case['id']}/prepare_{stage_index}")
                        lab.step(client, stage["settle_game_ticks"])
                    origin = lab.game_time(client)
                    marker(client, f"begin|{tag}|{case['id']}|{origin}")
                    samples = []
                    def sample(tick, phase=None):
                        lab.checked(client, f"function pdk_lab:{case['id']}/sample")
                        values = parse_probe_response(client.command("data get storage pdk_lab:sample values"), [p["name"] for p in case["probes"]])
                        current = lab.game_time(client)
                        if current != origin + max(0, tick):
                            raise RuntimeError("Unexpected game tick advancement while sampling")
                        for probe in case["probes"]:
                            if values[probe["name"]] not in [int(v) for v in probe["values"]]:
                                raise RuntimeError(f"Probe out of domain: {probe['name']}")
                        row = {"case": case["id"], "relative_game_tick": tick, "game_time": current,
                               "sample_index": len(samples), "phase": phase or ("baseline_before_stimulus" if tick == -1 else "after_commands_or_completed_tick"), "values": values}
                        samples.append(row)
                        observations.write(json.dumps(row) + "\n")
                        observations.flush()
                    sample(-1)
                    for tick in range(case["ticks"] + 1):
                        if tick > 0:
                            lab.step(client)
                        if tick in case["actions"]:
                            if tick > 0:
                                sample(tick, "before_action")
                            lab.checked(client, f"function pdk_lab:{case['id']}/action_{tick}")
                        sample(tick)
                    marker(client, "end")
                    result = analyze(case, samples)
                    analyses.append(result)
                    print("  " + ("PASS" if result["pass"] else "FAIL"), flush=True)
                    (destination / "progress.json").write_text(json.dumps({"completed": len(analyses), "total": len(chosen)}, indent=2) + "\n")
                lab.checked(client, "save-all")
        audit()
    except (OSError, RuntimeError, ValueError, KeyboardInterrupt) as exception:
        error = str(exception) or "Interrupted"
    finally:
        rows = [row for row in trace_rows() if row.get("run") == tag]
        (destination / "engine-events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    summary = write_summary(destination, metadata, analyses, error)
    print(f"Instrumented evidence: {destination}", flush=True)
    if error:
        raise RuntimeError(error)
    if not summary["pass"]:
        raise RuntimeError("One or more declared fixture checks failed")
    return destination
