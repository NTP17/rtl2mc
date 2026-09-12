"""Reanalyze additive coverage and compare transformed experiments with version 1."""
import json
from collections import Counter

from .characterize import build_contract, load_run, sha256
from .fixtures import cases, compile_functions
from .project import ROOT, read_json, technology
from .results import active_intervals

BASELINE = "characterizations/repeater-java-1.21.1.json"
TARGET = "characterizations/repeater-coverage-v2.json"


def compare_traces(observed, reference):
    """Compare all sampled values, retaining command boundary order but ignoring world age."""
    if len(observed) != len(reference):
        raise ValueError("Reference and transformed sample counts differ")
    differences = []
    for current, previous in zip(observed, reference):
        boundary = (current["relative_game_tick"], current["phase"])
        if boundary != (previous["relative_game_tick"], previous["phase"]) or set(current["values"]) != set(previous["values"]):
            raise ValueError("Reference observation boundaries or probe names differ")
        for name, value in current["values"].items():
            if value != previous["values"][name]:
                differences.append({"tick": boundary[0], "phase": boundary[1], "probe": name,
                                    "reference": previous["values"][name], "observed": value})
    return differences


def collect(paths, expected, compiled):
    analyses, rows, evidence = [], {}, []
    for path in paths:
        found, samples, provenance = load_run(path, expected, compiled)
        analyses.extend(found)
        rows.update(samples)
        evidence.append(provenance)
    counts = Counter(case["id"] for case in analyses)
    if set(counts) != set(expected) or any(count != 1 for count in counts.values()):
        raise ValueError(f"Require exactly one result for all {len(expected)} broader repeater fixtures")
    return sorted(analyses, key=lambda case: case["id"]), rows, evidence


def compact_trace(case, rows, definition):
    return {"fixture": case["id"], "experiment": case["experiment"], "duration_game_ticks": definition["ticks"],
            "sample_count": len(rows), "all_declared_checks_pass": case["pass"], "transitions": case["transitions"],
            "sampled_high_intervals": {name: active_intervals(rows, name, 1 if name in ("powered", "locked") else 15)
                                       for name in ("powered", "locked")},
            "observed_edges": case["edges"], "checked_pulses": case["pulses"]}


