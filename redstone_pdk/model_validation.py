"""Reproduce the bounded primitive-model comparison against saved game evidence."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from .event_model import simulate_fixture
from .project import ROOT, read_json, technology


DEFAULT_RUNS = ["results/20260910T144324Z-6f9b71", "results/20260910T144644Z-f26f65", "results/20260910T151115Z-97846b"]
EVENT_RUN = "results/20260910T162009Z-trace-c0f92a"
MODEL_PATH = "models/repeater-event-v1.json"
LIMITATIONS = [
    "Only static blocks in one horizontal layer on rigid support, with every represented chunk loaded and no scheduled-tick backlog.",
    "Dust runs are straight and have at most one driver; each driver may affect at most one timing-sensitive receiving diode. Junctions, multiple drivers, independent fanout ties, and feedback are rejected.",
    "Dust strength is resolved synchronously at each command or diode update. Intermediate dust update order, strong/weak powering through solids, vertical wiring, and chunk lifecycle are not modeled.",
    "Comparator helpers are restricted to compare mode, binary rear input, and no side inputs. This is not a complete comparator primitive model.",
    "Only fixed source positions may change during simulation. Moving blocks, parameter changes, forced power/lock properties, and unsupported block types are rejected.",
    "All 772 measured repeater fixtures match at sampled boundaries; internal scheduled-event behavior is directly checked only for the 96 recorded lock-sequence fixtures.",
    "Primitive model validation does not admit arbitrary cells or timing arcs. The separate guarded-buffer admission is documented in docs/repeater-cells.md.",
]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_run(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to((ROOT / "results").resolve()):
        raise ValueError("Model evidence must be inside results/")
    return path


def compare_samples(predicted, observed, fixture):
    if len(predicted) != len(observed):
        raise ValueError(f"{fixture}: sample count mismatch")
    readings = 0
    for a, b in zip(predicted, observed):
        for key in ("relative_game_tick", "phase", "sample_index", "values"):
            if a[key] != b[key]:
                raise ValueError(f"{fixture}: model mismatch at tick {b['relative_game_tick']}, phase {b['phase']}: {key}: {a[key]} != {b[key]}")
        readings += len(b["values"])
    return readings


def event_vectors(prediction, fixture):
    dut = tuple(next(p["position"] for p in fixture["probes"] if p["name"] == "powered"))
    sides = [tuple(p["position"]) for p in fixture["probes"] if p["property"] == "powered" and tuple(p["position"]) != dut]
    if len(sides) != 1:
        raise ValueError("Recorded engine trace expects exactly one side driver")
    roles = {dut: "dut", sides[0]: "side"}
    enqueues, dispatches = [], []
    for event in prediction["events"]:
        position = tuple(event["position"])
        kind = event["event"]
        if kind == "enqueue":
            enqueues.append({"tick": event["tick"], "block": roles[position], "due": event["due"], "priority": event["priority"]})
        elif kind == "dispatch":
            dispatches.append({"tick": event["tick"], "block": roles[position], "priority": event["priority"],
                               "before": event["powered"], "after": event["powered"],
                               "locked": bool(event["live_lock"]), "input": None})
        elif kind == "input_read":
            dispatches[-1]["input"] = event["value"]
        elif kind == "dispatch_end":
            dispatches[-1]["after"] = event["powered"]
    return enqueues, dispatches


def build_model_contract(runs=DEFAULT_RUNS, event_run=EVENT_RUN):
    from .fixtures import cases
    fixtures, origins, predictions, evidence = {}, {}, {}, []
    # Predictions depend only on physical setup, preparation, actions, probes,
    # and duration. Finish them before reading any observed samples/events.
    for value in runs:
        run = resolve_run(value)
        metadata = read_json(run / "metadata.json")
        if metadata["technology"] != technology()["id"] or metadata["server_sha1"] != technology()["server"]["sha1"]:
            raise ValueError("Wrong vanilla technology/build in model evidence")
        for fixture in read_json(run / "fixtures.json"):
            name = fixture["id"]
            if name in fixtures:
                raise ValueError(f"Duplicate model fixture: {name}")
            fixtures[name] = fixture
            origins[name] = run.relative_to(ROOT).as_posix()
            predictions[name] = simulate_fixture(fixture)
        evidence.append({"run": run.relative_to(ROOT).as_posix(), "files": {name: sha(run / name) for name in
                         ("metadata.json", "fixtures.json", "observations.jsonl", "commands.jsonl", "compiled-functions.json")}})
    expected = {f["id"]: json.loads(json.dumps(f)) for f in cases("repeater") + cases("repeater_broad")}
    if fixtures != expected:
        raise ValueError("Model validation requires exactly the 772 preserved repeater fixtures")
    # Reuse the established evidence admission checks: hashes, source snapshots,
    # raw command replies, probe domains, sample coverage, and declared checks.
    from .characterize import build_contract
    from .characterize_broad import build_broad_contract
    original_runs = sorted({origins[name] for name in fixtures if name in {f["id"] for f in cases("repeater")}})
    broad_runs = sorted(set(origins.values()) - set(original_runs))
    original = build_contract(original_runs)
    broad = build_broad_contract(broad_runs)
    observed = defaultdict(list)
    for item in evidence:
        with (resolve_run(item["run"]) / "observations.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                observed[row["case"]].append(row)
    if set(observed) != set(fixtures):
        raise ValueError("Observed model corpus differs from its fixture list")
    results, families = [], {}
    for name, fixture in fixtures.items():
        prediction = predictions[name]
        readings = compare_samples(prediction["samples"], observed[name], name)
        family = fixture["experiment"]["family"]
        counts = Counter(e["event"] for e in prediction["events"])
        entry = {"fixture": name, "family": family, "run": origins[name], "samples": len(observed[name]),
                 "probe_readings": readings, "all_samples_match": True,
                 "accepted_events": counts["enqueue"], "dispatched_events": counts["dispatch"],
                 "prediction_sha256": digest(prediction)}
        results.append(entry)
        bucket = families.setdefault(family, {"cases": 0, "samples": 0, "probe_readings": 0})
        bucket["cases"] += 1; bucket["samples"] += entry["samples"]; bucket["probe_readings"] += readings
    from .trace_analysis import verify_run
    recorded = verify_run(resolve_run(event_run))
    for case in recorded["cases"]:
        name = case["fixture"]
        enqueues, dispatches = event_vectors(predictions[name], fixtures[name])
        if enqueues != case["observed_enqueues"] or dispatches != case["observed_dispatches"]:
            raise ValueError(f"{name}: native model differs from recorded internal events")
    implementation = ["redstone_pdk/event_model.py", "redstone_pdk/model_validation.py"]
    return {
        "schema_version": 1, "id": "repeater_event_model_v1", "component": "repeater",
        "technology": technology()["id"], "server_sha1": technology()["server"]["sha1"],
        "status": "bounded_executable_model_validated", "mapping_eligible": False,
        "time_unit": "game_tick", "entry_point": "redstone_pdk.event_model.simulate_fixture",
        "implementation": {path: sha(ROOT / path) for path in implementation},
        "model_inputs": ["setup block commands", "preparation commands and settling ticks", "ordered source commands", "physical probe definitions", "simulation duration"],
        "state": ["block position, type and facing", "repeater setting and powered state", "live eligible side signals", "dust signal strength", "comparator helper output", "per-chunk scheduled queues", "pending-event deduplication", "events remaining in the current tick", "global scheduling sequence"],
        "coverage": {"cases": len(results), "samples": sum(r["samples"] for r in results),
                     "probe_readings": sum(r["probe_readings"] for r in results), "all_samples_match": True,
                     "engine_cases": recorded["case_count"], "engine_scheduled_events": recorded["accepted_and_dispatched_events"],
                     "all_recorded_scheduled_events_match": True},
        "families": families, "limitations": LIMITATIONS, "evidence": evidence,
        "admitted_vanilla_contracts": {"original_sha256": digest(original), "broader_sha256": digest(broad)},
        "event_evidence": {"run": recorded["run"], "files": recorded["evidence_sha256"]},
        "cases": results,
    }


def markdown(contract):
    c = contract["coverage"]
    lines = ["# Executable repeater event model", "",
             f"The model matches **{c['cases']}/{c['cases']} saved repeater fixtures**, **{c['samples']:,} sample points**, and **{c['probe_readings']:,} individual probe readings**.",
             f"Its accepted event schedule and dispatch/lock/input/output behavior also match all **{c['engine_scheduled_events']} recorded scheduled events** across the {c['engine_cases']} instrumented lock fixtures.", "",
             "The simulator reads block layouts, facing, delay settings, preparation, and ordered source commands. It does not read fixture names, experiment labels, expected outputs, or observations. Initial state is produced by executing setup and settling, including preasserted locks.", "",
             "## Coverage", "", "| Family | Fixtures | Sample points | Probe readings |", "|---|---:|---:|---:|"]
    for name, counts in contract["families"].items():
        lines.append(f"| {name} | {counts['cases']} | {counts['samples']:,} | {counts['probe_readings']:,} |")
    lines += ["", "## Mechanism", "",
              "Each repeater computes its rear input and eligible side locks from neighboring blocks. Its front neighbor determines whether an ordinary scheduled event gets a priority boost. Off-to-on pending ticks, short-pulse return ticks, and on-to-off ticks retain their distinct priority rules.", "",
              "Scheduled events carry a due game tick, priority, and scheduling sequence. A per-position/block pending set suppresses duplicate queue entries. The scheduler collects work from loaded chunk queues, then removes each event from the current tick's remaining work before dispatch. A locked scheduled event is consumed; unlock can schedule a fresh delay only when the old event is no longer waiting to run.", "",
              "This explains the brief-lock polarity difference and the 12 comparator/repeater driver mismatches through shared rules. Neither case names nor empirical delay exceptions are used. Wire attenuation is calculated from physical dust runs, including the 0–15 strength sweep.", "",
              "## Operating envelope", ""]
    lines += ["- " + limitation for limitation in contract["limitations"]]
    lines += ["", "The model reports UnsupportedCircuit for the explicitly unsupported arrangements. A layout that fits the supported representation still has experimental status outside the measured corpus; this report does not certify every possible history or composition.", "",
              "## Reproduce", "", "Rebuild the report and attach its hashed native model reference:", "", "```powershell", "python pdk.py model-repeater", "python pdk.py validate", "```", "",
              "The native [model contract](../models/repeater-event-v1.json) records implementation/evidence hashes and per-fixture prediction digests. Project validation reruns the comparison rather than trusting saved pass flags.", "",
              "For an individual fixture, use simulate_fixture with a physical fixture dictionary; the result contains samples, a predicted internal event trace, and any events pending at the measurement origin. Those predicted internal events are distinct from the raw instrumented records.", "",
              "Implementation: [event_model.py](../redstone_pdk/event_model.py). Evidence comparison: [model_validation.py](../redstone_pdk/model_validation.py). The original [engine confirmation](repeater-lock-order-confirmation.md) remains independently reproducible.", "",
              "All validation here uses saved evidence. No new Minecraft measurements were needed for step 2. The subsequent guarded-buffer cell admission and initial Liberty/SDF views use fresh measurements; see [cell admission](repeater-cells.md).", ""]
    return "\n".join(lines)


def write_model_contract():
    contract = build_model_contract()
    target = ROOT / MODEL_PATH
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    report = ROOT / "docs/repeater-event-model.md"
    report.write_text(markdown(contract), encoding="utf-8")
    component_path = ROOT / "components/repeater.json"
    component = read_json(component_path)
    component["evidence"]["executable_models"] = [{"path": MODEL_PATH, "sha256": sha(target)}]
    component["behavior"]["description"] = "Directional signal regeneration with configurable delay and physical side locking. A native event model reproduces all 772 measured repeater fixtures and the recorded scheduled events in 96 lock-sequence fixtures."
    component["behavior"]["limitations"] = list(LIMITATIONS)
    component["timing"]["uncharacterized"] = ["General primitive timing arcs; guarded buffer cells have a separate admission", "Behavior outside the executable model's declared physical and update-order envelope", "Arbitrary histories, composition, lifecycle, and unsupported powering modes"]
    component_path.write_text(json.dumps(component, indent=2) + "\n", encoding="utf-8")
    return target, report
