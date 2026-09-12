"""Vanilla block fixtures. Expected results are hypotheses until run in Minecraft.

All fixtures live inside the disposable lab volume. Sources use explicit
setblock updates; these tests do not characterize normal player interaction.
"""
import hashlib
import json

BOUNDS = ((0, 79, -5), (22, 84, 12))
LAB_BOUNDS = ((0, 79, -16), (63, 84, 47))


def block(x, z, state, y=80):
    return f"setblock {x} {y} {z} minecraft:{state}"


def power_probe(name, x, z):
    return {"name": name, "position": [x, 80, z], "block": "minecraft:redstone_wire", "property": "power", "values": list(range(16))}


def binary_probe(name, x, y, z, block_id, property_name):
    return {"name": name, "position": [x, y, z], "block": f"minecraft:{block_id}", "property": property_name, "values": [False, True]}


def core_cases():
    result = [{
        "id": "dust_line", "component": "dust", "ticks": 5,
        "setup": [block(x, 2, "redstone_wire") for x in range(2, 18)],
        "probes": [power_probe(f"d{x - 1}", x, 2) for x in (2, 3, 16, 17)],
        "actions": {0: [block(1, 2, "redstone_block")], 3: [block(1, 2, "air")]},
        "checks": [
            {"tick": 0, "values": {"d1": 15, "d2": 14, "d15": 1, "d16": 0}},
            {"tick": 3, "values": {"d1": 0, "d2": 0, "d15": 0, "d16": 0}}
        ]
    }, {
        "id": "torch_inversion", "component": "torch", "ticks": 16,
        "setup": [block(5, 5, "stone"), block(4, 5, "redstone_wire"), block(5, 5, "redstone_torch", y=81)],
        "probes": [power_probe("input", 4, 5), binary_probe("lit", 5, 81, 5, "redstone_torch", "lit")],
        "actions": {0: [block(3, 5, "redstone_block")], 8: [block(3, 5, "air")]},
        "checks": [{"tick": 6, "values": {"input": 15, "lit": 0}}, {"tick": 14, "values": {"input": 0, "lit": 1}}],
        "edge_hypotheses": [{"probe": "lit", "after": 0, "to": 0, "delay": 2}, {"probe": "lit", "after": 8, "to": 1, "delay": 2}]
    }]
    for delay in range(1, 5):
        result.append({
            "id": f"repeater_delay_{delay}", "component": "repeater", "ticks": 24,
            "setup": [block(5, 5, f"repeater[facing=west,delay={delay}]") , block(6, 5, "redstone_wire")],
            "probes": [binary_probe("powered", 5, 80, 5, "repeater", "powered"), power_probe("out", 6, 5)],
            "actions": {0: [block(4, 5, "redstone_block")], 12: [block(4, 5, "air")]},
            "checks": [{"tick": 10, "values": {"powered": 1, "out": 15}}, {"tick": 22, "values": {"powered": 0, "out": 0}}],
            "edge_hypotheses": [{"probe": "powered", "after": 0, "to": 1, "delay": 2 * delay}, {"probe": "powered", "after": 12, "to": 0, "delay": 2 * delay}]
        })
    for mode in ("compare", "subtract"):
        for side in (8, 15):
            source_z = -3 if side == 8 else 4
            expected = (12 if 12 >= side else 0) if mode == "compare" else max(12 - side, 0)
            result.append({
                "id": f"comparator_{mode}_side_{side}", "component": "comparator", "ticks": 18,
                "setup": [block(x, 6, "redstone_wire") for x in range(2, 6)]
                    + [block(6, z, "redstone_wire") for z in range(source_z + 1, 6)]
                    + [block(6, 6, f"comparator[facing=west,mode={mode}]"), block(7, 6, "redstone_wire")],
                "probes": [power_probe("rear", 5, 6), power_probe("side", 6, 5), power_probe("out", 7, 6)],
                "actions": {0: [block(1, 6, "redstone_block")], 6: [block(6, source_z, "redstone_block")], 12: [block(1, 6, "air"), block(6, source_z, "air")]},
                "checks": [{"tick": 4, "values": {"rear": 12, "side": 0, "out": 12}}, {"tick": 10, "values": {"rear": 12, "side": side, "out": expected}}, {"tick": 17, "values": {"rear": 0, "side": 0, "out": 0}}]
            })
    return result


