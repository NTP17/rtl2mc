"""Fresh admission fixtures for guarded, explicitly instantiated buffer cells."""
from .fixtures import block, power_probe, binary_probe
from .repeater_broad_fixtures import transform_layout


def buffer_cases():
    result = []
    for setting in range(1, 5):
        delay = 2 * setting
        for initial in (0, 1):
            for pattern in ("minimum", "mixed"):
                # Both polarities exercise the exact lower bound. Mixed gaps
                # additionally exercise idle time; expectations are a delayed
                # Boolean signal, independently of the native event simulator.
                gaps = [delay + 1] * 5 if pattern == "minimum" else [delay + 1, delay + 4, delay + 2, delay + 7, delay + 1]
                edges = [0]
                for gap in gaps:
                    edges.append(edges[-1] + gap)
                actions = {t: [block(8, 5, "redstone_block" if (initial ^ ((i + 1) % 2)) else "air")]
                           for i, t in enumerate(edges)}
                duration = edges[-1] + delay + 2
                fixture = {
                    "id": "temporary", "component": "repeater", "ticks": duration,
                    "setup": [block(9, 5, "redstone_wire"),
                              block(10, 5, f"repeater[facing=west,delay={setting}]"), block(11, 5, "redstone_wire")],
                    "prepare": [{"commands": [block(8, 5, "redstone_block" if initial else "air")], "settle_game_ticks": 20}],
                    "actions": actions,
                    "probes": [power_probe("input", 9, 5), power_probe("out", 11, 5),
                               binary_probe("powered", 10, 80, 5, "repeater", "powered"),
                               binary_probe("locked", 10, 80, 5, "repeater", "locked")],
                    "baseline_checks": {"input": 15 * initial, "out": 15 * initial, "powered": initial, "locked": 0},
                    "checks": [], "trace_probes": ["input", "out", "powered", "locked"],
                    "edge_hypotheses": [{"probe": "powered", "after": t, "to": initial ^ ((i + 1) % 2), "delay": delay}
                                        for i, t in enumerate(edges)],
                }
                for tick in range(duration + 1):
                    a = initial ^ (sum(t <= tick for t in edges) % 2)
                    q = initial ^ (sum(t + delay <= tick for t in edges) % 2)
                    fixture["checks"].append({"tick": tick, "values": {"input": 15 * a, "out": 15 * q, "powered": q, "locked": 0}})
                for rotation in range(4):
                    case = transform_layout(fixture, (10, 80, 5), rotation)
                    case["id"] = f"cell_rsbuf{delay}_r{rotation}_q{initial}_{pattern}"
                    case["experiment"] = {"family": "cell_admission", "cell": f"RSBUF{delay}", "delay_setting": setting,
                                          "quarter_turns": rotation, "initial_output": initial, "pattern": pattern}
                    result.append(case)
    return result
