"""Additive coverage beyond the version-1 repeater experiments.

Old fixtures and compiled commands remain unchanged. Spatial transforms map
positions and facing states; probe names retain their template-relative meaning.
"""
import copy
import re

from .fixtures import block
from .repeater_fixtures import action, base, brief_lock_cases, data_source, repeater_cases, side_source

VECTORS = {"east": (1, 0), "south": (0, 1), "west": (-1, 0), "north": (0, -1)}
SITES = {"interior": (10, 80, 5), "chunk_corner": (16, 80, 0)}


def rotate(x, z, turns):
    for _ in range(turns % 4):
        x, z = -z, x
    return x, z


def facing_after(facing, turns):
    vector = rotate(*VECTORS[facing], turns)
    return next(name for name, value in VECTORS.items() if value == vector)


def transform_layout(template, position, turns):
    case = copy.deepcopy(template)

    def point(x, y, z):
        dx, dz = rotate(x - 10, z - 5, turns)
        return [position[0] + dx, position[1] + y - 80, position[2] + dz]

    def command(text):
        parts = text.split()
        if len(parts) != 5 or parts[0] != "setblock":
            raise ValueError(f"Unsupported transform command: {text}")
        transformed = point(*map(int, parts[1:4]))
        state = re.sub(r"facing=(north|south|east|west)", lambda match: "facing=" + facing_after(match[1], turns), parts[4])
        return "setblock " + " ".join(map(str, transformed)) + " " + state

    case["setup"] = list(map(command, case["setup"]))
    case["actions"] = {tick: list(map(command, commands)) for tick, commands in case["actions"].items()}
    for stage in case.get("prepare", []):
        stage["commands"] = list(map(command, stage["commands"]))
    for probe in case["probes"]:
        probe["position"] = point(*probe["position"])
    return case


def spatial_templates():
    selected = []
    for case in repeater_cases():
        e = case["experiment"]
        if (e["family"] == "pulse" and e["input_width_game_ticks"] in (1, 2 * e["delay_setting"])) or (
            e["family"] == "brief_lock"
        ) or (e["family"] == "hold" and e["initial_output"] == 0 and e["side"] == "north") or (
            e["family"] == "pending" and e["initial_output"] == 1 and e["lock_due_offset"] == 0
        ):
            selected.append(case)
    return selected


def spatial_cases():
    result = []
    for site, position in SITES.items():
        for turns in range(4):
            if site == "interior" and turns == 0:
                continue  # The 48 original references are already in version 1.
            for template in spatial_templates():
                case = transform_layout(template, position, turns)
                case["id"] = f"repeater_spatial_{site}_r{turns}_{template['id'].removeprefix('repeater_')}"
                case["experiment"] = {**template["experiment"], "family": "spatial", "template_family": template["experiment"]["family"],
                                      "reference_fixture": template["id"], "site": site, "quarter_turns": turns,
                                      "dut_position": list(position), "facing": facing_after("west", turns)}
                result.append(case)
    return result


def strength_cases():
    result = []
    for delay in range(1, 5):
        for level in range(16):
            case = transform_layout(base(delay), (18, 80, 5), 0)
            source_x = 1 + level
            # 16-level dust blocks between source and DUT input: input strength=level.
            case["setup"] = [block(x, 5, "redstone_wire") for x in range(source_x + 1, 18)] + [
                block(18, 5, f"repeater[facing=west,delay={delay}]"), block(19, 5, "redstone_wire")]
            case.update(id=f"repeater_strength_d{delay}_s{level}", ticks=24,
                        experiment={"family": "strength", "delay_setting": delay, "input_level": level,
                                    "dut_position": [18, 80, 5], "source_position": [source_x, 80, 5], "stimulus_kind": "sustained"})
            action(case, 0, block(source_x, 5, "redstone_block"))
            action(case, 12, block(source_x, 5, "air"))
            case["checks"] = [{"tick": 0, "values": {"input": level}}, {"tick": 10, "values": {"input": level, "powered": int(level > 0)}},
                              {"tick": 12, "values": {"input": 0}}, {"tick": 24, "values": {"powered": 0, "out": 0}}]
            if level:
                case["edge_hypotheses"] = [{"probe": "powered", "after": t, "to": int(t == 0), "delay": 2 * delay} for t in (0, 12)]
            else:
                case["checks"] += [{"tick": t, "values": {"powered": 0}} for t in range(25)]
            result.append(case)
            if level in (1, 7, 15):
                pulse = copy.deepcopy(case)
                pulse["id"] += "_pulse1"
                pulse["experiment"]["stimulus_kind"] = "one_game_tick_high_pulse"
                pulse["ticks"] = 4 * delay + 3
                pulse["actions"] = {0: [block(source_x, 5, "redstone_block")], 1: [block(source_x, 5, "air")]}
                pulse["checks"] = [{"tick": pulse["ticks"], "values": {"input": 0, "powered": 0, "out": 0}}]
                pulse.pop("edge_hypotheses", None)
                pulse["pulse_hypotheses"] = [{"probe": "input", "active_value": level, "intervals": [[0, 1]]},
                                             {"probe": "powered", "active_value": 1, "intervals": [[2 * delay, 4 * delay]]}]
                result.append(pulse)
    return result


