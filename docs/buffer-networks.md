# Checked driver–cell–receiver networks

**204/204 Minecraft cases match the compositional prediction.**
200 cases are admitted; 4 deliberate overlength routes are rejected.
The run contains 8,640 observation boundaries, 116,552 block-property readings,
and 816 source transitions. All raw probe/time replies and executed function sequences were audited.
Evidence: [results/20260911T031639Z-05ea07](../results/20260911T031639Z-05ea07/summary.json).

| Coverage | Cases |
|---|---:|
| All driver/DUT/receiver repeater settings (4 × 4 × 4) | 64 |
| First route lengths 2–16 × four DUT settings | 60 |
| Binary comparator driver × DUT/receiver settings × both initial states | 32 |
| Elbow, dangling stub, two/three receivers × DUT settings × both initial states | 32 |
| Four rotations, chunk boundaries, both initial states, two delay triples | 16 |

This is not the full cross product of route, fanout, orientation, initial state and timing.
The admitted catalog lists exact measured geometries; the extractor's broader tree model is not permission to use arbitrary new layouts.
The older native event model independently agrees on 172 cases.
Its v1 geometry rules exclude the 32 bent/branched cases; those are checked directly against Minecraft using the independent compositional law.

## What the route measurements establish

The first driven dust block has strength 15. Each further dust block reduces HIGH by one.
A 15-block straight route reaches its receiver at strength 1 and works. All four 16-block controls reach 0 and fail to convey HIGH;
the checker rejects them before HDL export. Repeaters restore the output to 15.
Elbows and the measured stubs/fanouts add no delay at completed-game-tick resolution. Receiving repeaters retain their 2/4/6/8-tick delay.
This zero route delay does not mean that dust has no internal update sequence.

`RNETBUF2/4/6/8` describe connected repeaters receiving 0 versus 1..15.
`RNETCMP2` is only the measured binary source driver (compare mode, rear 0/15, empty sides).
These new symbols have a separate connection contract; the older `RSBUF` symbols remain isolated cells.

Every admitted net has one driver, a planar tree of at most 15 dust blocks, and at most three receiving diodes.
Every diode has rear/output dust, empty locking sides and empty space above. The support is an unpowered stone plane.
The lab reserve is x=0..63, y=79..84, z=-16..47, with at least two empty horizontal blocks around the body/source.
Only the declared source changes. No feedback, shared drivers, vertical routes, pistons, moving blocks, locks, external power or tick backlog is allowed.
All chunks stay loaded. Reflections, relocation and larger designs require further admission.

Hold the initial binary input for at least **20 + longest path delay** game ticks.
Then use integer tick boundaries and hold both HIGH and LOW for at least **max(cell delay) + 1** ticks.
For each cell, its input is still stable when its scheduled event executes, and its queue drains before the next edge.
Induction along this acyclic graph preserves pulse widths and adds delays. This is an engineering extension from finite evidence, not a formal proof of Minecraft.

## Synthesis and gate-level simulation handoff

The [manifest](../views/buffer-network/manifest.json) pins all views to this admission:

- [Liberty](../views/buffer-network/cells.lib), separate functional/specify/portable timed models, and an external input guard.
- 200 structural netlists, matching instance SDF (IOPATH and explicit INTERCONNECT), path-budget SDC, and exact lab placement/initialization functions.
- [EDA integration guide](eda-integration.md): Design Compiler/Library Compiler, Genus, VCS, Questa and Xcelium adapters, import/export checks, and local qualification results.

Synthesis reads the Liberty symbols and structural netlist. Preserve all diode instances: a Boolean optimizer can remove a physically necessary buffer.
The exported netlist must pass the instance/type/connectivity checker before its SDF or placement certificate can be reused.
The `.lib` remains `dont_use` for unconstrained mapping. A buffer-only library cannot map arbitrary RTL; general logic and state cells are still needed.
SDC path budgets do not encode the input dwell rule, geometry or wire strength.

**1 simulation ns = 1 game tick.** Equal SDF min/typ/max describe one build, not PVT corners.
Liberty area counts diode blocks and fanout_load counts receiving diodes; neither is an electrical quantity.
No capacitance, voltage, analog slew, power, ASIC layout or electrical STA qualification is supplied.
The native route certificate remains authoritative over a synthesis tool's inferred wire model or SDF.

## Reproduce

```powershell
python pdk.py admit-connections results/20260911T031639Z-05ea07
python tools/check_network_eda.py
python pdk.py validate
```

Fresh evidence: `python pdk.py start`, `python pdk.py run --suite connections`, `python pdk.py stop`.
Placement functions clear the full reserved lab and are inspectable artifacts; they are not automatically executed by synthesis or simulation.
