"""Validate recorded engine events independently of the measurement summary."""
from collections import defaultdict
import json
from pathlib import Path
import re

from . import lab
from .engine_trace import BASELINE
from .project import ROOT, read_json
from .results import analyze
from tools.investigate_lock_order import LockReplay


def require(condition, message):
    if not condition:
        raise ValueError(message)


def power(state):
    match = re.search(r"(?:\[|,)powered=(true|false)(?:,|\])", state)
    require(match is not None, f"Missing powered state: {state}")
    return int(match[1] == "true")


def predicted_events(case):
    replay = LockReplay(case).run()
    queue = []
    dispatches = []
    for event in replay.events:
        if event["event"] == "enqueue":
            queue.append({key: event[key] for key in ("tick", "block", "due", "priority")})
        elif event["event"] == "dispatch":
            dispatches.append({"tick": event["tick"], "block": event["block"], "priority": event["priority"],
                               "before": event["powered"], "after": event["powered"],
                               "locked": bool(event["live_lock"]), "input": event["input"] * 15})
        elif event["event"] == "output_change":
            require(dispatches[-1]["block"] == event["block"], "Unexpected replay output actor")
            dispatches[-1]["after"] = event["value"]
    return replay, queue, dispatches


def verify_case(case, events, samples, baseline):
    name = case["id"]
    require(events and events[0]["event"] == "case_begin" and events[-1]["event"] == "case_end", f"{name}: incomplete markers")
    require(sum(e["event"] == "case_begin" for e in events) == 1 and sum(e["event"] == "case_end" for e in events) == 1, f"{name}: duplicate markers")
    require(events[0]["tick"] == 0 and events[-1]["tick"] == case["ticks"], f"{name}: marker tick mismatch")
    require(samples and events[0]["game_time"] == samples[0]["game_time"], f"{name}: events and samples have different time origins")
    require(events[-1]["pending_events_remaining"] == 0, f"{name}: queued events remain at end")
    for previous, current in zip(events, events[1:]):
        require(previous["sequence"] < current["sequence"] and previous["tick"] <= current["tick"], f"{name}: event order invalid")
    require(all(e["game_time"] - e["tick"] == events[0]["game_time"] for e in events), f"{name}: event time inconsistency")
    replay, predicted_queue, predicted_dispatches = predicted_events(case)
    requests, accepted = {}, {}
    queue, dispatches = [], []
    group = None
    consumed = set()
    remaining_reads = []
    for event in events:
        kind = event["event"]
        if kind == "logger_error":
            raise ValueError(f"{name}: logger error")
        if kind in ("enqueue_request", "enqueue_accepted"):
            key = event["sub_tick_order"]
            fields = {k: event[k] for k in ("block", "due_tick", "priority", "sub_tick_order")}
            require(event["due_game_time"] - event["due_tick"] == events[0]["game_time"], f"{name}: due time inconsistency")
            if kind == "enqueue_request":
                require(key not in requests, f"{name}: repeated scheduling sequence")
                requests[key] = fields
            else:
                require(key in requests and requests[key] == fields and key not in accepted, f"{name}: acceptance has no matching request")
                accepted[key] = fields
                queue.append({"tick": event["tick"], "block": event["block"], "due": event["due_tick"], "priority": event["priority"]})
        elif kind == "dispatch_begin":
            key = event["sub_tick_order"]
            require(group is None and key in accepted and key not in consumed, f"{name}: dispatch is unpaired or nested")
            require(all(event[k] == v for k, v in accepted[key].items()), f"{name}: queued event changed before dispatch")
            require(event["tick"] == event["due_tick"], f"{name}: overdue/early dispatch")
            consumed.add(key)
            group = {"start": event, "entries": [], "exits": [], "locks": [], "inputs": []}
        elif kind == "dispatch_end":
            require(group is not None and group["start"]["sub_tick_order"] == event["sub_tick_order"], f"{name}: dispatch end mismatch")
            require(len(group["entries"]) == 1 and len(group["exits"]) == 1, f"{name}: missing block tick state")
            start = group["start"]
            block = start["block"]
            needs_lock = block == "dut" or case["experiment"]["driver"] == "repeater"
            require(len(group["locks"]) == int(needs_lock), f"{name}: missing/duplicate scheduled lock read")
            locked = group["locks"][0]["locked"] if needs_lock else False
            before, after = power(group["entries"][0]["state"]), power(group["exits"][0]["state"])
            if locked:
                require(before == after and not group["inputs"], f"{name}: locked tick did not return without reading input/changing output")
            else:
                require(group["inputs"], f"{name}: unlocked tick has no input read")
            dispatches.append({"tick": start["tick"], "block": block, "priority": start["priority"],
                               "before": before, "after": after, "locked": locked,
                               "input": None if locked else group["inputs"][0]["value"]})
            group = None
        elif kind in ("block_tick_enter", "block_tick_exit"):
            require(group is not None and event["block"] == group["start"]["block"], f"{name}: block tick has no recorded dispatch")
            group["entries" if kind == "block_tick_enter" else "exits"].append(event)
        elif kind == "lock_read" and event["site"] == "scheduled_tick":
            require(group is not None and event["block"] == group["start"]["block"], f"{name}: lock read has no dispatch")
            group["locks"].append(event)
        elif kind == "input_read" and group and event["block"] == group["start"]["block"]:
            group["inputs"].append(event)
        elif kind == "will_tick_this_tick":
            remaining_reads.append({"tick": event["tick"], "block": event["block"], "value": event["value"]})
    require(group is None and set(accepted) == consumed, f"{name}: accepted/consumed event mismatch")
    require(events[-1]["ignored_duplicate_requests"] == len(requests) - len(accepted), f"{name}: duplicate request accounting mismatch")
    require(queue == predicted_queue, f"{name}: observed enqueue schedule differs from replay")
    expected_dispatches = [{**e, "input": None if e["locked"] else e["input"]} for e in predicted_dispatches]
    require(dispatches == expected_dispatches, f"{name}: observed dispatch/lock/output sequence differs from replay")

    def sample_map(rows):
        keys = [(r["relative_game_tick"], r["phase"]) for r in rows]
        require(len(keys) == len(set(keys)), f"{name}: duplicate sample")
        return {key: row["values"] for key, row in zip(keys, rows)}
    observed, reference = sample_map(samples), sample_map(baseline)
    require(observed == reference == replay.samples, f"{name}: sample values/coverage differ from vanilla or replay")
    numeric_case = {**case, "actions": {int(k): v for k, v in case["actions"].items()}}
    require(analyze(numeric_case, samples)["pass"], f"{name}: declared fixture checks fail")
    return {"fixture": name, "experiment": case["experiment"], "sample_count": len(samples),
            "engine_event_count": len(events), "accepted_events": len(accepted),
            "ignored_duplicate_requests": len(requests) - len(accepted),
            "discarded_locked_dut_ticks": sum(e["block"] == "dut" and e["locked"] for e in dispatches),
            "sampled_vanilla_match": True, "engine_replay_match": True,
            "observed_enqueues": queue, "observed_dispatches": dispatches,
            "observed_remaining_tick_queries": remaining_reads}


