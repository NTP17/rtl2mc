"""Checked composition of quiet, feed-forward redstone buffer networks.

This deliberately narrow network model has no short-pulse/lock semantics.
It rejects unsupported inputs and geometry before using an additive delay law.
"""
from collections import deque
import json
import re

from .event_model import VECTORS, SIDES, OPPOSITE, adjacent
from .project import ROOT, read_json, technology
from .model_validation import digest, sha, compare_samples

CONTRACT = "connections/buffer-network-v1.json"


def parse_command(text):
    m = re.fullmatch(r"setblock (-?\d+) (-?\d+) (-?\d+) minecraft:([a-z_]+)(?:\[([^]]+)\])?", text)
    if not m:
        raise ValueError("Network commands must be absolute single-block placements")
    pos = tuple(map(int, m.group(1, 2, 3)))
    if pos[1] != 80:
        raise ValueError("Only the horizontal lab layer at y=80 is admitted")
    props = dict(p.split("=") for p in m[5].split(",")) if m[5] else {}
    if m[4] not in ("redstone_wire", "repeater", "comparator", "air", "redstone_block"):
        raise ValueError("Unsupported network block")
    allowed = {"repeater": {"facing", "delay"}, "comparator": {"facing", "mode"}}.get(m[4], set())
    if set(props) != allowed:
        raise ValueError("Missing static properties or forced block state")
    if m[4] in ("repeater", "comparator") and props["facing"] not in VECTORS:
        raise ValueError("Invalid facing")
    if m[4] == "repeater" and props["delay"] not in ("1", "2", "3", "4"):
        raise ValueError("Invalid repeater delay")
    if m[4] == "comparator" and props["mode"] != "compare":
        raise ValueError("Only the binary compare-mode source driver is admitted")
    return pos, {"kind": m[4], **props}


