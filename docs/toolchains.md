# Tool setup

Run `python rtl2mc.py doctor` to inspect available tools. It probes versions;
actual compilation is still required to establish license availability.

| Stage | Choices / requirements |
|---|---|
| Synthesis | `dc` + Library Compiler, `genus`, or `yosys` |
| Simulation | `vcs`, `xcelium`, `questa` (`vsim`, `vlog`, `vlib`), or `icarus` (`iverilog`, `vvp`) |
| Import and equivalence | Yosys is also required for commercial synthesis flows |
| Minecraft baseline | Java 21 and the checksum-pinned Java 1.21.1 server |
| Native GameTest compilation | ECJ 3.39.0 and pinned Mojang mappings, via `tools/setup_gametest.py --install` |

The open-source starting combination is `--synth yosys --sim icarus`. The
application can display and install missing supported tools with
`--install-missing`; it cannot supply commercial installations or licenses.
Its current portable bootstrap supports Windows/Linux x86-64. Run an actual
example after setup; a complete clean-host bootstrap has not been qualified on
every supported platform.

## Environment Modules profile used for qualification

The optional [eda/modules.sh](../eda/modules.sh) contains exactly these site
module names. Source it only on a host providing those modules:

```sh
module load synopsys/vcs/X-2025.06
module load synopsys/syn/V-2023.12
module load synopsys/libraryCompiler/V-2023.12
module load cadence/xcelium/23.03
module load cadence/ddi/23.10
module load siemens/questasim/2024.1
```

Yosys and Icarus must also be available. The generic regression scripts no
longer load site modules or embed a site's absolute executable paths. Use
`python tools/run_tool_matrix.py ...` directly, or set `RTL2MC_PYTHON` when
using the Bash wrappers.

## Discovery and overrides

Tools may be provided through PATH, repeated `--tool-dir` options,
`RTL2MC_TOOL_PATH`, vendor home variables or project-local installations.
Executable overrides are:

```text
RTL2MC_DC       RTL2MC_LC       RTL2MC_GENUS
RTL2MC_VCS      RTL2MC_XCELIUM
RTL2MC_QUESTA   RTL2MC_VLOG     RTL2MC_VLIB
RTL2MC_YOSYS    RTL2MC_ICARUS   RTL2MC_VVP
RTL2MC_JAVA
```

`RTL2MC_YOSYS=wasm` selects the installed project-local YoWASP fallback; it does
not install it. Forced `--synth` and `--sim` selections fail if unavailable.
They are not silently substituted. The tested module versions are a
qualification record, not a guarantee about every vendor patch or license setup.

For the optional Bash four-design wrapper, `RTL2MC_TEST_SYNTH` and
`RTL2MC_TEST_SIM` select the pair; defaults are Yosys and Icarus. Provision
dependencies and accept the Minecraft EULA through the main CLI first.
