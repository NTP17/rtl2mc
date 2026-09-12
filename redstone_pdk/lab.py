"""Provision a project-local, loopback-only vanilla Minecraft laboratory."""
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import cases, compile_functions
from .project import ROOT, read_json, technology
from .rcon import Rcon, RconError
from .results import analyze, parse_probe_response, write_summary

LOCAL = ROOT / ".local"
SERVER = LOCAL / "server"
IDENTITY = SERVER / "pdk-lab.json"
FUNCTIONS = SERVER / "lab-world/datapacks/pdk_lab/data/pdk_lab/function"
GAME_PORT = 25566
RCON_PORT = 25586
FLAT_SETTINGS = json.dumps({"layers": [{"block": "minecraft:bedrock", "height": 1},
    {"block": "minecraft:dirt", "height": 2}, {"block": "minecraft:grass_block", "height": 1}],
    "biome": "minecraft:plains", "lakes": False, "features": False, "structure_overrides": []}, separators=(",", ":"))


def file_hash(path, algorithm):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, path, algorithm, expected, size):
    path = Path(path)
    if path.exists() and path.stat().st_size == size and file_hash(path, algorithm) == expected:
        print(f"Already verified: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    print(f"Downloading {path.name} ({size / 1_000_000:.1f} MB)...", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "RedstonePDK/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output)
    if partial.stat().st_size != size or file_hash(partial, algorithm) != expected:
        raise RuntimeError(f"Download verification failed: {partial.name}")
    partial.replace(path)


def extract_runtime(archive, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination):
                raise RuntimeError("Runtime archive contains an unsafe path")
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError("Unexpected symlink in Windows runtime archive")
        package.extractall(destination)


def java_executable():
    for candidate in sorted((LOCAL / "java").glob("*/bin/java.exe")):
        return str(candidate)
    return shutil.which("java")


def java_version(executable):
    check = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=15)
    output = check.stderr + check.stdout
    match = re.search(r'version "(\d+)', output)
    if check.returncode or not match or int(match[1]) < technology()["required_java_major"]:
        raise RuntimeError(f"Java 21 or newer is required. Found: {output.strip()}")
    return output.strip()


def install_datapack(compiled=None):
    pack = FUNCTIONS.parents[2]
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "pack.mcmeta").write_text(json.dumps({"pack": {"pack_format": technology()["data_pack_format"],
        "description": "Redstone PDK measurement fixtures; disposable lab world only"}}, indent=2) + "\n", encoding="utf-8")
    for name, commands in (compile_functions() if compiled is None else compiled).items():
        path = FUNCTIONS / (name + ".mcfunction")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(commands, encoding="utf-8")


def setup():
    tech = technology()
    SERVER.mkdir(parents=True, exist_ok=True)
    server = tech["server"]
    download(server["url"], SERVER / "server.jar", "sha1", server["sha1"], server["size"])
    if java_executable() is None:
        if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise RuntimeError("Install Java 21 or newer, then rerun setup. The bundled runtime targets Windows x64.")
        runtime = tech["windows_x64_runtime"]
        archive = LOCAL / "downloads/temurin21-jre.zip"
        download(runtime["url"], archive, "sha256", runtime["sha256"], runtime["size"])
        extract_runtime(archive, LOCAL / "java")
    print(java_version(java_executable()).splitlines()[0])
    if not IDENTITY.exists():
        if (SERVER / "server.properties").exists() or (SERVER / "lab-world/level.dat").exists():
            raise RuntimeError("Existing server state has no lab identity. Refusing to adopt an unknown world.")
        marker = secrets.randbelow(1_000_000_000) + 1
        IDENTITY.write_text(json.dumps({"schema_version": 1, "marker": marker, "technology": tech["id"]}, indent=2) + "\n", encoding="utf-8")
        password = secrets.token_urlsafe(32)
        props = {
            "server-ip": "127.0.0.1", "server-port": str(GAME_PORT), "enable-rcon": "true",
            "rcon.port": str(RCON_PORT), "rcon.password": password,
            "broadcast-rcon-to-ops": "false", "online-mode": "true",
            "level-name": "lab-world", "level-type": "minecraft:flat", "level-seed": "0",
            "generator-settings": FLAT_SETTINGS,
            "generate-structures": "false", "gamemode": "creative", "force-gamemode": "true",
            "difficulty": "peaceful", "spawn-protection": "0", "view-distance": "3", "simulation-distance": "3",
            "max-players": "1", "enable-command-block": "false", "motd": "Redstone PDK local laboratory"
        }
        (SERVER / "server.properties").write_text("\n".join(f"{key}={value}" for key, value in props.items()) + "\n", encoding="utf-8")
    config = check_config()
    if config.get("generator-settings", "") in ("", "{}"):
        props_file = SERVER / "server.properties"
        lines = [line for line in props_file.read_text(encoding="utf-8").splitlines()
                 if line.split("=", 1)[0].strip() != "generator-settings"]
        props_file.write_text("\n".join(lines + ["generator-settings=" + FLAT_SETTINGS]) + "\n", encoding="utf-8")
    if not (SERVER / "eula.txt").exists():
        (SERVER / "eula.txt").write_text("# Read https://aka.ms/MinecraftEULA before accepting.\neula=false\n", encoding="utf-8")
    install_datapack()
    print("Lab prepared.")
    if re.search(r"^eula=true\s*$", (SERVER / "eula.txt").read_text(), re.M):
        print("EULA acceptance already recorded. Start with: python pdk.py start")
    else:
        print("Setup has not accepted the Minecraft EULA.")
        print("After reading it, start with: python pdk.py start --accept-minecraft-eula")


