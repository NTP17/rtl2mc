import argparse
import json
import sys

from . import lab
from .fixtures import SUITES, cases, compile_functions
from .project import ROOT, read_json, technology, validate_project


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start and inspect a project-local redstone characterization lab.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local prerequisites without downloading or starting Minecraft")
    commands.add_parser("validate", help="Validate component contracts and fixture references offline")
    commands.add_parser("catalog", help="List the full seed coverage backlog")
    fixtures = commands.add_parser("fixtures", help="Show a measurement suite")
    fixtures.add_argument("--suite", choices=SUITES, default="core")
    commands.add_parser("setup", help="Download verified server/runtime and prepare a separate lab world")
    start = commands.add_parser("start", help="Start the loopback-only laboratory in the background")
    start.add_argument("--accept-minecraft-eula", action="store_true", help="Accept https://aka.ms/MinecraftEULA for this lab server")
    run = commands.add_parser("run", help="Place fixtures in the lab and record actual Minecraft observations")
    run.add_argument("--case", choices=[case["id"] for case in cases()], help="Run a single fixture")
    run.add_argument("--suite", choices=SUITES, default="core", help="Measurement suite; default keeps the original ten core fixtures")
    commands.add_parser("stop", help="Save and stop this project's laboratory")
    commands.add_parser("export-fixtures", help="Write inspectable commands to .local/generated-fixtures")
    commands.add_parser("model-repeater", help="Validate the native event model against all 772 saved repeater fixtures and write its contract/report")
    admit = commands.add_parser("admit-buffer-cells", help="Admit four guarded buffers from a complete fresh cell run and generate their EDA views")
    admit.add_argument("run", help="Complete 64-fixture cell run directory under results/")
    connections = commands.add_parser("admit-connections", help="Audit all 204 routed buffer fixtures and export the checked connection catalog")
    connections.add_argument("run", help="Complete connection run directory under results/")
    characterize = commands.add_parser("characterize-repeater", help="Reanalyze complete saved repeater runs and write the bounded native contract")
    characterize.add_argument("runs", nargs="+", help="Run directories under results/; together they must cover the 200 repeater fixtures exactly once")
    broad = commands.add_parser("characterize-repeater-broad", help="Build the additive spatial, strength, and sequence coverage contract")
    broad.add_argument("runs", nargs="+", help="Complete nonoverlapping run directories covering all 572 broader repeater fixtures")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            print(f"Python: {sys.version.split()[0]}")
            print(f"Target: vanilla Java Edition {technology()['minecraft_version']}")
            executable = lab.java_executable()
            print(f"Java: {lab.java_version(executable).splitlines()[0] if executable else 'missing; setup installs a local Windows x64 runtime'}")
            print(f"Lab files: {'prepared' if lab.IDENTITY.exists() else 'not prepared'}")
            print("Offline checks: python pdk.py validate")
        elif args.command == "validate":
            errors = validate_project()
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            count = len(list((ROOT / "components").glob("*.json")))
            from .cells import LIBRARY
            cell_count = len(read_json(ROOT / LIBRARY)["cells"]) if (ROOT / LIBRARY).exists() else 0
            from .connections import CONTRACT
            network_count = read_json(ROOT / CONTRACT)["coverage"]["admitted"] if (ROOT / CONTRACT).exists() else 0
            print(f"Valid: {count} primitive contracts, {cell_count} isolated cells, {network_count} checked networks, {len(cases())} legacy fixtures.")
            if (ROOT/"validation/mapping/release.json").exists():
                print("RTL mapping: supported binary/synchronous subset qualified with 228 cell/route cases and two physical RTL builds; commercial execution pending.")
        elif args.command == "catalog":
            catalog = read_json(ROOT / "catalog/mechanisms.json")
            print("Seed inventory; completeness has not been established.")
            for entry in catalog["families"]:
                print(f"{entry['id']:27} {entry['status']:23} {entry['category']}")
        elif args.command == "fixtures":
            for case in cases(args.suite):
                print(f"{case['id']:30} {case['ticks'] + 1:3} samples + baseline")
        elif args.command == "setup":
            lab.setup()
        elif args.command == "start":
            lab.start(args.accept_minecraft_eula)
        elif args.command == "run":
            return lab.run(args.case, args.suite)
        elif args.command == "stop":
            lab.stop()
        elif args.command == "characterize-repeater":
            from .characterize import write_characterization
            for path in write_characterization(args.runs):
                print(path)
        elif args.command == "model-repeater":
            from .model_validation import write_model_contract
            for path in write_model_contract():
                print(path)
        elif args.command == "admit-buffer-cells":
            from .cells import write_cells
            for path in write_cells(args.run):
                print(path)
        elif args.command == "admit-connections":
            from .connections import write_connections
            for path in write_connections(args.run):
                print(path)
        elif args.command == "characterize-repeater-broad":
            from .characterize_broad import write_broad_characterization
            for path in write_broad_characterization(args.runs):
                print(path)
        elif args.command == "export-fixtures":
            for name, body in compile_functions().items():
                target = ROOT / ".local/generated-fixtures" / (name + ".mcfunction")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
            target = ROOT / ".local/generated-fixtures/suite.json"
            target.write_text(json.dumps(cases(), indent=2) + "\n", encoding="utf-8")
            print(target.parent)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
