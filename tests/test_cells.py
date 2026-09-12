"""Admission boundaries, evidence independence and fail-closed cell exports."""
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


class CellAdmissionTests(unittest.TestCase):

    def test_exact_minimum_and_long_idle_are_legal_for_both_polarities(self):
        for setting in range(1, 5):
            cell = cells.cell_definition(setting)
            for initial in (0, 1):
                cells.validate_protocol(cell, initial, [(0, 1-initial), (2*setting+1, initial), (1000, 1-initial)])
                cells.validate_protocol(cell, initial, [])

    def test_illegal_width_order_nonbinary_and_fractional_tick_are_rejected(self):
        for setting in range(1, 5):
            cell = cells.cell_definition(setting)
            for initial in (0, 1):
                for edges in ([(0, 1-initial), (2*setting, initial)], [(1, 1-initial), (1, initial)],
                              [(4, 1-initial), (3, initial)], [(0, initial)], [(0, 2)], [(0.5, 1-initial)], [(-1, 1-initial)]):
                    with self.subTest(setting=setting, initial=initial, edges=edges), self.assertRaises(ValueError):
                        cells.validate_protocol(cell, initial, edges)

    def test_initialization_is_required(self):
        cell = cells.cell_definition(4)
        for initial, settled in ((2, 20), (None, 20), (0, 19), (1, 19)):
            with self.assertRaises(ValueError):
                cells.validate_protocol(cell, initial, [], settled_game_ticks=settled)

    def test_names_and_hypotheses_cannot_change_a_cell_prediction(self):
        for fixture in buffer_cases():
            cell = cells.cell_definition(fixture["experiment"]["delay_setting"])
            physical = {k: copy.deepcopy(fixture[k]) for k in ("setup", "prepare", "actions", "probes", "ticks")}
            physical.update(id="misleading_name", experiment={"cell": "wrong"}, checks=[{"tick": 0, "values": {"out": 999}}])
            self.assertEqual(cells.expected_samples(cell, physical), cells.expected_samples(cell, fixture))
            compare_samples(cells.expected_samples(cell, physical), simulate_fixture(physical)["samples"], "unnamed")

    def test_geometry_side_driver_output_load_and_forced_state_are_rejected(self):
        fixture = buffer_cases()[0]
        variants = []
        for extra in ("setblock 10 80 4 minecraft:repeater[facing=north]", "setblock 12 80 5 minecraft:redstone_wire"):
            f = copy.deepcopy(fixture); f["setup"].append(extra); variants.append(f)
        f = copy.deepcopy(fixture); f["setup"][1] = "setblock 10 80 5 minecraft:repeater[facing=west,delay=1,powered=true]"; variants.append(f)
        f = copy.deepcopy(fixture); f["setup"][0] = "setblock 9 80 6 minecraft:redstone_wire"; variants.append(f)
        f = copy.deepcopy(fixture); f["actions"][0] = ["setblock 10 80 4 minecraft:redstone_block"]; variants.append(f)
        for f in variants:
            with self.assertRaises(ValueError):
                cells.fixture_inputs(cells.cell_definition(1), f)


    def test_sdf_requires_known_cells_and_concrete_instance_paths(self):
        lib = read_json(ROOT / cells.LIBRARY)
        for instances in ({"u0": "unknown"}, {"*": "RSBUF2"}, {"u0)": "RSBUF2"}, {}):
            with self.assertRaises(ValueError):
                render_sdf(lib, instances, "top")
        self.assertIn("(INSTANCE block/u0)", render_sdf(lib, {"block/u0": "RSBUF2"}, "top"))



if __name__ == "__main__":
    unittest.main()
