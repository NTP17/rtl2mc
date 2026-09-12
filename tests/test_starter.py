"""Offline transport, artifact, and result-integrity checks; not Minecraft tests."""
import copy
import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from redstone_pdk import lab
from redstone_pdk.fixtures import BOUNDS, cases, compile_functions
from redstone_pdk.project import ROOT, read_json, validate_project, validate_schema
from redstone_pdk.rcon import RconError, encode_packet, read_packet
from redstone_pdk.results import analyze, parse_probe_response


class FragmentedSocket:
    def __init__(self, payload):
        self.payload = io.BytesIO(payload)

    def recv(self, count):
        return self.payload.read(min(count, 2))


class RconTests(unittest.TestCase):
    def test_fragmented_utf8_packet(self):
        payload = "measurement: ✓".encode()
        raw = struct.pack("<iii", len(payload) + 10, 42, 0) + payload + b"\0\0"
        self.assertEqual(read_packet(FragmentedSocket(raw)), (42, 0, "measurement: ✓"))

    def test_truncated_packet_is_an_error(self):
        with self.assertRaises(RconError):
            read_packet(FragmentedSocket(struct.pack("<i", 20) + b"short"))

    def test_bad_length_and_terminator(self):
        for raw in (struct.pack("<i", -1), struct.pack("<i", 1000000), struct.pack("<iii", 10, 1, 0) + b"!!"):
            with self.assertRaises(RconError):
                read_packet(FragmentedSocket(raw))

    def test_rejects_embedded_nul(self):
        with self.assertRaises(RconError):
            encode_packet(1, 2, "tick freeze\0stop")


class ObservationTests(unittest.TestCase):
    def test_parse_actual_response_shape(self):
        self.assertEqual(parse_probe_response('Storage pdk_lab:sample has the following contents: {out: 15, powered: 1}', ["out", "powered"]), {"out": 15, "powered": 1})

    def test_missing_probe_duplicate_or_wrong_block_cannot_pass(self):
        for text in ("No elements found", "{out: -1}", "{out: 16}", "{out: 1, out: 1}", "{out: 15, unexpected: 0}"):
            with self.assertRaises(ValueError):
                parse_probe_response(text, ["out"])

    def test_edge_delay_comes_from_samples(self):
        case = {"id": "sample_only", "ticks": 6, "actions": {0: [], 4: []}, "checks": [],
                "edge_hypotheses": [{"probe": "q", "after": 0, "to": 1, "delay": 2}]}
        rows = [{"relative_game_tick": tick, "values": {"q": int(tick >= 3)}} for tick in range(-1, 7)]
        result = analyze(case, rows)
        self.assertFalse(result["pass"])
        self.assertEqual(result["edges"][0]["observed_delay_game_ticks"], 3)

    def test_already_high_is_not_a_rising_edge(self):
        case = {"id": "already_high", "ticks": 3, "actions": {0: []}, "checks": [],
                "edge_hypotheses": [{"probe": "q", "after": 0, "to": 1, "delay": 0}]}
        rows = [{"relative_game_tick": tick, "values": {"q": 1}} for tick in range(-1, 4)]
        self.assertIsNone(analyze(case, rows)["edges"][0]["observed_delay_game_ticks"])


class ArtifactTests(unittest.TestCase):

    def test_draft_schema_rejects_premature_certification(self):
        component = read_json(ROOT / "components/repeater.json")
        schema = read_json(ROOT / "schema/component.schema.json")
        for change in ("mapping", "arc", "measurement"):
            changed = copy.deepcopy(component)
            if change == "mapping":
                changed["mapping_eligible"] = True
            elif change == "arc":
                changed["timing"]["arcs"] = [{"delay": 2}]
            else:
                changed["evidence"]["measurements"] = ["fabricated"]
            self.assertTrue(validate_schema(changed, schema))

    def test_every_fixture_coordinate_stays_in_lab_volume(self):
        for case in cases():
            low, high = case.get("lab_bounds", BOUNDS)
            commands = case["setup"] + [command for actions in case["actions"].values() for command in actions]
            coords = [list(map(int, command.split()[1:4])) for command in commands]
            coords += [probe["position"] for probe in case["probes"]]
            for position in coords:
                self.assertTrue(all(a <= v <= b for a, v, b in zip(low, position, high)), (case["id"], position))

    def test_datapack_uses_version_correct_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            functions = Path(temp) / "pdk_lab/data/pdk_lab/function"
            with patch.object(lab, "FUNCTIONS", functions):
                lab.install_datapack()
            self.assertTrue((Path(temp) / "pdk_lab/pack.mcmeta").is_file())
            self.assertEqual(read_json(Path(temp) / "pdk_lab/pack.mcmeta")["pack"]["pack_format"], 48)
            self.assertEqual(len(list(functions.rglob("*.mcfunction"))), len(compile_functions()))

    def test_runtime_archive_cannot_escape_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("../escaped.txt", "bad")
            with self.assertRaises(RuntimeError):
                lab.extract_runtime(archive, Path(temp) / "java")
            self.assertFalse((Path(temp) / "escaped.txt").exists())

    def test_start_does_not_accept_eula_implicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(lab, "SERVER", Path(temp)), patch.object(lab, "check_config"):
                with self.assertRaisesRegex(RuntimeError, "EULA"):
                    lab.start()
            self.assertFalse((Path(temp) / "eula.txt").exists())


if __name__ == "__main__":
    unittest.main()
