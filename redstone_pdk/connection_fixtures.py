"""Connection admission: actual drivers, wire routes, receiver loads and guards."""
import copy

from .fixtures import binary_probe, power_probe, LAB_BOUNDS
from .repeater_broad_fixtures import rotate, facing_after

# Separate extended volume; all legacy compiled fixture functions stay identical.
CONNECTION_BOUNDS = [list(point) for point in LAB_BOUNDS]


def layout(driver=1, cell=1, receiver=1, length=2, shape="straight"):
    """Local coordinates, +x output. Component roots are explicitly physical."""
    blocks = {(-1, 0): "redstone_wire"}
    components = [("driver", (0, 0), "comparator" if driver == "comparator" else "repeater", 1 if driver == "comparator" else driver, "west")]
    for x in range(1, length + 1):
        blocks[(x, 0)] = "redstone_wire"
    x = length + 1
    components.append(("cell", (x, 0), "repeater", cell, "west"))
    if shape == "straight":
        blocks.update({(x + 1, 0): "redstone_wire", (x + 2, 0): "redstone_wire"})
        components.append(("receiver", (x + 3, 0), "repeater", receiver, "west"))
        blocks[(x + 4, 0)] = "redstone_wire"
    elif shape == "elbow":
        blocks.update({p: "redstone_wire" for p in ((x+1, 0), (x+2, 0), (x+2, 1), (x+2, 2))})
        components.append(("receiver", (x+2, 3), "repeater", receiver, "north"))
        blocks[(x+2, 4)] = "redstone_wire"
    elif shape in ("stub", "fanout2", "fanout3"):
        blocks.update({p: "redstone_wire" for p in ((x+1, 0), (x+2, 0), (x+3, 0), (x+2, -1), (x+2, -2))})
        components.append(("receiver", (x+4, 0), "repeater", receiver, "west"))
        blocks[(x+5, 0)] = "redstone_wire"
        if shape != "stub":
            components.append(("receiver_n", (x+2, -3), "repeater", 4, "south"))
            blocks[(x+2, -4)] = "redstone_wire"
        if shape == "fanout3":
            blocks.update({(x+2, 1): "redstone_wire", (x+2, 2): "redstone_wire"})
            components.append(("receiver_s", (x+2, 3), "repeater", 2, "north"))
            blocks[(x+2, 4)] = "redstone_wire"
    else:
        raise ValueError("Unknown route shape")
    for _, p, kind, setting, facing in components:
        blocks[p] = f"{kind}[facing={facing}," + ("mode=compare]" if kind == "comparator" else f"delay={setting}]")
    return blocks, components


def make_fixture(name, driver, cell, receiver, *, length=2, shape="straight", initial=0, rotation=0, anchor=(24, 16), family="chain"):
    blocks, components = layout(driver, cell, receiver, length, shape)
    def point(p):
        dx, dz = rotate(*p, rotation)
        return anchor[0] + dx, anchor[1] + dz
    def command(p, state):
        x, z = point(p)
        return f"setblock {x} 80 {z} minecraft:{state}"
    setup = []
    for p, state in blocks.items():
        for facing in ("west", "north", "east", "south"):
            if f"facing={facing}," in state:
                state = state.replace("facing=" + facing, "facing=" + facing_after(facing, rotation))
                break
        setup.append(command(p, state))
    probes = [power_probe("input", *point((-1, 0)))]
    vectors = {"west": (-1, 0), "east": (1, 0), "north": (0, -1), "south": (0, 1)}
    for role, p, kind, setting, facing in components:
        x, z = point(p)
        probes.append(binary_probe(role + "_q", x, 80, z, kind, "powered"))
        if kind == "repeater":
            probes.append(binary_probe(role + "_locked", x, 80, z, kind, "locked"))
        dx, dz = vectors[facing]
        probes.extend([power_probe(role + "_a", *point((p[0]+dx, p[1]+dz))),
                       power_probe(role + "_y", *point((p[0]-dx, p[1]-dz)))])
    delays = [2 * c[3] for c in components]
    gap = max(delays) + 1
    duration = 3 * gap + sum(delays) + 2
    fixture = {"id": name, "component": "repeater", "ticks": duration, "lab_bounds": CONNECTION_BOUNDS,
               "setup": setup, "prepare": [{"commands": [command((-2, 0), "redstone_block" if initial else "air")],
                                             "settle_game_ticks": 20 + sum(delays)}],
               "actions": {i * gap: [command((-2, 0), "redstone_block" if (initial ^ ((i+1) % 2)) else "air")] for i in range(4)},
               "probes": probes, "checks": [], "trace_probes": [p["name"] for p in probes],
               "experiment": {"family": family, "driver_kind": "comparator" if driver == "comparator" else "repeater",
                              "driver_setting": 1 if driver == "comparator" else driver, "cell_setting": cell,
                              "receiver_setting": receiver, "wire_length": length, "shape": shape, "initial": initial,
                              "quarter_turns": rotation, "admission_expected": length <= 15}}
    # Independent compositional law supplies hypotheses BEFORE Minecraft runs.
    from .connections import predict_fixture
    prediction = predict_fixture(fixture, allow_attenuated_off=True)
    fixture["baseline_checks"] = prediction["samples"][0]["values"]
    fixture["checks"] = [{"tick": r["relative_game_tick"], "values": r["values"]} for r in prediction["samples"]
                         if r["phase"] == "after_commands_or_completed_tick"]
    return fixture


def connection_cases():
    result = []
    for a in range(1, 5):
        for b in range(1, 5):
            for c in range(1, 5):
                result.append(make_fixture(f"net_chain_{a}_{b}_{c}", a, b, c, initial=(a+b+c) % 2))
    for length in range(2, 17):
        for b in range(1, 5):
            result.append(make_fixture(f"net_length_{length}_d{b}", 1, b, 1, length=length, initial=(length+b) % 2, family="attenuation"))
    for b in range(1, 5):
        for c in range(1, 5):
            for q in (0, 1):
                result.append(make_fixture(f"net_comparator_{b}_{c}_q{q}", "comparator", b, c, initial=q, family="comparator_driver"))
    for shape in ("elbow", "stub", "fanout2", "fanout3"):
        for b in range(1, 5):
            for q in (0, 1):
                result.append(make_fixture(f"net_{shape}_d{b}_q{q}", 1, b, 3, shape=shape, initial=q, family="routing_load"))
    for a, b, c in ((1, 4, 1), (4, 1, 4)):
        for rotation in range(4):
            for q in (0, 1):
                result.append(make_fixture(f"net_spatial_{a}_{b}_{c}_r{rotation}_q{q}", a, b, c, rotation=rotation,
                                           anchor=(15, 0), initial=q, family="spatial"))
    return copy.deepcopy(result)
