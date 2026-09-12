"""Build the pinned observation agent using the project-local Java runtime."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redstone_pdk import lab

BUILD = ROOT / ".local/instrumentation"
ENGINE_SHA256 = "c301de10f575027d13eac18c7f34409d60648cf56a35d566aa1f530ff617840a"
HOOKS = {
    "dcx": "{request=2}",
    "eyo": "{accepted=1}",
    "eyq": "{dispatch=1, dispatchExit=1, willTick=1}",
    "dia": "{tickEnter=1, lockRead=2, tickExit=2, neighborEnter=1, inputRead=2}",
    "dhi": "{inputRead=1, neighborEnter=1, tickEnter=1, tickExit=1}",
    "eu": "{command=1}",
}


def build():
    pins = json.loads((ROOT / "instrumentation/dependencies.json").read_text())
    for name, pin in pins.items():
        lab.download(pin["url"], BUILD / "dependencies" / name, "sha256", pin["sha256"], pin["size"])
    engine = ROOT / ".local/server/versions/1.21.1/server-1.21.1.jar"
    if lab.file_hash(engine, "sha256") != ENGINE_SHA256:
        raise RuntimeError("Engine differs from the inspected official build")
    classes = BUILD / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    sources = sorted((ROOT / "instrumentation/java").rglob("*.java"))
    subprocess.run([lab.java_executable(), "-jar", str(BUILD / "dependencies/ecj-3.39.0.jar"),
                    "-21", "-proc:none", "-encoding", "UTF-8", "-classpath", str(BUILD / "dependencies/asm-9.7.1.jar"),
                    "-d", str(classes), *map(str, sources)], check=True)
    class_pins = {}
    with zipfile.ZipFile(engine) as game:
        for name in HOOKS:
            class_pins[name] = hashlib.sha256(game.read(name + ".class")).hexdigest()
    properties = "\n".join(f"{name}={value}\n{name}.hooks={HOOKS[name]}" for name, value in class_pins.items()) + "\n"
    # Fixed archive timestamps make identical builds reproducible.
    def put(jar, name, data):
        jar.writestr(zipfile.ZipInfo(name, (2024, 8, 8, 0, 0, 0)), data)
    with zipfile.ZipFile(BUILD / "pdk-trace-agent.jar", "w") as agent:
        put(agent, "META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\r\nPremain-Class: pdk.trace.Agent\r\nClass-Path: pdk-trace-helper.jar\r\n\r\n")
        put(agent, "class-pins.properties", properties.encode())
        for path in sorted((classes / "pdk/trace").glob("Agent*.class")):
            put(agent, path.relative_to(classes).as_posix(), path.read_bytes())
        with zipfile.ZipFile(BUILD / "dependencies/asm-9.7.1.jar") as asm:
            for name in sorted(asm.namelist()):
                if name.startswith("org/objectweb/asm/") and name.endswith(".class"):
                    put(agent, name, asm.read(name))
    with zipfile.ZipFile(BUILD / "pdk-trace-helper.jar", "w") as helper:
        for path in sorted((classes / "pdk/trace").glob("Trace*.class")):
            put(helper, path.relative_to(classes).as_posix(), path.read_bytes())
    metadata = {
        "engine_sha256": ENGINE_SHA256, "class_sha256": class_pins, "expected_hooks": HOOKS,
        "dependencies": pins, "java": lab.java_version(lab.java_executable()),
        "sources": {p.relative_to(ROOT).as_posix(): lab.file_hash(p, "sha256") for p in [*sources, Path(__file__), ROOT / "instrumentation/dependencies.json"]},
        "artifacts": {name: lab.file_hash(BUILD / name, "sha256") for name in ("pdk-trace-agent.jar", "pdk-trace-helper.jar")},
    }
    (BUILD / "build.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print("Built pinned agent and bootstrap logger.")


if __name__ == "__main__":
    build()