def build_broad_contract(paths):
    baseline = read_json(ROOT / BASELINE)
    baseline_paths = [item["run"] for item in baseline["evidence"]]
    if baseline != build_contract(baseline_paths):
        raise ValueError("Version-1 reference contract differs from its reanalyzed evidence")
    compiled = compile_functions()
    reference_definitions = {case["id"]: case for case in cases("repeater")}
    reference_rows, reference_analyses = {}, {}
    for path in baseline_paths:
        analyses, rows, _ = load_run(path, reference_definitions, compiled)
        reference_rows.update(rows)
        reference_analyses.update({case["id"]: case for case in analyses})
    expected = {case["id"]: case for case in cases("repeater_broad")}
    analyses, rows, evidence = collect(paths, expected, compiled)
    records, references = [], {}
    for case in analyses:
        e = case["experiment"]
        record = compact_trace(case, rows[case["id"]], expected[case["id"]])
        if "reference_fixture" in e:
            reference = e["reference_fixture"]
            differences = compare_traces(rows[case["id"]], reference_rows[reference])
            record["reference_comparison"] = {"fixture": reference, "match": not differences, "differences": differences}
            references[reference] = compact_trace(reference_analyses[reference], reference_rows[reference], reference_definitions[reference])
        if e["family"] == "pulse_train":
            record["train_intervals"] = {"input": active_intervals(rows[case["id"]], "input", 15 * e["active_value"]),
                                         "output": active_intervals(rows[case["id"]], "powered", e["active_value"])}
        records.append(record)
    driver_comparisons = []
    for record in records:
        e = record["experiment"]
        if e["family"] != "lock_sequence" or e["driver"] != "comparator":
            continue
        counterpart = next(other for other in records if other["experiment"]["family"] == "lock_sequence"
                           and other["experiment"]["driver"] == "repeater"
                           and all(other["experiment"][key] == e[key] for key in ("delay_setting", "initial_output", "side", "pattern")))
        reference = counterpart["fixture"]
        differences = compare_traces(rows[record["fixture"]], rows[reference])
        input_lock_differences = [difference for difference in differences if difference["probe"] in ("input", "locked")]
        output_differences = [difference for difference in differences if difference["probe"] == "powered"]
        record["driver_reference_fixture"] = reference
        record["driver_reference_match"] = not differences
        driver_comparisons.append({"comparator_fixture": record["fixture"], "repeater_fixture": reference,
                                   "same_sampled_input_and_lock": not input_lock_differences,
                                   "same_sampled_output": not output_differences,
                                   "differences": differences})
    comparisons = [record for record in records if "reference_comparison" in record]
    return {
        "schema_version": 1, "id": "repeater_coverage_v2", "component": "repeater", "revision": 2,
        "technology": technology()["id"], "server_sha1": technology()["server"]["sha1"],
        "status": "measured_bounded", "mapping_eligible": False, "time_unit": "game_tick",
        "baseline": {"path": BASELINE, "sha256": sha256(ROOT / BASELINE), "case_count": baseline["coverage"]["case_count"]},
        "scope": {
            "spatial": {"reference_templates": len(references), "interior_dut_position": [10, 80, 5],
                        "chunk_corner_dut_position": [16, 80, 0], "facing_states": ["west", "north", "east", "south"],
                        "input_levels": [0, 15], "selection": "Pulse widths 1 and D, both polarities; brief locks, both held values and sides; hold Q=0 on template north with repeater/comparator; coincident pending lock Q=1 on both sides",
                        "comparison": "Every sampled probe at matching relative tick and command phase against the original fixture"},
            "strength": {"dut_position": [18, 80, 5], "facing": "west", "sustained_input_levels": list(range(16)),
                         "delay_settings": [1, 2, 3, 4], "one_tick_pulse_levels": [1, 7, 15],
                         "source": "Redstone block and a straight dust attenuator; actual rear dust power is probed"},
            "pulse_trains": {"dut_position": [10, 80, 5], "facing": "west", "input_levels": [0, 15],
                             "delay_settings": [1, 2, 3, 4], "polarities": [0, 1], "pulses_per_train": 3,
                             "active_width_and_gap": [["1", "1"], ["1", "D-1"], ["1", "D"], ["D", "1"], ["D", "D"], ["D+1", "D+1"]]},
            "lock_sequences": {"dut_position": [10, 80, 5], "facing": "west", "delay_settings": [1, 2, 3, 4],
                                "initial_output": [0, 1], "sides": ["north", "south"], "drivers": ["repeater delay=1", "comparator compare mode"],
                                "data_change_tick": 4, "T": "4+D, the nominal unlocked output due tick",
                                "lock_intervals": [["T-1", "T+3"], ["T-3", "T"], ["T-3", "T+1"]],
                                "command_order": "16 brief-lock variants drive the lock source before the data source at tick 4"},
            "measurement": "Frozen world, ordered source commands, single completed-game-tick steps at rate 20, before/after-action samples; no internal event trace",
            "configuration": "DUT delay setting, facing, support, and probe loads stay fixed during each case; only the documented sources change",
        },
        "coverage": {"new_case_count": len(records), "total_repeater_cases_with_baseline": len(records) + baseline["coverage"]["case_count"],
                     "sample_count": sum(item["sample_count"] for item in evidence),
                     "families": dict(sorted(Counter(record["experiment"]["family"] for record in records).items())),
                     "all_declared_checks_pass": True, "raw_samples_reanalyzed": True,
                     "reference_comparisons": len(comparisons),
                     "matching_reference_traces": sum(record["reference_comparison"]["match"] for record in comparisons),
                     "driver_pairs_compared": len(driver_comparisons),
                     "driver_pairs_with_same_input_lock_but_different_output": sum(pair["same_sampled_input_and_lock"] and not pair["same_sampled_output"] for pair in driver_comparisons)},
        "interpretation_rules": [
            "A passed declared check is separate from equivalence to a reference trace; differences are retained and counted.",
            "Strength timing results apply to the tested attenuator and output dust layout. They are not a complete face/powering-mode model.",
            "Only the spaced three-pulse trains declare an independent-pulse output hypothesis. Faster trains retain observed intervals and final settling checks.",
            "Lock sequence output timing is recorded without imposing a universal same-tick scheduling rule.",
        ],
        "limitations": [
            "Spatial coverage is a selected 48-template matrix, not the full cross-product of strengths, trains, lock patterns, and orientations.",
            "All tested chunks remain loaded. Crossing a loaded boundary does not characterize unload/reload or startup behavior.",
            "Two spatial sites plus one attenuator layout do not establish every world position, support block, neighbor arrangement, or vertical offset.",
            "No mirror transforms, moving components, mid-operation setting changes, alternate front loads, or complete strong/weak powering rules are certified.",
            "Three-pulse trains and selected lock windows do not cover arbitrary histories. Same-tick transient events and engine priority are unobserved.",
            "The next cell-admission step needs an explicit physical footprint, input protocol, and executable event model checked against these traces; Liberty/SDF views remain pending.",
        ],
        "evidence": evidence, "cases": records, "driver_comparisons": driver_comparisons,
        "reference_cases": sorted(references.values(), key=lambda record: record["fixture"]),
    }