def extract_network(fixture, *, allow_attenuated_off=False):
    blocks = {}
    for command in fixture["setup"]:
        pos, block = parse_command(command)
        if pos in blocks or block["kind"] not in ("redstone_wire", "repeater", "comparator"):
            raise ValueError("Duplicate body block or unsupported setup source")
        blocks[pos] = block
    prep = fixture.get("prepare", [])
    if len(prep) != 1 or len(prep[0]["commands"]) != 1:
        raise ValueError("One explicit source and settling stage is required")
    source, initial_block = parse_command(prep[0]["commands"][0])
    if source in blocks or initial_block["kind"] not in ("air", "redstone_block"):
        raise ValueError("Initialization must toggle the external source port")
    initial = int(initial_block["kind"] == "redstone_block")
    transitions = []
    for tick, commands in fixture["actions"].items():
        if str(int(tick)) != str(tick) or int(tick) < 0 or len(commands) != 1:
            raise ValueError("Source changes require distinct integer game ticks")
        pos, block = parse_command(commands[0])
        if pos != source or block["kind"] not in ("air", "redstone_block"):
            raise ValueError("Only one fixed external binary source may change")
        transitions.append((int(tick), int(block["kind"] == "redstone_block")))
    transitions.sort()
    low, high = fixture["lab_bounds"]
    if list(low) != [0, 79, -16] or list(high) != [63, 84, 47]:
        raise ValueError("Use the reserved, isolated connection lab volume")
    if any(not (low[0]+2 <= p[0] <= high[0]-2 and low[2]+2 <= p[2] <= high[2]-2 and low[1] == 79 and high[1] >= 82)
           for p in [source, *blocks]):
        raise ValueError("Network does not have the required empty outer margin and support")
    wires = {p for p, b in blocks.items() if b["kind"] == "redstone_wire"}
    diodes = {p: b for p, b in blocks.items() if b["kind"] != "redstone_wire"}
    if not diodes:
        raise ValueError("Expected at least one receiving cell")
    if len(diodes) > 5:
        raise ValueError("More than five diodes is outside this measured profile")
    for p, b in diodes.items():
        if adjacent(p, b["facing"]) not in wires or adjacent(p, OPPOSITE[b["facing"]]) not in wires:
            raise ValueError("Every diode needs separate rear and output dust ports")
        if any(adjacent(p, side) in blocks or adjacent(p, side) == source for side in SIDES[b["facing"]]):
            raise ValueError("Cell locking sides must remain empty")
    nets, wire_net = [], {}
    unseen = set(wires)
    while unseen:
        component, todo = set(), [min(unseen)]
        while todo:
            p = todo.pop()
            if p in component:
                continue
            component.add(p)
            todo.extend(adjacent(p, d) for d in VECTORS if adjacent(p, d) in wires and adjacent(p, d) not in component)
        unseen -= component
        edge_count = sum(adjacent(p, d) in component for p in component for d in VECTORS) // 2
        if edge_count != len(component)-1:
            raise ValueError("Dust loops are outside the tree-routing profile")
        if len(component) > (16 if allow_attenuated_off else 15):
            raise ValueError("At most 15 dust blocks are admitted per net")
        drivers = {}
        for p in component:
            for direction in VECTORS:
                other = adjacent(p, direction)
                if other == source:
                    drivers.setdefault("source", []).append(p)
                elif other in diodes and adjacent(other, OPPOSITE[diodes[other]["facing"]]) == p:
                    drivers.setdefault(other, []).append(p)
        if len(drivers) != 1 or len(next(iter(drivers.values()), [])) != 1:
            raise ValueError("Each dust net needs exactly one driver and one driven endpoint")
        driver, seeds = next(iter(drivers.items()))
        distance, queue = {seeds[0]: 0}, deque(seeds)
        while queue:
            p = queue.popleft()
            for direction in VECTORS:
                other = adjacent(p, direction)
                if other in component and other not in distance:
                    distance[other] = distance[p]+1
                    queue.append(other)
        sinks = [p for p, b in diodes.items() if adjacent(p, b["facing"]) in component]
        if len(sinks) > 3:
            raise ValueError("At most three receiving repeaters are admitted per net")
        net = {"driver": driver, "wires": sorted(component), "distance": distance, "sinks": sorted(sinks)}
        nets.append(net)
        wire_net.update({p: net for p in component})
    todo = dict(diodes)
    nodes, by_position = [], {}
    while todo:
        progress = False
        for pos, block in list(sorted(todo.items())):
            rear = adjacent(pos, block["facing"])
            net = wire_net[rear]
            driver = net["driver"]
            if driver != "source" and driver not in by_position:
                continue
            gain = max(0, 15-net["distance"][rear])
            if not gain and not allow_attenuated_off:
                raise ValueError("Signal reaches zero before a receiver; insert regeneration")
            if block["kind"] == "comparator" and (driver != "source" or gain != 15 or len(net["wires"]) != 1):
                raise ValueError("Comparator is allowed only as a binary source driver with one input dust")
            delay = 2 if block["kind"] == "comparator" else 2*int(block["delay"])
            parent = by_position.get(driver)
            node = {"id": f"n{len(nodes)}", "position": list(pos), "kind": block["kind"], "facing": block["facing"],
                    "delay": delay, "parent": parent["id"] if parent else "source", "input_high_strength": gain,
                    "arrival_delay": delay+(parent["arrival_delay"] if parent else 0),
                    "live": bool(gain and (parent["live"] if parent else True))}
            nodes.append(node); by_position[pos] = node; del todo[pos]; progress = True
        if not progress:
            raise ValueError("Feedback or a component detached from the source is not admitted")
    if sum(n["parent"] == "source" for n in nodes) != 1:
        raise ValueError("Exactly one source-driver diode is admitted")
    minimum = max(n["delay"] for n in nodes)+1
    settle = 20+max(n["arrival_delay"] for n in nodes)
    if type(prep[0]["settle_game_ticks"]) is not int or prep[0]["settle_game_ticks"] < settle:
        raise ValueError(f"Initialization requires at least {settle} game ticks")
    previous, last = initial, None
    for tick, value in transitions:
        if previous == value or (last is not None and tick-last < minimum):
            raise ValueError(f"Input transitions must alternate with both dwells >= {minimum} game ticks")
        last, previous = tick, value
    projected_nets = []
    for net in nets:
        driver = net["driver"]
        projected_nets.append({"driver": "source" if driver == "source" else by_position[driver]["id"],
            "wires": [{"position": list(p), "high_strength": max(0, 15-net["distance"][p])} for p in net["wires"]],
            "sinks": [by_position[p]["id"] for p in net["sinks"]]})
    return {"nodes": nodes, "nets": projected_nets, "source": list(source), "initial": initial,
            "transitions": [list(t) for t in transitions], "minimum_dwell": minimum, "initial_settle": settle,
            "reserved_box": {"min": list(low), "max": list(high)}}


