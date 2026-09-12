# Architecture

`rtl2mc.py` and `python -m rtl2mc` call [cli.py](../rtl2mc/cli.py). The application
is run from its source tree because the shared Python modules resolve model,
technology, Java and adapter paths relative to that tree. It is not currently
packaged as an independently installable wheel.

| Stage | Implementation | Result |
|---|---|---|
| File-list parsing and source snapshot | [filelist.py](../rtl2mc/filelist.py) | Ordered HDL inputs and byte hashes |
| Tool selection | [toolchain.py](../rtl2mc/toolchain.py) | Independent synthesis and simulator choices |
| Synthesis/import and equivalence | [frontend.py](../rtl2mc/frontend.py), [rtl.py](../redstone_pdk/rtl.py) | Checked binary graph |
| Macro placement and routing | [router.py](../redstone_pdk/router.py), [logic_cells.py](../redstone_pdk/logic_cells.py) | Actual block states, routes and geometry checks |
| HDL and extracted timing | [views.py](../rtl2mc/views.py), [mapping_views.py](../redstone_pdk/mapping_views.py) | Structural netlist, SDF and timing budget |
| RTL/routed comparison | [verification.py](../rtl2mc/verification.py) | Golden outputs, annotation checks and fault controls |
| Physical execution and export | [world.py](../rtl2mc/world.py) | Measurements, saved/reopened world and manifest |
| Independent example checks | [gametest.py](../rtl2mc/gametest.py), [Java harness](../gametest/) | Native GameTest XML and output observations |

The shared `redstone_pdk/` package also contains the earlier component
characterization laboratory. Its contracts and EDA views are retained because
they document the measured basis of the redstone models. Raw observations live
in an optional evidence bundle described in [pdk-lab.md](pdk-lab.md).

The modern `rtl2mc/views.py` adapter adds explicit wire port declarations for
simulator portability while preserving the original, hash-pinned PDK exporter.
Old admissions remain historical evidence. A source change cannot silently
inherit them as a fresh physical qualification.