def sequence_cases():
    result = []
    for delay in range(1, 5):
        d = 2 * delay
        patterns = [("rapid", 1, 1), ("short_near", 1, d - 1), ("short_at", 1, d),
                    ("long_short", d, 1), ("matched", d, d), ("spaced", d + 1, d + 1)]
        for active in (1, 0):
            for pattern, width, gap in patterns:
                case = base(delay, 1 - active)
                duration = 3 * (width + gap) + 2 * d + 4
                case.update(id=f"repeater_train_d{delay}_{'high' if active else 'low'}_{pattern}", ticks=duration,
                            experiment={"family": "pulse_train", "delay_setting": delay, "active_value": active,
                                        "pattern": pattern, "pulse_count": 3, "active_width": width, "gap_width": gap,
                                        "output_prediction": "independent_pulses" if pattern == "spaced" else "record_only"})
                intervals = []
                for index in range(3):
                    start = index * (width + gap)
                    intervals.append([start, start + width])
                    action(case, start, data_source(active))
                    action(case, start + width, data_source(1 - active))
                case["checks"] = [{"tick": duration, "values": {"input": 15 * (1 - active), "powered": 1 - active, "locked": 0}}]
                case["pulse_hypotheses"] = [{"probe": "input", "active_value": 15 * active, "intervals": intervals}]
                if pattern == "spaced":
                    case["pulse_hypotheses"].append({"probe": "powered", "active_value": active,
                                                     "intervals": [[start + d, end + d] for start, end in intervals]})
                result.append(case)
    return result


def lock_sequence_cases():
    result = []
    for delay in range(1, 5):
        due = 4 + 2 * delay
        patterns = [("assert_near_due", due - 1, due + 3), ("release_at_due", due - 3, due),
                    ("release_after_due", due - 3, due + 1)]
        for initial in (0, 1):
            for side in ("north", "south"):
                for driver in ("repeater", "comparator"):
                    for pattern, lock_at, unlock_at in patterns:
                        case = base(delay, initial, [(side, driver)])
                        duration = unlock_at + 4 * delay + 4
                        case.update(id=f"repeater_lockseq_d{delay}_q{initial}_{side}_{driver}_{pattern}", ticks=duration,
                                    experiment={"family": "lock_sequence", "delay_setting": delay, "initial_output": initial,
                                                "side": side, "driver": driver, "pattern": pattern, "data_change_tick": 4,
                                                "nominal_output_due_tick": due, "lock_due_tick": lock_at, "unlock_due_tick": unlock_at,
                                                "output_prediction": "record_only"})
                        action(case, 4, data_source(1 - initial))
                        action(case, lock_at - 2, side_source(side, 1))
                        action(case, unlock_at - 2, side_source(side, 0))
                        case["checks"] = [{"tick": 4, "values": {"input": 15 * (1 - initial)}},
                                          {"tick": duration, "values": {"powered": 1 - initial, "locked": 0}}]
                        case["pulse_hypotheses"] = [{"probe": "locked", "active_value": 1, "intervals": [[lock_at, unlock_at]]}]
                        result.append(case)
    return result


def command_order_cases():
    result = []
    for template in brief_lock_cases():
        case = copy.deepcopy(template)
        case["id"] = template["id"] + "_lock_command_first"
        case["actions"][4].reverse()
        case["experiment"] = {**template["experiment"], "family": "command_order", "reference_fixture": template["id"],
                              "command_order": "lock source before data source at tick 4"}
        result.append(case)
    return result


def broad_cases(suite="repeater_broad"):
    generators = {"repeater_spatial": spatial_cases, "repeater_strength": strength_cases,
                  "repeater_sequences": sequence_cases, "repeater_lock_sequences": lambda: lock_sequence_cases() + command_order_cases()}
    if suite in generators:
        return generators[suite]()
    if suite != "repeater_broad":
        raise ValueError(f"Unknown broader repeater suite: {suite}")
    return [case for generate in generators.values() for case in generate()]
