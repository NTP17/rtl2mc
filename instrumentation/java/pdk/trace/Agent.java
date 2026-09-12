package pdk.trace;

import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.ProtectionDomain;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;
import java.util.HashMap;
import java.util.jar.JarFile;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Observation-only hooks for the exact official Java 1.21.1 class bytes. */
public final class Agent implements ClassFileTransformer, Opcodes {
    private final Properties pins = new Properties();
    private static final String LOG = "pdk/trace/Trace";
    private static final String OBJECT = "Ljava/lang/Object;";
    private static final String TICK = "(Ldtc;Laqu;Ljd;Layw;)V";

    public static void premain(String argument, Instrumentation instrumentation) throws Exception {
        // The server bundler uses its own loader. Make the dependency-free logger
        // visible through the bootstrap loader without touching the game classpath.
        Path jar = Path.of(Agent.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        instrumentation.appendToBootstrapClassLoaderSearch(new JarFile(jar.resolveSibling("pdk-trace-helper.jar").toFile()));
        Trace.initialize();
        instrumentation.addTransformer(new Agent(), false);
    }

    public Agent() throws Exception {
        try (InputStream input = Agent.class.getResourceAsStream("/class-pins.properties")) {
            pins.load(input);
        }
    }

    private static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    @Override
    public byte[] transform(ClassLoader loader, String name, Class<?> redefining,
                            ProtectionDomain domain, byte[] original) {
        if (!pins.containsKey(name)) return null;
        try {
            String originalHash = hash(original);
            if (!pins.getProperty(name).equals(originalHash)) {
                throw new IllegalStateException("Class does not match the pinned engine: " + name);
            }
            Map<String, Integer> hooks = new LinkedHashMap<>();
            ClassReader reader = new ClassReader(original);
            // Recompute frames: the obfuscator drops otherwise-live argument types
            // once original code no longer needs them. Resolve hierarchy from class
            // resources, never by loading game classes during their transformation.
            Map<String, ClassReader> hierarchy = new HashMap<>();
            ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES) {
                private ClassReader type(String name) {
                    return hierarchy.computeIfAbsent(name, key -> {
                        try (InputStream input = loader.getResourceAsStream(key + ".class")) {
                            if (input == null) throw new IllegalStateException("Missing hierarchy resource " + key);
                            return new ClassReader(input);
                        } catch (Exception error) { throw new IllegalStateException(error); }
                    });
                }
                private boolean assignable(String target, String source) {
                    if (target.equals(source) || target.equals("java/lang/Object")) return true;
                    if (source.startsWith("[")) return target.equals("java/lang/Cloneable") || target.equals("java/io/Serializable");
                    ClassReader info = type(source);
                    if (info.getSuperName() != null && assignable(target, info.getSuperName())) return true;
                    for (String iface : info.getInterfaces()) if (assignable(target, iface)) return true;
                    return false;
                }
                @Override
                protected String getCommonSuperClass(String left, String right) {
                    if (left.equals(right)) return left;
                    if (left.startsWith("[") && right.startsWith("[")) {
                        String a = left.substring(1), b = right.substring(1);
                        if ((a.startsWith("L") || a.startsWith("[")) && (b.startsWith("L") || b.startsWith("["))) {
                            String common = getCommonSuperClass(a.startsWith("L") ? a.substring(1, a.length() - 1) : a,
                                                                b.startsWith("L") ? b.substring(1, b.length() - 1) : b);
                            return "[" + (common.startsWith("[") ? common : "L" + common + ";");
                        }
                        return "java/lang/Object";
                    }
                    if (assignable(left, right)) return left;
                    if (assignable(right, left)) return right;
                    if (left.startsWith("[") || right.startsWith("[")
                            || (type(left).getAccess() & ACC_INTERFACE) != 0
                            || (type(right).getAccess() & ACC_INTERFACE) != 0) return "java/lang/Object";
                    do { left = type(left).getSuperName(); } while (!assignable(left, right));
                    return left;
                }
            };
            reader.accept(new ClassVisitor(ASM9, writer) {
                @Override
                public MethodVisitor visitMethod(int access, String method, String desc,
                                                 String signature, String[] exceptions) {
                    MethodVisitor output = super.visitMethod(access, method, desc, signature, exceptions);
                    boolean tick = (name.equals("dia") || name.equals("dhi"))
                            && method.equals("a") && desc.equals(TICK);
                    boolean neighbor = (name.equals("dia") || name.equals("dhi"))
                            && method.equals("c") && desc.equals("(Ldcw;Ljd;Ldtc;)V");
                    boolean input = (name.equals("dia") || name.equals("dhi"))
                            && method.equals("b") && desc.equals("(Ldcw;Ljd;Ldtc;)I");
                    boolean create = name.equals("dcx") && method.equals("a")
                            && (desc.equals("(Ljd;Ljava/lang/Object;ILeyx;)Leyt;")
                                || desc.equals("(Ljd;Ljava/lang/Object;I)Leyt;"));
                    boolean accepted = name.equals("eyo") && method.equals("b") && desc.equals("(Leyt;)V");
                    boolean dispatch = name.equals("eyq") && method.equals("a")
                            && desc.equals("(Ljava/util/function/BiConsumer;)V");
                    boolean willTick = name.equals("eyq") && method.equals("b")
                            && desc.equals("(Ljd;Ljava/lang/Object;)Z");
                    boolean command = name.equals("eu") && method.equals("a")
                            && desc.equals("(Let;Ljava/lang/String;)V");
                    return new MethodVisitor(ASM9, output) {
                        private void count(String hook) { hooks.merge(hook, 1, Integer::sum); }
                        private void call(String hook, String descriptor) {
                            mv.visitMethodInsn(INVOKESTATIC, LOG, hook, descriptor, false);
                            count(hook);
                        }
                        private void loadWorldPos(int world, int pos) {
                            mv.visitVarInsn(ALOAD, world);
                            mv.visitVarInsn(ALOAD, pos);
                        }
                        @Override
                        public void visitCode() {
                            super.visitCode();
                            if (command) {
                                loadWorldPos(1, 2);
                                call("command", "(" + OBJECT + "Ljava/lang/String;)V");
                            }
                            if (accepted) {
                                mv.visitVarInsn(ALOAD, 1);
                                call("accepted", "(" + OBJECT + ")V");
                            }
                            if (tick) {
                                loadWorldPos(2, 3);
                                mv.visitVarInsn(ALOAD, 1);
                                call("tickEnter", "(" + OBJECT.repeat(3) + ")V");
                            }
                            if (neighbor) {
                                loadWorldPos(1, 2);
                                call("neighborEnter", "(" + OBJECT.repeat(2) + ")V");
                            }
                        }
                        @Override
                        public void visitInsn(int opcode) {
                            if (create && opcode == ARETURN) {
                                mv.visitInsn(DUP);
                                mv.visitVarInsn(ALOAD, 0);
                                call("request", "(" + OBJECT.repeat(2) + ")V");
                            }
                            if (willTick && opcode == IRETURN) {
                                mv.visitInsn(DUP);
                                mv.visitVarInsn(ALOAD, 1);
                                call("willTick", "(Z" + OBJECT + ")V");
                            }
                            if (input && opcode == IRETURN) {
                                mv.visitInsn(DUP);
                                loadWorldPos(1, 2);
                                call("inputRead", "(I" + OBJECT.repeat(2) + ")V");
                            }
                            if (tick && opcode == RETURN) {
                                loadWorldPos(2, 3);
                                call("tickExit", "(" + OBJECT.repeat(2) + ")V");
                            }
                            super.visitInsn(opcode);
                        }
                        @Override
                        public void visitMethodInsn(int opcode, String owner, String called,
                                                    String descriptor, boolean isInterface) {
                            boolean callback = dispatch && owner.equals("java/util/function/BiConsumer")
                                    && called.equals("accept") && descriptor.equals("(Ljava/lang/Object;Ljava/lang/Object;)V");
                            if (callback) {
                                // Original runCollectedTicks local 2 is the selected ScheduledTick.
                                mv.visitVarInsn(ALOAD, 2);
                                call("dispatch", "(" + OBJECT + ")V");
                            }
                            super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                            if (callback) call("dispatchExit", "()V");
                            if ((tick || neighbor) && called.equals("c")
                                    && descriptor.equals("(Ldcz;Ljd;Ldtc;)Z")) {
                                mv.visitInsn(DUP);
                                loadWorldPos(tick ? 2 : 1, tick ? 3 : 2);
                                mv.visitLdcInsn(tick ? "scheduled_tick" : "neighbor_check");
                                call("lockRead", "(Z" + OBJECT.repeat(2) + "Ljava/lang/String;)V");
                            }
                        }
                    };
                }
            }, ClassReader.SKIP_FRAMES);
            String expected = pins.getProperty(name + ".hooks");
            if (!hooks.toString().equals(expected)) {
                throw new IllegalStateException(name + " hook mismatch: " + hooks + "; expected " + expected);
            }
            byte[] transformed = writer.toByteArray();
            Path audit = Path.of(System.getProperty("pdk.trace.audit"));
            Files.createDirectories(audit);
            Files.write(audit.resolve(name + ".class"), transformed);
            Trace.audit(name, originalHash, hash(transformed), hooks.toString());
            return transformed;
        } catch (Throwable error) {
            Trace.failure("transform " + name, error);
            // Transformer exceptions can be ignored by the JVM. The runner treats
            // any logged failure or missing class audit as an invalid measurement.
            return null;
        }
    }
}
