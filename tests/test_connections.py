"""Connection admission, geometry hazards, and synthesis export corruption."""
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

sys.path.insert(0, str(ROOT / "tools"))
from check_network_eda import check_topology


class ConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = {f["id"]: f for f in connection_cases()}
        cls.contract = read_json(ROOT / connections.CONTRACT)


    def test_strength_one_works_and_zero_cannot_export(self):
        for setting in range(1, 5):
            g = connections.extract_network(self.fixtures[f"net_length_15_d{setting}"])
            self.assertEqual(g["nodes"][1]["input_high_strength"], 1)
            with self.assertRaisesRegex(ValueError, "15 dust"):
                connections.extract_network(self.fixtures[f"net_length_16_d{setting}"])
            p = connections.predict_fixture(self.fixtures[f"net_length_16_d{setting}"], allow_attenuated_off=True)
            self.assertTrue(all(row["values"]["cell_q"] == 0 for row in p["samples"]))

    def test_fixture_names_experiments_and_hypotheses_are_not_model_inputs(self):
        for name in ("net_chain_2_4_1", "net_fanout3_d4_q1", "net_comparator_3_2_q0"):
            f = copy.deepcopy(self.fixtures[name]); expected = connections.predict_fixture(f)
            f.update(id="wrong", experiment={"admission_expected": False}, checks=[], baseline_checks={"bogus": 999})
            self.assertEqual(connections.predict_fixture(f), expected)

    def test_empty_sides_no_vertical_routes_and_single_fixed_source(self):
        original = self.fixtures["net_chain_1_1_1"]
        for extra in ("setblock 24 80 17 minecraft:redstone_wire", "setblock 24 81 16 minecraft:redstone_wire",
                      "setblock 50 80 30 minecraft:redstone_wire", "setblock 40 80 30 minecraft:redstone_block"):
            f = copy.deepcopy(original); f["setup"].append(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                connections.extract_network(f)
        f = copy.deepcopy(original); f["actions"][0] = ["setblock 23 80 16 minecraft:redstone_block"]
        with self.assertRaisesRegex(ValueError, "fixed external"):
            connections.extract_network(f)

    def test_loop_and_short_dwell_rejected(self):
        f = copy.deepcopy(self.fixtures["net_length_5_d1"])
        f["setup"] += [f"setblock {x} 80 17 minecraft:redstone_wire" for x in (26, 27)]
        with self.assertRaisesRegex(ValueError, "loops"):
            connections.extract_network(f)
        for initial in (0, 1):
            f = copy.deepcopy(self.fixtures[f"net_fanout3_d4_q{initial}"])
            f["actions"][8] = f["actions"].pop(9)
            with self.assertRaisesRegex(ValueError, "dwells"):
                connections.extract_network(f)
        f = copy.deepcopy(self.fixtures["net_chain_4_4_4"])
        f["prepare"][0]["settle_game_ticks"] = 43
        with self.assertRaisesRegex(ValueError, "44 game ticks"):
            connections.extract_network(f)

    def test_noninteger_timing_and_forced_state_rejected(self):
        f = copy.deepcopy(self.fixtures["net_chain_1_1_1"])
        f["actions"][0.5] = f["actions"].pop(0)
        with self.assertRaises(ValueError):
            connections.extract_network(f)
        for command in ("setblock 24 80 16 minecraft:repeater[facing=west,delay=1,powered=true]",
                        "setblock 24 80 16 minecraft:comparator[facing=west,mode=subtract]"):
            with self.assertRaises(ValueError):
                connections.parse_command(command)

    def test_export_manifest_hashes_are_actual_file_bytes(self):
        manifest = read_json(ROOT / PREFIX / "manifest.json")
        for name, checksum in manifest["files"].items():
            self.assertEqual(sha(ROOT / name), checksum, name)

    def test_changed_synthesis_cell_name_type_or_wiring_invalidates_certificate(self):
        linked = read_json(ROOT / "tests/fixtures/network-linked.json")["modules"]
        record = next(r for r in self.contract["cases"] if r["fixture"] == "net_fanout3_d4_q1")
        original = linked[top_name(record)]
        check_topology(original, record)
        renamed = copy.deepcopy(original); renamed["cells"]["renamed"] = renamed["cells"].pop("n0")
        retimed = copy.deepcopy(original); retimed["cells"]["n0"]["type"] = "RNETBUF8"
        bypass = copy.deepcopy(original); bypass["cells"]["n1"]["connections"]["A"] = bypass["ports"]["A"]["bits"]
        folded = copy.deepcopy(original); folded["ports"]["Q"]["bits"][1] = folded["ports"]["Q"]["bits"][0]
        for damaged in (renamed, retimed, bypass, folded):
            with self.assertRaises(ValueError):
                check_topology(damaged, record)



if __name__ == "__main__":
    unittest.main()
