"""Measure a previously checked RTL build on the authorized local Minecraft server."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.mapping_lab import run
if __name__ == "__main__":
    run(sys.argv[1])
