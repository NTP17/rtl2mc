# Run from the repository root: lc_shell -f eda/commercial/library_compiler.tcl
# Compile with the installed Synopsys release; .db is not a portable source artifact.
set out .local/eda/commercial/lib
file mkdir $out
foreach {source library} {
  views/repeater-buffers/repeater-buffers.lib java_1_21_1_guarded_buffers
  views/buffer-network/cells.lib java_1_21_1_buffer_network
} {
  read_lib $source
  write_lib $library -format db -output $out/$library.db
  if {![file exists $out/$library.db]} {error "Missing compiled library: $library"}
}
puts "RNET_LIBRARY_COMPILE_DONE"
exit
