"""Check physical test construction and trace-only report support offline."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from redstone_pdk.fixtures import BOUNDS, cases
from redstone_pdk.repeater_broad_fixtures import SITES, VECTORS, facing_after, spatial_templates, transform_layout
from redstone_pdk.results import write_summary
from redstone_pdk.characterize_broad import collect, compare_traces
from redstone_pdk.waveforms import pack


class GeometryTests(unittest.TestCase):
    def test_four_rotations_restore_every_layout_and_command(self):
        for original in spatial_templates():
            current = copy.deepcopy(original)
            for _ in range(4):
                current = transform_layout(current, (10, 80, 5), 1)
            self.assertEqual(current, original)

    def test_transforms_do_not_mutate_reference_fixtures(self):
        template = spatial_templates()[-1]
        before = copy.deepcopy(template)
        transform_layout(template, SITES["chunk_corner"], 3)
        self.assertEqual(template, before)

    def test_ports_match_the_transformed_facing(self):
        for case in cases("repeater_spatial"):
            e = case["experiment"]
            probes = {probe["name"]: probe["position"] for probe in case["probes"]}
            x, y, z = e["dut_position"]
            dx, dz = VECTORS[e["facing"]]
            self.assertEqual(probes["input"], [x + dx, y, z + dz])
            self.assertEqual(probes["out"], [x - dx, y, z - dz])
            self.assertEqual(e["facing"], facing_after("west", e["quarter_turns"]))

    def test_chunk_corner_templates_really_cross_a_chunk_boundary(self):
        for case in cases("repeater_spatial"):
            if case["experiment"]["site"] != "chunk_corner":
                continue
            chunks = {(probe["position"][0] // 16, probe["position"][2] // 16) for probe in case["probes"]}
            self.assertGreater(len(chunks), 1)

    def test_every_preparation_command_stays_in_the_existing_lab_volume(self):
        low, high = BOUNDS
        for case in cases("repeater_broad"):
            for stage in case.get("prepare", []):
                for command in stage["commands"]:
                    point = list(map(int, command.split()[1:4]))
                    self.assertTrue(all(a <= value <= b for a, value, b in zip(low, point, high)), case["id"])

    def test_all_strengths_and_delay_settings_have_sustained_cases(self):
        combinations = {(case["experiment"]["input_level"], case["experiment"]["delay_setting"])
                        for case in cases("repeater_strength") if case["experiment"]["stimulus_kind"] == "sustained"}
        self.assertEqual(combinations, {(s, d) for s in range(16) for d in range(1, 5)})


class TraceReportTests(unittest.TestCase):
    def test_duplicate_new_evidence_cannot_replace_missing_coverage(self):
        with patch("redstone_pdk.characterize_broad.load_run", return_value=([{"id": "a"}], {}, {})):
            with self.assertRaisesRegex(ValueError, "exactly one result"):
                collect(["first", "duplicate"], {"a": {}, "b": {}}, {})

    def test_waveform_export_preserves_both_transitions_at_a_command_boundary(self):
        record = {"fixture": "synthetic", "experiment": {"family": "pulse_train", "delay_setting": 1},
                  "duration_game_ticks": 3, "transitions": {"powered": {"initial": 0, "edges": [
                      {"tick": 2, "to": 1, "phase": "before_action"},
                      {"tick": 2, "to": 0, "phase": "after_commands_or_completed_tick"}]}}}
        trace = pack(record)["signals"]["powered"]
        self.assertEqual(trace["edges"], [[2, 1, "before_action"], [2, 0, "after_commands_or_completed_tick"]])

    def test_reference_comparison_ignores_world_age_but_keeps_command_phases(self):
        before = [{"relative_game_tick": 2, "phase": "before_action", "game_time": 102, "values": {"q": 0}},
                  {"relative_game_tick": 2, "phase": "after_commands_or_completed_tick", "game_time": 102, "values": {"q": 1}}]
        after = copy.deepcopy(before)
        for row in after:
            row["game_time"] += 1000
        self.assertEqual(compare_traces(after, before), [])
        after[0]["values"]["q"] = 1
        difference = compare_traces(after, before)[0]
        self.assertEqual((difference["tick"], difference["phase"], difference["reference"], difference["observed"]), (2, "before_action", 0, 1))

    def test_a_single_observed_input_interval_does_not_require_an_output_hypothesis(self):
        analysis = {"id": "trace_only", "pass": True, "pulses": [{"probe": "input", "active_value": 15,
                    "observed_intervals": [[0, 1]], "observed_widths_game_ticks": [1]}]}
        with tempfile.TemporaryDirectory() as temporary:
            write_summary(temporary, {"technology": "synthetic", "minecraft_version": "synthetic"}, [analysis])
            report = (Path(temporary) / "README.md").read_text(encoding="utf-8")
        self.assertIn("| input | 15 |", report)


if __name__ == "__main__":
    unittest.main()
