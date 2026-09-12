"""Build a bounded repeater contract from complete, independently reanalyzed runs."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from .fixtures import cases, compile_functions
from .project import ROOT, read_json, technology
from .results import analyze


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def restore_case(case):
    return {**case, "actions": {int(tick): commands for tick, commands in case["actions"].items()}}


def check_samples(case, samples):
    """Require every declared observation boundary, probe domain, and game timestamp."""
    expected = [(-1, "baseline_before_stimulus")]
    for tick in range(case["ticks"] + 1):
        if tick > 0 and tick in case["actions"]:
            expected.append((tick, "before_action"))
        expected.append((tick, "after_commands_or_completed_tick"))
    if [(row["relative_game_tick"], row["phase"]) for row in samples] != expected:
        raise ValueError(f"{case['id']}: missing, reordered, or extra observation boundaries")
    domains = {probe["name"]: [int(value) for value in probe["values"]] for probe in case["probes"]}
    start = samples[0]["game_time"]
    for index, row in enumerate(samples):
        if row["sample_index"] != index or row["game_time"] != start + max(0, row["relative_game_tick"]):
            raise ValueError(f"{case['id']}: inconsistent sample index or game time")
        if set(row["values"]) != set(domains) or any(
            type(value) is not int or value not in domains[name] for name, value in row["values"].items()
        ):
            raise ValueError(f"{case['id']}: invalid probe values")


def load_run(path, expected_cases, compiled):
    run = Path(path)
    if not run.is_absolute():
        run = ROOT / run
    run = run.resolve()
    if not run.is_relative_to((ROOT / "results").resolve()):
        raise ValueError("Characterization inputs must be run directories under this project's results/")
    metadata, summary = read_json(run / "metadata.json"), read_json(run / "summary.json")
    tech = technology()
    if (metadata["technology"], metadata["minecraft_version"], metadata["server_sha1"]) != (
        tech["id"], tech["minecraft_version"], tech["server"]["sha1"]
    ):
        raise ValueError(f"{run.name}: technology or official server build differs")
    if metadata["resolution"] != {**tech["measurement"], "before_action_samples": True} or metadata["random_tick_speed"] != 0:
        raise ValueError(f"{run.name}: observation conditions differ")
    if summary.get("pass") is not True or summary.get("error") is not None or summary["metadata"] != metadata:
        raise ValueError(f"{run.name}: run is incomplete, failed, or has inconsistent metadata")
    fixtures = [restore_case(case) for case in read_json(run / "fixtures.json")]
    ids = [case["id"] for case in fixtures]
    if not ids or len(set(ids)) != len(ids) or ids != metadata["fixtures"]:
        raise ValueError(f"{run.name}: fixture manifest is inconsistent")
    digest = hashlib.sha256(json.dumps(fixtures, sort_keys=True).encode()).hexdigest()
    if digest != metadata["suite_sha256"]:
        raise ValueError(f"{run.name}: suite digest differs; use a complete repeater suite")
    saved_functions = read_json(run / "compiled-functions.json")
    for case in fixtures:
        if expected_cases.get(case["id"]) != case:
            raise ValueError(f"{case['id']}: fixture is outside the current repeater contract")
        prefix = case["id"] + "/"
        if {key: value for key, value in saved_functions.items() if key.startswith(prefix)} != {
            key: value for key, value in compiled.items() if key.startswith(prefix)
        }:
            raise ValueError(f"{case['id']}: compiled commands differ")
    for name, digest in metadata["harness_sha256"].items():
        if Path(name).name != name or sha256(run / "harness-source" / name) != digest:
            raise ValueError(f"{run.name}: saved harness source digest differs: {name}")
    samples = {cid: [] for cid in ids}
    observed_order = []
    with (run / "observations.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            cid = row["case"]
            if cid not in samples:
                raise ValueError(f"{run.name}: unexpected observed fixture {cid}")
            if not observed_order or observed_order[-1] != cid:
                observed_order.append(cid)
            samples[cid].append(row)
    if observed_order != ids:
        raise ValueError(f"{run.name}: missing or reordered fixture observations")
    analyses = []
    for case in fixtures:
        check_samples(case, samples[case["id"]])
        analysis = analyze(case, samples[case["id"]])
        if not analysis["pass"]:
            raise ValueError(f"{case['id']}: raw observations do not pass reanalysis")
        analyses.append(analysis)
    if analyses != summary["cases"]:
        raise ValueError(f"{run.name}: saved summary differs from raw-sample reanalysis")
    files = ["metadata.json", "fixtures.json", "compiled-functions.json", "observations.jsonl", "commands.jsonl", "summary.json"]
    evidence = {"run": run.relative_to(ROOT).as_posix(), "started_at_utc": metadata["started_at_utc"],
                "case_count": len(ids), "sample_count": sum(map(len, samples.values())),
                "sha256": {name: sha256(run / name) for name in files},
                "harness_sha256": metadata["harness_sha256"]}
    return analyses, samples, evidence


def require_coverage(analyses):
    counts = Counter(case["id"] for case in analyses)
    expected = {case["id"] for case in cases("repeater")}
    if set(counts) != expected or any(count != 1 for count in counts.values()):
        raise ValueError(f"Require exactly one observation of all {len(expected)} repeater fixtures; "
                         f"missing={len(expected - set(counts))}, duplicates={sum(n > 1 for n in counts.values())}")


def build_contract(paths):
    expected = {case["id"]: case for case in cases("repeater")}
    compiled = compile_functions()
    analyses, samples, evidence = [], {}, []
    for path in paths:
        found, rows, provenance = load_run(path, expected, compiled)
        analyses.extend(found)
        samples.update(rows)
        evidence.append(provenance)
    require_coverage(analyses)
    analyses.sort(key=lambda case: case["id"])
    pulses, locking = [], []
    for case in analyses:
        experiment = case["experiment"]
        if experiment["family"] == "pulse":
            data, output = case["pulses"]
            pulses.append({"fixture": case["id"], **experiment,
                           "input_intervals": data["observed_intervals"], "output_intervals": output["observed_intervals"],
                           "output_widths_game_ticks": output["observed_widths_game_ticks"]})
        else:
            rows = samples[case["id"]]
            first_lock = next((row for row in rows if row["values"]["locked"]), None)
            locking.append({"fixture": case["id"], **experiment,
                            "q_at_first_locked_observation": first_lock["values"]["powered"] if first_lock else None,
                            "transitions": case["transitions"]})
    pending_pattern = all(
        [edge["tick"] for edge in row["transitions"]["powered"]["edges"]] == [
            row["nominal_output_due_tick"] if row["lock_due_offset"] > 0 else row["unlock_due_tick"] + 2 * row["delay_setting"]
        ] for row in locking if row["family"] == "pending"
    )
    brief_pattern = all(
        [edge["tick"] for edge in row["transitions"]["powered"]["edges"]] == [
            {1: (10, 10), 2: (8, 12), 3: (10, 10), 4: (12, 12)}[row["delay_setting"]][row["initial_output"]]
        ] for row in locking if row["family"] == "brief_lock"
    )
    return {
        "schema_version": 1, "id": "repeater_pulse_lock_v1", "component": "repeater",
        "technology": technology()["id"], "server_sha1": technology()["server"]["sha1"],
        "status": "measured_bounded", "mapping_eligible": False, "time_unit": "game_tick",
        "scope": {
            "dut_position": [10, 80, 5], "block_state_facing": "west", "input_face": "west", "output_face": "east",
            "support": "stone floor at y=79", "input_probe_position": [9, 80, 5], "output_probe_position": [11, 80, 5],
            "delay_settings": [1, 2, 3, 4], "input_levels": [0, 15], "isolated_pulse_widths_game_ticks": list(range(1, 11)),
            "lock_sides": ["north", "south"], "hold_drivers": ["repeater delay=1", "comparator mode=compare, rear=15, no side input"],
            "pending_and_brief_lock_driver": "repeater delay=1", "side_control_position": "north",
            "stimulus": "Ordered source block commands while frozen, followed by single-game-tick stepping",
            "initialization": "20 game ticks after setup; prelocked fixtures then assert physical side drivers and settle 4 game ticks",
            "resolution": "Before/after command boundaries and after completed game ticks; no intra-tick event trace",
            "environment": "Vanilla 1.21.1 overworld; loaded fixed region; random ticks, mob spawning, daylight/weather cycles disabled",
        },
        "behavior_contract": {
            "kind": "bounded_sampled_observations", "parameters": {"D_game_ticks": "2 * delay_setting", "Q": "DUT powered state"},
            "rules": [
                {"id": "high_pulse", "families": ["pulse"], "claim": "confirmed_in_sweep",
                 "condition": "Initially settled Q=0; unlocked; one high input interval [0,w), w=1..10",
                 "observation": "Output high interval [D, D+max(w,D)); output dust is 15 when Q=1"},
                {"id": "low_gap", "families": ["pulse"], "claim": "confirmed_in_sweep",
                 "condition": "Initially settled Q=1; unlocked; one low input interval [0,w), w=1..10",
                 "observation": "No sampled output low gap if w<D; otherwise output low interval [D,D+w)"},
                {"id": "hold", "families": ["hold", "dual_lock", "locked_return"], "claim": "confirmed_in_fixtures",
                 "condition": "A listed side driver is powered, with Q already settled when the lock was established",
                 "observation": "Q remains held through rear-input changes. Either eligible side sustains the lock. After release with stable rear differing from Q, Q changes after D. A rear change that returns to held Q before release produces no sampled replay"},
                {"id": "side_eligibility", "families": ["side_control"], "claim": "confirmed_in_fixtures",
                 "condition": "Adjacent north neighbor is redstone block or powered dust, using the recorded layout",
                 "observation": "The neighbor does not lock the DUT"},
                {"id": "pending", "families": ["pending", "brief_lock"], "claim": "trace_only",
                 "condition": "A data transition is followed by lock/unlock near its nominal due tick",
                 "observation": "Use the per-fixture transitions; output depends on lock timing and transition polarity. No universal same-tick tie rule is admitted"},
            ],
            "state_model_implication": "Powered and locked booleans plus D are insufficient for a general event-driven model. Retain pending-event context as a modeling hypothesis; this experiment does not directly observe the engine's event queue.",
        },
        "coverage": {"case_count": len(analyses), "sample_count": sum(item["sample_count"] for item in evidence),
                     "families": dict(sorted(Counter(case["experiment"]["family"] for case in analyses).items())),
                     "all_fixture_checks_pass": True, "raw_samples_reanalyzed": True},
        "derived_findings": {"pending_matches_due_or_unlock_plus_D": pending_pattern,
                             "brief_lock_matches_first_observed_pattern": brief_pattern},
        "limitations": [
            "One fixed DUT position and orientation; no rotation, translation, mirror, or chunk-boundary guarantee.",
            "Rear levels 1..14, alternate powering modes, loads, and other side-driver configurations are untested.",
            "Isolated pulses only; arbitrary pulse trains and lock sequences are outside this contract.",
            "Same-game-tick engine ordering and transient intra-tick changes are unobserved; no setup/hold window is certified.",
            "No lifecycle, unload/reload, dimension, server restart, placement-order, or version equivalence guarantee.",
            "No Liberty/SDF timing arc, executable full primitive model, or synthesis cell admission is implied.",
        ],
        "evidence": evidence, "pulses": pulses, "locking": locking,
    }


def write_characterization(paths):
    contract = build_contract(paths)
    target = ROOT / "characterizations/repeater-java-1.21.1.json"
    report = ROOT / "docs/repeater-characterization.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    report.write_text(render_report(contract), encoding="utf-8")
    component_path = ROOT / "components/repeater.json"
    component = read_json(component_path)
    component["evidence"]["fixture_suites"] = sorted(set(component["evidence"].get("fixture_suites", []) + ["repeater"]))
    relative = target.relative_to(ROOT).as_posix()
    others = [reference for reference in component["evidence"].get("characterizations", []) if reference["path"] != relative]
    component["evidence"]["characterizations"] = [{"path": relative, "sha256": sha256(target)}] + others
    component_path.write_text(json.dumps(component, indent=2) + "\n", encoding="utf-8")
    return target, report


def render_report(contract):
    coverage = contract["coverage"]
    lines = ["# Repeater pulse and locking characterization", "",
             f"**{coverage['case_count']} live fixtures passed**, with {coverage['sample_count']:,} observed samples on vanilla Java Edition 1.21.1.",
             "Raw samples were reanalyzed before creating this report. The native [JSON contract](../characterizations/repeater-java-1.21.1.json) records scope, rules, per-fixture transitions, and evidence hashes.", "",
             "This is a bounded observation contract. The repeater primitive remains in draft and is not yet eligible for synthesis or Liberty/SDF export.", "",
             "## What was measured", "",
             "The DUT is at `(10,80,5)`, block state `facing=west`: rear input west, output east. Input and output dust sit immediately beside those faces, on a stone floor. Sources drive levels 0 and 15. Side repeaters/comparators physically drive locking; commands never force the DUT's powered or locked properties.", "",
             "All delays below are **game ticks** (gt); `D=2 × setting`. Measurements are taken before/after source commands and after completed ticks. They do not expose engine events inside a tick.", "",
             "| Family | Cases | Coverage |", "|---|---:|---|",
             "| Isolated pulses | 80 | Four settings, both polarities, widths 1–10 gt |",
             "| Held output and release | 32 | Four settings, Q=0/1, both sides, repeater/comparator drivers |",
             "| Lock near an output due tick | 48 | Four settings, Q=0/1, both sides, lock at due−1/due/due+1 |",
             "| Two side locks | 8 | Four settings, Q=0/1, staggered release |",
             "| Ineligible side neighbors | 8 | Four settings, north redstone block/powered dust |",
             "| Brief lock over a pending change | 16 | Four settings, Q=0/1, both sides |",
             "| Input returns while locked | 8 | Four settings, Q=0/1, north repeater |", "",
             "## Pulse behavior", "",
             "For a settled, unlocked repeater and an isolated input pulse of width `w=1..10`:", "",
             "- A high pulse starting at tick 0 produces output high on `[D, D+max(w,D))`.",
             "- A low gap shorter than D produces no observed low output. A gap of width at least D produces output low on `[D,D+w)`.", "",
             "These expressions matched every pulse in the sweep. Widths and pulse trains outside the sweep remain uncharacterized.", "",
             "Measured output widths follow. Each row lists input widths **1,2,3,4,5,6,7,8,9,10 gt**, in order; `—` means no sampled output pulse.", "",
             "| Setting | D (gt) | High output widths (gt) | Low output widths (gt) |", "|---|---:|---|---|"]
    for delay in range(1, 5):
        widths = []
        for active in (1, 0):
            rows = sorted((row for row in contract["pulses"] if row["delay_setting"] == delay and row["active_value"] == active), key=lambda row: row["input_width_game_ticks"])
            widths.append(", ".join(str(row["output_widths_game_ticks"][0]) if row["output_widths_game_ticks"] else "—" for row in rows))
        lines.append(f"| {delay} | {2 * delay} | {widths[0]} | {widths[1]} |")
    lines += ["", "For example, at setting 4, a one-gt high input `[0,1)` produces output high `[8,16)`. A one-gt low input gap is suppressed at the sampled boundaries. A symmetric fixed-delay buffer cannot represent both results.", "",
              "## Locking behavior", "",
              "Both eligible side repeaters and comparators held Q=0 and Q=1 through input changes. With both sides asserted, releasing only one kept the lock. A powered dust neighbor or redstone block at the tested north position did not lock the DUT.", "",
              "In the established-lock fixtures, after the final side driver turned off, a stable rear input differing from Q reached the output after D. An input excursion that returned to Q before release produced no sampled replay.", "",
              "### Lock assertion near a pending output change", "",
              "Data changes at tick 4; its nominal due tick is `T=4+D`. The side repeater asserts at `T−1`, `T`, or `T+1`, then releases at `U=T+8`. The table combines both sides and both output polarities at each setting, retaining every observed result.", "",
              "| Setting | Lock at T−1: Q change tick | Lock at T: Q change tick | Lock at T+1: Q change tick |", "|---|---|---|---|"]
    for delay in range(1, 5):
        values = []
        for offset in (-1, 0, 1):
            rows = [row for row in contract["locking"] if row["family"] == "pending" and row["delay_setting"] == delay and row["lock_due_offset"] == offset]
            ticks = sorted({tuple(edge["tick"] for edge in row["transitions"]["powered"]["edges"]) for row in rows})
            values.append(" / ".join(",".join(map(str, item)) or "none" for item in ticks))
        lines.append(f"| {delay} | {' | '.join(values)} |")
    pending_note = ("In this layout, early and coincident locks held the original Q until U+D; the late lock arrived after Q had changed at T."
                    if contract["derived_findings"]["pending_matches_due_or_unlock_plus_D"] else
                    "The new traces differ from the initial pattern of early/coincident changes at U+D and late changes at T; review the individual fixtures in the JSON.")
    lines += ["", pending_note + " The coincident result describes these fixtures and is not a universal priority rule.", "",
              "### A brief lock exposes additional state", "",
              "Here data changes at tick 4 and stays changed. The side repeater creates a lock on `[6,8)`. The table preserves all measured transition times across both sides.", "",
              "| Setting | Original due tick | Observed rising Q tick | Observed falling Q tick |", "|---|---:|---|---|"]
    for delay in range(1, 5):
        values = []
        for initial in (0, 1):
            rows = [row for row in contract["locking"] if row["family"] == "brief_lock" and row["delay_setting"] == delay and row["initial_output"] == initial]
            ticks = sorted({tuple(edge["tick"] for edge in row["transitions"]["powered"]["edges"]) for row in rows})
            values.append(" / ".join(",".join(map(str, item)) or "none" for item in ticks))
        lines.append(f"| {delay} | {4 + 2 * delay} | {' | '.join(values)} |")
    brief_note = ("Both sides agreed. At settings 3 and 4, unlocking before the original due tick preserved the original observed change time. At setting 2, unlock coincided with the due tick: the rising change appeared at 8, the falling change at 12."
                  if contract["derived_findings"]["brief_lock_matches_first_observed_pattern"] else
                  "These measurements differ from the first observed brief-lock pattern. Review polarity and side differences in the individual JSON traces before generalizing.")
    lines += ["", brief_note + " Pending-event context belongs in a future model; the traces do not directly reveal which internal event was canceled, retained, or rescheduled.", "",
              "## Operating envelope and next work", ""]
    lines += [f"- {limitation}" for limitation in contract["limitations"]]
    lines += ["", "Next, vary orientation, position, input strength, and pulse/lock sequences; use event instrumentation for coincident boundaries. A reviewed physical cell can then declare a narrower legal input protocol and derive functional/timing views from that protocol.", "",
              "## Evidence and reproduction", "",
              "| Run | Cases | Samples |", "|---|---:|---:|"]
    for item in contract["evidence"]:
        lines.append(f"| [{Path(item['run']).name}](../{item['run']}/README.md) | {item['case_count']} | {item['sample_count']} |")
    lines += ["", "Each run retains its fixture definitions, compiled Minecraft commands, harness source snapshot, raw command replies, observed samples, and analysis. SHA-256 digests in the JSON identify this evidence; they are consistency checks, not cryptographic attestation by Minecraft.", "",
              "Rebuild this report offline from the saved runs:", "", "```powershell",
              "python pdk.py characterize-repeater " + " ".join(item["run"] for item in contract["evidence"]), "```", "",
              "Repeat the complete 200-case measurement in the prepared lab:", "", "```powershell",
              "python pdk.py start", "python pdk.py run --suite repeater", "python pdk.py stop", "```", "",
              "The report builder requires complete coverage without duplicate fixtures, matching version and layout definitions, intact saved harness hashes, all observation boundaries, valid probe domains, and raw-sample results matching the saved analysis. It never fills missing measurements with expectations."]
    return "\n".join(lines) + "\n"
