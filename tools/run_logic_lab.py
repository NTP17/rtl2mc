"""Run the current logic macro experiments on the authorized vanilla lab."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from redstone_pdk.lab import run
from redstone_pdk.logic_fixtures import pilot_cases, logic_cases
from redstone_pdk.route_fixtures import route_cases
if __name__ == "__main__":
    full = "--full" in sys.argv
    chosen = logic_cases()+route_cases() if full else pilot_cases()
    raise SystemExit(run(suite="mapping_logic" if full else "logic_pilot",fixtures=chosen,tick_rate=1000 if full else 20))
