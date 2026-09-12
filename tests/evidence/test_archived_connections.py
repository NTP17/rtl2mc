"""Reanalyze original measurements; requires the optional lab evidence bundle."""
import copy
import json
import sys
import unittest
from unittest.mock import patch
from redstone_pdk.project import ROOT, read_json
from redstone_pdk import connections
from redstone_pdk.connection_fixtures import connection_cases
from redstone_pdk.connection_views import PREFIX, top_name
from redstone_pdk.model_validation import compare_samples, sha


class ArchivedConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = read_json(ROOT / connections.CONTRACT)

    def test_all_recorded_boundaries_and_raw_commands_reproduce_admission(self):
        rebuilt = connections.build_contract(self.contract["evidence"]["run"])
        self.assertEqual(rebuilt, self.contract)
        c = rebuilt["coverage"]
        self.assertEqual((c["cases"], c["admitted"], c["negative_controls"], c["native_model_matches"]), (204, 200, 4, 172))


    def test_corrupted_admission_never_validates(self):
        damaged = copy.deepcopy(self.contract); damaged["cases"][0]["graph"]["nodes"][0]["delay"] = 999
        def reader(path):
            return damaged if path == ROOT / connections.CONTRACT else read_json(path)
        with patch.object(connections, "read_json", side_effect=reader):
            self.assertIn("differs from raw evidence", " ".join(connections.validate_connections(include_eda=False)))