SUITES = ("core", "repeater", "repeater_pulses", "repeater_locks", "repeater_broad", "repeater_spatial",
          "repeater_strength", "repeater_sequences", "repeater_lock_sequences", "cells", "connections", "all")


def cases(suite="all"):
    from .repeater_fixtures import repeater_cases
    if suite not in SUITES:
        raise ValueError(f"Unknown suite: {suite}")
    if suite == "core":
        return core_cases()
    if suite == "cells":
        from .cell_fixtures import buffer_cases
        return buffer_cases()
    if suite == "connections":
        from .connection_fixtures import connection_cases
        return connection_cases()
    if suite.startswith("repeater_") and suite not in ("repeater_pulses", "repeater_locks"):
        from .repeater_broad_fixtures import broad_cases
        return broad_cases(suite)
    extended = repeater_cases()
    if suite == "all":
        from .repeater_broad_fixtures import broad_cases
        from .cell_fixtures import buffer_cases
        from .connection_fixtures import connection_cases
        return core_cases() + extended + broad_cases() + buffer_cases() + connection_cases()
    if suite == "repeater_pulses":
        return [case for case in extended if case["experiment"]["family"] == "pulse"]
    if suite == "repeater_locks":
        return [case for case in extended if case["experiment"]["family"] != "pulse"]
    return extended


def suite_hash(suite="all"):
    return hashlib.sha256(json.dumps(cases(suite), sort_keys=True).encode()).hexdigest()


def compile_functions(fixtures=None):
    """Compile fixtures to 1.21's singular data/<namespace>/function paths."""
    generated = {}
    low, high = BOUNDS
    clear = "fill " + " ".join(map(str, low + high)) + " minecraft:air"
    floor = "fill 0 79 -5 22 79 12 minecraft:stone"
    for case in cases() if fixtures is None else fixtures:
        prefix = case["id"]
        case_clear, case_floor = clear, floor
        if "lab_bounds" in case:
            a, b = case["lab_bounds"]
            if not all(lo <= v <= hi for p in (a, b) for lo, v, hi in zip(LAB_BOUNDS[0], p, LAB_BOUNDS[1])):
                raise ValueError("Fixture bounds escape the reserved lab")
            case_clear = "fill " + " ".join(map(str, (*a, *b))) + " minecraft:air"
            case_floor = f"fill {a[0]} 79 {a[2]} {b[0]} 79 {b[2]} minecraft:stone"
        generated[f"{prefix}/setup"] = "\n".join([case_clear, case_floor] + case["setup"]) + "\n"
        for index, stage in enumerate(case.get("prepare", [])):
            generated[f"{prefix}/prepare_{index}"] = "\n".join(stage["commands"]) + "\n"
        for tick, actions in case["actions"].items():
            generated[f"{prefix}/action_{tick}"] = "\n".join(actions) + "\n"
        sample = ["data modify storage pdk_lab:sample values set value {}"]
        for probe in case["probes"]:
            sample.append("scoreboard players set #probe pdk_lab -1")
            position = " ".join(map(str, probe["position"]))
            for value in probe["values"]:
                state_value = str(value).lower() if isinstance(value, bool) else str(value)
                sample.append(f"execute if block {position} {probe['block']}[{probe['property']}={state_value}] run scoreboard players set #probe pdk_lab {int(value)}")
            sample.append(f"execute store result storage pdk_lab:sample values.{probe['name']} int 1 run scoreboard players get #probe pdk_lab")
        generated[f"{prefix}/sample"] = "\n".join(sample) + "\n"
    return generated