def properties():
    path = SERVER / "server.properties"
    if not path.exists():
        raise RuntimeError("Run python pdk.py setup first.")
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().replace("\\:", ":")
    return result


def check_config():
    if not IDENTITY.exists():
        raise RuntimeError("No project-local lab identity. Run setup first.")
    config = properties()
    expected = {"server-ip": "127.0.0.1", "server-port": str(GAME_PORT), "rcon.port": str(RCON_PORT),
                "enable-rcon": "true", "online-mode": "true", "level-name": "lab-world"}
    for key, value in expected.items():
        if config.get(key) != value:
            raise RuntimeError(f"Lab setting {key} differs from the isolated lab configuration")
    if read_json(IDENTITY)["technology"] != technology()["id"]:
        raise RuntimeError("Lab technology differs from the project manifest")
    return config


def connect(log=None):
    config = check_config()
    return Rcon(int(config["rcon.port"]), config["rcon.password"], log=log)


def score(response):
    match = re.search(r"(-?\d+)\s+\[pdk_lab\]\s*$", response)
    if not match:
        raise RuntimeError(f"Expected a lab scoreboard value, received: {response}")
    return int(match[1])


def assert_identity(client):
    observed = score(client.command("scoreboard players get #identity pdk_lab"))
    if observed != read_json(IDENTITY)["marker"]:
        raise RuntimeError("The connected server is not this project's laboratory")


def checked(client, command):
    result = client.command(command)
    failures = ("Unknown or incomplete command", "Incorrect argument", "Unknown function", "Unknown scoreboard", "An unexpected error occurred")
    if any(message in result for message in failures):
        raise RuntimeError(f"Minecraft rejected {command!r}: {result}")
    return result


