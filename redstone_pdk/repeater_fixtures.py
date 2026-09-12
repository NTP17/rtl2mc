"""Repeater experiments and explicit, falsifiable hypotheses.

The device under test is at (10,80,5), facing west (input west/output east).
All time values are game ticks. Drivers are physical neighboring blocks;
the tests never force the DUT's powered/locked properties.
"""
from .fixtures import binary_probe, block, power_probe


def data_source(power):
    return block(8, 5, "redstone_block" if power else "air")


def side_source(side, power):
    return block(10, 2 if side == "north" else 8, "redstone_block" if power else "air")


def base(delay, initial=0, sides=()):
    setup = [block(9, 5, "redstone_wire"), block(10, 5, f"repeater[facing=west,delay={delay}]"), block(11, 5, "redstone_wire")]
    probes = [power_probe("input", 9, 5), binary_probe("powered", 10, 80, 5, "repeater", "powered"),
              binary_probe("locked", 10, 80, 5, "repeater", "locked"), power_probe("out", 11, 5)]
    drivers = []
    for side, kind in sides:
        driver_z, input_z = (4, 3) if side == "north" else (6, 7)
        state = f"repeater[facing={side},delay=1]" if kind == "repeater" else f"comparator[facing={side},mode=compare]"
        setup += [block(10, input_z, "redstone_wire"), block(10, driver_z, state)]
        probes += [power_probe(f"{side}_input", 10, input_z), binary_probe(f"{side}_powered", 10, 80, driver_z, kind, "powered")]
        drivers.append(f"{side}_powered")
    if initial:
        setup.append(data_source(1))
    return {"component": "repeater", "setup": setup, "probes": probes,
            "actions": {}, "checks": [], "baseline_checks": {"input": 15 * initial, "powered": initial, "out": 15 * initial, "locked": 0},
            "invariants": [{"kind": "binary_output", "state": "powered", "output": "out"},
                           {"kind": "lock_equals_or", "lock": "locked", "drivers": drivers},
                           {"kind": "hold_while_locked", "lock": "locked", "state": "powered"}],
            "trace_probes": [probe["name"] for probe in probes]}


def action(case, tick, *commands):
    case["actions"].setdefault(tick, []).extend(commands)


def pulse_cases():
    result = []
    for delay in range(1, 5):
        latency = 2 * delay
        for active in (1, 0):
            for width in range(1, 11):
                initial = 1 - active
                case = base(delay, initial)
                case.update(id=f"repeater_pulse_d{delay}_{'high' if active else 'low'}_w{width}", ticks=width + 2 * latency + 3,
                            experiment={"family": "pulse", "delay_setting": delay, "active_value": active, "input_width_game_ticks": width})
                action(case, 0, data_source(active))
                action(case, width, data_source(initial))
                # Candidate behavior, compared with actual intervals in the game.
                # A short high pulse is stretched; a short low gap is rejected.
                output_intervals = [[latency, latency + max(width, latency)]] if active else ([] if width < latency else [[latency, latency + width]])
                case["pulse_hypotheses"] = [
                    {"probe": "input", "active_value": 15 * active, "intervals": [[0, width]]},
                    {"probe": "powered", "active_value": active, "intervals": output_intervals}
                ]
                case["checks"] = [{"tick": case["ticks"], "values": {"input": 15 * initial, "powered": initial, "locked": 0, "out": 15 * initial}}]
                result.append(case)
    return result


def hold_cases():
    result = []
    for delay in range(1, 5):
        for initial in (0, 1):
            for side in ("north", "south"):
                for kind in ("repeater", "comparator"):
                    case = base(delay, initial, [(side, kind)])
                    case.update(id=f"repeater_hold_d{delay}_q{initial}_{side}_{kind}", ticks=40,
                                experiment={"family": "hold", "delay_setting": delay, "initial_output": initial, "side": side, "driver": kind})
                    case["prepare"] = [{"commands": [side_source(side, 1)], "settle_game_ticks": 4}]
                    case["baseline_checks"].update(locked=1, **{f"{side}_powered": 1, f"{side}_input": 15})
                    action(case, 0, data_source(1 - initial))
                    action(case, 5, data_source(initial))
                    action(case, 10, data_source(1 - initial))
                    action(case, 16, side_source(side, 0))
                    action(case, 30, data_source(initial))
                    case["checks"] = [{"tick": tick, "values": {"powered": initial, "locked": 1}} for tick in range(18)]
                    case["checks"] += [{"tick": 18, "values": {"locked": 0}},
                                       {"tick": 18 + 2 * delay, "values": {"powered": 1 - initial}},
                                       {"tick": 40, "values": {"powered": initial}}]
                    case["edge_hypotheses"] = [{"probe": "powered", "after": 18, "to": 1 - initial, "delay": 2 * delay}]
                    result.append(case)
    return result


