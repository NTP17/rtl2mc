# Invoked by tools/check_synopsys.py in an isolated build directory.
# All delays are abstract game ticks, represented by simulation ns.
set top $env(RMAP_TOP)
file mkdir WORK
define_design_lib WORK -path WORK
set_app_var target_library [list ../library/mapping.db]
set_app_var link_library [list * ../library/mapping.db]
set_app_var verilogout_no_tri true
if {![analyze -format sverilog source.sv]} {error "RTL analysis failed"}
if {![elaborate $top]} {error "RTL elaboration failed"}
current_design $top
if {![link]} {error "Library link failed"}
if {$top in {counter shift2}} {
    create_clock -name game_clock -period 2000 [get_ports clk]
    set_input_delay 0 -clock game_clock [remove_from_collection [all_inputs] [get_ports clk]]
    set_output_delay 0 -clock game_clock [all_outputs]
}
set_max_delay 1000 -from [all_inputs] -to [all_outputs]
if {![check_design]} {error "Pre-synthesis design check failed"}
if {![compile]} {error "Synthesis failed"}
change_names -rules verilog -hierarchy
rename_design $top ${top}_gate
if {![check_design]} {error "Post-synthesis design check failed"}
redirect check_design.rpt {check_design}
redirect references.rpt {report_reference}
redirect area.rpt {report_area}
redirect timing.rpt {report_timing -max_paths 10}
redirect constraints.rpt {report_constraint -all_violators}
set manifest [open cells.tsv w]
foreach_in_collection cell [get_cells -hierarchical *] {
    set ref [get_attribute $cell ref_name]
    if {$ref ni {RMAP_NOR2 RMAP_INV RMAP_DFF RMAP_BUF2 RMAP_BUF4 RMAP_BUF6 RMAP_BUF8}} {
        error "Unmapped or unsupported cell: $ref"
    }
    puts $manifest "$ref\t[get_object_name $cell]"
}
close $manifest
write_file -format verilog -hierarchy -output netlist.v
write_file -format ddc -hierarchy -output design.ddc
write_sdf -version 3.0 -significant_digits 6 netlist.sdf
write_sdc export.sdc
puts "RMAP_SYNTHESIS_EXPORT_DONE"
exit
