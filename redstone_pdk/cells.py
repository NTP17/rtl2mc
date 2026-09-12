"""Admission and legal-use checks for the first guarded buffer cells.

The general repeater remains an experimental primitive. These separate cell
contracts describe a deliberately narrower physical and temporal envelope.
"""
import json

from .project import ROOT, read_json, technology
from .repeater_broad_fixtures import facing_after, rotate
from .model_validation import digest, sha, compare_samples

LIBRARY = "cells/repeater-buffers.json"
ADMISSION = "characterizations/repeater-cells-v1.json"


def cell_definition(setting):
    if type(setting) is not int or setting not in range(1, 5):
        raise ValueError("Repeater setting must be 1..4")
    d = 2 * setting
    return {
        "name": f"RSBUF{d}", "kind": "guarded_binary_buffer", "primitive": "repeater",
        "setting": setting, "function": "Y = A", "mapping_eligible": False,
        "use": "explicit_instances_with_envelope_checks",
        "ports": {"A": {"direction": "input", "position": [-1, 0, 0], "access_face": "west", "levels": [0, 15]},
                  "Y": {"direction": "output", "position": [1, 0, 0], "access_face": "east", "levels": [0, 15],
                        "external_connections_admitted": False}},
        "physical": {
            "origin": "repeater block; local +x is the output direction",
            "blocks": [{"position": [-1, 0, 0], "state": "minecraft:redstone_wire"},
                       {"position": [0, 0, 0], "state": f"minecraft:repeater[facing=west,delay={setting}]"},
                       {"position": [1, 0, 0], "state": "minecraft:redstone_wire"}],
            "reserved_box": {"min": [-3, -1, -2], "max": [3, 2, 2]},
            "support": "entire reserved box at y=-1 is stone; no external power is applied to it",
            "air": "all other reserved positions except the three body blocks and stimulus source",
            "stimulus_source": {"position": [-2, 0, 0], "states": ["minecraft:air", "minecraft:redstone_block"]},
            "rotations_quarter_turns": [0, 1, 2, 3], "mirrors": [],
            "output_load": "the single included Y dust block; no external receiver or extra dust",
        },
        "protocol": {"time_unit": "game_tick", "input_encoding": "A=0 means power 0; A=1 means power 15",
                     "initial_settle_game_ticks": 20, "initial_A": [0, 1],
                     "minimum_high_game_ticks": d + 1, "minimum_low_game_ticks": d + 1,
                     "stimulus_phase": "ordered source replacement after a completed game tick",
                     "sampling_phase": "after all scheduled work and source updates at each game tick",
                     "one_input_transition_per_game_tick": True},
        "timing": {"time_unit": "game_tick", "arcs": [{"from": "A", "to": "Y", "sense": "positive_unate",
                    "rise": d, "fall": d}], "scope": "all legal histories under the declared operating assumptions"},
        "assumptions": ["Java Edition 1.21.1 vanilla, pinned official server build",
                        "All affected chunks remain loaded; scheduled ticks are not deferred by a work backlog",
                        "Static horizontal layout on rigid stone support; reserved air stays empty",
                        "Only the source port changes; no player interactions, block moves, or forced state edits",
                        "No incoming power through the floor, above, below, or outside the input source",
                        "No output connections, side drivers, feedback, or shared nets; probe reads do not load Y"],
    }


def placement(cell, rotation=0):
    """Exact reserved-volume contents before initialization, in local coordinates."""
    if type(rotation) is not int or rotation not in cell["physical"]["rotations_quarter_turns"]:
        raise ValueError("Unadmitted rotation")
    physical = cell["physical"]
    low, high = physical["reserved_box"]["min"], physical["reserved_box"]["max"]
    world = {(x, y, z): "minecraft:stone" if y == -1 else "minecraft:air"
             for x in range(low[0], high[0] + 1) for y in range(low[1], high[1] + 1) for z in range(low[2], high[2] + 1)}
    world.update({tuple(b["position"]): b["state"] for b in physical["blocks"]})
    return {(rotate(x, z, rotation)[0], y, rotate(x, z, rotation)[1]):
            state.replace("facing=west", "facing=" + facing_after("west", rotation)) for (x, y, z), state in world.items()}