def tick_list(record, probe="powered"):
    return [edge["tick"] for edge in record["transitions"][probe]["edges"]]


def observed_ticks(records):
    return " / ".join(",".join(map(str, ticks)) or "none" for ticks in sorted({tuple(tick_list(record)) for record in records}))


def render_broad_report(contract):
    coverage = contract["coverage"]
    records = contract["cases"]
    spatial = [record for record in records if record["experiment"]["family"] == "spatial"]
    order = [record for record in records if record["experiment"]["family"] == "command_order"]
    lines = ["# Broader repeater coverage", "",
             f"**{coverage['new_case_count']} new live fixtures passed**, with {coverage['sample_count']:,} observed samples. Combined with the original 200 cases, the library now has **{coverage['total_repeater_cases_with_baseline']} repeater fixtures** measured on vanilla Java Edition 1.21.1.", "",
             "The [native coverage contract](../characterizations/repeater-coverage-v2.json) adds evidence to the [version-1 contract](repeater-characterization.md). All new raw samples were reanalyzed. Passing a fixture means its declared checks passed; the tables separately report trace equivalence and observed-only timing.", "",
             "A self-contained [waveform browser](repeater-waveforms.html) lets you select cases, inspect integer game ticks, and overlay available reference traces. It makes no network requests and derives its data directly from this contract.", "",
             "## Coverage matrix", "", "| Family | New cases | Scope |", "|---|---:|---|"]
    descriptions = {"spatial": "48 selected reference templates at seven additional site/orientation combinations",
                    "strength": "Levels 0–15 at all four settings; one-gt pulses at levels 1, 7, and 15",
                    "pulse_train": "Three pulses, six width/gap patterns, both polarities, all four settings",
                    "lock_sequence": "Three near-due lock windows, both drivers, sides, held values, and all settings",
                    "command_order": "Reverse the source-command order in all 16 original brief-lock fixtures"}
    for family, count in coverage["families"].items():
        lines.append(f"| {family.replace('_', ' ')} | {count} | {descriptions[family]} |")
    lines += ["", "D means twice the repeater delay setting, in game ticks. All chunks stay loaded, and all measured changes are caused by the documented command sequence.", "",
              "## Rotations and loaded chunk boundaries", "",
              "Reference DUT position: `(10,80,5)`. The second site is `(16,80,0)`, where four chunks meet. Each site's four horizontal orientations are represented: the interior west-facing references already exist in version 1, and the other seven combinations add 336 cases.", "",
              "The comparison uses every sampled probe and command boundary, ignoring absolute world age. Probe names such as `north_powered` keep their template-relative meaning after rotation; the JSON gives the transform and the run records give actual coordinates.", "",
              "| Site | Facing state | Compared | Exact sampled-trace matches |", "|---|---|---:|---:|"]
    for site in ("interior", "chunk_corner"):
        for facing in ("west", "north", "east", "south"):
            selected = [record for record in spatial if record["experiment"]["site"] == site and record["experiment"]["facing"] == facing]
            if selected:
                lines.append(f"| {site.replace('_', ' ')} | {facing} | {len(selected)} | {sum(record['reference_comparison']['match'] for record in selected)} |")
    differences = [record for record in spatial + order if not record["reference_comparison"]["match"]]
    if differences:
        lines += ["", "Differences from the original traces:", ""]
        for record in differences:
            first = record["reference_comparison"]["differences"][0]
            lines.append(f"- `{record['fixture']}`: first difference at tick {first['tick']} ({first['phase']}), {first['probe']}: reference={first['reference']}, observed={first['observed']}.")
    else:
        lines += ["", "Every transformed and command-order trace matched its reference at all sampled boundaries. This supports the listed transforms for the selected templates; it does not certify every possible circuit arrangement."]
    lines += ["", "## Input-strength sweep", "",
              "A straight dust line drives the DUT at `(18,80,5)`. Its rear dust probe directly checks each requested strength, including strength zero after attenuation. The output dust probe checks regeneration.", "",
              "| Setting | Input levels with timed on/off edges | Observed rising delays (gt) | Observed falling delays (gt) |", "|---|---|---|---|"]
    for delay in range(1, 5):
        selected = [record for record in records if record["experiment"]["family"] == "strength" and record["experiment"]["stimulus_kind"] == "sustained"
                    and record["experiment"]["delay_setting"] == delay and record["experiment"]["input_level"] > 0]
        edges = [edge for record in selected for edge in record["observed_edges"]]
        rising = sorted({edge["observed_delay_game_ticks"] for edge in edges if edge["to"] == 1})
        falling = sorted({edge["observed_delay_game_ticks"] for edge in edges if edge["to"] == 0})
        lines.append(f"| {delay} | 1–15 | {rising} | {falling} |")
    lines += ["", "Level zero stayed off at every setting. The one-game-tick high pulses at levels 1, 7, and 15 also passed the expected `[D,2D)` output interval. These are measured results for this dust-driven input and dust output.", "",
              "## Repeated pulses", "",
              "Each case sends three active pulses. The table lists actual active output intervals `[start,end)`, in game ticks. An empty list means no sampled pulse. For low-polarity cases, these are low gaps in an initially high output.", "",
              "| Setting | Pattern | Active width / gap | High output intervals | Low output intervals |", "|---|---|---|---|---|"]
    for delay in range(1, 5):
        for pattern in ("rapid", "short_near", "short_at", "long_short", "matched", "spaced"):
            selected = [record for record in records if record["experiment"]["family"] == "pulse_train" and record["experiment"]["delay_setting"] == delay and record["experiment"]["pattern"] == pattern]
            by_active = {record["experiment"]["active_value"]: record for record in selected}
            e = selected[0]["experiment"]
            lines.append(f"| {delay} | {pattern} | {e['active_width']} / {e['gap_width']} | {by_active[1]['train_intervals']['output']} | {by_active[0]['train_intervals']['output']} |")
    lines += ["", "The `spaced` cases (active width and gap both D+1) passed the independent-pulse hypothesis. Other patterns record output shape without forcing the isolated-pulse rule onto interacting pulses. Every case checks the driven input sequence, output consistency, and final settling.", "",
              "## Lock release and command order", "",
              "Data changes at tick 4 and remains changed. T=4+D is its nominal due tick if unlocked. The three physical lock windows are `[T−1,T+3)`, `[T−3,T)`, and `[T−3,T+1)`. A lock may already be asserted when the data changes; the report therefore treats T as a reference time, not proof that an output event was scheduled.", "",
              "The table lists observed Q transition ticks, combining both sides. Multiple distinct outcomes, if present, are separated by `/`.", "",
              "| Setting | Lock window | Repeater rise | Repeater fall | Comparator rise | Comparator fall |", "|---|---|---|---|---|---|"]
    for delay in range(1, 5):
        for pattern in ("assert_near_due", "release_at_due", "release_after_due"):
            values = []
            for driver in ("repeater", "comparator"):
                for initial in (0, 1):
                    selected = [record for record in records if record["experiment"]["family"] == "lock_sequence"
                                and record["experiment"]["delay_setting"] == delay and record["experiment"]["pattern"] == pattern
                                and record["experiment"]["driver"] == driver and record["experiment"]["initial_output"] == initial]
                    values.append(observed_ticks(selected))
            lines.append(f"| {delay} | {pattern} | {' | '.join(values)} |")
    lines += ["", f"**{coverage['driver_pairs_with_same_input_lock_but_different_output']} of {coverage['driver_pairs_compared']} repeater/comparator driver pairs produced different sampled Q traces despite identical sampled rear-input and lock traces.** This is evidence that a model based only on those sampled Boolean inputs loses relevant context. The waveform viewer overlays the paired repeater trace when a comparator lock case is selected. Internal event priority is not directly observed.", "",
              f"Reversing the two source commands at tick 4 matched the original brief-lock trace in **{sum(record['reference_comparison']['match'] for record in order)}/{len(order)} cases**. The sampled result does not reveal the engine's internal event priority.", "",
              "## What remains before cell admission", ""]
    lines += [f"- {limitation}" for limitation in contract["limitations"]]
    lines += ["", "## Evidence and reproduction", "", "| Run | New cases | Samples |", "|---|---:|---:|"]
    for item in contract["evidence"]:
        lines.append(f"| [{item['run'].split('/')[-1]}](../{item['run']}/README.md) | {item['case_count']} | {item['sample_count']} |")
    lines += ["", "The JSON includes hashes of the version-1 contract and new evidence files, full per-fixture transition lists, and every sampled difference from a reference. Source snapshots and raw Minecraft replies remain in each run directory.", "",
              "Repeat the expansion, then rebuild this report from the new result directory:", "", "```powershell", "python pdk.py start",
              "python pdk.py run --suite repeater_broad", "python pdk.py stop", "```", "",
              "Rebuild from the evidence used here, without starting Minecraft:", "", "```powershell",
              "python pdk.py characterize-repeater-broad " + " ".join(item["run"] for item in contract["evidence"]),
              "python pdk.py validate", "```", "",
              "The original 200-case `repeater` suite and native version-1 contract remain reproducible. Sub-suites are `repeater_spatial`, `repeater_strength`, `repeater_sequences`, and `repeater_lock_sequences`; their complete nonoverlapping runs can also be combined by the report builder."]
    return "\n".join(lines) + "\n"