def verify_run(run):
    run = Path(run).resolve()
    metadata = read_json(run / "metadata.json")
    require(metadata["technology"] == "java-1.21.1-vanilla-instrumented", "Wrong instrumented technology")
    require(metadata["suite"] in ("lock_order_minimal", "lock_order_96"), "Unknown instrumented suite")
    require(metadata["server_sha1"] == "59353fb40c36d304f2035d51e7d6e6baa98dc05c", "Wrong server wrapper")
    require(metadata["vanilla_observations_sha256"] == lab.file_hash(BASELINE / "observations.jsonl", "sha256"), "Vanilla reference hash mismatch")
    build = metadata["instrumentation"]["build"]
    require(build["engine_sha256"] == "c301de10f575027d13eac18c7f34409d60648cf56a35d566aa1f530ff617840a", "Wrong engine build")
    require(build == read_json(run / "instrumentation-source/build.json"), "Build manifest snapshot differs")
    for name, digest in build["artifacts"].items():
        require(lab.file_hash(run / "instrumentation-source" / name, "sha256") == digest, "Logger artifact hash mismatch")
    for path, digest in build["sources"].items():
        snapshot = run / "instrumentation-source" / Path(path).name
        require(snapshot.exists() and lab.file_hash(snapshot, "sha256") == digest, f"Build source snapshot mismatch: {path}")
    transforms = metadata["instrumentation"]["transforms"]
    require(set(transforms) == set(build["class_sha256"]), "Missing transformation audit")
    for name, row in transforms.items():
        require(row["original_sha256"] == build["class_sha256"][name] and row["hooks"] == build["expected_hooks"][name], "Transformation audit mismatch")
    fixtures = read_json(run / "fixtures.json")
    require([f["id"] for f in fixtures] == metadata["fixtures"], "Fixture list mismatch")
    require(len(fixtures) == (2 if metadata["suite"] == "lock_order_minimal" else 96), "Incomplete fixture suite")
    baseline_fixtures = {f["id"]: f for f in read_json(BASELINE / "fixtures.json")}
    expected = ({"repeater_lockseq_d2_q0_north_repeater_release_at_due", "repeater_lockseq_d2_q0_north_comparator_release_at_due"}
                if metadata["suite"] == "lock_order_minimal" else
                {name for name, f in baseline_fixtures.items() if f.get("experiment", {}).get("family") == "lock_sequence"})
    require(len(metadata["fixtures"]) == len(set(metadata["fixtures"])) and set(metadata["fixtures"]) == expected, "Missing/duplicate expected fixture")
    for fixture in fixtures:
        require(fixture == baseline_fixtures[fixture["id"]], "Fixture changed from vanilla baseline")
    def groups(path, key="case"):
        result = defaultdict(list)
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                result[row[key]].append(row)
        return result
    events, samples, baseline = groups(run / "engine-events.jsonl"), groups(run / "observations.jsonl"), groups(BASELINE / "observations.jsonl")
    require(set(events) == set(samples) == set(metadata["fixtures"]), "Missing/extra recorded fixture")
    require(all(e.get("run") == run.name for rows in events.values() for e in rows), "Engine log belongs to a different run")
    results = [verify_case(f, events[f["id"]], samples[f["id"]], baseline[f["id"]]) for f in fixtures]
    comparisons = []
    for case in fixtures:
        name = case["id"]
        if "_comparator_" not in name:
            continue
        reference = name.replace("_comparator_", "_repeater_")
        a, b = samples[name], samples[reference]
        same_inputs = [(r["relative_game_tick"], r["phase"], r["values"]["input"], r["values"]["locked"]) for r in a] == [(r["relative_game_tick"], r["phase"], r["values"]["input"], r["values"]["locked"]) for r in b]
        same_output = [r["values"]["powered"] for r in a] == [r["values"]["powered"] for r in b]
        require(same_inputs, "Paired sampled inputs differ")
        comparisons.append({"comparator_fixture": name, "repeater_fixture": reference, "same_sampled_inputs": same_inputs, "same_sampled_output": same_output})
    files = ("metadata.json", "fixtures.json", "compiled-functions.json", "engine-events.jsonl", "observations.jsonl", "commands.jsonl")
    return {"run": run.relative_to(ROOT).as_posix(), "pass": True,
            "evidence_sha256": {name: lab.file_hash(run / name, "sha256") for name in files},
            "case_count": len(results), "sample_count": sum(c["sample_count"] for c in results),
            "engine_event_count": sum(c["engine_event_count"] for c in results),
            "accepted_and_dispatched_events": sum(c["accepted_events"] for c in results),
            "discarded_locked_dut_ticks": sum(c["discarded_locked_dut_ticks"] for c in results),
            "driver_pairs": len(comparisons), "differing_driver_pairs": sum(not c["same_sampled_output"] for c in comparisons),
            "cases": results, "driver_comparisons": comparisons}


def write_report(run):
    result = verify_run(run)
    destination = Path(run) / "engine-analysis.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {result['case_count']} cases, {result['sample_count']} samples, "
          f"{result['accepted_and_dispatched_events']} scheduled events: vanilla samples and engine replay match.")
    return result
