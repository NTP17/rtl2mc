// Test body for the pinned, unmodified Mojang 1.21.1 GameTest framework.
package rtl2mc.gametest;
import com.google.gson.*;
import java.io.*;
import java.nio.file.*;
import static rtl2mc.gametest.Mc1211.*;

public final class VanillaGameTests {
    private static JsonObject test;
    private static PrintWriter observations;
    private static int outputBits;
    private static int samples;

    public static void main(String[] args) throws Exception {
        test = JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject();
        observations = new PrintWriter(Files.newBufferedWriter(Path.of("observations.jsonl")), true);
        Mc1211.launch(test.get("name").getAsString(), test.get("timeout_ticks").getAsInt(),
            VanillaGameTests::run);
    }

    private static BlockPos position(JsonArray p) {
        return new BlockPos(p.get(0).getAsInt(), p.get(1).getAsInt(), p.get(2).getAsInt());
    }

    private static void run(Context context) {
        var world = context.getLevel();
        for (var item : test.getAsJsonArray("chunks")) {
            var chunk = item.getAsJsonArray();
            int x = chunk.get(0).getAsInt(), z = chunk.get(1).getAsInt();
            world.setChunkForced(x, z, true);
            world.getChunk(x, z);
        }
        // Register every callback before ticking starts. Adding many entries
        // while GameTestInfo iterates its runnable map can rehash that map and
        // repeat callbacks on 1.21.1. The fixed loading window also makes the
        // stimulus schedule independent of machine/chunk-loading speed.
        long ready = 4000;
        context.runAtTickTime(ready, () -> {
            for (var item : test.getAsJsonArray("chunks")) {
                var chunk = item.getAsJsonArray();
                int x = chunk.get(0).getAsInt(), z = chunk.get(1).getAsInt();
                long packed = (x & 0xffffffffL) | ((z & 0xffffffffL) << 32);
                context.assertTrue(world.getChunkSource().isPositionTicking(packed),
                    "RMAP_GAMETEST_CHUNKS_TIMEOUT " + x + " " + z);
            }
            checkLayout(context);
            if (test.get("negative_control").getAsBoolean()) {
                var first = test.getAsJsonArray("outputs").get(0).getAsJsonObject();
                world.setBlockAndUpdate(position(first.getAsJsonArray("position")), "minecraft:air");
            }
        });
        int settle = test.get("settle").getAsInt();
        context.runAtTickTime(ready + settle, () -> {
            sample(context, -1, "saved_world", test.getAsJsonObject("saved_outputs"));
            drive(context, test.getAsJsonObject("initial"));
        });
        long origin = ready + 2L * settle + 1;
        for (var item : test.getAsJsonArray("events")) {
            var event = item.getAsJsonObject();
            long tick = event.get("tick").getAsLong();
            context.runAtTickTime(origin + tick, () -> drive(context, event.getAsJsonObject("inputs")));
        }
        for (var item : test.getAsJsonArray("checks")) {
            var check = item.getAsJsonObject();
            long tick = check.get("tick").getAsLong();
            context.runAtTickTime(origin + tick, () -> sample(context, tick,
                check.get("phase").getAsString(), check.getAsJsonObject("outputs")));
        }
        long last = test.get("last_tick").getAsLong();
        context.runAtTickTime(origin + last + 1, () -> {
            context.assertTrue(samples == test.get("expected_samples").getAsInt(),
                "RMAP_GAMETEST_SAMPLE_COUNT " + samples);
            context.assertTrue(outputBits == test.get("expected_output_bits").getAsInt(),
                "RMAP_GAMETEST_BIT_COUNT " + outputBits);
            System.out.println("RMAP_GAMETEST_PASS " + test.get("top").getAsString()
                + " samples=" + samples + " output_bits=" + outputBits);
            observations.close();
            context.succeed();
        });
    }

    private static void checkLayout(Context context) {
        var world = context.getLevel();
        int count = 0;
        for (var item : test.getAsJsonArray("blocks")) {
            var block = item.getAsJsonObject();
            var pos = position(block.getAsJsonArray("position"));
            var state = world.getBlockState(pos);
            String id = state.blockId();
            context.assertTrue(id.equals(block.get("id").getAsString()),
                "RMAP_GAMETEST_LAYOUT " + pos + " expected=" + block.get("id") + " actual=" + id);
            var expected = block.getAsJsonObject("properties");
            for (var property : state.properties().entrySet()) {
                String name = property.getKey();
                if (expected.has(name)) {
                    context.assertTrue(property.getValue().equals(expected.get(name).getAsString()),
                        "RMAP_GAMETEST_LAYOUT_PROPERTY " + pos + " " + name);
                }
            }
            count++;
        }
        System.out.println("RMAP_GAMETEST_LAYOUT_PASS blocks=" + count);
    }

    private static void drive(Context context, JsonObject inputs) {
        var world = context.getLevel();
        for (var item : test.getAsJsonArray("sources")) {
            var source = item.getAsJsonObject();
            String port = source.get("port").getAsString();
            if (inputs.has(port)) {
                int bit = (inputs.get(port).getAsInt() >> source.get("bit_index").getAsInt()) & 1;
                world.setBlockAndUpdate(position(source.getAsJsonArray("position")),
                    (bit == 0 ? "minecraft:air" : "minecraft:redstone_block"));
            }
        }
    }

    private static void sample(Context context, long tick, String phase, JsonObject expected) {
        var world = context.getLevel();
        var actual = new JsonObject();
        for (var item : test.getAsJsonArray("outputs")) {
            var output = item.getAsJsonObject();
            var pos = position(output.getAsJsonArray("position"));
            var state = world.getBlockState(pos);
            context.assertTrue(state.blockId().equals("minecraft:redstone_wire"), "RMAP_GAMETEST_OUTPUT_BLOCK " + pos);
            int power = state.power();
            String port = output.get("port").getAsString();
            int index = output.get("bit_index").getAsInt();
            int want = (expected.get(port).getAsInt() >> index) & 1;
            var reading = new JsonObject();
            reading.addProperty("power", power);
            reading.addProperty("expected", want);
            actual.add(output.get("name").getAsString(), reading);
            // Record failures before throwing the native GameTest assertion.
            if ((power > 0 ? 1 : 0) != want) {
                record(context, tick, phase, actual);
                context.assertTrue(false, "RMAP_GAMETEST_MISMATCH " + port + "[" + index + "] tick="
                    + tick + " expected=" + want + " power=" + power);
            }
            outputBits++;
        }
        record(context, tick, phase, actual);
        samples++;
    }

    private static void record(Context context, long tick, String phase, JsonObject actual) {
        var row = new JsonObject();
        row.addProperty("tick", tick);
        row.addProperty("gametest_tick", context.getTick());
        row.addProperty("phase", phase);
        row.add("outputs", actual);
        observations.println(row);
        System.out.println("RMAP_GAMETEST_SAMPLE tick=" + tick + " phase=" + phase + " " + actual);
    }
}
