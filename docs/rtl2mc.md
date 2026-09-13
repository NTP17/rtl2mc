# RTL2MC: RTL sources to a Minecraft world

RTL2MC snapshots the sources, synthesizes and proves the logic, places and
routes the physical cells, generates timing views, compares routed simulation
with source RTL, measures the actual circuit in an isolated vanilla Minecraft
world, saves and reopens that world, and packages the save folder.

This initial implementation uses the existing binary combinational and
single-positive-edge-clock subset. The spacious router, capacity limits,
explicit initialization, and settled-observation timing contract still apply.
Automation does not turn a finite Minecraft regression into an exhaustive
physical proof or make unrestricted SystemVerilog implementable.

## One-command runs

Python 3.12 or newer is the bootstrap prerequisite. From the project directory:

```text
python rtl2mc.py run examples/rtl/adder.sv
python rtl2mc.py run examples/rtl/multifile/adder.sv examples/rtl/multifile/half_adder.sv -top adder
python rtl2mc.py run -f examples/rtl/counter.f --out builds/my-counter
python rtl2mc.py doctor
python rtl2mc.py run examples/rtl/counter.sv --plan
```

The Python entry point is shared by Windows and Linux. Windows also has
`rtl2mc.cmd`; Linux has `sh tools/rtl2mc` (or make that launcher executable).
No shell activation is required for tools discovered by the driver.

The default output is a fresh timestamped directory under `builds/rtl2mc`.
Its name starts with the file-list stem when `-f` is supplied, or the first
source's stem otherwise.
An explicit output directory must be new or empty. Existing circuits and worlds
are never silently overwritten. Failures return nonzero and retain logs.
`run.json` records success only after simulation, physical checks, clean
shutdown, reopen verification, and packaging all pass. Incremental resume is
not implemented; restart a failed run into a fresh directory.

## Minecraft versions and snapshots

```text
python rtl2mc.py run -f examples/rtl/adder.f --minecraft-version 1.21.1
python rtl2mc.py run -f examples/rtl/adder.f --minecraft-version 24w33a
python rtl2mc.py run -f examples/rtl/adder.f --minecraft-version latest-release
python rtl2mc.py run -f examples/rtl/adder.f --minecraft-version latest-snapshot
```

