"""Evidence, physical-input independence, and unsupported-envelope checks."""
import copy
import unittest

from redstone_pdk.event_model import Circuit, UnsupportedCircuit, simulate_fixture
from redstone_pdk.fixtures import cases
from redstone_pdk.model_validation import build_model_contract, compare_samples
from redstone_pdk.project import ROOT, read_json


FIXTURES = {f["id"]: f for f in cases("repeater") + cases("repeater_broad")}


class EventModelTests(unittest.TestCase):

    def test_fixture_names_metadata_and_expectations_are_not_inputs(self):
        original = FIXTURES["repeater_hold_d2_q1_north_repeater"]
        physical = {key: copy.deepcopy(original[key]) for key in ("setup", "prepare", "actions", "probes", "ticks")}
        expected = simulate_fixture(original)
        self.assertEqual(expected, simulate_fixture(physical))
        physical.update(id="nothing_to_do_with_repeaters", experiment={"delay_setting": 99, "initial_output": 0},
                        checks=[{"powered": "deliberately wrong"}], baseline_checks={"powered": 0})
        self.assertEqual(expected, simulate_fixture(physical))

    def test_physical_driver_type_controls_the_lock_release_result(self):
        fixture = copy.deepcopy(FIXTURES["repeater_lockseq_d2_q0_north_repeater_release_at_due"])
        reference = FIXTURES["repeater_lockseq_d2_q0_north_comparator_release_at_due"]
        # Retain the repeater name/experiment metadata while changing actual blocks.
        fixture["setup"] = copy.deepcopy(reference["setup"])
        fixture["probes"] = copy.deepcopy(reference["probes"])
        self.assertEqual(simulate_fixture(fixture), simulate_fixture(reference))

    def test_physical_delay_controls_pulse_behavior(self):
        fixture = copy.deepcopy(FIXTURES["repeater_pulse_d2_high_w1"])
        reference = FIXTURES["repeater_pulse_d4_high_w1"]
        fixture["setup"] = copy.deepcopy(reference["setup"])
        fixture["ticks"] = reference["ticks"]
        self.assertEqual(simulate_fixture(fixture), simulate_fixture(reference))

    def test_sample_damage_is_not_accepted_as_a_match(self):
        prediction = simulate_fixture(FIXTURES["repeater_pulse_d2_high_w1"])["samples"]
        damaged = copy.deepcopy(prediction)
        damaged[2]["values"]["powered"] ^= 1
        with self.assertRaises(ValueError):
            compare_samples(prediction, damaged, "damaged")
        with self.assertRaises(ValueError):
            compare_samples(prediction, prediction[:-1], "missing")

    def test_vertical_and_forced_state_commands_are_rejected(self):
        for command in ("setblock 0 81 0 minecraft:redstone_wire", "setblock 0 80 0 minecraft:repeater[powered=true]", "setblock 0 80 0 minecraft:redstone_torch"):
            with self.subTest(command=command), self.assertRaises(UnsupportedCircuit):
                Circuit().command(command, setup=True)

    def test_multiple_wire_drivers_are_rejected(self):
        world = Circuit()
        for command in ("setblock 0 80 0 minecraft:redstone_wire", "setblock -1 80 0 minecraft:redstone_block", "setblock 1 80 0 minecraft:redstone_block"):
            world.command(command, setup=True)
        with self.assertRaises(UnsupportedCircuit):
            world.validate_topology({(-1, 80, 0), (1, 80, 0)})

    def test_independent_fanout_ties_are_rejected(self):
        world = Circuit()
        for command in ("setblock 0 80 0 minecraft:redstone_wire", "setblock -1 80 0 minecraft:repeater[facing=east]", "setblock 1 80 0 minecraft:repeater[facing=west]"):
            world.command(command, setup=True)
        with self.assertRaises(UnsupportedCircuit):
            world.validate_topology({(0, 80, -1)})

    def test_runtime_topology_edits_and_undeclared_sources_are_rejected(self):
        world = Circuit()
        world.command("setblock 0 80 0 minecraft:repeater", setup=True)
        world.validate_topology({(1, 80, 0)})
        for command in ("setblock 0 80 0 minecraft:air", "setblock 2 80 0 minecraft:redstone_block"):
            with self.subTest(command=command), self.assertRaises(UnsupportedCircuit):
                world.command(command)


if __name__ == "__main__":
    unittest.main()
