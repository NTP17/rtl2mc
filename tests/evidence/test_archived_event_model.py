"""Reanalyze original measurements; requires the optional lab evidence bundle."""
import copy
import unittest
from redstone_pdk.event_model import Circuit, UnsupportedCircuit, simulate_fixture
from redstone_pdk.fixtures import cases
from redstone_pdk.model_validation import build_model_contract, compare_samples
from redstone_pdk.project import ROOT, read_json


class ArchivedEventModelTests(unittest.TestCase):
    def test_complete_vanilla_corpus_and_recorded_events_match(self):
        contract = build_model_contract()
        self.assertEqual(contract, read_json(ROOT / "models/repeater-event-v1.json"))
        self.assertEqual(contract["coverage"]["cases"], 772)
        self.assertEqual(contract["coverage"]["probe_readings"], 121168)
        self.assertEqual(contract["coverage"]["engine_scheduled_events"], 356)
