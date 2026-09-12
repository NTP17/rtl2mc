"""Mapping failure controls and geometry extraction checks, without Minecraft."""
import copy
import json
import unittest
from pathlib import Path

from redstone_pdk.rtl import graph_from_json,logical_verilog
from redstone_pdk.router import route,check_layout
from redstone_pdk.mapping_views import timing_budget
from redstone_pdk.mapping_validation import validate_vectors,example_vectors

ROOT = Path(__file__).resolve().parents[1]


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((ROOT/"tests/fixtures/counter-lowered.json").read_text())
        self.graph = graph_from_json(self.raw,"counter")
        self.layout = route(self.graph)

    def test_async_register_rejected(self):
        next(iter(self.raw["modules"]["counter"]["cells"].values()))["type"] = "$_DFF_PP0_"
        with self.assertRaisesRegex(ValueError,"Unsupported mapped cell"):
            graph_from_json(self.raw,"counter")

    def test_gated_clock_rejected(self):
        cells = self.raw["modules"]["counter"]["cells"]
        ff = next(c for c in cells.values() if c["type"] == "$_DFF_P_")
        ff["connections"]["C"] = ff["connections"]["D"]
        with self.assertRaisesRegex(ValueError,"one ungated"):
            graph_from_json(self.raw,"counter")

    def test_unknown_rejected(self):
        self.raw["modules"]["counter"]["ports"]["q"]["bits"][0] = "x"
        with self.assertRaisesRegex(ValueError,"X/Z"):
            graph_from_json(self.raw,"counter")

    def test_multiple_driver_rejected(self):
        cells = self.raw["modules"]["counter"]["cells"]
        cells["duplicate"] = copy.deepcopy(next(iter(cells.values())))
        with self.assertRaisesRegex(ValueError,"Multiple drivers"):
            graph_from_json(self.raw,"counter")

    def test_capacity_rejected(self):
        with self.assertRaisesRegex(ValueError,"capacity"):
            graph_from_json(self.raw,"counter",max_cells=1)

    def test_combinational_cycle_rejected(self):
        cell = next(c for c in self.raw["modules"]["counter"]["cells"].values() if c["type"] == "$_NOR_")
        cell["connections"]["A"] = cell["connections"]["Y"]
        with self.assertRaisesRegex(ValueError,"Combinational feedback"):
            graph_from_json(self.raw,"counter")

    def test_register_initialization_rejected(self):
        self.raw["modules"]["counter"]["netnames"]["q"]["attributes"]["init"] = "00"
        with self.assertRaisesRegex(ValueError,"initialization"):
            graph_from_json(self.raw,"counter")

    def test_missing_support_rejected(self):
        self.layout["blocks"] = [b for b in self.layout["blocks"] if b["position"] != (280,83,18)]
        with self.assertRaisesRegex(ValueError,"support"):
            check_layout(self.layout)

    def test_repeater_change_rejected(self):
        target = next(c for c in self.layout["components"] if c["kind"] == "BUF2")
        next(b for b in self.layout["blocks"] if b["position"] == target["position"])["state"] = "repeater[facing=north,delay=4]"
        with self.assertRaisesRegex(ValueError,"setting mismatch"):
            check_layout(self.layout)

    def test_unregistered_redstone_rejected(self):
        self.layout["blocks"].append({"position":(282,84,21),"state":"redstone_wire"})
        with self.assertRaisesRegex(ValueError,"unregistered"):
            check_layout(self.layout)

    def test_net_relabel_rejected(self):
        self.layout["wires"][0]["net"] = "incorrect"
        with self.assertRaises(ValueError): check_layout(self.layout)

    def test_clock_balanced(self):
        self.assertGreater(self.layout["clock_delay"],0)
        self.assertTrue(check_layout(self.layout)["pass"])

    def test_insufficient_settle_rejected(self):
        budget = timing_budget(self.graph,self.layout)
        vectors = example_vectors(self.graph,budget); vectors["checks"] = [1]
        with self.assertRaisesRegex(ValueError,"deadline"):
            validate_vectors(self.graph,budget,vectors)

    def test_wrong_phase_rejected(self):
        budget = timing_budget(self.graph,self.layout)
        vectors = example_vectors(self.graph,budget)
        vectors["events"][1]["inputs"]["enable"] = 1
        with self.assertRaisesRegex(ValueError,"falling clock"):
            validate_vectors(self.graph,budget,vectors)

    def test_early_first_clock_rejected(self):
        budget = timing_budget(self.graph,self.layout)
        vectors = example_vectors(self.graph,budget)
        vectors["events"][1]["tick"] = 1
        with self.assertRaisesRegex(ValueError,"First clock"):
            validate_vectors(self.graph,budget,vectors)

    def test_ascending_port_range(self):
        g = {"ports":{"a":{"direction":"input","bits":[2,3],"upto":1,"offset":4},
                       "y":{"direction":"output","bits":[2,3]}},"cells":[]}
        v = logical_verilog(g,"ports")
        self.assertIn("input [4:5] a",v)
        self.assertIn("assign n2 = a[5]",v)
        self.assertIn("assign n3 = a[4]",v)

if __name__ == "__main__": unittest.main()
