"""Verify measurement analysis and experiment coverage without emulating redstone."""
import unittest

from redstone_pdk.fixtures import BOUNDS, cases, compile_functions
from redstone_pdk.results import active_intervals, analyze, check_invariant


def rows(values):
    return [{"relative_game_tick": tick, "values": {"q": value}} for tick, value in values]


class PulseAnalysisTests(unittest.TestCase):
    def test_pulse_can_begin_after_input_has_already_ended(self):
        samples = rows([(-1, 0), (0, 0), (1, 0), (2, 0), (3, 0), (4, 1), (5, 1), (6, 1), (7, 1), (8, 0)])
        self.assertEqual(active_intervals(samples, "q", 1), [[4, 8]])

    def test_negative_pulse_and_suppressed_pulse(self):
        self.assertEqual(active_intervals(rows([(-1, 1), (0, 1), (1, 0), (2, 0), (3, 1)]), "q", 0), [[1, 3]])
        self.assertEqual(active_intervals(rows([(-1, 1), (0, 1), (1, 1)]), "q", 0), [])

    def test_censored_boundary_is_never_invented(self):
        self.assertEqual(active_intervals(rows([(-1, 0), (0, 0), (1, 1), (2, 1)]), "q", 1), [[1, None]])
        self.assertEqual(active_intervals(rows([(-1, 1), (0, 1), (1, 0)]), "q", 1), [[None, 1]])

    def test_observed_same_tick_changes_remain_visible(self):
        self.assertEqual(active_intervals(rows([(-1, 0), (0, 0), (1, 1), (1, 0), (2, 0)]), "q", 1), [[1, 1]])

    def test_missing_ticks_cannot_pass_an_absence_check(self):
        case = {"id": "missing", "ticks": 3, "actions": {0: []}, "checks": [],
                "pulse_hypotheses": [{"probe": "q", "active_value": 1, "intervals": []}]}
        result = analyze(case, rows([(-1, 0), (0, 0), (3, 0)]))
        self.assertFalse(result["pass"])
        self.assertEqual(result["integrity"]["missing_ticks"], [1, 2])


class LockAnalysisTests(unittest.TestCase):
    def test_change_under_continuous_lock_is_detected(self):
        samples = [{"relative_game_tick": t, "values": {"locked": 1, "q": q}} for t, q in [(0, 0), (1, 1)]]
        self.assertFalse(check_invariant({"kind": "hold_while_locked", "lock": "locked", "state": "q"}, samples)["pass"])

    def test_lock_assertion_boundary_is_not_assumed_to_have_internal_order(self):
        samples = [{"relative_game_tick": 0, "values": {"locked": 0, "q": 0}},
                   {"relative_game_tick": 1, "values": {"locked": 1, "q": 1}}]
        result = check_invariant({"kind": "hold_while_locked", "lock": "locked", "state": "q"}, samples)
        self.assertTrue(result["pass"])
        self.assertEqual(result["samples_checked"], 0)

    def test_either_side_can_hold_the_lock(self):
        rule = {"kind": "lock_equals_or", "lock": "locked", "drivers": ["n", "s"]}
        for north, south in ((0, 1), (1, 0), (1, 1), (0, 0)):
            sample = {"relative_game_tick": 0, "values": {"n": north, "s": south, "locked": int(bool(north or south))}}
            self.assertTrue(check_invariant(rule, [sample])["pass"])


class CoverageTests(unittest.TestCase):
    def test_positive_and_negative_width_sweeps_are_complete(self):
        combinations = {(c["experiment"]["delay_setting"], c["experiment"]["active_value"], c["experiment"]["input_width_game_ticks"])
                        for c in cases("repeater_pulses")}
        self.assertEqual(combinations, {(d, value, width) for d in range(1, 5) for value in (0, 1) for width in range(1, 11)})

    def test_physical_lock_driver_coverage(self):
        combinations = {(c["experiment"]["delay_setting"], c["experiment"]["initial_output"], c["experiment"]["side"], c["experiment"]["driver"])
                        for c in cases("repeater_locks") if c["experiment"]["family"] == "hold"}
        self.assertEqual(combinations, {(d, q, side, driver) for d in range(1, 5) for q in (0, 1)
                                       for side in ("north", "south") for driver in ("repeater", "comparator")})

    def test_unique_identifiers_and_original_suite_preserved(self):
        self.assertEqual(len(cases("core")), 10)
        identifiers = [case["id"] for case in cases()]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_prelude_is_exported_and_stays_in_reserved_volume(self):
        functions = compile_functions()
        low, high = BOUNDS
        for case in cases("repeater_locks"):
            for index, stage in enumerate(case.get("prepare", [])):
                self.assertIn(f"{case['id']}/prepare_{index}", functions)
                for command in stage["commands"]:
                    position = list(map(int, command.split()[1:4]))
                    self.assertTrue(all(a <= v <= b for a, v, b in zip(low, position, high)))


if __name__ == "__main__":
    unittest.main()
