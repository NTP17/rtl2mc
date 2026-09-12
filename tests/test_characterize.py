"""Evidence-admission failures, using synthetic records rather than a redstone simulator."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from redstone_pdk import characterize
from redstone_pdk.fixtures import cases
from redstone_pdk.project import technology
from redstone_pdk.results import analyze


class CoverageAdmissionTests(unittest.TestCase):
    def test_missing_or_duplicate_fixtures_are_rejected(self):
        complete = [{"id": case["id"]} for case in cases("repeater")]
        characterize.require_coverage(complete)
        for incomplete in (complete[:-1], complete + [complete[0]], complete[:-1] + [complete[0]]):
            with self.assertRaisesRegex(ValueError, "exactly one observation"):
                characterize.require_coverage(incomplete)


class EvidenceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Match project.ROOT, including expansion of Windows short-path aliases.
        self.root = Path(self.temporary.name).resolve()
        self.run = self.root / "results/synthetic"
        self.run.mkdir(parents=True)
        self.case = {"id": "synthetic", "ticks": 1, "actions": {1: ["synthetic action"]},
                     "probes": [{"name": "q", "values": [0, 1]}], "checks": [{"tick": 1, "values": {"q": 0}}]}
        self.rows = [{"case": "synthetic", "relative_game_tick": tick, "game_time": 100 + max(0, tick),
                      "sample_index": index, "phase": phase, "values": {"q": 0}}
                     for index, (tick, phase) in enumerate([
                         (-1, "baseline_before_stimulus"), (0, "after_commands_or_completed_tick"),
                         (1, "before_action"), (1, "after_commands_or_completed_tick")])]
        tech = technology()
        source_dir = self.run / "harness-source"
        source_dir.mkdir()
        (source_dir / "example.py").write_text("# synthetic evidence; never executed\n", encoding="utf-8")
        self.metadata = {"technology": tech["id"], "minecraft_version": tech["minecraft_version"],
                         "server_sha1": tech["server"]["sha1"], "fixtures": ["synthetic"],
                         "suite_sha256": hashlib.sha256(json.dumps([self.case], sort_keys=True).encode()).hexdigest(),
                         "resolution": {**tech["measurement"], "before_action_samples": True},
                         "random_tick_speed": 0, "started_at_utc": "synthetic test timestamp",
                         "harness_sha256": {"example.py": characterize.sha256(source_dir / "example.py")}}
        self.compiled = {"synthetic/action_1": "synthetic action\n"}
        self.dump("metadata.json", self.metadata)
        self.dump("fixtures.json", [self.case])
        self.dump("compiled-functions.json", self.compiled)
        self.dump("summary.json", {"metadata": self.metadata, "cases": [analyze(self.case, self.rows)], "pass": True, "error": None})
        (self.run / "commands.jsonl").write_text("", encoding="utf-8")
        self.write_rows()
        self.root_patch = patch.object(characterize, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def dump(self, name, value):
        (self.run / name).write_text(json.dumps(value), encoding="utf-8")

    def write_rows(self):
        (self.run / "observations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")

    def load(self):
        return characterize.load_run("results/synthetic", {"synthetic": self.case}, self.compiled)

    def test_complete_records_can_be_reanalyzed_without_a_server(self):
        analyses, rows, evidence = self.load()
        self.assertTrue(analyses[0]["pass"])
        self.assertEqual(rows["synthetic"], self.rows)
        self.assertEqual(evidence["sample_count"], 4)

    def test_saved_pass_cannot_override_changed_observations(self):
        self.rows[-1]["values"]["q"] = 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "raw observations do not pass"):
            self.load()

    def test_missing_before_action_sample_cannot_hide_a_transition(self):
        self.rows.pop(2)
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "observation boundaries"):
            self.load()

    def test_game_timestamp_must_match_the_relative_tick(self):
        self.rows[-1]["game_time"] += 1
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "game time"):
            self.load()

    def test_probe_domain_is_checked_before_reanalysis(self):
        self.rows[0]["values"]["q"] = 7
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "invalid probe values"):
            self.load()

    def test_changed_harness_snapshot_is_rejected(self):
        (self.run / "harness-source/example.py").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source digest differs"):
            self.load()

    def test_edited_saved_summary_is_rejected(self):
        summary = json.loads((self.run / "summary.json").read_text())
        summary["cases"][0]["checks"][0]["observed"] = 99
        self.dump("summary.json", summary)
        with self.assertRaisesRegex(ValueError, "summary differs"):
            self.load()

    def test_changed_build_is_rejected(self):
        self.metadata["server_sha1"] = "0" * 40
        self.dump("metadata.json", self.metadata)
        with self.assertRaisesRegex(ValueError, "server build differs"):
            self.load()


if __name__ == "__main__":
    unittest.main()