def predict_fixture(fixture, *, allow_attenuated_off=False):
    graph = extract_network(fixture, allow_attenuated_off=allow_attenuated_off)
    nodes = {n["id"]: n for n in graph["nodes"]}
    positions = {tuple(n["position"]): n for n in nodes.values()}
    wires = {tuple(w["position"]): (net["driver"], w["high_strength"]) for net in graph["nets"] for w in net["wires"]}
    def bit(driver, tick, phase):
        if driver == "source":
            delay, live = 0, True
        else:
            delay, live = nodes[driver]["arrival_delay"], nodes[driver]["live"]
        if not live:
            return 0
        value = graph["initial"]
        for t, v in graph["transitions"]:
            if t+delay < tick or (t+delay == tick and (delay > 0 or phase == "after_commands_or_completed_tick")):
                value = v
        return value
    bounds = [(-1, "baseline_before_stimulus")]
    actions = {int(t) for t in fixture["actions"]}
    for t in range(fixture["ticks"]+1):
        if t and t in actions:
            bounds.append((t, "before_action"))
        bounds.append((t, "after_commands_or_completed_tick"))
    samples = []
    for index, (tick, phase) in enumerate(bounds):
        values = {}
        for p in fixture["probes"]:
            pos, prop = tuple(p["position"]), p["property"]
            if pos in wires and p["block"] == "minecraft:redstone_wire" and prop == "power":
                driver, gain = wires[pos]
                value = gain*bit(driver, tick, phase)
            elif pos in positions and p["block"] == "minecraft:"+positions[pos]["kind"] and prop in ("locked", "powered"):
                value = 0 if prop == "locked" else bit(positions[pos]["id"], tick, phase)
            else:
                raise ValueError("Probe is outside the checked network interface")
            values[p["name"]] = value
        samples.append({"relative_game_tick": tick, "phase": phase, "sample_index": index, "values": values})
    return {"graph": graph, "samples": samples}


