"""Damage tests for direct engine evidence, using preserved real observations."""
import copy
import json
import unittest

from redstone_pdk.engine_trace import BASELINE
from redstone_pdk.project import ROOT, read_json
from redstone_pdk.trace_analysis import verify_case, verify_run


PILOT = ROOT / "results/20260910T161924Z-trace-3d44a1"
FULL = ROOT / "results/20260910T162009Z-trace-c0f92a"
NAME = "repeater_lockseq_d2_q0_north_comparator_release_at_due"


class EngineTraceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = next(f for f in read_json(PILOT / "fixtures.json") if f["id"] == NAME)
        def rows(path):
            with path.open(encoding="utf-8") as stream:
                return [r for line in stream if (r := json.loads(line)).get("case") == NAME]
        cls.events = rows(PILOT / "engine-events.jsonl")
        cls.samples = rows(PILOT / "observations.jsonl")
        cls.baseline = rows(BASELINE / "observations.jsonl")

    def check_damaged(self, events=None, samples=None):
        with self.assertRaises(ValueError):
            verify_case(self.fixture, self.events if events is None else events,
                        self.samples if samples is None else samples, self.baseline)

    def test_preserved_full_engine_events_and_samples_agree(self):
        result = verify_run(FULL)
        self.assertEqual((result["case_count"], result["sample_count"], result["accepted_and_dispatched_events"]), (96, 2808, 356))
        self.assertEqual(result["differing_driver_pairs"], 12)

    def test_missing_scheduled_lock_read_is_rejected(self):
        self.check_damaged(events=[e for e in self.events if not (e["event"] == "lock_read" and e.get("site") == "scheduled_tick" and e["tick"] == 8)])

    def test_changed_queued_priority_is_rejected(self):
        events = copy.deepcopy(self.events)
        next(e for e in events if e["event"] == "enqueue_accepted")["priority"] = 0
        self.check_damaged(events=events)

    def test_missing_dispatch_completion_is_rejected(self):
        events = copy.deepcopy(self.events)
        events.remove(next(e for e in events if e["event"] == "dispatch_end"))
        self.check_damaged(events=events)

    def test_output_change_during_locked_tick_is_rejected(self):
        events = copy.deepcopy(self.events)
        row = next(e for e in events if e["event"] == "block_tick_exit" and e["block"] == "dut" and e["tick"] == 8)
        row["state"] = row["state"].replace("powered=false", "powered=true")
        self.check_damaged(events=events)

    def test_missing_sample_is_rejected(self):
        self.check_damaged(samples=self.samples[:-1])

    def test_changed_observed_sample_is_rejected(self):
        samples = copy.deepcopy(self.samples)
        next(s for s in samples if s["relative_game_tick"] == 8)["values"]["powered"] = 1
        self.check_damaged(samples=samples)

    def test_event_clock_detached_from_samples_is_rejected(self):
        events = copy.deepcopy(self.events)
        for row in events:
            row["game_time"] += 1
            if "due_game_time" in row:
                row["due_game_time"] += 1
        self.check_damaged(events=events)


if __name__ == "__main__":
    unittest.main()
