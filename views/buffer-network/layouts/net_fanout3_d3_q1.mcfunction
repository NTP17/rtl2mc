# Exact lab placement, not a relocatable template. Clears the reserved lab volume.
fill 0 79 -16 63 84 47 minecraft:air
fill 0 79 -16 63 79 47 minecraft:stone
setblock 23 80 16 minecraft:redstone_wire
setblock 25 80 16 minecraft:redstone_wire
setblock 26 80 16 minecraft:redstone_wire
setblock 28 80 16 minecraft:redstone_wire
setblock 29 80 16 minecraft:redstone_wire
setblock 30 80 16 minecraft:redstone_wire
setblock 29 80 15 minecraft:redstone_wire
setblock 29 80 14 minecraft:redstone_wire
setblock 32 80 16 minecraft:redstone_wire
setblock 29 80 12 minecraft:redstone_wire
setblock 29 80 17 minecraft:redstone_wire
setblock 29 80 18 minecraft:redstone_wire
setblock 29 80 20 minecraft:redstone_wire
setblock 24 80 16 minecraft:repeater[facing=west,delay=1]
setblock 27 80 16 minecraft:repeater[facing=west,delay=3]
setblock 31 80 16 minecraft:repeater[facing=west,delay=3]
setblock 29 80 13 minecraft:repeater[facing=south,delay=4]
setblock 29 80 19 minecraft:repeater[facing=north,delay=2]

# Initialize separately and hold for the declared interval.