def build_contract(run):
    from collections import Counter
    from .connection_fixtures import connection_cases
    from .characterize import load_run
    from .fixtures import compile_functions
    from .cells import audit_commands
    from .event_model import simulate_fixture
    fixtures = {f["id"]: f for f in connection_cases()}
    _, observed, evidence = load_run(run, fixtures, compile_functions())
    if set(observed) != set(fixtures):
        raise ValueError("Require the complete 204-case connection run")
    commands = [json.loads(s) for s in (ROOT / evidence["run"] / "commands.jsonl").read_text().splitlines()]
    replies = audit_commands(commands, list(fixtures.values()), observed)
    records = []
    for name, fixture in fixtures.items():
        predicted = predict_fixture(fixture, allow_attenuated_off=True)
        readings = compare_samples(predicted["samples"], observed[name], name)
        rejection = None
        try:
            extract_network(fixture)
        except ValueError as error:
            rejection = str(error)
        if (rejection is None) != fixture["experiment"]["admission_expected"]:
            raise ValueError(f"Unexpected connection admission result: {name}")
        native_match = False
        try:
            native = simulate_fixture(fixture)
        except ValueError:
            # The old event model deliberately rejects bends/branches/extra loads.
            if fixture["experiment"]["family"] != "routing_load":
                raise
        else:
            if native["initial_pending_events"]:
                raise ValueError("Initial event queue is not empty")
            compare_samples(predicted["samples"], native["samples"], name)
            native_match = True
        records.append({"fixture": name, **fixture["experiment"], "admitted": rejection is None,
                        "rejection": rejection, "samples": len(observed[name]), "probe_readings": readings,
                        "prediction_sha256": digest(predicted["samples"]), "graph": predicted["graph"],
                        "native_model_match": native_match, "all_samples_match": True})
    return {"schema_version": 1, "id": "buffer_network_v1", "technology": technology()["id"],
            "server_sha1": technology()["server"]["sha1"], "status": "measured_checked_composition",
            "mapping_eligible": False, "checked_composition_eligible": True,
            "scope": "Only the admitted catalog geometries, under the stated protocol; arbitrary tree routing remains a candidate model",
            "implementation": {p: sha(ROOT / p) for p in ("redstone_pdk/connections.py", "redstone_pdk/connection_fixtures.py")},
            "primitive_model_sha256": sha(ROOT / "models/repeater-event-v1.json"), "evidence": evidence,
            "coverage": {"cases": len(records), "admitted": sum(r["admitted"] for r in records),
                "negative_controls": sum(not r["admitted"] for r in records),
                "samples": sum(r["samples"] for r in records), "probe_readings": sum(r["probe_readings"] for r in records),
                "source_transitions": sum(len(f["actions"]) for f in fixtures.values()),
                "families": dict(sorted(Counter(r["family"] for r in records).items())),
                "native_model_matches": sum(r["native_model_match"] for r in records),
                "raw_probe_and_time_replies_checked": replies, "all_samples_match": True},
            "rules": {"support": "stone at y=79; no external power; remaining reserved volume air except declared body/source",
                "plane": "static y=80 layout, empty locking sides and above; no vertical routing or diagonal shortcuts",
                "nets": "single-driver dust trees, up to 15 dust blocks and three receiver loads; no loops or feedback",
                "input_levels": "source and comparator helper: 0/15; receiving repeaters: 0 versus 1..15",
                "routing": "wire strength is 15 minus distance from first driven dust; every receiver must get at least 1",
                "time": "1 simulation ns represents 1 game tick, sampled after all boundary work",
                "protocol": "initial hold >= 20 + longest path delay; subsequent high AND low dwells >= max cell delay + 1; integer ticks",
                "environment": "pinned vanilla build, all chunks loaded, no scheduled-tick backlog or external interaction",
                "history_argument": "Each input stays stable past every cell's due event. The output reproduces its parent's legal pulse with D delay. Induction over the acyclic graph preserves dwell widths and adds delays. This is an engineering argument, not a formal proof of the engine."},
            "cases": records}


def write_connections(run):
    from .connection_views import render_views, render_report
    contract = build_contract(run)
    artifacts = {CONTRACT: json.dumps(contract, indent=2) + "\n"}
    artifacts.update(render_views(contract))
    artifacts["docs/buffer-networks.md"] = render_report(contract)
    for name, content in artifacts.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return [ROOT / CONTRACT, ROOT / "docs/buffer-networks.md", ROOT / "views/buffer-network/manifest.json"]


def validate_connections(*, include_eda=True):
    from .connection_views import render_views, render_report
    if not (ROOT / CONTRACT).exists():
        return []
    try:
        contract = read_json(ROOT / CONTRACT)
        if contract != build_contract(contract["evidence"]["run"]):
            raise ValueError("Connection contract differs from raw evidence reanalysis")
        expected = render_views(contract)
        expected["docs/buffer-networks.md"] = render_report(contract)
        for name, value in expected.items():
            if (ROOT / name).read_text(encoding="utf-8") != value:
                raise ValueError(f"Generated connection view differs: {name}")
        if include_eda:
            report = read_json(ROOT / "validation/network-eda/report.json")
            if report["pass"] is not True or report["trace_cases"] != contract["coverage"]["admitted"]:
                raise ValueError("Incomplete connection EDA validation")
            for field in ("inputs_sha256", "evidence_sha256"):
                for name, checksum in report[field].items():
                    p = (ROOT / name).resolve()
                    if not p.is_relative_to(ROOT) or sha(p) != checksum:
                        raise ValueError(f"Network EDA evidence changed: {name}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f"Invalid connection library: {error}"]
    return []
