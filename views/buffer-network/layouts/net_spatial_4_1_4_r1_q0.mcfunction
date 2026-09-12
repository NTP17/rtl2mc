# Exact lab placement, not a relocatable template. Clears the reserved lab volume.
fill 0 79 -16 63 84 47 minecraft:air
fill 0 79 -16 63 79 47 minecraft:stone
setblock 15 80 -1 minecraft:redstone_wire
setblock 15 80 1 minecraft:redstone_wire
setblock 15 80 2 minecraft:redstone_wire
setblock 15 80 4 minecraft:redstone_wire
setblock 15 80 5 minecraft:redstone_wire
setblock 15 80 7 minecraft:redstone_wire
setblock 15 80 0 minecraft:repeater[facing=north,delay=4]
setblock 15 80 3 minecraft:repeater[facing=north,delay=1]
setblock 15 80 6 minecraft:repeater[facing=north,delay=4]

# Initialize separately and hold for the declared interval.
