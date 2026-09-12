"""One-command RTL-to-world driver, with honest stage and coverage reports."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import zipfile

from redstone_pdk.router import route
from .views import export
from .common import ROOT, dump, read, sha, write
from .filelist import parse, snapshot
from .frontend import synthesize
from .toolchain import discover, select
from .verification import vectors, verify
from .world import accepted_eula, measure, record_eula, server_jar
from .minecraft import resolve as minecraft_target


def confirmation(message, preapproved=False):
    if preapproved:
        return True
    if not sys.stdin.isatty():
        return False
    return input(message + " [y/N] ").strip().lower() in ("y", "yes")


def config_for(filelist, explicit=None):
    path = Path(explicit).resolve() if explicit else Path(filelist).with_suffix(".rtl2mc.json")
    config = read(path) if path.exists() else {}
    allowed = {"top", "clock", "initial", "boot", "transactions", "vectors", "seed"}
    if not isinstance(config, dict) or set(config)-allowed:
        raise ValueError("Unknown project configuration fields: " + str(set(config)-allowed if isinstance(config, dict) else config))
    if explicit and not path.is_file():
        raise ValueError("Project configuration file does not exist")
    if "vectors" in config and isinstance(config["vectors"], str):
        config["vectors"] = read(path.parent / config["vectors"])
    return config


def ensure_dependencies(found, env, args, target):
    selection = select(found, args.synth, args.sim, imported=bool(args.netlist))
    try:
        server_jar(target)
        minecraft_missing = False
    except ValueError:
        minecraft_missing = True
    if selection["missing"] or minecraft_missing:
        from .install import plan, install
        proposal = plan(found, target)
        print(json.dumps(proposal, indent=2))
        if not proposal["packages"]:
            raise ValueError("Requested licensed tools are unavailable; portable installation cannot supply commercial licenses")
        if not confirmation("Install these latest stable tools and repository dependencies in the project-local cache?", args.install_missing):
            raise PermissionError("No installation performed. Review the proposal and rerun with --install-missing to approve it.")
        install(proposal, confirmed=True)
        found, env = discover(args.tool_dir, java_major=target["java_major"])
        selection = select(found, args.synth, args.sim, imported=bool(args.netlist))
        if selection["missing"]:
            raise ValueError("Required tools remain unavailable: " + ", ".join(selection["missing"]))
    if not accepted_eula():
        if not confirmation("Accept the Minecraft EULA (https://aka.ms/MinecraftEULA) for this local world builder?", args.accept_minecraft_eula):
            raise PermissionError("Minecraft EULA acceptance is required; no world has been launched")
        record_eula()
    return found, env, selection


def package(output, top):
    world = output / "world"
    archive = output / (top + "-world.zip")
    files = sorted(p for p in world.rglob("*") if p.is_file() and p.name != "session.lock")
    hashes = {p.relative_to(world).as_posix(): sha(p) for p in files}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, "rtl2mc_" + top + "/" + path.relative_to(world).as_posix())
    dump(output / "world-manifest.json", {"files_sha256": hashes, "zip_sha256": sha(archive)})
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="discover tools without installing or changing system configuration")
    doctor.add_argument("--tool-dir", action="append", default=[])
    run = sub.add_parser("run", help="file list to routed, tested Minecraft world")
    run.add_argument("-f", "--filelist", required=True)
    run.add_argument("--top")
    run.add_argument("--config")
    run.add_argument("--out")
    run.add_argument("--tool-dir", action="append", default=[])
    run.add_argument("--synth", choices=("auto", "dc", "genus", "yosys"), default="auto")
    run.add_argument("--sim", choices=("auto", "vcs", "xcelium", "questa", "icarus"), default="auto")
    run.add_argument("--netlist", help="route an existing RMAP netlist, preserving logic topology")
    run.add_argument("--netlist-top", help="top name in the existing netlist (defaults to RTL top)")
    run.add_argument("--minecraft-version", default="1.21.1", metavar="ID",
                     help="Java release or snapshot ID, latest-release, or latest-snapshot (default: measured 1.21.1)")
    run.add_argument("--max-cells", type=int, default=64)
    run.add_argument("--plan", action="store_true", help="show resolved sources and tool choices; no synthesis/download/world writes")
    run.add_argument("--install-missing", action="store_true", help="explicit approval to install missing latest stable open-source dependencies portably")
    run.add_argument("--accept-minecraft-eula", action="store_true", help="explicitly accept Minecraft's EULA for this local builder")
    args = parser.parse_args(argv)
    output, report = None, None
    try:
        if sys.version_info < (3, 12):
            raise ValueError("RTL2MC requires Python 3.12 or newer")
        target = minecraft_target(args.minecraft_version) if args.command == "run" else None
        found, env = discover(args.tool_dir, java_major=target["java_major"] if target else 21)
        if args.command == "doctor":
            print(json.dumps({"tools": found, "selection": select(found), "installation": "latest stable only; confirmation required"}, indent=2))
            return 0
        inputs = parse(args.filelist)
        config = config_for(Path(args.filelist).resolve(), args.config)
        selection = select(found, args.synth, args.sim, imported=bool(args.netlist))
        if args.plan:
            print(json.dumps({"inputs": inputs, "config": config, "selection": selection,
                              "minecraft": target,
                              "scope": "bounded binary combinational or single positive-edge clock; physical regression required",
                              "install_policy": "latest upstream stable tools only; consent required; explicit Minecraft snapshots are an opt-in exception"}, indent=2))
            return 0
        if args.max_cells < 1:
            raise ValueError("--max-cells must be positive")
        found, env, selection = ensure_dependencies(found, env, args, target)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = Path(args.out).resolve() if args.out else ROOT / "builds/rtl2mc" / (Path(args.filelist).stem + "-" + stamp)
        if output.exists() and any(output.iterdir()):
            raise ValueError("Output directory must be new or empty; existing worlds and results are never overwritten")
        output.mkdir(parents=True, exist_ok=True)
        build = output / "build"
        build.mkdir()
        report = {"flow": "RTL2MC", "schema_version": 1, "status": "running", "pass": False,
                  "started_utc": stamp, "stages": [], "selection": selection}
        dump(output / "run.json", report)
        dump(output / "toolchain.json", found)
        dump(output / "project.json", config)
        dump(output / "minecraft-target.json", target)
        implementations = list((ROOT / "rtl2mc").glob("*.py")) + [ROOT / "redstone_pdk" / n for n in (
            "rtl.py", "router.py", "mapping_views.py", "mapping_validation.py", "mapping_lab.py", "lab.py", "logic_cells.py", "rcon.py", "results.py")]
        dump(output / "implementation-manifest.json", {p.relative_to(ROOT).as_posix(): sha(p) for p in implementations})
        def stage(name):
            print("RTL2MC: " + name, flush=True)
            report["active_stage"] = name
            dump(output / "run.json", report)
        def passed(name):
            report["stages"].append({"name": name, "status": "passed"})
            dump(output / "run.json", report)
        stage("snapshot sources")
        manifest = snapshot(inputs, build)
        passed("snapshot sources")
        stage("synthesis and equivalence")
        graph = synthesize(build, manifest, args.top or config.get("top"), selection, found, env, config,
                           imported=args.netlist, imported_top=args.netlist_top, max_cells=args.max_cells)
        passed("synthesis and equivalence")
        stage("placement, routing and timing extraction")
        layout = route(graph)
        budget = export(graph, layout, build)
        vector_set = vectors(graph, budget, config)
        dump(build / "vectors.json", vector_set)
        passed("placement, routing and timing extraction")
        stage("source and routed simulation")
        golden, simulation = verify(build, graph, layout, vector_set, selection, found, env)
        passed("source and routed simulation")
        stage("Minecraft measurement and saved-world reopen")
        physical = measure(output, build, graph, layout, budget, vector_set, golden, found, env, target)
        passed("Minecraft measurement and saved-world reopen")
        stage("world packaging")
        archive = package(output, graph["top"])
        passed("world packaging")
        report.update(status="passed", pass_checks=True, **{"pass": True}, top=graph["top"],
                      synthesis=graph["provenance"]["backend"], simulation=simulation["backend"],
                      minecraft_version=target["id"], minecraft_qualification=target["qualification"],
                      world="world", archive=archive.name, logic_cells=len(graph["cells"]),
                      blocks=len(layout["blocks"]), route_repeaters=layout["drc"]["route_repeaters"],
                      physical_comparisons=physical["comparisons"], reopen_comparisons=physical["reopen_comparisons"],
                      coverage=vector_set.get("coverage", "user vectors"),
                      limitations=["Supported RTL subset and current router capacity only", "Settled/captured behavior; transient waveforms not qualified",
                                   "A passing regression is not exhaustive physical state-space proof"])
        report.pop("active_stage", None)
        dump(output / "run.json", report)
        write(output / "README.md", f"# RTL2MC — {graph['top']}\n\nPassed source/GLS and Minecraft checks, including save/reopen.\n\n"
              f"Copy `world/` into your Minecraft Java {target['id']} saves directory, or extract `{archive.name}` there.\n"
              "Read `world/RTL2MC-README.txt` for input controls, output readout and replay.\n\n"
              f"Coverage: {report['coverage']}. The router uses conservative timing; unrestricted RTL and transient equivalence are outside this release.\n")
        print("RTL2MC PASS - world: " + str(output / "world"), flush=True)
        print("Archive: " + str(archive), flush=True)
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, StopIteration) as exc:
        if output is not None and report is not None:
            report.update(status="failed", **{"pass": False}, error=str(exc))
            dump(output / "run.json", report)
        print("RTL2MC FAILED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