def write_broad_characterization(paths):
    contract = build_broad_contract(paths)
    target, report = ROOT / TARGET, ROOT / "docs/repeater-coverage-v2.md"
    target.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    report.write_text(render_broad_report(contract), encoding="utf-8")
    component_path = ROOT / "components/repeater.json"
    component = read_json(component_path)
    evidence = component["evidence"]
    evidence["fixture_suites"] = sorted(set(evidence.get("fixture_suites", []) + ["repeater_broad"]))
    evidence["characterizations"] = [reference for reference in evidence["characterizations"] if reference["path"] != TARGET] + [
        {"path": TARGET, "sha256": sha256(target)}]
    if not evidence.get("executable_models"):
        component["behavior"]["description"] = "Directional signal regeneration with configurable delay and side locking. Native contracts record 772 measured fixtures covering pulses, selected rotations and positions, input strengths 0..15, pulse trains, and physical lock sequences."
        component["behavior"]["limitations"] = contract["limitations"]
        component["timing"]["uncharacterized"] = ["Executable event model and certified cell input protocol", "Arbitrary histories and internal event priority",
                                                    "Untested powering modes, loads, neighboring arrangements, and lifecycle events"]
    component_path.write_text(json.dumps(component, indent=2) + "\n", encoding="utf-8")
    from .waveforms import write_waveforms
    viewer = write_waveforms(contract)
    return target, report, viewer
