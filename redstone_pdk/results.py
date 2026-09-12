"""Parse actual game observations and compare them with declared hypotheses."""
import json
import re
from pathlib import Path


def parse_probe_response(response, names):
    match = re.search(r"\{([^{}]*)\}\s*$", response)
    if not match:
        raise ValueError(f"Minecraft did not return a probe object: {response}")
    body = match.group(1)
    values = {}
    if body.strip():
        for member in body.split(","):
            item = re.fullmatch(r'\s*"?([a-zA-Z0-9_]+)"?\s*:\s*(-?\d+)\s*', member)
            if not item or item[1] in values:
                raise ValueError(f"Invalid or duplicate probe field: {member}")
            values[item[1]] = int(item[2])
    if set(values) != set(names):
        raise ValueError(f"Probe keys differ: expected {names}, observed {sorted(values)}")
    if any(value < 0 or value > 15 for value in values.values()):
        raise ValueError(f"A probe did not match its expected block state: {values}")
    return values


def analyze(case, samples):
    by_tick = {row["relative_game_tick"]: row["values"] for row in samples}
    expected_ticks = set(range(-1, case["ticks"] + 1))
    ordered = [row["relative_game_tick"] for row in samples]
    integrity = {"pass": set(by_tick) == expected_ticks and ordered == sorted(ordered),
                 "missing_ticks": sorted(expected_ticks - set(by_tick)),
                 "unexpected_ticks": sorted(set(by_tick) - expected_ticks)}
    checks = []
    expected_values = list(case["checks"])
    if "baseline_checks" in case:
        expected_values.insert(0, {"tick": -1, "values": case["baseline_checks"]})
    for expected in expected_values:
        actual = by_tick.get(expected["tick"], {})
        for name, value in expected["values"].items():
            checks.append({"tick": expected["tick"], "probe": name, "expected": value,
                           "observed": actual.get(name), "pass": actual.get(name) == value})
    edges = []
    action_times = sorted(case["actions"])
    for hypothesis in case.get("edge_hypotheses", []):
        start = hypothesis["after"]
        end = next((tick for tick in action_times if tick > start), case["ticks"] + 1)
        # Baseline is explicitly observed before actions, not inferred from setup.
        previous = next((row["values"][hypothesis["probe"]] for row in reversed(samples)
                         if row["relative_game_tick"] < start), None)
        transition = None
        for row in samples:
            tick = row["relative_game_tick"]
            if start <= tick < end:
                value = row["values"][hypothesis["probe"]]
                if previous is not None and previous != hypothesis["to"] and value == hypothesis["to"]:
                    transition = tick - start
                    break
                previous = value
        edges.append({**hypothesis, "observed_delay_game_ticks": transition,
                      "pass": transition == hypothesis["delay"]})
    pulses = []
    for hypothesis in case.get("pulse_hypotheses", []):
        intervals = active_intervals(samples, hypothesis["probe"], hypothesis["active_value"])
        pulses.append({**hypothesis, "observed_intervals": intervals,
                       "observed_widths_game_ticks": [end - start if end is not None and start is not None else None for start, end in intervals],
                       "pass": intervals == hypothesis["intervals"]})
    invariants = [check_invariant(invariant, samples) for invariant in case.get("invariants", [])]
    transitions = {}
    for name in case.get("trace_probes", []):
        changes = []
        for previous, current in zip(samples, samples[1:]):
            before, after = previous["values"][name], current["values"][name]
            if before != after:
                changes.append({"tick": current["relative_game_tick"], "from": before, "to": after,
                                "phase": current.get("phase"), "sample_index": current.get("sample_index")})
        transitions[name] = {"initial": samples[0]["values"][name] if samples else None, "edges": changes}
    return {"id": case["id"], "experiment": case.get("experiment"), "integrity": integrity,
            "checks": checks, "edges": edges, "pulses": pulses, "invariants": invariants, "transitions": transitions,
            "pass": integrity["pass"] and all(check["pass"] for check in checks + edges + pulses + invariants)}


def active_intervals(samples, probe, active):
    """Extract complete pulses; None bounds mean the observation is censored."""
    intervals = []
    if not samples:
        return intervals
    previous = samples[0]["values"][probe]
    started = previous == active
    start = None
    for row in samples[1:]:
        value = row["values"][probe]
        if value == active and previous != active:
            start = row["relative_game_tick"]
            started = True
        elif value != active and previous == active and started:
            intervals.append([start, row["relative_game_tick"]])
            started = False
        previous = value
    if started:
        intervals.append([start, None])
    return intervals


def check_invariant(rule, samples):
    failures = []
    checked = 0
    for index, row in enumerate(samples):
        values = row["values"]
        kind = rule["kind"]
        if kind == "binary_output":
            expected = 15 * values[rule["state"]]
            actual = values[rule["output"]]
        elif kind == "lock_equals_or":
            expected = int(any(values[name] for name in rule["drivers"]))
            actual = values[rule["lock"]]
        elif kind == "hold_while_locked":
            if not index or not samples[index - 1]["values"][rule["lock"]] or not values[rule["lock"]]:
                continue
            expected = samples[index - 1]["values"][rule["state"]]
            actual = values[rule["state"]]
        else:
            raise ValueError(f"Unsupported invariant: {kind}")
        checked += 1
        if actual != expected:
            failures.append({"tick": row["relative_game_tick"], "phase": row.get("phase"), "expected": expected, "observed": actual})
    return {**rule, "samples_checked": checked, "failures": failures, "pass": not failures}


def write_summary(run_dir, metadata, analyses, error=None):
    summary = {"schema_version": 1, "metadata": metadata, "cases": analyses, "error": error,
               "pass": bool(analyses) and error is None and all(case["pass"] for case in analyses)}
    run_dir = Path(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    resolution_text = ("Resolution: observations after commands and completed game ticks. Targeted intra-tick engine events are recorded separately in `engine-events.jsonl`."
                       if metadata.get("instrumentation") else
                       "Resolution: observations after commands and completed game ticks. Intra-tick events are not observed.")
    lines = ["# Redstone characterization run", "", f"Technology: `{metadata['technology']}`",
             f"Minecraft: `{metadata['minecraft_version']}`", "",
             resolution_text,
             "A passing fixture is evidence for that arrangement only; no primitive or cell is automatically certified.", "",
             "| Fixture | Result |", "|---|---|"]
    for case in analyses:
        lines.append(f"| {case['id']} | {'PASS' if case['pass'] else 'FAIL'} |")
    pulse_cases = [case for case in analyses if case.get("pulses")]
    if pulse_cases:
        lines += ["", "## Pulse measurements", "", "Intervals are [start, end) in game ticks; null is an unobserved boundary.", "",
                  "| Fixture | Probe | Active value | Observed intervals | Widths |", "|---|---|---|---|---|"]
        for case in pulse_cases:
            for pulse in case["pulses"]:
                lines.append(f"| {case['id']} | {pulse['probe']} | {pulse['active_value']} | {pulse['observed_intervals']} | {pulse['observed_widths_game_ticks']} |")
    if error:
        lines += ["", "Run interrupted:", "", str(error)]
    lines += ["", "See `observations.jsonl` for measured samples and `commands.jsonl` for raw game replies.",
              "The expected values and edge delays in `summary.json` are hypotheses compared with observations."]
    (run_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