def start(accept_eula=False, *, jvm_args=()):
    check_config()
    eula = SERVER / "eula.txt"
    if accept_eula:
        eula.write_text("# Accepted by the user through --accept-minecraft-eula.\neula=true\n", encoding="utf-8")
    if not eula.exists() or not re.search(r"^eula=true\s*$", eula.read_text(), re.M):
        raise RuntimeError("Minecraft requires acceptance of https://aka.ms/MinecraftEULA. After reading it, use start --accept-minecraft-eula.")
    executable = java_executable()
    if not executable:
        raise RuntimeError("Java was not found. Run setup first.")
    version = java_version(executable)
    if file_hash(SERVER / "server.jar", "sha1") != technology()["server"]["sha1"]:
        raise RuntimeError("Server jar differs from the pinned official build")
    try:
        with connect() as client:
            assert_identity(client)
            print("This project's lab is already running.")
            return
    except OSError:
        pass
    install_datapack()
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with (SERVER / "console.log").open("ab") as log:
        process = subprocess.Popen([executable, "-Xms512M", "-Xmx1536M", *jvm_args, "-jar", "server.jar", "nogui"],
            cwd=SERVER, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options)
    (SERVER / "process.json").write_text(json.dumps({"pid": process.pid, "java": version, "jvm_args": list(jvm_args)}, indent=2) + "\n", encoding="utf-8")
    print("Starting the local Minecraft lab...", flush=True)
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Minecraft exited. Read .local/server/console.log.")
        try:
            with connect() as client:
                checked(client, "scoreboard objectives add pdk_lab dummy")
                checked(client, f"scoreboard players set #identity pdk_lab {read_json(IDENTITY)['marker']}")
                checked(client, "gamerule doDaylightCycle false")
                checked(client, "gamerule doWeatherCycle false")
                checked(client, "gamerule doMobSpawning false")
                checked(client, "gamerule randomTickSpeed 0")
                checked(client, "gamerule maxCommandChainLength 65536")
                checked(client, "forceload add 0 -16 31 15")
                checked(client, "tick freeze")
                print(f"Lab ready. Join with a Java 1.21.1 client at 127.0.0.1:{GAME_PORT} if desired.")
                return
        except (OSError, RconError):
            time.sleep(1)
    raise RuntimeError("Startup timed out; the process may still be running. Read .local/server/console.log.")


def game_time(client):
    checked(client, "execute store result score #time pdk_lab run time query gametime")
    return score(client.command("scoreboard players get #time pdk_lab"))


def step(client, count=1):
    before = game_time(client)
    checked(client, f"tick step {count}t")
    deadline = time.monotonic() + max(15, count)
    while time.monotonic() < deadline:
        current = game_time(client)
        if current == before + count:
            return current
        if current > before + count:
            raise RuntimeError("The world advanced beyond the requested step; this observation is invalid")
        time.sleep(0.01)
    raise RuntimeError("Minecraft did not complete the requested tick step")


def prepare_measurement(client, tick_rate=20):
    for name, value in (("doDaylightCycle", "false"), ("doWeatherCycle", "false"),
                        ("doMobSpawning", "false"), ("randomTickSpeed", "0"),
                        ("maxCommandChainLength", "65536")):
        checked(client, f"gamerule {name} {value}")
    checked(client, f"tick rate {tick_rate}")
    checked(client, "tick freeze")
    checked(client, "forceload add 0 -16 63 47")
    for _ in range(100):
        checked(client, "scoreboard players set #loaded pdk_lab 0")
        for x, z in ((x, z) for x in (0, 16, 32, 48) for z in (-16, 0, 16, 32)):
            checked(client, f"execute if loaded {x} 80 {z} run scoreboard players add #loaded pdk_lab 1")
        if score(client.command("scoreboard players get #loaded pdk_lab")) == 16:
            # Clear any previous extended fixture before a later legacy suite.
            # Existing per-fixture compiled functions remain byte-identical.
            checked(client, "fill 0 79 -16 63 84 47 minecraft:air")
            checked(client, "fill 0 79 -16 63 79 47 minecraft:stone")
            return
        step(client)
    raise RuntimeError("The fixture region did not finish loading")