def validate_protocol(cell, initial, transitions, *, settled_game_ticks=20):
    """Reject illegal inputs instead of assigning them a fictitious cell delay."""
    if type(initial) is not int or initial not in (0, 1):
        raise ValueError("Initial A must be a binary integer")
    if type(settled_game_ticks) is not int or settled_game_ticks < cell["protocol"]["initial_settle_game_ticks"]:
        raise ValueError("The initial input must settle for at least 20 game ticks")
    last_tick, previous = None, initial
    for tick, value in transitions:
        if type(tick) is not int or tick < 0 or type(value) is not int or value not in (0, 1):
            raise ValueError("Input changes require nonnegative integer game ticks and binary values")
        if value == previous:
            raise ValueError("Transition list contains a repeated value")
        if last_tick is not None:
            bound = cell["protocol"]["minimum_high_game_ticks" if previous else "minimum_low_game_ticks"]
            if tick - last_tick < bound:
                raise ValueError(f"Input dwell below {bound} game ticks")
        last_tick, previous = tick, value


def _command(command):
    parts = command.split()
    if len(parts) != 5 or parts[0] != "setblock":
        raise ValueError("Cells require absolute, single-block commands")
    return tuple(map(int, parts[1:4])), parts[4]


def fixture_inputs(cell, fixture):
    """Check actual commands and geometry, independent of fixture names/checks."""
    parsed = [_command(c) for c in fixture["setup"]]
    if len(parsed) != 3 or len({p for p, _ in parsed}) != 3:
        raise ValueError("Buffer body must contain exactly three distinct blocks")
    dut = [(p, state) for p, state in parsed if state.startswith("minecraft:repeater[")]
    if len(dut) != 1:
        raise ValueError("Expected one repeater")
    origin, state = dut[0]
    rotation = next((r for r in range(4) if state == f"minecraft:repeater[facing={facing_after('west', r)},delay={cell['setting']}]"), None)
    if rotation is None:
        raise ValueError("Wrong repeater setting or forced state")
    volume = placement(cell, rotation)
    body = {p: s for p, s in volume.items() if s not in ("minecraft:air", "minecraft:stone")}
    def local(position):
        return tuple(a - b for a, b in zip(position, origin))
    if {local(p): s for p, s in parsed} != body:
        raise ValueError("Layout differs from admitted buffer body")
    sx, sz = rotate(-2, 0, rotation)
    source = (sx, 0, sz)
    def value(commands):
        if len(commands) != 1:
            raise ValueError("Only one source command is allowed at a boundary")
        p, s = _command(commands[0])
        if local(p) != source or s not in ("minecraft:air", "minecraft:redstone_block"):
            raise ValueError("Only the declared binary source may change")
        return int(s == "minecraft:redstone_block")
    preparation = fixture.get("prepare", [])
    if len(preparation) != 1:
        raise ValueError("Expected one initial settling stage")
    initial = value(preparation[0]["commands"])
    transitions = [(int(t), value(commands)) for t, commands in sorted(fixture["actions"].items(), key=lambda item: int(item[0]))]
    validate_protocol(cell, initial, transitions, settled_game_ticks=preparation[0]["settle_game_ticks"])
    expected_probes = {"input": ((rotate(-1, 0, rotation)[0], 0, rotate(-1, 0, rotation)[1]), "minecraft:redstone_wire", "power"),
                       "out": ((rotate(1, 0, rotation)[0], 0, rotate(1, 0, rotation)[1]), "minecraft:redstone_wire", "power"),
                       "powered": ((0, 0, 0), "minecraft:repeater", "powered"), "locked": ((0, 0, 0), "minecraft:repeater", "locked")}
    if {p["name"]: (local(p["position"]), p["block"], p["property"]) for p in fixture["probes"]} != expected_probes:
        raise ValueError("Cell probe interface differs")
    return initial, transitions, rotation


