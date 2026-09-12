"""Failure controls for new dependency setup and optional evidence restoration."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import restore_lab_evidence, setup_gametest


class RepositoryArtifactTests(unittest.TestCase):
    def test_dependency_plan_does_not_download_or_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = {"path": ".local/test.jar", "url": "https://example.test/file",
                    "algorithm": "sha256", "digest": hashlib.sha256(b"good").hexdigest()}
            with patch.object(setup_gametest, "ROOT", root), patch.object(setup_gametest, "fetch") as fetch:
                self.assertEqual(setup_gametest.ensure(item), "missing or changed")
                fetch.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_changed_download_cannot_replace_existing_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "compiler.jar"
            path.write_bytes(b"previous")
            item = {"path": path.name, "url": "https://example.test/file", "algorithm": "sha256",
                    "digest": hashlib.sha256(b"correct").hexdigest()}
            with patch.object(setup_gametest, "ROOT", root), patch.object(setup_gametest, "fetch", return_value=b"changed"):
                with self.assertRaisesRegex(ValueError, "checksum"):
                    setup_gametest.ensure(item, install=True)
            self.assertEqual(path.read_bytes(), b"previous")

    def make_bundle(self, root, members):
        path = root / "evidence.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            for name, data in members.items():
                bundle.writestr(name, data)
        fixture = root / "tests/fixtures/lab-evidence.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text(json.dumps({"archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "files_sha256": {n: hashlib.sha256(d).hexdigest() for n, d in members.items()}}))
        return path

    def test_evidence_cannot_escape_or_replace_source(self):
        for name in ("../escaped", "results/../../escaped", "rtl2mc/cli.py", "results\\escaped"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle = self.make_bundle(root, {"results/valid.json": b"{}", name: b"bad"})
                # Windows zipfile normalizes backslashes, so membership validation
                # can reject this malformed member before the destination check.
                error = "Unsafe|Archive membership differs" if "\\" in name else "Unsafe"
                with patch.object(restore_lab_evidence, "ROOT", root), self.assertRaisesRegex(ValueError, error):
                    restore_lab_evidence.restore(bundle)
                self.assertFalse((root / "results").exists())

    def test_different_existing_evidence_blocks_all_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = self.make_bundle(root, {"results/new.json": b"{}", "results/old.json": b"old"})
            existing = root / "results/old.json"
            existing.parent.mkdir()
            existing.write_bytes(b"important")
            with patch.object(restore_lab_evidence, "ROOT", root), self.assertRaisesRegex(ValueError, "Refusing"):
                restore_lab_evidence.restore(bundle)
            self.assertEqual(existing.read_bytes(), b"important")
            self.assertFalse((root / "results/new.json").exists())


if __name__ == "__main__":
    unittest.main()
