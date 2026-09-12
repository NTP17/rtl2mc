# Abstract timing budget in ns, where 1 ns = 1 game tick.
# Dwell/initialization and physical guards require the native checker + GLS monitor.
# No electrical load, clock frequency, wire capacitance, or PVT is asserted here.
set_max_delay 4 -from [get_ports A] -to [get_ports {Q[0]}]
set_max_delay 10 -from [get_ports A] -to [get_ports {Q[1]}]
set_max_delay 16 -from [get_ports A] -to [get_ports {Q[2]}]
