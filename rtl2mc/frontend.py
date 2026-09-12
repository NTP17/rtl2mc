"""Synthesis adapters and topology-preserving RMAP netlist ingestion."""
import copy
import json
from pathlib import Path
import re
import shutil

from redstone_pdk.rtl import graph_from_json, logical_verilog, identifier
from redstone_pdk.mapping_views import liberty
from .views import cells_verilog
from .common import dump, execute, quote, read, sha, tcl_list, write
from .toolchain import unavailable_license


def yosys(folder, label, script, tools, env):
    write(folder / (label + ".ys"), script)
    _, log = execute([*tools["yosys"]["argv"], "-T", "-s", label + ".ys"], folder, label, env)
    return log


def source_read(inputs):
    args = ["-sv", "-noautowire"]
    args += ["-I" + quote(p) for p in inputs["include_dirs"]]
    args += ["-D" + quote(d) for d in inputs["defines"]]
    args += [quote(p["file"]) for p in inputs["sources"]]
    return "read_verilog " + " ".join(args) + "\n"


def interface(folder, inputs, top, tools, env):
    yosys(folder, "interface", source_read(inputs) + "proc\nwrite_json interface.json\n", tools, env)
    modules = read(folder / "interface.json")["modules"]
    if top is None:
        instantiated = {c["type"] for m in modules.values() for c in m.get("cells", {}).values()}
        candidates = [n for n, m in modules.items() if n not in instantiated and not m.get("attributes", {}).get("blackbox")]
        if len(candidates) != 1:
            raise ValueError("Ambiguous top module; set top in the companion config or --top. Candidates: " + ", ".join(candidates))
        top = candidates[0]
    identifier(top)
    if top not in modules:
        raise ValueError("Top module was not found: " + top)
    return top, modules[top]


def preserve(raw, top, max_cells=64):
    """Validate each existing RMAP cell; change representation, never optimize."""
    m = copy.deepcopy(raw["modules"][top])
    if m.get("memories") or m.get("processes"):
        raise ValueError("Imported netlist must contain only mapped cells and wires")
    names = {}
    for name, cell in m["cells"].items():
        kind = cell["type"]
        pins = {"RMAP_NOR2": ("A", "B", "Y"), "RMAP_INV": ("A", "Y"), "RMAP_DFF": ("D", "CLK", "Q")}
        if kind not in pins or set(cell["connections"]) != set(pins[kind]) or cell.get("parameters"):
            raise ValueError(f"Unsupported imported cell/pins: {kind} {name}; synthesis may use only RMAP_NOR2/INV/DFF")
        names[name] = kind
        cell["type"] = {"RMAP_NOR2": "$_NOR_", "RMAP_INV": "$_NOT_", "RMAP_DFF": "$_DFF_P_"}[kind]
        if kind == "RMAP_DFF":
            cell["connections"]["C"] = cell["connections"].pop("CLK")
    graph = graph_from_json({"modules": {top: m}}, top, max_cells)
    for cell in graph["cells"]:
        cell["source_type"] = names[cell["source_cell"]]
    graph["import_policy"] = "One physical logic instance per imported instance; canonical names with source_cell correspondence; no logic re-synthesis"
    return graph


def ingest(netlist, netlist_top, top, folder, tools, env, max_cells=64):
    identifier(netlist_top)
    shutil.copyfile(netlist, folder / "synthesized.v")
    write(folder / "import-cells.sv", cells_verilog("functional"))
    yosys(folder, "import", "read_verilog -lib import-cells.sv\nread_verilog synthesized.v\n"
          + f"hierarchy -check -top {netlist_top}\nflatten\ncheck -assert\nwrite_json imported.json\n", tools, env)
    raw = read(folder / "imported.json")
    graph = preserve(raw, netlist_top, max_cells)
    graph["top"] = top
    dump(folder / "instance-map.json", [{"source": c["source_cell"], "physical": c["name"], "cell": c["source_type"]} for c in graph["cells"]])
    return graph


