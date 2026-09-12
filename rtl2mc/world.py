"""Fresh, owned vanilla worlds; physical replay, clean shutdown, and reopen check."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import time

from redstone_pdk import lab
from redstone_pdk.mapping_lab import functions, expected_values, check_bounds
from redstone_pdk.project import technology
from redstone_pdk.rcon import Rcon, RconError
from redstone_pdk.results import parse_probe_response
from .common import CACHE, ROOT, dump, sha, write
from .nbt import configure_world
from .minecraft import pack_settings, gamerule, resolve


def accepted_eula():
    return any(p.exists() and re.search(r"(?m)^eula=true\s*$", p.read_text())
               for p in (CACHE / "eula.txt", ROOT / ".local/server/eula.txt"))


def record_eula():
    write(CACHE / "eula.txt", "# Accepted explicitly by the user for local Minecraft runs.\neula=true\n")


def server_jar(target=None):
    pin = (target or resolve())["server"]["sha1"]
    for path in (ROOT / ".local/server/server.jar", CACHE / "server.jar", CACHE / "minecraft" / pin / "server.jar"):
        if path.exists() and hashlib.sha1(path.read_bytes()).hexdigest() == pin:
            return path
    raise ValueError("Pinned Minecraft server is missing; use the consent-gated dependency installer")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, output, tools, env, target):
        self.output = Path(output).resolve()
        self.folder = self.output / "work/server"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.tools, self.env = tools, env
        self.process = None
        self.port, self.game_port = free_port(), free_port()
        while self.game_port == self.port:
            self.game_port = free_port()
        self.password = secrets.token_urlsafe(32)
        self.marker = secrets.randbelow(1_000_000_000) + 1
        if not accepted_eula():
            raise PermissionError("Minecraft EULA acceptance is required")
        shutil.copyfile(server_jar(target), self.folder / "server.jar")
        for source in (ROOT / ".local/server", CACHE / "server-runtime"):
            for name in ("libraries", "versions"):
                if (source / name).is_dir():
                    shutil.copytree(source / name, self.folder / name, dirs_exist_ok=True)
        write(self.folder / "eula.txt", "eula=true\n")
        settings = {"server-ip": "127.0.0.1", "server-port": self.game_port, "enable-rcon": "true",
                    "rcon.port": self.port, "rcon.password": self.password, "broadcast-rcon-to-ops": "false",
                    "online-mode": "true", "level-name": "world", "level-type": "minecraft:flat",
                    "level-seed": "0", "generator-settings": lab.FLAT_SETTINGS, "generate-structures": "false",
                    "gamemode": "creative", "force-gamemode": "true", "difficulty": "peaceful",
                    "spawn-protection": "0", "view-distance": "3", "simulation-distance": "3", "max-players": "1",
                    "enable-command-block": "false", "motd": "RTL2MC isolated world qualification"}
        write(self.folder / "server.properties", "\n".join(f"{k}={v}" for k, v in settings.items())+"\n")
        if os.name != "nt":
            (self.folder / "server.properties").chmod(0o600)

    def connect(self, log=None):
        return Rcon(self.port, self.password, log)

    def start(self):
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        command = [*self.tools["java"]["argv"], "-Xms512M", "-Xmx1536M", "-jar", "server.jar",
                   "--universe", str(self.output), "--world", "world", "--nogui"]
        with (self.folder / "console.log").open("ab") as output:
            self.process = subprocess.Popen(command, cwd=self.folder, env=self.env, stdin=subprocess.DEVNULL,
                                            stdout=output, stderr=subprocess.STDOUT, **flags)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Minecraft exited; see work/server/console.log")
            try:
                with self.connect() as client:
                    lab.checked(client, "scoreboard objectives add pdk_lab dummy")
                    lab.checked(client, f"scoreboard players set #identity pdk_lab {self.marker}")
                    lab.checked(client, "tick freeze")
                    for name, value in (("doDaylightCycle", "false"), ("doWeatherCycle", "false"),
                                        ("doMobSpawning", "false"), ("randomTickSpeed", "0"),
                                        ("doTileDrops", "false"), ("maxCommandChainLength", "65536")):
                        gamerule(client, name, value)
                return
            except (OSError, RconError):
                time.sleep(0.5)
        raise RuntimeError("Minecraft startup timed out")

    def stop(self):
        if self.process is None or self.process.poll() is not None:
            return
        try:
            with self.connect() as client:
                if lab.score(client.command("scoreboard players get #identity pdk_lab")) != self.marker:
                    raise ValueError("Isolated server identity changed")
                lab.checked(client, "save-all flush")
                lab.checked(client, "stop")
            self.process.wait(timeout=60)
        except Exception:
            # Only terminate the child process created by this object.
            self.process.terminate()
            self.process.wait(timeout=15)
            raise
        if self.process.returncode:
            raise RuntimeError("Minecraft did not stop cleanly")


def datapack(world, namespace, compiled, description, pack):
    root = world / "datapacks" / namespace
    dump_root = root / "pack.mcmeta"
    write(dump_root, json.dumps({"pack": {**pack, "description": description}}))
    for name, commands in compiled.items():
        write(root / "data" / namespace / "function" / (name + ".mcfunction"), commands)


def user_controls(world, graph, layout, budget, vectors, target, pack):
    """Controls drive the same admitted redstone-block interface as the tests."""
    compiled = {}
    lines = [f"RTL2MC — {graph['top']}", "", f"Minecraft Java Edition {target['id']}; open this world in creative mode.",
             "Inputs use the measured redstone-block/air interface. Commands require cheats (enabled in this world).",
             f"After changing inputs, allow {budget['settle']} game ticks to settle.",
             "Read outputs with /function rtl2mc:read. Values report dust strength: zero=0, positive=1.", "", "Input controls:"]
    initial = []
    control_names = {}
    for index, source in enumerate(layout["sources"]):
        if "port" not in source:
            continue
        key = "p" + str(index)
        control_names[source["name"]] = key
        pos = " ".join(map(str, source["position"]))
        for bit, block in ((0, "air"), (1, "redstone_block")):
            compiled[f"input/{key}_{bit}"] = f"setblock {pos} minecraft:{block}\n"
        value = (vectors["initial"][source["port"]] >> source["bit_index"]) & 1
        initial.append(f"function rtl2mc:input/{key}_{value}")
        lines.append(f"  {source['port']} bit {source['bit_index']}: /function rtl2mc:input/{key}_0 or {key}_1; block at {pos}")
    compiled["initial_inputs"] = "\n".join(initial)+"\n"
    read_cmds = []
    for output in layout["outputs"]:
        pos = " ".join(map(str, output["position"]))
        name = output["name"]
        read_cmds.append(f"tellraw @a {json.dumps({'text': name + ' at ' + pos})}")
        for value in range(16):
            read_cmds.append(f"execute if block {pos} minecraft:redstone_wire[power={value}] run tellraw @a {json.dumps({'text': str(value)})}")
    compiled["read"] = "\n".join(read_cmds)+"\n"
    # Replay the verified stimulus with scheduled functions at the same tick
    # intervals. No live player command is required between events.
    replay = ["function rtl2mc:initial_inputs"]
    for i, event in enumerate(vectors["events"]):
        key = "replay/event_" + str(i)
        commands = []
        for source in layout["sources"]:
            if source.get("port") in event["inputs"]:
                value = (event["inputs"][source["port"]] >> source["bit_index"]) & 1
                commands.append(f"function rtl2mc:input/{control_names[source['name']]}_{value}")
        compiled[key] = "\n".join(commands)+"\n"
        replay.append(f"schedule function rtl2mc:{key} {event['tick']+budget['settle']+1}t replace")
    compiled["replay"] = "\n".join(replay)+"\n"
    lines += ["", "Replay the verified initialization and transactions: /function rtl2mc:replay",
              "Wait for a replay to finish before starting it again or changing inputs.",
              "The saved world starts in the final measured state. Clocked designs require their declared boot sequence after manual changes.",
              "All circuit chunks are force-loaded. Keep that setting for correct operation.",
              "The generated clock periods are intentionally very slow; use /tick rate to accelerate game time if desired."]
    datapack(world, "rtl2mc", compiled, "RTL2MC input controls and verified stimulus replay", pack)
    write(world / "RTL2MC-README.txt", "\n".join(lines)+"\n")
    return compiled


def measure(output, build, graph, layout, budget, vectors, golden, tools, env, target=None):
    output, build = Path(output), Path(build)
    world = output / "world"
    target = target or resolve()
    pack = pack_settings(server_jar(target), target)
    dump(output / "minecraft-target.json", target)
    check_bounds(layout["bounds"])
    compiled, probes, chunks = functions({**graph, "top": graph["top"].lower()}, layout, vectors, layout["bounds"])
    datapack(world, "pdk_lab", compiled, "RTL2MC physical qualification fixtures", pack)
    user_controls(world, graph, layout, budget, vectors, target, pack)
    prefix = "mapped_" + graph["top"].lower()
    evidence = output / "verification"
    evidence.mkdir(exist_ok=True)
    dump(evidence / "compiled-functions.json", compiled)
    server = Server(output, tools, env, target)
    count, failures = 0, []
    low, high = layout["bounds"]
    try:
        print("Starting isolated Minecraft world", flush=True)
        server.start()
        with (evidence / "commands.jsonl").open("w", encoding="utf-8") as commands_log, (evidence / "observations.jsonl").open("w", encoding="utf-8") as observations:
            def log(entry):
                commands_log.write(json.dumps(entry)+"\n")
                commands_log.flush()
            with server.connect(log) as client:
                lab.checked(client, "tick rate 1000")
                for x in range(low[0]//16, high[0]//16+1, 16):
                    for z in range(low[2]//16, high[2]//16+1, 16):
                        lab.checked(client, f"forceload add {x*16} {z*16} {min(x+15,high[0]//16)*16} {min(z+15,high[2]//16)*16}")
                for _ in range(200):
                    lab.checked(client, f"function pdk_lab:{prefix}/loaded")
                    if lab.score(client.command("scoreboard players get #loaded pdk_lab")) == len(chunks):
                        break
                    lab.step(client, 10)
                else:
                    raise ValueError("Circuit chunks did not load")
                lab.checked(client, f"function pdk_lab:{prefix}/setup")
                lab.step(client, budget["settle"])
                lab.checked(client, f"function pdk_lab:{prefix}/initial")
                lab.step(client, budget["settle"])
                start = lab.game_time(client)
                def sample(tick, phase, expected=None):
                    nonlocal count
                    lab.checked(client, f"function pdk_lab:{prefix}/sample")
                    actual = parse_probe_response(client.command("data get storage pdk_lab:sample values"), [p["name"] for p in probes])
                    game_time = lab.game_time(client)
                    if game_time != start + tick:
                        raise ValueError("Unexpected Minecraft tick advancement")
                    observations.write(json.dumps({"tick": tick, "phase": phase, "game_time": game_time, "values": actual})+"\n")
                    observations.flush()
                    if expected is not None:
                        for name, value in expected.items():
                            count += 1
                            if int(actual[name] > 0) != value:
                                failures.append({"tick": tick, "probe": name, "expected": value, "actual": actual[name]})
                    return actual
                events = {e["tick"]: e for e in vectors["events"]}
                now = 0
                for tick in sorted(set(events) | set(golden)):
                    if tick > now:
                        lab.step(client, tick-now)
                    now = tick
                    if tick in events:
                        sample(tick, "before_action")
                        lab.checked(client, f"function pdk_lab:{prefix}/action_{tick}")
                        sample(tick, "after_action")
                    if tick in golden:
                        sample(tick, "settled_check", expected_values(layout, golden[tick]))
                        print(f"Minecraft {graph['top']} t={tick}: {'FAIL' if failures else 'PASS'}", flush=True)
                if failures:
                    dump(evidence / "minecraft.json", {"pass": False, "comparisons": count, "failures": failures})
                    raise ValueError("Physical Minecraft behavior differs from the source RTL")
                # A platform outside the routing volume gives the player a safe spawn.
                lab.checked(client, f"forceload add {low[0]} -16 {min(low[0]+31,high[0])} 0")
                lab.step(client, 40)
                lab.checked(client, f"fill {low[0]} 82 -4 {low[0]+15} 82 4 minecraft:stone")
                lab.checked(client, f"setworldspawn {low[0]+7} 83 0")
                gamerule(client, "spawnRadius", 0)
                lab.checked(client, "tick rate 20")
                lab.checked(client, "tick unfreeze")
        server.stop()
        configure_world(world / "level.dat", "RTL2MC - " + graph["top"])
        if not (world / "region").is_dir() or not list((world / "region").glob("*.mca")):
            raise ValueError("World save contains no region files")
        print("Reopening the saved world and checking retained circuit state", flush=True)
        server.start()
        with server.connect() as client:
            lab.checked(client, "tick rate 1000")
            lab.step(client, budget["settle"])
            lab.checked(client, f"function pdk_lab:{prefix}/sample")
            actual = parse_probe_response(client.command("data get storage pdk_lab:sample values"), [p["name"] for p in probes])
            expected = expected_values(layout, golden[max(golden)])
            mismatch = [name for name, value in expected.items() if int(actual[name] > 0) != value]
            if mismatch:
                raise ValueError("Saved-world reopen comparison failed: " + ", ".join(mismatch))
            lab.checked(client, "tick rate 20")
            lab.checked(client, "tick unfreeze")
        server.stop()
        report = {"pass": True, "comparisons": count, "observations": len(golden), "reopen_comparisons": len(expected),
                  "reopen_pass": True, "minecraft_version": target["id"], "target_qualification": target["qualification"],
                  "server_sha1": target["server"]["sha1"], "coverage": vectors.get("coverage", "user vectors"),
                  "resolution": "before/after stimulus and settled integer game ticks; transient waveforms not qualified",
                  "evidence_sha256": {p.name: sha(p) for p in evidence.iterdir() if p.is_file()}}
        dump(evidence / "minecraft.json", report)
        return report
    finally:
        server.stop()
