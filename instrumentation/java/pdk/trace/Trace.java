package pdk.trace;

import java.io.BufferedWriter;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Writes observations only. No game setter, scheduler, or neighbor updater is called. */
public final class Trace {
    private static BufferedWriter output;
    private static final Map<String, Method> methods = new ConcurrentHashMap<>();
    private static final Map<Object, Map<String, Object>> tracked = new IdentityHashMap<>();
    private static final Map<Object, Map<String, Object>> pending = new IdentityHashMap<>();
    private static final ThreadLocal<Map<String, Object>> dispatch = new ThreadLocal<>();
    private static Object world;
    private static String run;
    private static String fixture;
    private static long origin;
    private static long sequence;
    private static boolean active;
    private static int sideZ;
    private static final String PREFIX = "data modify storage pdk_lab:trace marker set value \"";

    public static void initialize() throws Exception {
        Path path = Path.of(System.getProperty("pdk.trace.path"));
        Files.createDirectories(path.getParent());
        output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        emit("agent_start", Map.of("version", "java-1.21.1-lock-order-v1"));
    }

    private static Object invoke(Object object, String name, Object... args) throws Exception {
        String key = object.getClass().getName() + "/" + name + "/" + args.length;
        Method method = methods.get(key);
        if (method == null) {
            for (Method candidate : object.getClass().getMethods()) {
                if (!candidate.getName().equals(name) || candidate.getParameterCount() != args.length) continue;
                boolean matches = true;
                Class<?>[] parameters = candidate.getParameterTypes();
                for (int i = 0; i < args.length; i++) matches &= parameters[i].isInstance(args[i]);
                if (matches) { method = candidate; break; }
            }
            if (method == null) throw new NoSuchMethodException(key);
            methods.put(key, method);
        }
        return method.invoke(object, args);
    }

    private static String role(Object pos) throws Exception {
        int x = ((Number) invoke(pos, "u")).intValue();
        int y = ((Number) invoke(pos, "v")).intValue();
        int z = ((Number) invoke(pos, "w")).intValue();
        if (x != 10 || y != 80) return null;
        if (z == 5) return "dut";
        return z == sideZ ? "side" : null;
    }

    private static boolean observes(Object level, Object pos) throws Exception {
        return active && world == level && role(pos) != null;
    }

    private static String state(Object level, Object pos) throws Exception {
        return invoke(level, "a_", pos).toString();
    }

    private static Map<String, Object> eventInfo(Object tick) throws Exception {
        String block = role(invoke(tick, "b"));
        if (block == null) return null;
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("block", block);
        info.put("block_type", invoke(tick, "a").toString());
        info.put("due_game_time", invoke(tick, "c"));
        info.put("due_tick", ((Number) invoke(tick, "c")).longValue() - origin);
        Object priority = invoke(tick, "d");
        info.put("priority", invoke(priority, "a"));
        info.put("sub_tick_order", invoke(tick, "e"));
        return info;
    }

    public static void command(Object source, String command) {
        if (!command.startsWith(PREFIX) || !command.endsWith("\"")) return;
        try {
            String[] fields = command.substring(PREFIX.length(), command.length() - 1).split("\\|");
            if (fields[0].equals("begin") && fields.length == 4) {
                world = invoke(source, "e");
                run = fields[1]; fixture = fields[2]; origin = Long.parseLong(fields[3]);
                sideZ = fixture.contains("_north_") ? 4 : 6;
                tracked.clear(); pending.clear(); dispatch.remove(); active = true;
                emit("case_begin", Map.of());
            } else if (fields[0].equals("end") && fields.length == 1) {
                emit("case_end", Map.of("pending_events_remaining", pending.size(), "ignored_duplicate_requests", tracked.size()));
                active = false; tracked.clear(); pending.clear(); dispatch.remove();
            }
        } catch (Throwable error) { failure("command marker", error); }
    }

    public static void request(Object tick, Object level) {
        if (!active || world != level) return;
        try {
            Map<String, Object> info = eventInfo(tick);
            if (info != null) { tracked.put(tick, info); emit("enqueue_request", info); }
        } catch (Throwable error) { failure("enqueue request", error); }
    }

    public static void accepted(Object tick) {
        if (!active) return;
        Map<String, Object> info = tracked.remove(tick);
        if (info != null) { pending.put(tick, info); emit("enqueue_accepted", info); }
    }

    public static void dispatch(Object tick) {
        if (!active) return;
        Map<String, Object> info = pending.remove(tick);
        dispatch.set(info);
        if (info != null) emit("dispatch_begin", info);
    }

    public static void dispatchExit() {
        if (active && dispatch.get() != null) emit("dispatch_end", dispatch.get());
        dispatch.remove();
    }

    public static void tickEnter(Object level, Object pos, Object before) {
        try {
            if (observes(level, pos)) emit("block_tick_enter", Map.of("block", role(pos), "state", before.toString()));
        } catch (Throwable error) { failure("tick entry", error); }
    }

    public static void tickExit(Object level, Object pos) {
        try {
            if (observes(level, pos)) emit("block_tick_exit", Map.of("block", role(pos), "state", state(level, pos)));
        } catch (Throwable error) { failure("tick exit", error); }
    }

    public static void neighborEnter(Object level, Object pos) {
        try {
            if (observes(level, pos)) emit("neighbor_check", Map.of("block", role(pos), "state", state(level, pos)));
        } catch (Throwable error) { failure("neighbor check", error); }
    }

    public static void lockRead(boolean locked, Object level, Object pos, String site) {
        try {
            if (observes(level, pos)) emit("lock_read", Map.of("block", role(pos), "site", site, "locked", locked));
        } catch (Throwable error) { failure("lock read", error); }
    }

    public static void inputRead(int value, Object level, Object pos) {
        try {
            if (observes(level, pos)) emit("input_read", Map.of("block", role(pos), "value", value));
        } catch (Throwable error) { failure("input read", error); }
    }

    public static void willTick(boolean value, Object pos) {
        try {
            if (active && role(pos) != null) emit("will_tick_this_tick", Map.of("block", role(pos), "value", value));
        } catch (Throwable error) { failure("remaining tick read", error); }
    }

    public static void audit(String name, String original, String transformed, String hooks) {
        emit("class_transform", Map.of("class", name, "original_sha256", original,
                "transformed_sha256", transformed, "hooks", hooks));
    }

    public static void failure(String where, Throwable error) {
        emit("logger_error", Map.of("where", where, "error", error.toString()));
    }

    private static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof Number || value instanceof Boolean) return value.toString();
        if (value instanceof Map<?, ?> map) {
            StringBuilder result = new StringBuilder("{");
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (result.length() > 1) result.append(',');
                result.append(json(entry.getKey().toString())).append(':').append(json(entry.getValue()));
            }
            return result.append('}').toString();
        }
        return "\"" + value.toString().replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }

    private static synchronized void emit(String event, Map<String, Object> details) {
        try {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("sequence", ++sequence); row.put("event", event);
            if (active) {
                long time = ((Number) invoke(world, "Z")).longValue();
                row.put("run", run); row.put("case", fixture);
                row.put("game_time", time); row.put("tick", time - origin);
            }
            Map<String, Object> current = dispatch.get();
            if (current != null) row.put("dispatch_sub_tick_order", current.get("sub_tick_order"));
            row.putAll(details);
            output.write(json(row)); output.newLine(); output.flush();
        } catch (Throwable error) {
            System.err.println("PDK_TRACE_FATAL " + event + " " + error);
        }
    }
}
