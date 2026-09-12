"""Exact Java Edition target resolution; qualification is separate from selection."""
import hashlib
import io
import json
import re
import zipfile

from redstone_pdk.project import technology
from .install import fetch

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
OLDEST_TARGET = "1.21.1"


def resolve(requested=OLDEST_TARGET):
    if requested == OLDEST_TARGET:
        tech = technology()
        return {"id": OLDEST_TARGET, "type": "release", "java_major": 21,
                "server": tech["server"], "qualification": "measured library baseline",
                "minimum_target": OLDEST_TARGET, "pack_format": tech["data_pack_format"]}
    manifest = json.loads(fetch(MANIFEST))
    if requested in ("latest-release", "latest-snapshot"):
        requested = manifest["latest"][requested.split("-", 1)[1]]
    entries = {entry["id"]: entry for entry in manifest["versions"]}
    if requested not in entries:
        raise ValueError("Unknown Minecraft Java version/snapshot ID: " + requested)
    entry = entries[requested]
    if entry["releaseTime"] < entries[OLDEST_TARGET]["releaseTime"]:
        raise ValueError(f"Oldest implemented target is {OLDEST_TARGET}; this is a measured support floor, not a claim that all redstone became stable then")
    if entry["type"] not in ("release", "snapshot"):
        raise ValueError("Only modern Java releases and explicitly selected snapshots are supported")
    data = fetch(entry["url"])
    if hashlib.sha1(data).hexdigest() != entry["sha1"]:
        raise ValueError("Minecraft version metadata checksum mismatch")
    metadata = json.loads(data)
    if metadata["id"] != requested or "server" not in metadata.get("downloads", {}):
        raise ValueError("This Minecraft target has no usable vanilla server")
    return {"id": requested, "type": entry["type"], "java_major": metadata["javaVersion"]["majorVersion"],
            "server": metadata["downloads"]["server"], "metadata_sha1": entry["sha1"],
            "qualification": "candidate: requires this circuit's physical measurement and save/reopen; library-wide qualification not inherited",
            "minimum_target": OLDEST_TARGET}


def pack_settings(server, target):
    """Read the downloaded engine's actual pack version, including minor versions."""
    with zipfile.ZipFile(server) as outer:
        if "version.json" in outer.namelist():
            version = json.loads(outer.read("version.json"))
        else:
            rows = outer.read("META-INF/versions.list").decode().strip().splitlines()
            if len(rows) != 1:
                raise ValueError("Unsupported Minecraft server bundle structure")
            digest, _, name = rows[0].split("\t")
            contents = outer.read("META-INF/versions/" + name)
            if hashlib.sha256(contents).hexdigest() != digest:
                raise ValueError("Embedded Minecraft engine checksum mismatch")
            with zipfile.ZipFile(io.BytesIO(contents)) as inner:
                version = json.loads(inner.read("version.json"))
    if version["id"] != target["id"]:
        raise ValueError("Downloaded engine version differs from the requested target")
    pack = version["pack_version"]["data"]
    if isinstance(pack, dict):
        major, minor = pack["major"], pack["minor"]
    elif isinstance(pack, list):
        major, minor = pack
    else:
        major, minor = int(pack), version["pack_version"].get("data_minor", 0)
    if major < 48:
        raise ValueError("This engine predates the implemented datapack interface")
    target["pack_format"] = [major, minor]
    target["data_version"] = version["world_version"]
    return {"min_format": [major, minor], "max_format": [major, minor]} if major >= 82 else {"pack_format": major}


RULES = {"doDaylightCycle": "advance_time", "doWeatherCycle": "advance_weather",
         "doMobSpawning": "spawn_mobs", "randomTickSpeed": "random_tick_speed", "doTileDrops": "block_drops",
         "maxCommandChainLength": "max_command_sequence_length", "spawnRadius": "respawn_radius"}


def gamerule(client, name, value):
    from redstone_pdk.lab import checked
    try:
        return checked(client, f"gamerule {name} {value}")
    except RuntimeError:
        # 1.21.11 introduced namespaced snake_case IDs. Probe the actual engine
        # instead of guessing snapshot names or calendar-version ordering.
        return checked(client, f"gamerule minecraft:{RULES[name]} {value}")
