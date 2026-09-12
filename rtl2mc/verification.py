"""Route-budgeted stimuli and source/routed simulation with explicit controls."""
import random
import re

from redstone_pdk.mapping_validation import testbench, validate_vectors
from redstone_pdk.mapping_controls import artifacts
from .common import dump, execute, read, sha, write
from .toolchain import unavailable_license


def vectors(graph, budget, config):
    inputs = {n: p for n, p in graph["ports"].items() if p["direction"] == "input"}
    initial = {n: 0 for n in inputs}
    half = budget["settle"] + 2
    if "vectors" in config:
        result = config["vectors"]
    elif graph["clock_bit"] is None:
        count = sum(len(p["bits"]) for p in inputs.values())
        if count <= 6:
            values = list(range(1 << count))
            scope = "exhaustive binary input combinations"
        else:
            r = random.Random(config.get("seed", 1))
            values = list(dict.fromkeys([0, (1 << count)-1] + [1 << i for i in range(count)]
                                       + [r.getrandbits(count) for _ in range(32)]))
            scope = "zero, all-one, walking-one and 32 seeded random vectors; not exhaustive"
        events = []
        for index, value in enumerate(values):
            state, offset = {}, 0
            for name, port in inputs.items():
                width = len(port["bits"])
                state[name] = (value >> offset) & ((1 << width)-1)
                offset += width
            events.append({"tick": index*(half+1), "inputs": state})
        result = {"initial": initial, "events": events, "checks": [e["tick"]+half for e in events], "coverage": scope}
    else:
        clock = next(n for n, p in inputs.items() if graph["clock_bit"] in p["bits"])
        if config.get("clock", clock) != clock:
            raise ValueError("Configured clock differs from the mapped register clock")
        boot = config.get("boot", [])
        if len(boot) < 2:
            raise ValueError("Clocked RTL needs at least two explicit boot cycles in the .rtl2mc.json config; reset polarity/behavior is never guessed")
        initial.update(config.get("initial", {}))
        initial[clock] = 0
        steps = boot + config.get("transactions", [])
        if len(steps) > 256:
            raise ValueError("At most 256 clocked verification cycles per run")
        events, checks = [], []
        for i, step in enumerate(steps):
            if clock in step:
                raise ValueError("Boot/transaction entries contain data inputs only; the flow generates the clock")
            events += [{"tick": 2*i*half, "inputs": {**step, clock: 0}},
                       {"tick": (2*i+1)*half, "inputs": {clock: 1}}]
            if i >= len(boot)-1:
                checks.append((2*i+2)*half-1)
        # Leave the saved world with a low, settled external clock.
        events.append({"tick": 2*len(steps)*half, "inputs": {clock: 0}})
        checks.append((2*len(steps)+1)*half-1)
        result = {"initial": initial, "events": events, "checks": checks,
                  "coverage": "explicit boot and user transaction sequence; not exhaustive state-space verification"}
    validate_vectors(graph, budget, result)
    return result


def commands(backend, tools, files, top, label, mode, inputs=None, negative=False):
    opts = inputs or {"include_dirs": [], "defines": []}
    defines = list(opts["defines"])
    if mode == "sdf":
        defines.append("RMAP_SDF_ONLY")
    if mode in ("golden", "portable") or negative:
        defines.append("NO_ANNOTATE")
    if backend == "icarus":
        flags = ["-g2012", "-s", top]
        if mode == "sdf":
            flags.append("-gspecify")
        flags += ["-I" + p for p in opts["include_dirs"]] + ["-D" + d for d in defines]
        return [[*tools["icarus"]["argv"], *flags, "-o", label+".vvp", *files],
                [*tools["vvp"]["argv"], label+".vvp"]]
    flags = ["+incdir+"+p for p in opts["include_dirs"]] + ["+define+"+d for d in defines]
    if backend == "vcs":
        return [[*tools["vcs"]["argv"], "-full64", "-sverilog", "-timescale=1ns/1ps", "-top", top,
                 "+sdfverbose", *flags, *files, "-o", label+"-simv"], ["./"+label+"-simv", "+sdfverbose"]]
    if backend == "xcelium":
        return [[*tools["xcelium"]["argv"], "-64bit", "-sv", "-timescale", "1ns/1ps", "-top", top,
                 "-xmlibdirname", label+".d", *flags, *files]]
    if backend == "questa":
        library = label.replace("-", "_") + "_work"
        sdf_flags = ["-sdfannotatepercentage", "-sdfreport=" + label + "-sdf.rpt"] if mode == "sdf" else []
        return [[*tools["vlib"]["argv"], library],
                [*tools["vlog"]["argv"], "-64", "-sv", "-timescale", "1ns/1ps", "-work", library, *flags, *files],
                [*tools["questa"]["argv"], "-64", "-c", "-lib", library, "-onfinish", "stop", "-voptargs=+acc",
                 "-wlf", label + ".wlf", "-l", label + "-transcript.log", *sdf_flags, top,
                 "-do", label + ".do"]]
    raise ValueError("Unsupported simulation backend")


