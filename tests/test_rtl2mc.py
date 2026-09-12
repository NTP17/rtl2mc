"""Automation boundaries: file lists, stable-only provisioning, topology, evidence."""
import copy
import gzip
import io
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from rtl2mc.common import ROOT
from rtl2mc.filelist import parse, tokens, snapshot
from rtl2mc.frontend import preserve
from rtl2mc.install import stable_release, install, extract
from rtl2mc.nbt import unpack, encode, configure_world
from rtl2mc.toolchain import discover, select
from rtl2mc.verification import vectors, parse_golden
from rtl2mc.cli import package, confirmation
from rtl2mc.minecraft import resolve, pack_settings


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content="module x; endmodule\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_filelist_nested_environment_and_spaces(self):
        self.write("src with spaces/x.sv")
        self.write("inc/x.svh", "`define X 1\n")
        child = self.write("nested/child.f", '"../src with spaces/x.sv"\n')
        listing = self.write("design.f", "+incdir+${INC}\n+define+WIDTH=4\n-F nested/child.f // explanation\n")
        result = parse(listing, {"INC": "inc"})
        self.assertEqual(result["sources"], [str((self.root / "src with spaces/x.sv").resolve())])
        self.assertEqual(result["defines"], ["WIDTH=4"])

    def test_windows_paths_not_unescaped(self):
        self.assertEqual(tokens(r'"C:\design files\top.sv"'), [r"C:\design files\top.sv"])

    def test_lowercase_f_inherits_base(self):
        self.write("x.sv")
        self.write("nested/child.f", "x.sv")
        self.assertEqual(len(parse(self.write("top.f", "-f nested/child.f"))["sources"]), 1)

    def test_recursive_filelists_rejected(self):
        with self.assertRaisesRegex(ValueError, "Recursive"):
            parse(self.write("loop.f", "-f loop.f"))

    def test_unknown_options_and_missing_environment_rejected(self):
        for text in ("+nospecify", "+incdir+$MISSING"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(self.write("bad.f", text), {})

    def test_snapshots_retain_includes_and_hashes(self):
        source = self.write("src/x.sv", '`include "x.svh"\nmodule x; endmodule\n')
        self.write("src/x.svh", "`define X 1\n")
        dest = self.root / "out"
        dest.mkdir()
        record = snapshot(parse(self.write("x.f", "src/x.sv")), dest)
        source.write_text("changed")
        self.assertIn("`include", (dest / record["sources"][0]["file"]).read_text())
        self.assertTrue((dest / record["include_dirs"][0] / "x.svh").exists())

    def found(self, *names):
        return {name: {"available": True} for name in names}

    def test_mixed_commercial_open_source_selection(self):
        result = select(self.found("dc", "lc", "yosys", "icarus", "vvp", "java"))
        self.assertEqual((result["synthesis"], result["simulation"]), ("dc", "icarus"))
        self.assertEqual(result["missing"], [])

    def test_dc_without_library_compiler_falls_back(self):
        result = select(self.found("dc", "genus", "yosys", "vcs", "xcelium", "java"))
        self.assertEqual((result["synthesis"], result["simulation"]), ("genus", "vcs"))

    def test_verilator_does_not_masquerade_as_sdf_simulator(self):
        result = select(self.found("yosys", "verilator", "java"))
        self.assertIn("four-state simulation backend", result["missing"])

    def test_explicit_backend_is_not_silently_replaced(self):
        result = select(self.found("yosys", "icarus", "vvp", "java"), "dc")
        self.assertIsNone(result["synthesis"])
        self.assertIn("dc", result["missing"])

    def test_dc_version_banner_with_exit_one(self):
        for text, code, expected in (
            ("dc_shell version    -  V-2023.12-SP3\ndc_shell build date - Apr 17, 2024", 1, True),
            ("dc_shell version    -  V-2023.12-SP3\nError: cannot start", 1, False),
            ("license server unavailable", 1, False),
            ("dc_shell version    -  V-2023.12-SP3", 2, False),
        ):
            with self.subTest(text=text, code=code), \
                 patch("rtl2mc.toolchain.environment", return_value={"PATH": ""}), \
                 patch("rtl2mc.toolchain.TOOLS", {"dc": ("dc_shell", "-version")}), \
                 patch("rtl2mc.toolchain.shutil.which", return_value="/test/dc_shell"), \
                 patch("rtl2mc.toolchain.subprocess.run", return_value=subprocess.CompletedProcess([], code, text, "")):
                found, _ = discover()
                self.assertEqual(found["dc"]["available"], expected)
                self.assertEqual(found["dc"]["version_exit_code"], code)

    def test_latest_stable_rejects_prerelease_and_nightly(self):
        for record in ({"tag_name": "v0.69", "prerelease": True}, {"tag_name": "nightly", "prerelease": False},
                       {"tag_name": "v0.70rc1", "prerelease": False}):
            with self.subTest(record=record), patch("rtl2mc.install.fetch", return_value=json.dumps(record).encode()), self.assertRaises(ValueError):
                stable_release("example/tool")
        with patch("rtl2mc.install.fetch", return_value=b'{"tag_name":"v13_0","draft":false,"prerelease":false}'):
            self.assertEqual(stable_release("example/tool")[1], "13.0")

    def test_install_cannot_run_without_confirmation(self):
        with patch("rtl2mc.install.download") as download, self.assertRaises(PermissionError):
            install({"packages": []})
        download.assert_not_called()
        with patch("sys.stdin.isatty", return_value=False):
            self.assertFalse(confirmation("Install?"))

    def test_archive_traversal_rejected(self):
        path = self.root / "bad.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("../escape", "bad")
        with self.assertRaises(ValueError):
            extract(path, self.root / "extract")
        self.assertFalse((self.root / "escape").exists())

    def raw(self):
        return {"modules": {"x": {"ports": {"a": {"direction": "input", "bits": [2]}, "y": {"direction": "output", "bits": [3]}},
                                   "cells": {"DC_U19": {"type": "RMAP_INV", "parameters": {}, "connections": {"A": [2], "Y": [3]}}}}}}

    def test_import_retains_cell_and_pin_topology(self):
        graph = preserve(self.raw(), "x")
        self.assertEqual(graph["cells"][0]["source_cell"], "DC_U19")
        self.assertEqual(graph["cells"][0]["pins"], {"A": 2, "Y": 3})
        self.assertEqual(len(graph["cells"]), 1)

    def test_import_rejects_extra_pins_unsupported_cells_and_duplicates(self):
        for change in ("pins", "cell", "duplicate"):
            raw = self.raw()
            c = raw["modules"]["x"]["cells"]["DC_U19"]
            if change == "pins": c["connections"]["B"] = [2]
            if change == "cell": c["type"] = "RMAP_BUF2"
            if change == "duplicate": raw["modules"]["x"]["cells"]["extra"] = copy.deepcopy(c)
            with self.subTest(change=change), self.assertRaises(ValueError):
                preserve(raw, "x")

    def test_unknown_or_missing_golden_values_cannot_pass(self):
        graph = preserve(self.raw(), "x")
        for log in ("GOLD 10 out_y x\n", "GOLD 10 out_y 0\n", "GOLD 10 out_y 0\nGOLD 10 out_y 0\n"):
            with self.subTest(log=log), self.assertRaises(ValueError):
                parse_golden(log, graph, {"checks": [10]})

    def test_sequential_boot_never_guessed(self):
        graph = {"ports": {"clk": {"direction": "input", "bits": [2]}}, "clock_bit": 2}
        with self.assertRaisesRegex(ValueError, "explicit boot"):
            vectors(graph, {"settle": 50}, {})

    def test_nbt_roundtrip_and_world_metadata(self):
        root = {b"Data": (10, {b"Keep": (9, (4, [1, -8, 9])), b"LevelName": (8, b"old")})}
        raw = b"\x0a" + encode(8, b"") + encode(10, root)
        name, decoded = unpack(raw)
        self.assertEqual(raw, b"\x0a" + encode(8, name) + encode(10, decoded))
        path = self.root / "level.dat"
        path.write_bytes(gzip.compress(raw))
        configure_world(path, "RTL2MC")
        data = unpack(gzip.decompress(path.read_bytes()))[1][b"Data"][1]
        self.assertEqual(data[b"allowCommands"], (1, 1))
        self.assertEqual(data[b"Keep"], root[b"Data"][1][b"Keep"])

    def test_world_zip_contains_no_server_configuration(self):
        self.write("world/level.dat", "world")
        self.write("world/session.lock", "lock")
        self.write("work/server/server.properties", "secret")
        archive = package(self.root, "test")
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.namelist(), ["rtl2mc_test/level.dat"])

    def test_default_minecraft_target_is_offline_and_measured(self):
        with patch("rtl2mc.minecraft.fetch") as fetch:
            target = resolve()
        self.assertEqual(target["id"], "1.21.1")
        self.assertIn("baseline", target["qualification"])
        fetch.assert_not_called()

    def test_snapshot_and_latest_alias_resolve_exact_hash(self):
        import hashlib
        metadata = json.dumps({"id": "24w33a", "javaVersion": {"majorVersion": 21}, "downloads": {"server": {"sha1": "server-pin"}}}).encode()
        manifest = {"latest": {"snapshot": "24w33a"}, "versions": [
            {"id": "1.21.1", "releaseTime": "2024-08-08T12:00:00+00:00"},
            {"id": "24w33a", "releaseTime": "2024-08-15T12:00:00+00:00", "type": "snapshot", "url": "https://example/metadata", "sha1": hashlib.sha1(metadata).hexdigest()}]}
        for requested in ("24w33a", "latest-snapshot"):
            with patch("rtl2mc.minecraft.fetch", side_effect=[json.dumps(manifest).encode(), metadata]):
                target = resolve(requested)
            self.assertEqual(target["id"], "24w33a")
            self.assertIn("candidate", target["qualification"])
        with patch("rtl2mc.minecraft.fetch", side_effect=[json.dumps(manifest).encode(), b"altered"]), self.assertRaisesRegex(ValueError, "checksum"):
            resolve("24w33a")

    def test_older_minecraft_version_not_falsely_admitted(self):
        manifest = {"versions": [{"id": "1.21.1", "releaseTime": "2024-08-08"}, {"id": "1.20.4", "releaseTime": "2023-12-07"}]}
        with patch("rtl2mc.minecraft.fetch", return_value=json.dumps(manifest).encode()), self.assertRaisesRegex(ValueError, "measured support floor"):
            resolve("1.20.4")

    def test_datapack_format_read_from_actual_engine(self):
        for version in (48, {"major": 94, "minor": 1}):
            path = self.root / "server.jar"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("version.json", json.dumps({"id": "test", "pack_version": {"data": version}, "world_version": 99}))
            target = {"id": "test"}
            pack = pack_settings(path, target)
            self.assertEqual(pack, {"pack_format": 48} if version == 48 else {"min_format": [94, 1], "max_format": [94, 1]})
            self.assertEqual(target["data_version"], 99)


if __name__ == "__main__":
    unittest.main()