def expected_samples(cell, fixture):
    initial, transitions, _ = fixture_inputs(cell, fixture)
    d = cell["timing"]["arcs"][0]["rise"]
    boundaries = [(-1, "baseline_before_stimulus")]
    for t in range(fixture["ticks"] + 1):
        if t > 0 and t in {int(k) for k in fixture["actions"]}:
            boundaries.append((t, "before_action"))
        boundaries.append((t, "after_commands_or_completed_tick"))
    samples = []
    for i, (tick, phase) in enumerate(boundaries):
        a = q = initial
        for t, value in transitions:
            if t < tick or (t == tick and phase == "after_commands_or_completed_tick"):
                a = value
            if t + d <= tick:
                q = value
        samples.append({"relative_game_tick": tick, "phase": phase, "sample_index": i,
                        "values": {"input": 15 * a, "out": 15 * q, "powered": q, "locked": 0}})
    return samples


def audit_commands(commands, fixtures, observed):
    """Match the recorded function order and raw probe/time replies to samples."""
    from .results import parse_probe_response
    from .lab import score
    expected_functions = []
    flat = []
    for fixture in fixtures:
        prefix = "function pdk_lab:" + fixture["id"] + "/"
        expected_functions.append(prefix + "setup")
        expected_functions.extend(prefix + f"prepare_{i}" for i in range(len(fixture.get("prepare", []))))
        expected_functions.append(prefix + "sample")
        for tick in range(fixture["ticks"] + 1):
            if tick in {int(t) for t in fixture["actions"]}:
                if tick > 0:
                    expected_functions.append(prefix + "sample")
                expected_functions.append(prefix + f"action_{tick}")
            expected_functions.append(prefix + "sample")
        flat.extend(observed[fixture["id"]])
    if [r["command"] for r in commands if r["command"].startswith("function pdk_lab:")] != expected_functions:
        raise ValueError("Raw function execution order differs from admitted fixtures")
    replies = [(i, r) for i, r in enumerate(commands) if r["command"] == "data get storage pdk_lab:sample values"]
    if len(replies) != len(flat):
        raise ValueError("Raw probe response count differs")
    for (index, reply), sample in zip(replies, flat):
        if parse_probe_response(reply["response"], list(sample["values"])) != sample["values"]:
            raise ValueError("Raw Minecraft probe reply differs from observation")
        following = commands[index + 1:index + 3]
        if [r["command"] for r in following] != ["execute store result score #time pdk_lab run time query gametime", "scoreboard players get #time pdk_lab"]:
            raise ValueError("Missing raw sample-time query")
        if score(following[1]["response"]) != sample["game_time"]:
            raise ValueError("Raw Minecraft time differs from observation")
    return len(replies)


