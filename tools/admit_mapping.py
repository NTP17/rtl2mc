"""Rebuild mapping-cell admission from the complete measured sweep."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.mapping_admission import ADMISSION,admit_cells
from redstone_pdk.rtl import dump
if __name__ == "__main__":
    record = admit_cells(sys.argv[1])
    dump(ADMISSION,record)
    print(record["coverage"])