def run(selected=None, suite="core", *, fixtures=None, tick_rate=20):
    if type(tick_rate) is not int or not 1 <= tick_rate <= 1000:
        raise ValueError("Measurement tick rate must be 1..1000")
    check_config()
    if file_hash(SERVER / "server.jar", "sha1") != technology()["server"]["sha1"]:
        raise RuntimeError("Server jar no longer matches the pinned build")
    chosen = [case for case in (cases("all" if selected else suite) if fixtures is None else fixtures) if selected is None or case["id"] == selected]
    if not chosen:
        raise RuntimeError(f"Unknown fixture {selected!r}")
    now = datetime.now(timezone.utc)
    run_dir = ROOT / "results" / (now.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3))
    run_dir.mkdir(parents=True)
    metadata = {"technology": technology()["id"], "minecraft_version": technology()["minecraft_version"],
                "server_sha1": technology()["server"]["sha1"], "suite": "selected_case" if selected else suite,
                "suite_sha256": hashlib.sha256(json.dumps(chosen, sort_keys=True).encode()).hexdigest(),
                "started_at_utc": now.isoformat(), "fixtures": [case["id"] for case in chosen],
                "resolution": {**technology()["measurement"], "before_action_samples": True}, "random_tick_speed": 0,
                "java": read_json(SERVER / "process.json").get("java") if (SERVER / "process.json").exists() else None}
    metadata["harness_sha256"] = {path.name: file_hash(path, "sha256") for path in sorted((ROOT / "redstone_pdk").glob("*.py"))}
    if fixtures is not None:
        metadata["requested_tick_rate"] = tick_rate
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (run_dir / "fixtures.json").write_text(json.dumps(chosen, indent=2) + "\n", encoding="utf-8")
    compiled = compile_functions() if fixtures is None else compile_functions(chosen)
    (run_dir / "compiled-functions.json").write_text(json.dumps(compiled, indent=2) + "\n", encoding="utf-8")
    source_dir = run_dir / "harness-source"
    source_dir.mkdir()
    for path in (ROOT / "redstone_pdk").glob("*.py"):
        shutil.copy2(path, source_dir / path.name)
    analyses = []
    error = None
    try:
        with (run_dir / "commands.jsonl").open("w", encoding="utf-8") as commands, (run_dir / "observations.jsonl").open("w", encoding="utf-8") as observations:
            def log(entry):
                commands.write(json.dumps(entry) + "\n")
                commands.flush()
            with connect(log) as client:
                assert_identity(client)
                install_datapack(compiled)
                checked(client, "reload")
                prepare_measurement(client, tick_rate)
                for case in chosen:
                    print(f"Measuring {case['id']}...", flush=True)
                    checked(client, f"function pdk_lab:{case['id']}/setup")
                    step(client, 20)
                    for index, stage in enumerate(case.get("prepare", [])):
                        checked(client, f"function pdk_lab:{case['id']}/prepare_{index}")
                        step(client, stage["settle_game_ticks"])
                    start_time = game_time(client)
                    samples = []
                    def sample(tick, phase=None):
                        checked(client, f"function pdk_lab:{case['id']}/sample")
                        values = parse_probe_response(client.command("data get storage pdk_lab:sample values"), [probe["name"] for probe in case["probes"]])
                        current = game_time(client)
                        if current != start_time + max(0, tick):
                            raise RuntimeError("Unexpected tick advancement while taking a sample")
                        for probe in case["probes"]:
                            if values[probe["name"]] not in [int(value) for value in probe["values"]]:
                                raise RuntimeError(f"Probe {probe['name']} returned a value outside its declared domain")
                        row = {"case": case["id"], "relative_game_tick": tick, "game_time": current,
                               "sample_index": len(samples),
                               "phase": phase or ("baseline_before_stimulus" if tick == -1 else "after_commands_or_completed_tick"),
                               "values": values}
                        observations.write(json.dumps(row) + "\n")
                        observations.flush()
                        samples.append(row)
                    sample(-1)
                    for tick in range(case["ticks"] + 1):
                        if tick > 0:
                            step(client)
                        if tick in case["actions"]:
                            if tick > 0:
                                sample(tick, "before_action")
                            checked(client, f"function pdk_lab:{case['id']}/action_{tick}")
                        sample(tick)
                    analysis = analyze(case, samples)
                    analyses.append(analysis)
                    print(f"  {'PASS' if analysis['pass'] else 'FAIL'}")
                    # A live run remains reviewable even if the process is stopped externally.
                    (run_dir / "progress.json").write_text(json.dumps({"completed": len(analyses), "total": len(chosen), "cases": analyses}, indent=2) + "\n", encoding="utf-8")
                checked(client, "save-all")
    except (OSError, RuntimeError, ValueError, KeyboardInterrupt) as exception:
        error = str(exception) or "Interrupted by user"
    summary = write_summary(run_dir, metadata, analyses, error)
    print(f"Report: {run_dir / 'README.md'}")
    if error:
        raise RuntimeError(error)
    return 0 if summary["pass"] else 1


def stop():
    with connect() as client:
        assert_identity(client)
        checked(client, "stop")
    print("The laboratory is saving and stopping.")