def build_admission(run):
    from .cell_fixtures import buffer_cases
    from .characterize import load_run
    from .fixtures import compile_functions
    from .event_model import simulate_fixture
    fixtures = {f["id"]: f for f in buffer_cases()}
    definitions = {f"RSBUF{2 * s}": cell_definition(s) for s in range(1, 5)}
    predicted = {}
    for name, fixture in fixtures.items():
        cell = definitions[fixture["experiment"]["cell"]]
        predicted[name] = expected_samples(cell, fixture)
        native = simulate_fixture(fixture)
        if native["initial_pending_events"]:
            raise ValueError("Initialization left pending events")
        compare_samples(predicted[name], native["samples"], name)
    # The fixed compiled setup guarantees empty reserved air and stone support.
    analyses, observed, evidence = load_run(run, fixtures, compile_functions())
    if set(observed) != set(fixtures):
        raise ValueError("Cell admission requires the complete set of 64 fresh fixtures")
    command_rows = [json.loads(line) for line in (ROOT / evidence["run"] / "commands.jsonl").read_text().splitlines()]
    replies_checked = audit_commands(command_rows, list(fixtures.values()), observed)
    records = []
    for name, fixture in fixtures.items():
        readings = compare_samples(predicted[name], observed[name], name)
        records.append({"fixture": name, **fixture["experiment"], "samples": len(observed[name]),
                        "probe_readings": readings, "input_edges": len(fixture["actions"]),
                        "all_samples_match": True, "prediction_sha256": digest(predicted[name])})
    return {"schema_version": 1, "id": "repeater_cells_v1", "technology": technology()["id"],
            "server_sha1": technology()["server"]["sha1"], "status": "admitted_under_explicit_envelope",
            "mapping_eligible": False, "definitions_sha256": digest(list(definitions.values())),
            "model_reference": {"path": "models/repeater-event-v1.json", "sha256": sha(ROOT / "models/repeater-event-v1.json")},
            "implementation": {p: sha(ROOT / p) for p in ("redstone_pdk/cells.py", "redstone_pdk/cell_fixtures.py")},
            "evidence": evidence, "coverage": {"cells": 4, "cases": len(records), "rotations_per_cell": 4,
                "samples": sum(r["samples"] for r in records), "probe_readings": sum(r["probe_readings"] for r in records),
                "input_edges": sum(r["input_edges"] for r in records), "raw_probe_and_time_replies_checked": replies_checked,
                "all_samples_match": True}, "cases": records}


def library(admission):
    return {"schema_version": 1, "id": "java_1_21_1_guarded_buffers_v1", "technology": technology()["id"],
            "admission": {"path": ADMISSION, "content_sha256": digest(admission)},
            "eda_time_scale": {"canonical_unit": "game_tick", "export_unit": "1ns", "game_ticks_per_export_unit": 1,
                               "meaning": "abstract simulation scale; never elapsed wall-clock nanoseconds"},
            "cells": [cell_definition(s) for s in range(1, 5)]}


def write_cells(run):
    from .cell_views import render_views, render_report
    admission = build_admission(run)
    lib = library(admission)
    artifacts = {ADMISSION: json.dumps(admission, indent=2) + "\n", LIBRARY: json.dumps(lib, indent=2) + "\n"}
    artifacts.update(render_views(lib))
    artifacts["docs/repeater-cells.md"] = render_report(lib, admission)
    for relative, content in artifacts.items():
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return [ROOT / p for p in (LIBRARY, ADMISSION, "docs/repeater-cells.md", "views/repeater-buffers/repeater-buffers.lib")]


def validate_cells(*, include_eda=True):
    from .cell_views import render_views, render_report
    if not (ROOT / LIBRARY).exists():
        return []
    try:
        admission = read_json(ROOT / ADMISSION)
        rebuilt = build_admission(admission["evidence"]["run"])
        if admission != rebuilt:
            raise ValueError("Cell admission differs from evidence/implementation reanalysis")
        lib = library(rebuilt)
        if read_json(ROOT / LIBRARY) != lib:
            raise ValueError("Cell definitions differ from admitted definitions")
        views = render_views(lib)
        views["docs/repeater-cells.md"] = render_report(lib, admission)
        for name, expected in views.items():
            if (ROOT / name).read_text(encoding="utf-8") != expected:
                raise ValueError(f"Generated cell view differs: {name}")
        if include_eda:
            report = read_json(ROOT / "validation/cell-eda/report.json")
            if report["pass"] is not True or report["trace_cases"] != admission["coverage"]["cases"]:
                raise ValueError("Missing or failed EDA validation")
            for field in ("inputs_sha256", "evidence_sha256"):
                for name, checksum in report[field].items():
                    path = (ROOT / name).resolve()
                    if not path.is_relative_to(ROOT) or sha(path) != checksum:
                        raise ValueError(f"EDA evidence changed: {name}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f"Invalid cell library: {error}"]
    return []
