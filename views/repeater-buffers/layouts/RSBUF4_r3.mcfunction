# RSBUF4 rotation 3; origin is the repeater block.
# Clears the declared reserved volume; place only in a reserved lab area.
# Keep A stable for 20 game ticks before use; external wiring is not admitted.
fill ~-2 ~-1 ~-3 ~2 ~2 ~3 minecraft:air
fill ~-2 ~-1 ~-3 ~2 ~-1 ~3 minecraft:stone
setblock ~ ~ ~1 minecraft:redstone_wire
setblock ~ ~ ~ minecraft:repeater[facing=south,delay=2]
setblock ~ ~ ~-1 minecraft:redstone_wire
