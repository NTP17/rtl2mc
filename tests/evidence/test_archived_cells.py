"""Reanalyze original measurements; requires the optional lab evidence bundle."""
import copy
import json
import unittest
from unittest.mock import patch
from redstone_pdk import cells
from redstone_pdk.cell_fixtures import buffer_cases
from redstone_pdk.cell_views import render_sdf
from redstone_pdk.event_model import simulate_fixture
from redstone_pdk.model_validation import compare_samples
from redstone_pdk.project import ROOT, read_json

RUN = "results/20260910T170353Z-1c3356"


class ArchivedCellAdmissionTests(unittest.TestCase):
    def test_complete_fresh_game_evidence_matches_both_models(self):
        admission = cells.build_admission(RUN)
        self.assertEqual(admission, read_json(ROOT / cells.ADMISSION))
        self.assertEqual(admission["coverage"]["cases"], 64)
        self.assertEqual(admission["coverage"]["raw_probe_and_time_replies_checked"], 3136)
        self.assertEqual(admission["coverage"]["input_edges"], 384)


    def test_raw_replies_and_execution_order_cannot_disagree_with_observations(self):
        commands = [json.loads(line) for line in (ROOT / RUN / "commands.jsonl").read_text().splitlines()]
        observed = {}
        for line in (ROOT / RUN / "observations.jsonl").read_text().splitlines():
            row = json.loads(line); observed.setdefault(row["case"], []).append(row)
        damaged = copy.deepcopy(commands)
        probe = next(r for r in damaged if r["command"] == "data get storage pdk_lab:sample values")
        probe["response"] = probe["response"].replace("out: 0", "out: 15")
        with self.assertRaisesRegex(ValueError, "probe reply"):
            cells.audit_commands(damaged, buffer_cases(), observed)
        damaged = [r for r in commands if r["command"] != "function pdk_lab:cell_rsbuf2_r0_q0_minimum/action_0"]
        with self.assertRaisesRegex(ValueError, "execution order"):
            cells.audit_commands(damaged, buffer_cases(), observed)


    def test_tampered_admission_cannot_validate(self):
        damaged = read_json(ROOT / cells.ADMISSION)
        damaged["coverage"]["input_edges"] += 1
        def reader(path):
            return damaged if path == ROOT / cells.ADMISSION else read_json(path)
        with patch.object(cells, "read_json", side_effect=reader):
            self.assertIn("differs from evidence", " ".join(cells.validate_cells()))
