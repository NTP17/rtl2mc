"""Export a self-contained browser for measured traces, with no runtime dependencies."""
import json

from .project import ROOT


def display_label(record):
    e = record["experiment"]
    parts = [f"Setting {e['delay_setting']}"]
    if e["family"] == "spatial":
        parts += [e["site"].replace("_", " "), e["facing"], e["template_family"].replace("_", " ")]
    if "input_level" in e:
        parts += [f"level {e['input_level']}", e["stimulus_kind"].replace("_", " ")]
    if "active_value" in e:
        parts += ["high" if e["active_value"] else "low"]
    if "initial_output" in e:
        parts += [f"initial Q={e['initial_output']}"]
    for name in ("pattern", "side", "driver"):
        if name in e:
            parts.append(str(e[name]).replace("_", " "))
    if "input_width_game_ticks" in e:
        parts.append(f"width {e['input_width_game_ticks']} gt")
    return " · ".join(parts)


def pack(record):
    e = record["experiment"]
    details = {key.replace("_", " "): value for key, value in e.items()
               if key not in ("reference_fixture", "family", "template_family", "output_prediction")}
    return {"id": record["fixture"], "family": e["family"], "label": display_label(record),
            "duration": record["duration_game_ticks"], "details": details,
            "signals": {name: {"initial": trace["initial"], "edges": [[edge["tick"], edge["to"], edge["phase"]] for edge in trace["edges"]]}
                        for name, trace in record["transitions"].items()},
            "reference": record.get("driver_reference_fixture", e.get("reference_fixture")),
            "match": record.get("driver_reference_match", record.get("reference_comparison", {}).get("match"))}


def write_waveforms(contract, target=None):
    target = target or ROOT / "docs/repeater-waveforms.html"
    data = {"technology": contract["technology"], "coverage": contract["coverage"],
            "cases": [pack(record) for record in contract["cases"]],
            "references": {record["fixture"]: pack(record) for record in contract["reference_cases"]}}
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    assets = ROOT / "redstone_pdk/assets"
    fragment = (assets / "repeater-waveforms.html").read_text(encoding="utf-8").replace("__MEASURED_DATA__", payload)
    css = (assets / "visualize.css").read_text(encoding="utf-8")
    document = ('<!doctype html><html lang="en" data-visualize-standalone><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\'">'
                '<title>Measured repeater waveforms</title><style>' + css + '</style></head><body>' + fragment + '</body></html>')
    target.write_text(document, encoding="utf-8")
    return target
