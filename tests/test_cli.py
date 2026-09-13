# SPDX-License-Identifier: Apache-2.0
"""Public CLI input forms, configuration selection and reproducible snapshots."""
from contextlib import chdir, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from rtl2mc import cli
from rtl2mc.filelist import parse_sources, snapshot
from rtl2mc.frontend import source_read


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.found = {name: {"available": True} for name in ("yosys", "icarus", "vvp", "java")}

    def write(self, name, text="module test; endmodule\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def plan(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        output = self.root / "unwritten-output"
        with chdir(self.root), redirect_stdout(stdout), redirect_stderr(stderr), \
             patch.object(cli, "discover", return_value=(self.found, {})), \
             patch.object(cli, "ensure_dependencies") as dependencies:
            code = cli.main(["run", *map(str, arguments), "--plan", "--out", str(output)])
        self.assertEqual(code, 0, stderr.getvalue())
        dependencies.assert_not_called()
        self.assertFalse(output.exists())
        return json.loads(stdout.getvalue())

    def test_single_source_and_filelist_have_same_inputs_and_config(self):
        self.write("counter.sv")
        self.write("counter.f", "counter.sv\n")
        config = {"top": "counter", "clock": "clk", "boot": [{"reset": 1}, {"reset": 1}]}
        self.write("counter.rtl2mc.json", json.dumps(config))
        direct, listed = self.plan("counter.sv"), self.plan("-f", "counter.f")
        for key in ("sources", "include_dirs", "defines"):
            self.assertEqual(direct["inputs"][key], listed["inputs"][key])
        self.assertEqual(direct["inputs"]["filelists"], [])
        self.assertEqual(listed["inputs"]["filelists"][0]["path"], str(self.root / "counter.f"))
        self.assertEqual(direct["config"], config)
        self.assertEqual(listed["config"], config)
        self.assertEqual(direct["top"], "counter")

    def test_multiple_sources_keep_order_with_spaces_and_interleaved_options(self):
        first = self.write("src with spaces/first.sv")
        second = self.write("other/second.v")
        result = self.plan("src with spaces/first.sv", "-top", "design", "+define+ENABLED",
                           "other/second.v", "--synth", "yosys", "+define+WIDTH=8+CHECKS")
        self.assertEqual(result["inputs"]["sources"], [str(first), str(second)])
        self.assertEqual(result["inputs"]["defines"], ["ENABLED", "WIDTH=8", "CHECKS"])
        self.assertEqual(result["top"], "design")

    def test_top_aliases_override_config_for_either_input_form(self):
        self.write("design.sv")
        self.write("design.f", "design.sv")
        self.write("design.rtl2mc.json", '{"top":"configured"}')
        for top_flag in ("-top", "--top"):
            for inputs in (("design.sv",), ("-f", "design.f")):
                with self.subTest(top_flag=top_flag, inputs=inputs):
                    result = self.plan(top_flag, "selected", *inputs)
                    self.assertEqual(result["top"], "selected")
                    self.assertEqual(result["config"]["top"], "configured")

    def test_first_source_selects_default_config(self):
        self.write("first.sv")
        self.write("second.sv")
        self.write("first.rtl2mc.json", '{"seed":1}')
        self.write("second.rtl2mc.json", '{"seed":2}')
        result = self.plan("+define+BEFORE_FILES", "first.sv", "second.sv")
        self.assertEqual(result["config"], {"seed": 1})

    def test_explicit_config_and_relative_vectors_override_source_sidecar(self):
        self.write("design.sv")
        self.write("design.rtl2mc.json", '{"top":"ignored"}')
        vectors = {"initial": {}, "events": [], "checks": []}
        self.write("config/vectors.json", json.dumps(vectors))
        self.write("config/project.json", '{"top":"selected","vectors":"vectors.json"}')
        result = self.plan("design.sv", "--config", "config/project.json")
        self.assertEqual(result["config"], {"top": "selected", "vectors": vectors})

    def test_filelist_expands_before_direct_sources_and_command_line_defines(self):
        listed = self.write("lists/src/listed.sv")
        extra = self.write("extra.v")
        self.write("lists/inc/defs.svh", "`define LOCAL 1\n")
        listing = self.write("lists/design.f", "+incdir+inc\n+define+FROM_LIST=1\nsrc/listed.sv\n")
        self.write("lists/design.rtl2mc.json", '{"seed":7}')
        self.write("extra.rtl2mc.json", '{"seed":9}')
        result = self.plan("extra.v", "+define+FROM_CLI=2", "-f", "lists/design.f")
        self.assertEqual(result["inputs"]["sources"], [str(listed), str(extra)])
        self.assertEqual(result["inputs"]["defines"], ["FROM_LIST=1", "FROM_CLI=2"])
        self.assertEqual(result["inputs"]["include_dirs"], [str(self.root / "lists/inc")])
        self.assertEqual(result["inputs"]["filelists"], [
            {"path": str(listing), "sha256": hashlib.sha256(listing.read_bytes()).hexdigest()}])
        self.assertEqual(result["config"], {"seed": 7})

    def test_options_only_filelist_can_accompany_direct_sources(self):
        source = self.write("design.sv")
        self.write("options.f", "+define+SHARED=1\n")
        result = self.plan("-f", "options.f", "design.sv", "+define+LOCAL")
        self.assertEqual(result["inputs"]["sources"], [str(source)])
        self.assertEqual(result["inputs"]["defines"], ["SHARED=1", "LOCAL"])

    def test_macro_values_and_literal_source_paths_are_not_expanded_again(self):
        source = self.write("src/$UNSET source.sv")
        result = self.plan("src/$UNSET source.sv", '+define+LABEL="two words"+EMPTY=', "+define+VALUE=$UNSET")
        self.assertEqual(result["inputs"]["sources"], [str(source)])
        self.assertEqual(result["inputs"]["defines"], ['LABEL="two words"', "EMPTY=", "VALUE=$UNSET"])

    def test_end_of_options_allows_source_names_starting_with_dash(self):
        source = self.write("-design.sv")
        # Keep --plan before -- so it remains an option rather than a source name.
        stdout = io.StringIO()
        with chdir(self.root), redirect_stdout(stdout), \
             patch.object(cli, "discover", return_value=(self.found, {})):
            code = cli.main(["run", "--plan", "--", "-design.sv"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["inputs"]["sources"], [str(source)])

    def test_bad_inputs_fail_before_metadata_discovery_or_installation(self):
        self.write("design.sv")
        self.write("design.f", "design.sv")
        self.write("bad.txt")
        self.write("empty.f", "# no sources\n")
        cases = [
            (["missing.sv"], "existing .v/.sv"),
            (["bad.txt"], "existing .v/.sv"),
            (["design.sv", "./design.sv"], "Duplicate"),
            (["-f", "design.f", "design.sv"], "Duplicate"),
            (["-f", "empty.f"], "No RTL sources"),
            (["+define+ONLY_MACRO"], "No RTL sources"),
            (["design.sv", "+define+"], "Invalid macro"),
            (["design.sv", "+define+9INVALID"], "Invalid macro"),
            (["design.sv", "+define+GOOD+"], "Invalid macro"),
            (["design.sv", "+define+VALUE=one\ntwo"], "Invalid macro"),
            (["design.sv", "+unsupported"], "Unsupported source argument"),
            (["design.sv", "--config", "missing.json"], "configuration file does not exist"),
        ]
        for arguments, message in cases:
            with self.subTest(arguments=arguments), chdir(self.root), \
                 redirect_stderr(io.StringIO()) as stderr, \
                 patch.object(cli, "minecraft_target") as target, \
                 patch.object(cli, "discover") as discover, \
                 patch.object(cli, "ensure_dependencies") as dependencies:
                code = cli.main(["run", *arguments])
                self.assertEqual(code, 1)
                self.assertIn(message, stderr.getvalue())
                target.assert_not_called()
                discover.assert_not_called()
                dependencies.assert_not_called()

    def test_missing_sources_and_unknown_switches_are_argument_errors(self):
        self.write("design.sv")
        for arguments in ([], ["design.sv", "--unknown"], ["design.sv", "-top"]):
            with self.subTest(arguments=arguments), chdir(self.root), \
                 redirect_stderr(io.StringIO()), patch.object(cli, "discover") as discover:
                with self.assertRaises(SystemExit) as error:
                    cli.main(["run", *arguments])
                self.assertEqual(error.exception.code, 2)
                discover.assert_not_called()

    def test_direct_sources_snapshot_selected_files_in_order_and_copy_headers(self):
        first = self.write("src/first.sv", '`include "defs.svh"\nmodule first; endmodule\n')
        second = self.write("lib/second.v", "module second; endmodule\n")
        self.write("src/defs.svh", "`define LOCAL 1\n")
        destination = self.root / "snapshot"
        inputs = parse_sources([first, second, "+define+ENABLED"])
        record = snapshot(inputs, destination)
        self.assertEqual([p["file"] for p in record["sources"]], ["sources/d0/first.sv", "sources/d1/second.v"])
        self.assertEqual(record["filelists"], [])
        self.assertEqual(record["defines"], ["ENABLED"])
        self.assertTrue((destination / "sources/d0/defs.svh").is_file())
        for source, row in zip((first, second), record["sources"]):
            self.assertEqual((destination / row["file"]).read_bytes(), source.read_bytes())
            self.assertEqual(row["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_yosys_receives_literal_macro_bodies_before_source_files(self):
        source = self.write("source.sv")
        destination = self.root / "snapshot"
        definitions = ["ENABLED", "WIDTH=(1 * 2)", 'LABEL="hello world"', r'PATH="a\\b"', "EMPTY="]
        record = snapshot(parse_sources([source, *["+define+" + d for d in definitions]]), destination)
        command = source_read(record, destination)
        files = [destination / arg for arg in shlex.split(command) if (destination / arg).is_file()]
        self.assertEqual(files[1:], [destination / row["file"] for row in record["sources"]])
        bodies = {}
        for line in files[0].read_text().splitlines():
            directive, _, definition = line.partition(" ")
            self.assertEqual(directive, "`define")
            name, _, body = definition.partition(" ")
            bodies[name] = body
        self.assertEqual(bodies, {"ENABLED": "1", "WIDTH": "(1 * 2)", "LABEL": '"hello world"',
                                  "PATH": r'"a\\b"', "EMPTY": ""})

    def test_doctor_still_works_without_source_arguments(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch.object(cli, "discover", return_value=(self.found, {})):
            code = cli.main(["doctor"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["selection"]["missing"], [])


if __name__ == "__main__":
    unittest.main()
