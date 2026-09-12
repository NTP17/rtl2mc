"""Commercial-tool handoff files. Actual vendor qualification is separate."""
from .mapping_views import public_bit


def scripts(graph,budget):
    source_files = " ".join(r["file"] for r in graph["provenance"]["sources"])
    top = graph["top"]
    files = {}
    files["library_compiler.tcl"] = '''read_lib mapping.lib
write_lib redstone_mapping -format db -output mapping.db
if {![file exists mapping.db]} {error "Missing mapping.db"}
puts "RMAP_LIBRARY_COMPILE_DONE"
exit
'''
    constraints = ""
    if graph["clock_bit"] is not None:
        name,p = next((n,p) for n,p in graph["ports"].items() if p["direction"] == "input" and graph["clock_bit"] in p["bits"])
        ref = public_bit(name,p,p["bits"].index(graph["clock_bit"]))
        constraints = f"create_clock -name game_clock -period {budget['minimum_clock_period']} [get_ports {{{ref}}}]\n"
    constraints += f"set_max_delay {budget['settle']} -from [all_inputs] -to [all_outputs]\n"
    files["synthesis.sdc"] = "# Abstract game-tick units; reroute the technology-mapped export before physical GLS.\n"+constraints
    for mode in ("rtl","preserve"):
        design = top if mode == "rtl" else top+"_mapped"
        out = "commercial_"+mode
        dc_read = f"analyze -format sverilog [list {source_files}]\nelaborate {top}\n" if mode == "rtl" else "read_verilog mapped.v\n"
        genus_read = f"read_hdl -sv [list {source_files}]\n" if mode == "rtl" else "read_hdl mapped.v\n"
        dc_lock = "" if mode == "rtl" else "set_dont_touch [get_cells -hierarchical *] true\n"
        genus_lock = "" if mode == "rtl" else "set_db [get_db insts] .dont_touch true\n"
        sdc = "synthesis.sdc" if mode == "rtl" else "mapped.sdc"
        files[f"dc_{mode}.tcl"] = f'''# Logical Design Compiler; run in this build directory.
if {{![file exists mapping.db]}} {{error "Run library_compiler.tcl with this tool release first"}}
file mkdir {out}_dc
define_design_lib WORK -path {out}_dc/WORK
set_app_var target_library [list mapping.db]
set_app_var link_library [list * mapping.db]
{dc_read}current_design {design}
if {{![link]}} {{error "Unresolved library cells"}}
{dc_lock}source {sdc}
check_design > {out}_dc/check_design.rpt
compile
report_reference > {out}_dc/references.rpt
report_timing > {out}_dc/timing.rpt
write_file -format verilog -hierarchy -output {out}_dc/netlist.v
write_file -format ddc -hierarchy -output {out}_dc/design.ddc
write_sdc {out}_dc/export.sdc
puts "RMAP_SYNTHESIS_EXPORT_DONE"
exit
'''
        files[f"genus_{mode}.tcl"] = f'''# Genus Stylus Common UI; logical synthesis, no ASIC physical technology.
file mkdir {out}_genus
read_libs mapping.lib
{genus_read}elaborate {design}
check_design -unresolved
{genus_lock}read_sdc {sdc}
syn_generic
syn_map
syn_opt
report_gates > {out}_genus/references.rpt
report_timing > {out}_genus/timing.rpt
write_hdl > {out}_genus/netlist.v
write_sdc > {out}_genus/export.sdc
puts "RMAP_SYNTHESIS_EXPORT_DONE"
exit
'''
    files["commercial.f"] = "\n".join([*source_files.split(),"logical.v","mapped.v","cells-timing.sv","tb-sdf.sv"])+"\n"
    return files


def plan(tool,mode="rtl",netlist=None):
    if tool == "lc": return [["lc_shell","-f","library_compiler.tcl"]],"RMAP_LIBRARY_COMPILE_DONE"
    if tool in ("dc","genus"):
        return [["dc_shell","-f",f"dc_{mode}.tcl"]] if tool == "dc" else [["genus","-no_gui","-f",f"genus_{mode}.tcl"]],"RMAP_SYNTHESIS_EXPORT_DONE"
    if tool == "vcs":
        return [["vcs","-full64","-sverilog","-timescale=1ns/1ps","-top","mapping_tb","+define+RMAP_SDF_ONLY","+sdfverbose","-f","commercial.f","-o","commercial_simv"],
                ["./commercial_simv","+sdfverbose"]],"RMAP_RTL_PASS"
    if tool == "questa":
        return [["vlib","commercial_work"],["vlog","-sv","-timescale","1ns/1ps","-work","commercial_work","+define+RMAP_SDF_ONLY","-f","commercial.f"],
                ["vsim","-c","-t","1ps","-lib","commercial_work","mapping_tb","-do","onerror {quit -code 1}; run -all; quit -code 0"]],"RMAP_RTL_PASS"
    if tool == "xcelium":
        return [["xrun","-64bit","-sv","-timescale","1ns/1ps","-top","mapping_tb","+define+RMAP_SDF_ONLY","-f","commercial.f","-xmlibdirname","commercial_xcelium.d"]],"RMAP_RTL_PASS"
    raise ValueError("Unknown commercial tool")


def control_plans(tool):
    if tool in ("lc","dc","genus"): return []
    base,_ = plan(tool)
    records = []
    for label,top,marker in (("arcs","arc_tb","RMAP_ARCS_PASS"),("missing_sdf","arc_tb","RMAP_ARC_MISMATCH"),("width","width_tb","RMAP_WIDTH_CAUGHT")):
        substitutions = {"mapping_tb":top,"commercial.f":"arc-commercial.f",
                         "commercial_simv":f"commercial_{label}_simv","./commercial_simv":f"./commercial_{label}_simv",
                         "commercial_xcelium.d":f"commercial_{label}_xcelium.d","commercial_work":f"commercial_{label}_work"}
        commands = [[substitutions.get(a,a) for a in c] for c in base]
        if label == "missing_sdf":
            for c in commands:
                if c[0] in ("vcs","vlog","xrun"): c.append("+define+NO_ANNOTATE")
        records.append({"label":label,"commands":commands,"marker":marker,"expected_failure":label=="missing_sdf"})
    return records
