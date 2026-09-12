# First admitted redstone cells

Four guarded repeater buffers are admitted for **explicit isolated instances** in vanilla Java Edition 1.21.1, under the physical and temporal envelope below. General synthesis mapping remains disabled (`mapping_eligible: false`, Liberty `dont_use: true`).

Fresh Minecraft evidence: **64/64 fixtures, 384 input transitions, 3,136 sample points, 12,544 probe readings**. Every sample matches both the independent delayed-Boolean cell law and the native event model, including before-action observations.

| Cell | Repeater setting | Rise / fall delay | Minimum HIGH | Minimum LOW |
|---|---:|---:|---:|---:|
| RSBUF2 | 1 | 2 gt | 3 gt | 3 gt |
| RSBUF4 | 2 | 4 gt | 5 gt | 5 gt |
| RSBUF6 | 3 | 6 gt | 7 gt | 7 gt |
| RSBUF8 | 4 | 8 gt | 9 gt | 9 gt |

## Physical contract

Local coordinates place the repeater at (0,0,0); +x points toward its output. Rotation turns this entire volume, ports included, around the vertical axis.

```text
Top view at y=0; all unmarked reserved positions are air

          x=-3   -2       -1       0        +1      +2   +3
z=-2      .      .        .        .        .       .    .
z=-1      .      .        .        .        .       .    .
z= 0      .    source -> A dust -> repeater -> Y dust .    .
z=+1      .      .        .        .        .       .    .
z=+2      .      .        .        .        .       .    .
```

The reserved volume is 7 × 5 × 4 blocks: x=-3..3, z=-2..2, y=-1..2. Its bottom layer is stone with no external power applied; the remaining positions are air except the three body blocks and the source port. Both locking sides and the space above stay empty. The input access face is west, at dust (-1,0,0), driven by air or a redstone block at (-2,0,0). The output access face is east, at dust (+1,0,0). The only output load is this included dust, observed without a connected receiver.

All four horizontal rotations were measured with both initial states and both stimulus patterns. Reflections and vertical layouts are not admitted. All affected chunks must stay loaded, the queue must have no backlog, and outside mechanisms must not power the support or alter the reserved volume. Fresh fixtures use an otherwise empty lab on a stone plane; the air margin is an integration rule, not evidence of immunity to arbitrary external circuits.

## Input protocol and why it gives a fixed delay

Initialize A to 0 or 1 and hold it for at least 20 game ticks. A means dust strength 0 or 15, respectively. Thereafter, change only the declared source, after a completed game tick, at integer game-tick boundaries. Both high and low intervals must be at least D+1 ticks, where D is the cell delay. Hold the final input indefinitely or until the next legal transition. Sample after scheduled work and source updates finish.

With no lock and a settled initial state, an input transition schedules one output event at t+D. The input is still stable when that event executes. The output reaches the new input value and the queue is empty before another transition is permitted at t+D+1. This restores the same condition for the next transition. This induction is the engineering argument for extending the measured finite histories to the stated protocol; it is not a formal proof of the entire Minecraft engine.

D+1 is a conservative admission boundary, not a claim that every shorter pulse fails. Short pulses, locks, alternate drivers and order-sensitive cases must use the native event model. The simpler cell timing view does not emulate their behavior.

## Generated views

- [Native cell definitions](../cells/repeater-buffers.json): ports, body blocks, support, air, transforms, protocol and timing arcs.
- [Liberty](../views/repeater-buffers/repeater-buffers.lib): function, scalar rise/fall timing, minimum pulse widths and mapping exclusion.
- [Timing SystemVerilog](../views/repeater-buffers/repeater-buffers.sv): specify paths, width checks and a procedural input guard that rejects illegal timing or X/Z inputs.
- [Functional Verilog](../views/repeater-buffers/repeater-buffers-functional.v): zero-delay logical view only; no timing or envelope enforcement.
- [Example netlist](../views/repeater-buffers/buffer-bank.v) and [SDF](../views/repeater-buffers/buffer-bank.sdf): four independent instances with matching instance names.
- [View manifest](../views/repeater-buffers/manifest.json): hashes and scale; layouts/ contains sixteen relative Minecraft placement functions.

**1 simulation ns = 1 game tick.** This is a numerical interchange scale, never elapsed wall-clock time. Native JSON keeps game ticks. Equal SDF min/typ/max values describe one deterministic build and envelope; they are not PVT corners. Liberty supplies no invented capacitance, slew, voltage, power or electrical load tables. It is an initial logical timing view, not a complete electrical/STA library.

Specify paths use IEEE 1800-2023 §30.4.2 (pp.873–874), rise/fall delays §30.5.1 (pp.882–883), pulse checks §31.4.4 (pp.911–912), and `$sdf_annotate` §32.9 (pp.932–933). The standard maps SDF IOPATH to module paths (§32.4.1, p.925) and WIDTH to `$width` (§32.4.2, p.926). The procedural guard is also necessary for tools that do not execute all timing checks. Enable specify support; compile with `RS_SDF_ONLY` when the SDF should supply all path delays.

Liberty representation was cross-checked against the primary [OpenSTA reader](https://github.com/The-OpenROAD-Project/OpenSTA/blob/master/liberty/LibertyReader.cc). Tool setup follows [YoWASP](https://yowasp.org/) and [Icarus documentation](https://steveicarus.github.io/iverilog/usage/installation.html); the [MSYS2 package](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-iverilog) supplies the portable simulator. See [EDA validation](repeater-cells-eda.md) for the actual tested versions, results and limitations.

## Reproduce and next integration gate

```powershell
python pdk.py admit-buffer-cells results/20260910T170353Z-1c3356
python tools/check_cell_eda.py
python pdk.py validate
```

Rebuild rechecks the complete raw run, saved commands, source hashes, probe domains and coverage before writing any admitted view. Fresh measurements can be repeated with `python pdk.py start`, `python pdk.py run --suite cells`, then `python pdk.py stop`.

The next admission gate is a **driver–cell–receiver connection contract**: characterize actual routed input drivers and receiving loads, dust joins/strength/fanout, guard compatibility, and chains. Only then can a mapper compose these into a circuit. This milestone does not yet admit arbitrary input waveforms, cell chaining, branching, clocks, state cells, or unrestricted mapping.
