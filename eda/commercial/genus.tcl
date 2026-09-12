# Genus Stylus Common UI, logical synthesis mode. Run from the repository root.
set fixture net_fanout3_d4_q1
if {[info exists ::env(SV2RT_FIXTURE)]} {set fixture $::env(SV2RT_FIXTURE)}
if {![regexp {^net_[a-z0-9_]+$} $fixture]} {error "Invalid fixture identifier"}
set top conn_$fixture
set out .local/eda/commercial/genus/$fixture
file mkdir $out
read_libs {views/repeater-buffers/repeater-buffers.lib views/buffer-network/cells.lib}
read_hdl views/buffer-network/netlists/$fixture.v
elaborate $top
check_design -unresolved
# Preserve every physical diode; the post-export checker rejects any changed graph.
set_db [get_db insts] .dont_touch true
read_sdc views/buffer-network/constraints/$fixture.sdc
syn_generic
syn_map
syn_opt
report_gates > $out/references.rpt
report_timing > $out/timing.rpt
write_hdl > $out/netlist.v
write_sdc > $out/export.sdc
puts "RNET_SYNTHESIS_EXPORT_DONE"
puts "Required next gate: python tools/check_linked_netlist.py $fixture $out/netlist.v"
exit
