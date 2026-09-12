"""Yosys frontend, checked Boolean graph, and logical equivalence certificate."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

from tools.eda_tools import runtime

CELL_TYPES = {"$_NOR_": ("NOR2", ("A", "B"), "Y"),
              "$_NOT_": ("INV", ("A",), "Y"),
              "$_DFF_P_": ("DFF", ("D", "C"), "Q")}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True)+"\n", encoding="utf-8", newline="\n")


def identifier(name):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        raise ValueError("Use a simple Verilog identifier for top and public ports: "+name)
    return name


def yosys(folder, name, script):
    rt = runtime(require_iverilog=False)
    if rt["yosys_path_prefix"]:
        raise ValueError("RTL mapping requires native Yosys on PATH or in SV2RT_UCRT_ROOT")
    path = folder / (name+".ys")
    path.write_text(script, encoding="utf-8", newline="\n")
    p = subprocess.run([*rt["yosys"], "-T", "-s", path.name], cwd=folder, env=rt["env"],
                       capture_output=True, text=True, timeout=300)
    (folder / (name+".log")).write_text(p.stdout+p.stderr, encoding="utf-8", newline="\n")
    if p.returncode:
        raise ValueError(f"Yosys {name} failed; inspect {folder / (name+'.log')}")
    return p.stdout+p.stderr


def graph_from_json(raw, top, max_cells=64):
    m = raw["modules"][top]
    ports = dict(sorted(m["ports"].items()))
    for name, port in ports.items():
        identifier(name)
        if port["direction"] not in ("input", "output"):
            raise ValueError("Inout/tristate ports are outside the binary mapping contract")
        if any(bit in ("x", "z") for bit in port["bits"]):
            raise ValueError("X/Z output bits cannot be represented by binary redstone")
    nodes, drivers, clock_bits = [], {}, set()
    for name, p in ports.items():
        if p["direction"] == "input":
            for i, b in enumerate(p["bits"]):
                if not isinstance(b, int) or b in drivers:
                    raise ValueError("Aliased or constant input bits are unsupported")
                drivers[b] = f"{name}[{i}]"
    primary_bits = set(drivers)
    for i, (original, c) in enumerate(sorted(m["cells"].items())):
        if c["type"] not in CELL_TYPES:
            raise ValueError(f"Unsupported mapped cell {c['type']} at {original}; use positive-edge registers, synchronous reset, and binary logic")
        kind, inputs, output = CELL_TYPES[c["type"]]
        pins = {}
        for pin in (*inputs, output):
            bits = c["connections"][pin]
            if len(bits) != 1 or bits[0] in ("x", "z"):
                raise ValueError("Nonbinary or nonscalar primitive connection")
            pins["CLK" if pin == "C" else pin] = bits[0]
        if pins[output] in drivers:
            raise ValueError("Multiple drivers on a mapped signal")
        name = f"u{i:03d}"
        drivers[pins[output]] = name
        if kind == "DFF":
            clock_bits.add(pins["CLK"])
        nodes.append({"name": name, "kind": kind, "pins": dict(sorted(pins.items())), "source_cell": original})
    if len(nodes) > max_cells:
        raise ValueError(f"Mapped design has {len(nodes)} cells; requested capacity is {max_cells}")
    if any(b not in drivers and b not in ("0","1") for p in ports.values() if p["direction"] == "output" for b in p["bits"]):
        raise ValueError("An output has no driver")
    if len(clock_bits) > 1 or not clock_bits <= primary_bits:
        raise ValueError("Require one ungated positive-edge primary-input clock")
    clock = next(iter(clock_bits), None)
    for n in nodes:
        for pin, bit in n["pins"].items():
            if bit not in drivers and bit not in ("0", "1"):
                raise ValueError("Undriven net in mapped graph")
            if bit == clock and pin != "CLK":
                raise ValueError("Clock used as data; the mapping contract separates clock and data")
    if clock is not None and any(clock in p["bits"] for p in ports.values() if p["direction"] == "output"):
        raise ValueError("Clock forwarding requires a separate characterized interface")
    # A topological order with registers as cut points detects combinational loops.
    ready = primary_bits | {"0", "1"} | {n["pins"]["Q"] for n in nodes if n["kind"] == "DFF"}
    todo = [n for n in nodes if n["kind"] != "DFF"]
    order = []
    while todo:
        found = [n for n in todo if all(b in ready for p,b in n["pins"].items() if p != "Y")]
        if not found:
            raise ValueError("Combinational feedback is outside the supported RTL contract")
        for n in found:
            order.append(n["name"]); ready.add(n["pins"]["Y"]); todo.remove(n)
    # Reject initial-register semantics: physical startup needs a clocked reset/boot sequence.
    if any("init" in n.get("attributes", {}) for n in m.get("netnames", {}).values()):
        raise ValueError("Register initialization is unsupported; use an explicit synchronous reset")
    return {"schema_version": 1, "top": top, "ports": ports, "cells": nodes,
            "combinational_order": order, "clock_bit": clock, "semantics": "binary synchronous; startup state unconstrained"}


def declarations(graph, module):
    lines = ["module "+module+"("+", ".join(graph["ports"])+");"]
    for name, port in graph["ports"].items():
        width, offset = len(port["bits"]), port.get("offset", 0)
        hi, lo = offset+width-1, offset
        if port.get("upto", 0):
            hi, lo = lo, hi
        size = f" [{hi}:{lo}]" if width > 1 or offset else ""
        lines.append(f"  {port['direction']}{size} {name};")
    bits = sorted({b for n in graph["cells"] for b in n["pins"].values() if isinstance(b,int)} |
                  {b for p in graph["ports"].values() for b in p["bits"] if isinstance(b,int)})
    lines += [f"  wire n{b};" for b in bits]
    for name, port in graph["ports"].items():
        for i,b in enumerate(port["bits"]):
            index = port.get("offset", 0)+(len(port["bits"])-1-i if port.get("upto",0) else i)
            ref = name if len(port["bits"]) == 1 and not port.get("offset",0) else f"{name}[{index}]"
            lhs,rhs = (bit_expr(b),ref) if port["direction"] == "input" else (ref,bit_expr(b))
            lines.append(f"  assign {lhs} = {rhs};")
    return lines


def bit_expr(bit):
    return f"n{bit}" if isinstance(bit, int) else "1'b"+bit


def logical_verilog(graph, module):
    lines = declarations(graph, module)
    for n in graph["cells"]:
        p = {k:bit_expr(v) for k,v in n["pins"].items()}
        if n["kind"] == "DFF":
            lines += [f"  reg {n['name']}_q;", f"  always @(posedge {p['CLK']}) {n['name']}_q <= {p['D']};",
                      f"  assign {p['Q']} = {n['name']}_q;"]
        else:
            expr = p["A"] if n["kind"] == "INV" else f"({p['A']} | {p['B']})"
            lines.append(f"  assign {p['Y']} = ~{expr};")
    return "\n".join(lines+["endmodule", ""])


def synthesize(sources, top, folder, max_cells=64):
    identifier(top)
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if any(c in str(folder) for c in ('"', '\n', '\r')):
        raise ValueError("Unsupported path character")
    copied = []
    for i, source in enumerate(sources):
        p = Path(source).resolve()
        target = folder / f"source_{i}.sv"
        target.write_bytes(p.read_bytes())
        copied.append({"original": p.name, "file": target.name, "sha256": sha(target)})
    script = "read_verilog -sv -noautowire "+" ".join(r["file"] for r in copied)+"\n"
    script += f"hierarchy -check -top {top}\nsynth -top {top} -flatten -noabc\ndffunmap\ncheck -assert\n"
    script += "write_rtlil golden.il\nabc -g NOR\nclean\ncheck -assert\nwrite_json lowered.json\n"
    log = yosys(folder, "synthesis", script)
    graph = graph_from_json(json.loads((folder / "lowered.json").read_text()), top, max_cells)
    (folder / "logical.v").write_text(logical_verilog(graph, "gate"), encoding="utf-8", newline="\n")
    proof = (f"read_rtlil golden.il\nrename {top} gold\nread_verilog logical.v\n"
             "proc\nflatten gate\ntechmap\nopt\nequiv_make gold gate equiv\nhierarchy -top equiv\n"
             "equiv_simple\nequiv_induct -seq 4\nequiv_status -assert\n")
    result = yosys(folder, "equivalence", proof)
    if "Equivalence successfully proven!" not in result:
        raise ValueError("Missing Yosys equivalence success marker")
    graph["provenance"] = {"sources": copied, "yosys_version": next((l for l in log.splitlines() if l.startswith(" Yosys ") or l.startswith("Yosys ")), "see synthesis.log"),
                           "proof": "Yosys equiv_simple + equiv_induct; all output equivalence cells proven",
                           "files_sha256": {n:sha(folder/n) for n in ("synthesis.ys","synthesis.log","golden.il","lowered.json","logical.v","equivalence.ys","equivalence.log")}}
    dump(folder/"graph.json", graph)
    return graph