def pending_cases():
    result = []
    for delay in range(1, 5):
        for initial in (0, 1):
            for side in ("north", "south"):
                for offset in (-1, 0, 1):
                    due = 4 + 2 * delay
                    lock_at = due + offset
                    release_command = due + 6
                    case = base(delay, initial, [(side, "repeater")])
                    case.update(id=f"repeater_pending_d{delay}_q{initial}_{side}_{'early' if offset < 0 else 'same' if offset == 0 else 'late'}",
                                ticks=release_command + 2 + 2 * delay + 3,
                                experiment={"family": "pending", "delay_setting": delay, "initial_output": initial,
                                            "side": side, "driver": "repeater", "data_change_tick": 4,
                                            "nominal_output_due_tick": due, "lock_due_offset": offset,
                                            "lock_due_tick": lock_at, "unlock_due_tick": release_command + 2})
                    # If the commands share a tick, data is written before lock input.
                    action(case, 4, data_source(1 - initial))
                    action(case, lock_at - 2, side_source(side, 1))
                    action(case, release_command, side_source(side, 0))
                    case["checks"] = [{"tick": lock_at - 1, "values": {"locked": 0}},
                                       {"tick": lock_at, "values": {"locked": 1}},
                                       {"tick": release_command + 2, "values": {"locked": 0}},
                                       {"tick": case["ticks"], "values": {"powered": 1 - initial, "input": 15 * (1 - initial)}}]
                    if offset < 0:
                        case["checks"] += [{"tick": tick, "values": {"powered": initial}} for tick in range(lock_at, release_command + 2)]
                    elif offset > 0:
                        case["checks"].append({"tick": due, "values": {"powered": 1 - initial}})
                    # Equal-tick ordering is recorded, not generalized as a timing guarantee.
                    result.append(case)
    return result


def dual_lock_cases():
    result = []
    for delay in range(1, 5):
        for initial in (0, 1):
            case = base(delay, initial, [("north", "repeater"), ("south", "repeater")])
            case.update(id=f"repeater_dual_d{delay}_q{initial}", ticks=28,
                        experiment={"family": "dual_lock", "delay_setting": delay, "initial_output": initial})
            case["prepare"] = [{"commands": [side_source("north", 1), side_source("south", 1)], "settle_game_ticks": 4}]
            case["baseline_checks"].update(locked=1, north_powered=1, south_powered=1)
            action(case, 0, data_source(1 - initial))
            action(case, 5, side_source("north", 0))
            action(case, 14, side_source("south", 0))
            case["checks"] = [{"tick": tick, "values": {"powered": initial, "locked": 1}} for tick in range(16)]
            case["checks"] += [{"tick": 7, "values": {"north_powered": 0, "south_powered": 1}},
                               {"tick": 16, "values": {"locked": 0}},
                               {"tick": 16 + 2 * delay, "values": {"powered": 1 - initial}}]
            case["edge_hypotheses"] = [{"probe": "powered", "after": 16, "to": 1 - initial, "delay": 2 * delay}]
            result.append(case)
    return result


def ineligible_side_cases():
    result = []
    for delay in range(1, 5):
        for kind in ("redstone_block", "redstone_wire"):
            case = base(delay)
            case.update(id=f"repeater_side_control_d{delay}_{kind}", ticks=24,
                        experiment={"family": "side_control", "delay_setting": delay, "side_block": kind})
            case["setup"].append(block(10, 4, kind))
            if kind == "redstone_wire":
                case["setup"].append(block(10, 3, "redstone_block"))
                case["probes"].append(power_probe("side_input", 10, 4))
                case["baseline_checks"]["side_input"] = 15
            action(case, 0, data_source(1))
            action(case, 12, data_source(0))
            case["checks"] = [{"tick": 10, "values": {"locked": 0, "powered": 1}}, {"tick": 22, "values": {"locked": 0, "powered": 0}}]
            result.append(case)
    return result


def brief_lock_cases():
    result = []
    for delay in range(1, 5):
        for initial in (0, 1):
            for side in ("north", "south"):
                case = base(delay, initial, [(side, "repeater")])
                case.update(id=f"repeater_brief_lock_d{delay}_q{initial}_{side}", ticks=26,
                            experiment={"family": "brief_lock", "delay_setting": delay, "initial_output": initial,
                                        "side": side, "data_change_tick": 4, "nominal_output_due_tick": 4 + 2 * delay,
                                        "lock_due_tick": 6, "unlock_due_tick": 8})
                action(case, 4, data_source(1 - initial), side_source(side, 1))
                action(case, 5, side_source(side, 0))
                case["checks"] = [{"tick": 5, "values": {"locked": 0}}, {"tick": 6, "values": {"locked": 1}},
                                   {"tick": 7, "values": {"locked": 1}}, {"tick": 8, "values": {"locked": 0}},
                                   {"tick": 26, "values": {"powered": 1 - initial}}]
                if delay >= 3:
                    # Lock is fully released before the original pending event is due.
                    case["checks"].append({"tick": 4 + 2 * delay, "values": {"powered": 1 - initial}})
                result.append(case)
    return result


def return_while_locked_cases():
    result = []
    for delay in range(1, 5):
        for initial in (0, 1):
            case = base(delay, initial, [("north", "repeater")])
            case.update(id=f"repeater_locked_return_d{delay}_q{initial}", ticks=26,
                        experiment={"family": "locked_return", "delay_setting": delay, "initial_output": initial, "side": "north"})
            case["prepare"] = [{"commands": [side_source("north", 1)], "settle_game_ticks": 4}]
            case["baseline_checks"].update(locked=1, north_powered=1)
            action(case, 0, data_source(1 - initial))
            action(case, 5, data_source(initial))
            action(case, 10, side_source("north", 0))
            case["checks"] = [{"tick": tick, "values": {"powered": initial}} for tick in range(27)]
            case["checks"].append({"tick": 12, "values": {"locked": 0}})
            result.append(case)
    return result


def repeater_cases():
    return (pulse_cases() + hold_cases() + pending_cases() + dual_lock_cases() + ineligible_side_cases()
            + brief_lock_cases() + return_while_locked_cases())
