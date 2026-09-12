"""Evidence controls for the independent GameTest reference and raw trace audit."""
import copy
import unittest

from rtl2mc.gametest import audit_samples, oracle, reference


class GameTestEvidenceTests(unittest.TestCase):
    def test_reference_truth_tables(self):
        # Explicit reference tables keep a shared arithmetic/mux bug visible.
        adder = [(0, 0), (1, 0), (1, 0), (0, 1), (1, 0), (0, 1), (0, 1), (1, 1)]
        mux = [0, 1, 0, 1, 0, 0, 1, 1]
        for i in range(8):
            self.assertEqual(reference("adder", {"a": i & 1, "b": (i >> 1) & 1, "cin": i >> 2}, None),
                             dict(zip(("sum", "cout"), adder[i])))
            self.assertEqual(reference("mux2", {"a": i & 1, "b": (i >> 1) & 1, "select_b": i >> 2}, None),
                             {"y": mux[i]})

    def test_sequential_reset_enable_wrap_and_low_hold(self):
        steps = [(1, 0, 0), (1, 1, 1), (0, 1, 1), (0, 1, 0),
                 (0, 0, 1), (0, 1, 1), (0, 1, 1), (1, 1, 0)]
        events = []
        for i, (reset, enable, serial) in enumerate(steps):
            events.extend([{"tick": 20 * i, "inputs": {"clk": 0, "reset": reset, "enable": enable, "serial_in": serial}},
                           {"tick": 20 * i + 10, "inputs": {"clk": 1}}])
        vectors = {"initial": {"clk": 0}, "events": events, "checks": [20 * i + 19 for i in range(8)]}
        for top, expected in (("counter", [0, 0, 1, 2, 2, 3, 0, 0]), ("shift2", [0, 0, 1, 2, 2, 1, 3, 0])):
            rows, coverage = oracle(top, vectors)
            self.assertEqual([r["outputs"]["q"] for r in rows if r["phase"] == "settled"], expected)
            self.assertEqual([r["outputs"]["q"] for r in rows if r["phase"] == "low_hold"], expected[1:-1])
            self.assertEqual(coverage["low_hold_checks"], 6)

    def test_trace_audit_rejects_missing_duplicate_or_false_readings(self):
        case = {"saved_outputs": {"y": 0}, "checks": [{"tick": 10, "phase": "settled", "outputs": {"y": 1}}],
                "outputs": [{"name": "out_y_0", "port": "y", "bit_index": 0}]}
        rows = [{"tick": -1, "gametest_tick": 20, "phase": "saved_world", "outputs": {"out_y_0": {"power": 0, "expected": 0}}},
                {"tick": 10, "gametest_tick": 50, "phase": "settled", "outputs": {"out_y_0": {"power": 15, "expected": 1}}}]
        audit_samples(case, rows)
        variants = [rows[:1], [rows[0], rows[0]], list(reversed(rows))]
        for key, value in (("power", 0), ("power", 16), ("expected", 0)):
            changed = copy.deepcopy(rows)
            changed[1]["outputs"]["out_y_0"][key] = value
            variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                audit_samples(case, changed)


if __name__ == "__main__":
    unittest.main()
