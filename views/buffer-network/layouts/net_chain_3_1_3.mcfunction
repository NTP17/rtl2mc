# Exact lab placement, not a relocatable template. Clears the reserved lab volume.
fill 0 79 -16 63 84 47 minecraft:air
fill 0 79 -16 63 79 47 minecraft:stone
setblock 23 80 16 minecraft:redstone_wire
setblock 25 80 16 minecraft:redstone_wire
setblock 26 80 16 minecraft:redstone_wire
setblock 28 80 16 minecraft:redstone_wire
setblock 29 80 16 minecraft:redstone_wire
setblock 31 80 16 minecraft:redstone_wire
setblock 24 80 16 minecraft:repeater[facing=west,delay=3]
setblock 27 80 16 minecraft:repeater[facing=west,delay=1]
setblock 30 80 16 minecraft:repeater[facing=west,delay=3]

# Initialize separately and hold for the declared interval.