def diagnostic_text(log, label):
    checked = re.sub(r"(?m)^# ?", "", log) if label.startswith("questa-") else log
    if label == "questa-width" and "RMAP_WIDTH_CAUGHT" in checked:
        # Questa emits Error severity for the deliberately illegal pulse.
        # Only this one native width error is expected; all other errors fail.
        checked, count = re.subn(r"(?m)^\*\* Error: \$width\([^\r\n]*\);\r?$", "", checked)
        if count != 1 or "Process: /width_tb/dut/c_dff/#Width#" not in checked:
            raise ValueError("Questa width control did not report exactly the expected native violation")
    if label.startswith("icarus-"):
        checked = re.sub(r"(?m)^SDF WARNING: [^\r\n]+:\d+: TIMINGCHECK not supported\.\r?$", "", checked)
    return checked


DIAGNOSTICS = r"(?im)^\s*(?:\*\*\s*)?(?:FATAL:|Error:|Error-\[|Fatal-\[)|\*[EF],|SDF (?:ERROR|WARNING)|Warning-\[SDF|\*W,SDF\w*|\*\* Warning:.*\bSDF\b"


def run_commands(folder, jobs, label, env, marker, negative=False):
    if label.startswith("questa-"):
        write(folder / (label + ".do"), "onerror {quit -force -code 1}\nrun -all\nquit -force -code 0\n")
    logs = []
    for index, argv in enumerate(jobs):
        code, log = execute(argv, folder, f"{label}-{index}", env, timeout=1800, allow_failure=True)
        logs.append(log)
        if unavailable_license(log):
            raise LicenseUnavailable(label)
        expected_failure = negative and marker in log
        if code and not expected_failure:
            raise RuntimeError(f"Simulation failed: {label}-{index}.log")
        checked_log = diagnostic_text(log, label)
        if not expected_failure and re.search(DIAGNOSTICS, checked_log):
            raise ValueError("Simulator diagnostics prevent qualification: " + label)
    log = "\n".join(logs)
    write(folder / (label + ".log"), log)
    # Some VCS hosts return zero even after $fatal; the marker is mandatory.
    if marker not in log or (negative and "RMAP_ARCS_PASS" in log):
        raise ValueError("Missing or contradictory simulation control marker: " + label)
    return log


class LicenseUnavailable(RuntimeError):
    pass


def xcelium_annotation(log, sdf_text):
    """Require the native annotation counts to match every generated SDF arc."""
    expected = {
        "Pathdelays": len(re.findall(r"\(IOPATH\b", sdf_text)),
        "Tchecks": len(re.findall(r"\((?:SETUPHOLD|SETUP|HOLD|WIDTH)\b", sdf_text)),
    }
    report = {}
    for kind, count in expected.items():
        pattern = (r"No\. of " + kind + r"\s*=\s*(\d+)\s+No\. of Disabled " + kind
                   + r"\s*=\s*(\d+)\s+Annotated\s*=\s*[\d.]+%\s*\((\d+)/(\d+)\)")
        matches = re.findall(pattern, log)
        if len(matches) != 1:
            raise ValueError("Missing or ambiguous Xcelium SDF annotation statistics: " + kind)
        total, disabled, annotated, eligible = map(int, matches[0])
        if disabled or (total, annotated, eligible) != (count, count, count):
            raise ValueError("Incomplete Xcelium SDF annotation: " + kind)
        report[kind] = {"expected": count, "annotated": annotated, "disabled": disabled}
    return report


def questa_annotation(log, sdf_text, unannotated_report):
    """Check native counts and require a completely annotated specify model."""
    text = re.sub(r"(?m)^# ?", "", log)
    expected = {kind: len(re.findall(r"\(" + kind + r"\b", sdf_text))
                for kind in ("IOPATH", "SETUPHOLD", "SETUP", "HOLD", "WIDTH")}
    total_checks = sum(count for kind, count in expected.items() if kind != "IOPATH")
    summaries = re.findall(r"SDF statistics: No\. of Pathdelays = (\d+) Annotated = ([\d.]+)% "
                           r"No\. of Tchecks = (\d+) Annotated = ([\d.]+)%", text)
    if len(summaries) != 1:
        raise ValueError("Missing or ambiguous Questa SDF annotation statistics")
    paths, path_percent, checks, check_percent = summaries[0]
    if (int(paths), int(checks)) != (expected["IOPATH"], total_checks) or any(
            float(percent) != 100 for count, percent in ((int(paths), path_percent), (int(checks), check_percent)) if count):
        raise ValueError("Incomplete Questa SDF annotation")
    for kind, count in expected.items():
        name = "Path Delays" if kind == "IOPATH" else kind
        rows = re.findall(r"(?m)^\s*" + name + r"\s+(\d+)\s+(\d+)\s+([\d.]+)\s*$", text)
        if count and (len(rows) != 1 or tuple(map(int, rows[0][:2])) != (count, count) or float(rows[0][2]) != 100):
            raise ValueError("Incomplete Questa annotation table: " + kind)
        if not count and rows:
            raise ValueError("Unexpected Questa annotation entries: " + kind)
    complete = ["Unannotated Specify Objects Report:", "===================================",
                "All instances with specify block objects were completely annotated."]
    if [line.strip() for line in unannotated_report.splitlines() if line.strip()] != complete:
        raise ValueError("Questa found unannotated or partially annotated specify objects")
    return {"Pathdelays": {"expected": int(paths), "annotated": int(paths)},
            "Tchecks": {"expected": int(checks), "annotated": int(checks)},
            "timing_check_types": {k: v for k, v in expected.items() if k != "IOPATH" and v},
            "unannotated_instances": 0}


