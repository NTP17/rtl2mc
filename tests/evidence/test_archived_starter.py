"""Reanalyze original measurements; requires the optional lab evidence bundle."""
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


class ArchivedArtifactTests(unittest.TestCase):
    def test_all_contracts_and_references_validate(self):
        self.assertEqual(validate_project(), [])
