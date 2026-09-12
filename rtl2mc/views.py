"""Portable HDL declarations for new exports, preserving archived PDK views."""
from pathlib import Path
import re

from redstone_pdk import mapping_views as legacy
from .common import write


def cells_verilog(mode):
    # These generated ANSI ports are nets, including the DFF's assigned Q.
    return re.sub(r"\b(input|output) (?!wire\b)", r"\1 wire ", legacy.cells_verilog(mode))


def structural(graph, layout):
    return re.sub(r"(?m)^(  (?:input|output)) (?!wire\b)", r"\1 wire ", legacy.structural(graph, layout))


def export(graph, layout, folder):
    folder = Path(folder)
    budget = legacy.export(graph, layout, folder)
    for mode in ("functional", "timing", "portable"):
        write(folder / f"cells-{mode}.sv", cells_verilog(mode))
    write(folder / "mapped.v", structural(graph, layout))
    return budget
