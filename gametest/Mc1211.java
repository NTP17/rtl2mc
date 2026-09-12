package rtl2mc.gametest;

import java.io.File;
import java.lang.reflect.*;
import java.nio.file.Path;
import java.util.*;
import java.util.function.Consumer;
import java.util.function.Function;

/** Narrow reflection adapter to Mojang's signed, obfuscated 1.21.1 classes.
 *  Default-package game classes cannot be imported into a named Java package.
 *  Reflection keeps the official JAR, its signatures and class bytes intact.
 *  Symbols are pinned to Mojang server mappings SHA1
 *  03f8985492bda0afc0898465341eb0acef35f570.
 */
public final class Mc1211 {
    private static final Map<String, Method> methods = new HashMap<>();
    private static final Map<Class<?>, Class<?>> BOX = Map.of(
        boolean.class, Boolean.class, int.class, Integer.class, long.class, Long.class,
        float.class, Float.class, double.class, Double.class);

    private static Class<?> type(String name) {
        try { return Class.forName(name); }
        catch (ReflectiveOperationException e) { throw new IllegalStateException(e); }
    }

    private static RuntimeException unwrap(ReflectiveOperationException e) {
        Throwable cause = e instanceof InvocationTargetException ? e.getCause() : e;
        if (cause instanceof RuntimeException runtime) return runtime;
        if (cause instanceof Error error) throw error;
        return new IllegalStateException(cause);
    }

    private static boolean matches(Class<?>[] parameters, Object[] args) {
        if (parameters.length != args.length) return false;
        for (int i = 0; i < args.length; i++)
            if (args[i] != null && !BOX.getOrDefault(parameters[i], parameters[i]).isInstance(args[i])) return false;
        return true;
    }

    private static Object invoke(Object receiver, String name, Object... args) {
        Class<?> owner = receiver instanceof Class<?> c ? c : receiver.getClass();
        String key = owner.getName() + "." + name + Arrays.toString(Arrays.stream(args).map(Object::getClass).toArray());
        Method selected = methods.get(key);
        if (selected == null) {
            for (Method method : owner.getMethods()) {
                if (method.getName().equals(name) && matches(method.getParameterTypes(), args) && !method.isBridge()
                    && Modifier.isStatic(method.getModifiers()) == (receiver instanceof Class<?>)) {
                    if (selected != null) throw new IllegalStateException("Ambiguous mapped API: " + key);
                    selected = method;
                }
            }
            if (selected == null) throw new IllegalStateException("Missing mapped API: " + key);
            methods.put(key, selected);
        }
        try { return selected.invoke(receiver instanceof Class<?> ? null : receiver, args); }
        catch (ReflectiveOperationException e) { throw unwrap(e); }
    }

    private static Object make(String name, Object... args) {
        for (Constructor<?> constructor : type(name).getConstructors()) {
            if (matches(constructor.getParameterTypes(), args)) {
                try { return constructor.newInstance(args); }
                catch (ReflectiveOperationException e) { throw unwrap(e); }
            }
        }
        throw new IllegalStateException("Missing mapped constructor: " + name);
    }

    private static Object field(String owner, String name) {
        try { return type(owner).getField(name).get(null); }
        catch (ReflectiveOperationException e) { throw unwrap(e); }
    }

    public static void launch(String name, int timeout, Consumer<Context> test) throws Exception {
        invoke(type("ab"), "a"); // SharedConstants.tryDetectVersion
        invoke(type("akt"), "a"); // Bootstrap.bootStrap
        Object storage = invoke(type("erf"), "b", Path.of(".")); // createDefault
        Object access = invoke(storage, "d", "world"); // validateAndCreateAccess
        Object packs = invoke(type("ats"), "a", access); // ServerPacksSource.createPackRepository
        invoke(type("tf"), "a", make("tg", new File("gametest.xml"))); // Native JUnit reporter
        Consumer<Object> body = raw -> test.accept(new Context(raw));
        Object function = make("tr", "rtl2mc", name, "rtl2mc:empty", timeout, 0L, true, body);
        Function<Thread, Object> factory = thread -> invoke(type("tc"), "a", thread, access, packs,
            List.of(function), new BlockPos(0, 80, 0).raw);
        type("ab").getField("aV").setBoolean(null, true); // Native GameTestTicker enable
        invoke(type("net.minecraft.server.MinecraftServer"), "a", factory); // spin(GameTestServer.create)
    }

    public static final class BlockPos {
        final Object raw;
        public BlockPos(int x, int y, int z) { raw = make("jd", x, y, z); }
        @Override public String toString() { return raw.toString(); }
    }

    public static final class Context {
        final Object raw;
        Context(Object raw) { this.raw = raw; }
        public Level getLevel() { return new Level(invoke(raw, "a")); }
        public long getTick() { return (Long) invoke(raw, "i"); }
        public void assertTrue(boolean ok, String message) { invoke(raw, "a", ok, message); }
        public void runAfterDelay(long ticks, Runnable action) { invoke(raw, "b", ticks, action); }
        public void runAtTickTime(long ticks, Runnable action) { invoke(raw, "a", ticks, action); }
        public void succeed() { invoke(raw, "e"); }
    }

    public static final class Level {
        final Object raw;
        Level(Object raw) { this.raw = raw; }
        public void setChunkForced(int x, int z, boolean forced) { invoke(raw, "a", x, z, forced); }
        public void getChunk(int x, int z) { invoke(raw, "d", x, z); }
        public Level getChunkSource() { return new Level(invoke(raw, "l")); }
        public boolean isPositionTicking(long chunk) { return (Boolean) invoke(raw, "a", chunk); }
        public State getBlockState(BlockPos pos) { return new State(invoke(raw, "a_", pos.raw)); }
        public void setBlockAndUpdate(BlockPos pos, String id) {
            String block = switch (id) {
                case "minecraft:air" -> "a";
                case "minecraft:redstone_block" -> "ha";
                default -> throw new IllegalArgumentException(id);
            };
            invoke(raw, "b", pos.raw, invoke(field("dga", block), "o"));
        }
    }

    public static final class State {
        final Object raw;
        State(Object raw) { this.raw = raw; }
        public String blockId() { return invoke(field("lt", "e"), "b", invoke(raw, "b")).toString(); }
        public int power() { return (Integer) invoke(raw, "c", field("dts", "aT")); }
        public Map<String, String> properties() {
            var result = new HashMap<String, String>();
            for (Object property : (Collection<?>) invoke(raw, "B"))
                result.put((String) invoke(property, "f"), invoke(raw, "c", property).toString());
            return result;
        }
    }
}