The default and **oldest implemented target is 1.21.1**, the measured library
baseline. This is a qualification boundary, not a claim that every redstone
mechanism became stable then. Mojang continues to change redstone behavior and
experiment with update ordering; the
[24w33a redstone experiment](https://feedback.minecraft.net/hc/en-us/articles/29296154589581-Minecraft-Java-Edition-Snapshot-24w33a)
is one example. Experimental feature toggles stay at vanilla defaults. Selecting
a snapshot does not enable every experiment included in it.

Other releases and snapshots at or after the baseline's release date are
**candidate targets**. Exact IDs, Mojang metadata/server hashes, required Java
version, and engine-declared datapack versions are recorded. Aliases resolve
once per invocation. Datapack format changes and the
[1.21.11 game-rule renames](https://www.minecraft.net/en-us/article/minecraft-java-edition-1-21-11)
have adapters; unknown interface changes fail the affected stage.

A candidate is qualified **for that circuit and its recorded checks** only
after its own Minecraft and save/reopen checks pass. It does not inherit the
whole 1.21.1 PDK characterization. Earlier versions need a compatible harness
and characterization before lowering the floor. Only 1.21.1 has been run end
to end in this implementation so far.

An explicit Minecraft snapshot selection is separate from dependency policy:
it never authorizes nightly synthesis tools, simulators, or Java runtimes.

## File lists and sequential initialization

Supply one or more `.sv`/`.v` files as positional arguments to `run`. Direct
paths are relative to the current working directory and retain their supplied
order. Quote paths containing spaces. Options may appear before, between or
after source arguments. The sources are compiled together as one design.

Use `-top MODULE` or `--top MODULE` to select the top module by name. These are
equivalent and override the `top` field in the project configuration. Without
either setting, synthesis infers the top when there is exactly one root module;
ambiguous designs fail with a list of candidates. `--plan` reports the requested
top, or `null` when it will be inferred during synthesis.

Command-line macros accept `+define+NAME`, `+define+NAME=VALUE`, and multiple
definitions in one argument, such as `+define+FEATURE+WIDTH=8`. A definition
without `=VALUE` has value `1`; `+define+NAME=` explicitly defines empty text.
Repeat the option to add more definitions. Quote an entire argument when its
value contains spaces. These definitions are recorded in `build/inputs.json`
and passed to the synthesis, equivalence and source/routed simulation stages.

`-f FILELIST` remains supported and can be combined with direct sources and
`+define+` arguments. The file list expands first; direct sources and command-line
definitions are appended in their respective supplied order. Duplicate sources
are rejected, including duplicates across the two input forms. A file list
containing only options may accompany direct sources. Include directories and
other file-list flags are supplied through the file list.

The top-level list is relative to its own directory. Sources retain their listed
order. Supported entries: `.v`/`.sv` paths, quoted paths with spaces,
`+incdir+...`, `+define+NAME=VALUE`, `-I`, `-D`, `-sv`, `-sverilog`, nested `-f`/`-F`,
`#`/`//` comments, and `$VAR`, `${VAR}`, `%VAR%` environment references. A nested
`-f` inherits the parent base directory; `-F` uses the included file's directory.
These are RTL2MC's rules; vendor file-list dialects are not identical.
Unknown switches, recursive lists, undefined variables, and duplicate sources
fail explicitly. Arbitrary compiler scripts and library search switches are
not accepted.

Source/include trees are copied with SHA256 manifests. Every subsequent tool
reads those bytes. Limit include roots to HDL directories: snapshots are
bounded to 4096 files / 64 MiB. Direct source inputs use the same snapshot and
validation path as listed sources; no temporary file list is generated.

With `-f`, the default configuration is its sibling
`<filelist-stem>.rtl2mc.json`. Otherwise it is the sibling
`<first-source-stem>.rtl2mc.json` of the first direct source. `--config` overrides
that choice, which is useful when a shared package or helper is listed first.

Clocked designs also need initialization and test transactions in that config.
Both `counter.sv` and `-f counter.f` automatically pick up `counter.rtl2mc.json`:

```json
{
  "top": "counter",
  "clock": "clk",
  "initial": {"reset": 1, "enable": 0},
  "boot": [{"reset": 1}, {"reset": 1}],
  "transactions": [{"reset": 0, "enable": 1}, {}, {}, {"enable": 0}]
}
```

Each entry is one generated clock cycle. Data changes with the falling edge;
observations follow the extracted settling budget. Omitted input fields retain
their values. At least two explicit boot cycles are required, and unknown RTL
state at an observation fails qualification. Reset polarity/behavior is never
guessed. `--config` chooses another config. Its `vectors` field can instead
contain a tick-level vector object or a JSON path relative to the config.

Combinational designs with at most six input bits get exhaustive binary input
combinations. Larger designs get zero/all-one/walking-one and seeded random
stimuli; the coverage limit is recorded. Source equivalence and finite physical
regression remain separate evidence.

## Tool selection and stable portable installation

| Stage | Automatic preference |
|---|---|
| Logic synthesis | DC with Library Compiler, then Genus, then Yosys |
| Source/routed simulation | VCS, then Xcelium, then Questa, then Icarus + vvp |
| Structural import/equivalence | Yosys helper, including commercial synthesis runs |
| Placement/routing | Minecraft-specific router |
| Physical checks/save | Selected vanilla server and compatible Java runtime |

Selection is independent per stage: DC + Icarus and Yosys + VCS are valid.
Verilator is inventoried as an optional portable-timing cross-check; it cannot
replace four-state/SDF qualification. The automatic flow does not require or
execute Verilator. Native binaries take precedence over cached portable tools.

Discovery checks PATH, `--tool-dir`, `RTL2MC_TOOL_PATH`, vendor home variables,
`SV2RT_UCRT_ROOT` (Windows default `C:/msys64/ucrt64`), and project-local tools.
`RTL2MC_DC`, `RTL2MC_LC`, `RTL2MC_GENUS`, `RTL2MC_VCS`, `RTL2MC_XCELIUM`,
`RTL2MC_QUESTA`, `RTL2MC_VLOG`, `RTL2MC_VLIB`, `RTL2MC_YOSYS`, `RTL2MC_ICARUS`,
`RTL2MC_VVP`, and `RTL2MC_JAVA` can specify executables. Questa requires the
`vsim`, `vlog` and `vlib` companions. `RTL2MC_YOSYS=wasm` selects an installed YoWASP fallback.
`--synth` and `--sim` force a backend.

Version probes do not prove license availability. Automatic runs can advance
to another discovered candidate on a recognized license failure. Design errors
fail the run; forced selections never silently change backend. DC without
Library Compiler is incomplete for this flow. Commercial products/licenses
are never installed automatically.

If required dependencies are missing, a concrete package plan is resolved and
shown before installation. Consent is interactive or supplied explicitly via
`--install-missing`. Noninteractive runs without approval fail without
installing. Existing EULA acceptance is reused; fresh users separately accept
Minecraft's EULA, interactively or with `--accept-minecraft-eula`.

**Every newly installed EDA tool must correspond to the latest upstream stable
release at installation time.** Drafts, prereleases, development snapshots,
nightly bundles, and older substitutes are rejected. Versions, URLs, and
checksums are locked. Existing installed tools are not automatically upgraded.

Portable Yosys uses a release-derived
[YoWASP wheel](https://github.com/YoWASP/yosys/tree/develop/pypi): its upstream
snapshot distance must be zero and its version must match the latest stable
Yosys release. Windows Icarus uses an official MSYS2 UCRT package only when its
upstream version matches the stable release. Linux Icarus uses an exact-version
conda-forge environment created with stable, checksum-verified micromamba;
solved packages are locked before installation. Java uses the latest GA release
in the feature line required by the selected Minecraft target.

Dependencies stay under `.local/rtl2mc`, with no administrator installation or
permanent PATH changes. A missing stable build, unsupported architecture,
unresolvable dependency, checksum mismatch, or unavailable compatible stable
Java runtime fails explicitly. Bootstrap initially targets Windows/Linux
x86-64. Metadata resolution has been checked; fresh installer execution on
clean hosts remains unqualified.

## Direct commercial netlists and routed timing

```text
python rtl2mc.py run -f examples/rtl/counter.f --netlist my-netlists/counter.v --netlist-top counter_gate --out builds/counter-from-dc
```

The importer reads RMAP instances as blackboxes, resolves/flattens wiring, and
preserves each logic instance and its pin connections without another logic
optimization/mapping pass. Canonical physical names have correspondence in
`instance-map.json`. Unsupported gates/pins, multiple drivers, and unsupported
clocks fail. The initial adapter admits RMAP_NOR2/INV/DFF; synthesis buffers are
excluded, and the router adds characterized physical repeaters.

Source-to-import equivalence is proven before routing. Its reference frontend
is still Yosys: commercial-only RTL language features are not automatically
supported because DC/Genus accepts them. Post-route `mapped.v`, `mapped.sdf`,
and `mapped.sdc` contain actual routing repeaters and clock balancing.

Simulation uses regenerated timing views, mandatory positive arc tests, and
deliberately missing-SDF controls. Commercial simulators additionally run the
native pulse-width notifier control. Icarus cannot implement native SDF
TIMINGCHECK; the report records that limit and procedural checks guard routed
data/clock interfaces. Transient glitch equivalence remains outside the claim.
The original 48-run matrix covered DC/Yosys/Genus paired with
VCS/Icarus/Xcelium/Questa across four designs, including world export,
save/reopen and native GameTest. See [recorded validation](validation.md) and
[reproduction commands](testing.md). These archived measurements are distinct
from validation of a changed checkout. Icarus's native timing-check limit applies.

## Outputs and validation

`world/` is a standalone save with a creative spawn platform, input commands,
output readout, replay datapack, and README. Circuit chunks stay force-loaded.
Inputs retain the measured redstone-block/air driver interface. No additional
lever/lamp load is attached to a certified pin.

`<top>-world.zip` contains only the save, never server binaries/properties or an
RCON password. `world-manifest.json` records its contents and checksum.
`build/` contains source, HDL, timing, and layout evidence; `verification/`
contains raw Minecraft commands and observations. Local server files stay in
`work/server`, outside the distributable world.

Earlier development included Windows adder and imported-counter checks and
Linux qualification of all four examples. The current repository preparation
and historical matrix are described separately in [validation.md](validation.md).
Only the 1.21.1 baseline has full native GameTest support. Clean-host dependency
installation and other Minecraft engines require their own qualification.
