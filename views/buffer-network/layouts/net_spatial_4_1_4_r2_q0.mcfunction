# Exact lab placement, not a relocatable template. Clears the reserved lab volume.
fill 0 79 -16 63 84 47 minecraft:air
fill 0 79 -16 63 79 47 minecraft:stone
setblock 16 80 0 minecraft:redstone_wire
setblock 14 80 0 minecraft:redstone_wire
setblock 13 80 0 minecraft:redstone_wire
setblock 11 80 0 minecraft:redstone_wire
setblock 10 80 0 minecraft:redstone_wire
setblock 8 80 0 minecraft:redstone_wire
setblock 15 80 0 minecraft:repeater[facing=east,delay=4]
setblock 12 80 0 minecraft:repeater[facing=east,delay=1]
setblock 9 80 0 minecraft:repeater[facing=east,delay=4]

# Initialize separately and hold for the declared interval.
