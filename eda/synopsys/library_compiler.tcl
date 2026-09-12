if {![read_lib mapping.lib]} {error "Liberty import failed"}
if {![write_lib redstone_mapping -format db -output mapping.db]} {error "Library export failed"}
if {![file exists mapping.db]} {error "Missing mapping.db"}
puts "RMAP_LIBRARY_COMPILE_DONE"
exit
