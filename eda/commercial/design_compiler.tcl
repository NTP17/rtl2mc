# Logical (wireload/non-topographical) Design Compiler. No ASIC physical technology is modeled.
# Default example is a measured three-receiver fanout. Override SV2RT_FIXTURE to another admitted entry.
set fixture net_fanout3_d4_q1
if {[info exists ::env(SV2RT_FIXTURE)]} {set fixture $::env(SV2RT_FIXTURE)}
if {![regexp {^net_[a-z0-9_]+$} $fixture]} {error "Invalid fixture identifier"}
set top conn_$fixture
set out .local/eda/commercial/dc/$fixture
file mkdir $out
set libraries [list .local/eda/commercial/lib/java_1_21_1_guarded_buffers.db .local/eda/commercial/lib/java_1_21_1_buffer_network.db]
foreach lib $libraries {if {![file exists $lib]} {error "Run library_compiler.tcl first: $lib"}}
set_app_var target_library $libraries
set_app_var link_library [concat [list *] $libraries]
read_verilog views/buffer-network/netlists/$fixture.v
current_design $top
if {![link]} {error "Unresolved library cells"}
# No logical deletion, cloning, resizing or renaming of physical diodes is legal.
set_dont_touch [get_cells -hierarchical *] true
source views/buffer-network/constraints/$fixture.sdc
check_design > $out/check_design.rpt
# The input is already structural and technology-bound. compile exercises the
# synthesis handoff while preserving its physical instances; it is not RTL mapping.
compile
report_reference > $out/references.rpt
report_timing > $out/timing.rpt
write_file -format verilog -hierarchy -output $out/netlist.v
write_file -format ddc -hierarchy -output $out/design.ddc
write_sdc $out/export.sdc
puts "RNET_SYNTHESIS_EXPORT_DONE"
puts "Required next gate: python tools/check_linked_netlist.py $fixture $out/netlist.v"
exit
