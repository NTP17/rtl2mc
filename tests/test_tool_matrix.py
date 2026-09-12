"""Cross-tool annotation checks must reject incomplete or absent evidence."""
import unittest
import re

from rtl2mc.verification import xcelium_annotation, questa_annotation, diagnostic_text, DIAGNOSTICS
from rtl2mc.toolchain import select


class AnnotationTests(unittest.TestCase):
    def test_questa_requires_compiler_and_library_tool(self):
        found = {n: {"available": True} for n in ("yosys", "questa", "vlog", "vlib", "java")}
        self.assertEqual(select(found, simulation="questa")["missing"], [])
        for name in ("vlog", "vlib"):
            incomplete = {k:v for k,v in found.items() if k != name}
            self.assertIn("questa", select(incomplete, simulation="questa")["missing"])

    def test_questa_rejects_partial_and_ambiguous_annotation(self):
        sdf = '(IOPATH A Y (2) (2)) (SETUPHOLD D CLK (11) (3)) (WIDTH CLK (17))'
        log = ('# SDF statistics: No. of Pathdelays = 1 Annotated = 100.00% No. of Tchecks = 2 Annotated = 100.00%\n'
               '# Path Delays 1 1 100.00\n# SETUPHOLD 1 1 100.00\n# WIDTH 1 1 100.00\n')
        complete = ('Unannotated Specify Objects Report:\n===================================\n'
                    'All instances with specify block objects were completely annotated.\n')
        self.assertEqual(questa_annotation(log, sdf, complete)['Tchecks']['annotated'], 2)
        for bad in (log.replace('WIDTH 1 1', 'WIDTH 1 0'), log + log, '',
                    log.replace('Tchecks = 2', 'Tchecks = 1'), log.replace('100.00%', '50.00%', 1)):
            with self.subTest(log=bad), self.assertRaises(ValueError):
                questa_annotation(bad, sdf, complete)
        with self.assertRaises(ValueError):
            questa_annotation(log, sdf, complete + '/dut: (UATC)\n')

    def test_questa_combinational_zero_timing_checks(self):
        log = ('# SDF statistics: No. of Pathdelays = 1 Annotated = 100.00% No. of Tchecks = 0 Annotated = 0.00%\n'
               '# Path Delays 1 1 100.00\n')
        complete = ('Unannotated Specify Objects Report:\n===================================\n'
                    'All instances with specify block objects were completely annotated.\n')
        self.assertEqual(questa_annotation(log, '(IOPATH A Y (2) (2))', complete)['Tchecks']['expected'], 0)

    def test_questa_width_control_keeps_unexpected_errors_fatal(self):
        log = ('# ** Error: $width( posedge CLK:120 ns, :125 ns, 17 ns );\n'
               '# Time: 125 ns Process: /width_tb/dut/c_dff/#Width#\n# RMAP_WIDTH_CAUGHT\n')
        self.assertIsNone(re.search(DIAGNOSTICS, diagnostic_text(log, 'questa-width')))
        self.assertIsNotNone(re.search(DIAGNOSTICS, diagnostic_text(log, 'questa-sdf')))
        self.assertIsNotNone(re.search(DIAGNOSTICS, diagnostic_text(log + '# ** Error: unrelated failure\n', 'questa-width')))
        with self.assertRaises(ValueError):
            diagnostic_text(log + log, 'questa-width')

    def test_xcelium_annotation_requires_all_generated_entries(self):
        sdf = '(IOPATH A Y (2) (2)) (SETUPHOLD D CLK (11) (3)) (WIDTH CLK (17))'
        log = ('No. of Pathdelays = 1 No. of Disabled Pathdelays = 0 Annotated = 100.00% (1/1)\n'
               'No. of Tchecks = 2 No. of Disabled Tchecks = 0 Annotated = 100.00% (2/2)')
        self.assertEqual(xcelium_annotation(log, sdf)['Tchecks']['annotated'], 2)
        bad = [log.replace('(2/2)', '(1/2)'), log.replace('Disabled Tchecks = 0', 'Disabled Tchecks = 1'),
               log.splitlines()[0], log + '\n' + log, log.replace('Pathdelays = 1', 'Pathdelays = 0')]
        for text in bad:
            with self.subTest(log=text), self.assertRaises(ValueError):
                xcelium_annotation(text, sdf)

    def test_combinational_design_allows_zero_timing_checks(self):
        log = ('No. of Pathdelays = 1 No. of Disabled Pathdelays = 0 Annotated = 100.00% (1/1)\n'
               'No. of Tchecks = 0 No. of Disabled Tchecks = 0 Annotated = 0.00% (0/0)')
        self.assertEqual(xcelium_annotation(log, '(IOPATH A Y (2) (2))')['Tchecks']['expected'], 0)


if __name__ == '__main__':
    unittest.main()