def annotation_report(backend, folder, label, sdf_name):
    log, sdf_text = (folder / (label + ".log")).read_text(), (folder / sdf_name).read_text()
    if backend == "xcelium":
        return xcelium_annotation(log, sdf_text)
    path = folder / (label + "-sdf.rpt")
    report = questa_annotation(log, sdf_text, path.read_text())
    return {**report, "unannotated_report_sha256": sha(path)}


def parse_golden(log, graph, vectors):
    expected_names = {"out_"+n for n, p in graph["ports"].items() if p["direction"] == "output"}
    expected_names |= {c["name"]+"_"+p for c in graph["cells"] for p in c["pins"]}
    rows = {}
    for tick, name, value in re.findall(r"^(?:# )?GOLD (\d+) (\w+) ([0-9a-fxXzZ]+)$", log, re.M):
        if any(c in value.lower() for c in "xz"):
            raise ValueError("Initialization left unknown RTL state at an observation")
        row = rows.setdefault(int(tick), {})
        if name in row:
            raise ValueError("Duplicate golden observation")
        row[name] = int(value, 16 if name.startswith("out_") else 2)
    if set(rows) != set(vectors["checks"]) or any(set(r) != expected_names for r in rows.values()):
        raise ValueError("Incomplete golden observation coverage")
    return rows


def verify(folder, graph, layout, vector_set, selection, tools, env):
    inputs = read(folder / "inputs.json")
    attempts = []
    for backend in selection["simulation_candidates"]:
        try:
            golden = None
            annotation = {}
            for mode in ("golden", "sdf", "portable"):
                tb = "tb-"+mode+".sv"
                write(folder / tb, testbench(graph, layout, vector_set, mode))
                files = [p["file"] for p in inputs["sources"]] + ["logical.v", tb]
                if mode != "golden":
                    files += ["mapped.v", "cells-"+("portable" if mode == "portable" else "timing")+".sv"]
                log = run_commands(folder, commands(backend, tools, files, "mapping_tb", backend+"-"+mode, mode, inputs),
                                   backend+"-"+mode, env, "RMAP_RTL_PASS")
                if backend in ("xcelium", "questa") and mode == "sdf":
                    annotation["routed"] = annotation_report(backend, folder, backend + "-" + mode, "mapped.sdf")
                rows = parse_golden(log, graph, vector_set)
                if golden is not None and golden != rows:
                    raise ValueError("Golden source behavior differs between simulation modes")
                golden = rows
            for name, content in artifacts().items():
                write(folder / name, content)
            controls = []
            for label, top, marker, negative in (("arcs", "arc_tb", "RMAP_ARCS_PASS", False),
                                                 ("missing-sdf", "arc_tb", "RMAP_ARC_MISMATCH", True),
                                                 ("width", "width_tb", "RMAP_WIDTH_CAUGHT", False)):
                if label == "width" and backend == "icarus":
                    controls.append({"name": label, "status": "not supported by Icarus; routed procedural guards active"})
                    continue
                jobs = commands(backend, tools, ["cells-timing.sv", "arc-bench.sv"], top, backend+"-"+label, "sdf", negative=negative)
                log = run_commands(folder, jobs, backend+"-"+label, env, marker, negative)
                if backend in ("xcelium", "questa") and not negative:
                    annotation[label] = annotation_report(backend, folder, backend + "-" + label, "arc.sdf")
                controls.append({"name": label, "status": "passed", "log_sha256": sha(folder / (backend+"-"+label+".log"))})
            attempts.append({"backend": backend, "status": "passed"})
            report = {"pass": True, "backend": backend, "attempts": attempts,
                      "observations": len(golden), "source_probes": sum(map(len, golden.values())), "controls": controls,
                      "scope": "Source RTL vs routed outputs at settled checks; source internal oracle from the equivalent logical graph",
                      "coverage": vector_set.get("coverage", "user vectors"),
                      "sdf_annotation": annotation,
                      "sdf_timing_checks": "native plus procedural guards" if backend != "icarus" else "procedural guards; native SDF TIMINGCHECK unsupported"}
            dump(folder / "eda-report.json", report)
            dump(folder / "golden.json", golden)
            return golden, report
        except LicenseUnavailable:
            attempts.append({"backend": backend, "status": "license unavailable"})
    raise RuntimeError("No simulation candidate has an available license/runtime")
