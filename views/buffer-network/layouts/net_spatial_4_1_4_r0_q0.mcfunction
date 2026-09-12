# Exact lab placement, not a relocatable template. Clears the reserved lab volume.
fill 0 79 -16 63 84 47 minecraft:air
fill 0 79 -16 63 79 47 minecraft:stone
setblock 14 80 0 minecraft:redstone_wire
setblock 16 80 0 minecraft:redstone_wire
setblock 17 80 0 minecraft:redstone_wire
setblock 19 80 0 minecraft:redstone_wire
setblock 20 80 0 minecraft:redstone_wire
setblock 22 80 0 minecraft:redstone_wire
setblock 15 80 0 minecraft:repeater[facing=west,delay=4]
setblock 18 80 0 minecraft:repeater[facing=west,delay=1]
setblock 21 80 0 minecraft:repeater[facing=west,delay=4]

# Initialize separately and hold for the declared interval.
