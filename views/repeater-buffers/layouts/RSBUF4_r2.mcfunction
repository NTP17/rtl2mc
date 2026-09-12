# RSBUF4 rotation 2; origin is the repeater block.
# Clears the declared reserved volume; place only in a reserved lab area.
# Keep A stable for 20 game ticks before use; external wiring is not admitted.
fill ~-3 ~-1 ~-2 ~3 ~2 ~2 minecraft:air
fill ~-3 ~-1 ~-2 ~3 ~-1 ~2 minecraft:stone
setblock ~1 ~ ~ minecraft:redstone_wire
setblock ~ ~ ~ minecraft:repeater[facing=east,delay=2]
setblock ~-1 ~ ~ minecraft:redstone_wire