def commercial_scripts(folder, inputs, top, clock=None):
    source_files = tcl_list([r["file"] for r in inputs["sources"]])
    includes = tcl_list(inputs["include_dirs"])
    defines = tcl_list(inputs["defines"])
    clock_sdc = ""
    if clock:
        identifier(clock)
        clock_sdc = f"create_clock -name game_clock -period 100000 [get_ports {{{clock}}}]\n"
    write(folder / "library_compiler.tcl", 'if {![read_lib mapping.lib]} {error "Liberty import failed"}\n'
          'if {![write_lib redstone_mapping -format db -output mapping.db]} {error "Library export failed"}\n'
          'puts "RTL2MC_LC_PASS"\nexit\n')
    write(folder / "synthesis.sdc", clock_sdc + "set_max_delay 50000 -from [all_inputs] -to [all_outputs]\n")
    write(folder / "dc.tcl", f'''file mkdir WORK
define_design_lib WORK -path WORK
set_app_var target_library [list mapping.db]
set_app_var link_library [list * mapping.db]
set_app_var search_path [concat $search_path {includes}]
set_app_var verilogout_no_tri true
set_dont_use [get_lib_cells redstone_mapping/RMAP_BUF*]
if {{![analyze -format sverilog -define {defines} {source_files}]}} {{error "RTL analysis failed"}}
if {{![elaborate {top}]}} {{error "RTL elaboration failed"}}
current_design {top}
if {{![link]}} {{error "Library linking failed"}}
source synthesis.sdc
if {{![check_design]}} {{error "Input design check failed"}}
if {{![compile]}} {{error "Synthesis failed"}}
ungroup -all -flatten
change_names -rules verilog -hierarchy
if {{![check_design]}} {{error "Mapped design check failed"}}
redirect references.rpt {{report_reference}}
redirect timing.rpt {{report_timing -max_paths 10}}
write_file -format verilog -hierarchy -output synthesized.v
puts "RTL2MC_SYNTH_PASS"
exit
''')
    write(folder / "genus.tcl", f'''set_db init_hdl_search_path {includes}
read_libs mapping.lib
set_db [get_db lib_cells */RMAP_BUF*] .avoid true
read_hdl -sv -define {defines} {source_files}
elaborate {top}
check_design -unresolved
read_sdc synthesis.sdc
syn_generic
syn_map
syn_opt
write_hdl > synthesized.v
report_gates > references.rpt
puts "RTL2MC_SYNTH_PASS"
exit
''')


def synthesize(folder, inputs, top, selection, tools, env, config, imported=None, imported_top=None, max_cells=64):
    top, info = interface(folder, inputs, top, tools, env)
    write(folder / "mapping.lib", liberty())
    # This helper creates the reference for equivalence. The commercial tool
    # still receives the original snapshotted source, not this lowered design.
    yosys(folder, "reference", source_read(inputs) + f"hierarchy -check -top {top}\nsynth -top {top} -flatten -noabc\n"
          "dffunmap\ncheck -assert\nwrite_rtlil golden.il\n", tools, env)
    attempts = []
    backend = "import" if imported else None
    if imported:
        graph = ingest(imported, imported_top or top, top, folder, tools, env, max_cells)
    else:
        for candidate in selection["synthesis_candidates"]:
            backend = candidate
            if candidate == "yosys":
                yosys(folder, "synthesis", "read_rtlil golden.il\nabc -g NOR\nclean\ncheck -assert\nwrite_json lowered.json\n", tools, env)
                graph = graph_from_json(read(folder / "lowered.json"), top, max_cells)
                attempts.append({"backend": candidate, "status": "passed"})
                break
            commercial_scripts(folder, inputs, top, config.get("clock"))
            jobs = [(candidate, ["-f", "dc.tcl"] if candidate == "dc" else ["-no_gui", "-f", "genus.tcl"], "RTL2MC_SYNTH_PASS")]
            if candidate == "dc":
                jobs.insert(0, ("lc", ["-f", "library_compiler.tcl"], "RTL2MC_LC_PASS"))
            unavailable = False
            for tool, args, marker in jobs:
                code, log = execute([*tools[tool]["argv"], *args], folder, tool + "-synthesis", env, timeout=1800, allow_failure=True)
                if unavailable_license(log):
                    attempts.append({"backend": candidate, "status": "license unavailable"})
                    unavailable = True
                    break
                if code or marker not in log or re.search(r"(?m)^Error:|\*E,|\*F,", log):
                    raise RuntimeError(f"{tool} synthesis failed; inspect {tool}-synthesis.log (design errors do not trigger fallback)")
            if unavailable:
                continue
            # ingest copies from a distinct path, retaining the original vendor file.
            shutil.copyfile(folder / "synthesized.v", folder / "vendor-netlist.v")
            graph = ingest(folder / "vendor-netlist.v", top, top, folder, tools, env, max_cells)
            attempts.append({"backend": candidate, "status": "passed"})
            break
        else:
            raise RuntimeError("No synthesis candidate has an available license/runtime")
    write(folder / "logical.v", logical_verilog(graph, "gate"))
    proof = yosys(folder, "equivalence", f"read_rtlil golden.il\nrename {top} gold\nread_verilog logical.v\n"
                  "proc\nflatten gate\ntechmap\nopt\nequiv_make gold gate equiv\nhierarchy -top equiv\n"
                  "equiv_simple\nequiv_induct -seq 4\nequiv_status -assert\n", tools, env)
    if "Equivalence successfully proven!" not in proof:
        raise ValueError("Equivalence proof did not complete")
    graph["provenance"] = {"sources": inputs["sources"], "compile_options": {k: inputs[k] for k in ("include_dirs", "defines")},
                           "backend": backend, "attempts": attempts,
                           "proof": "All Yosys equivalence cells proven against snapshotted source RTL",
                           "files_sha256": {p.name: sha(p) for p in folder.iterdir() if p.suffix in (".ys", ".log", ".il")}}
    dump(folder / "graph.json", graph)
    return graph
