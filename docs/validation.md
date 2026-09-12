# Recorded validation

The [machine-readable summary](validation-summary.json) was derived from two
passing original Linux qualification reports: 36 runs across VCS, Icarus and
Xcelium, followed by 12 Questa runs. It retains original report hashes and
per-design layout/vector/golden hashes without local executable paths.

| Synthesis | VCS | Icarus | Xcelium | Questa |
|---|---:|---:|---:|---:|
| Design Compiler | 4/4 | 4/4 | 4/4 | 4/4 |
| Yosys | 4/4 | 4/4 | 4/4 | 4/4 |
| Genus | 4/4 | 4/4 | 4/4 | 4/4 |

Each cell covers `adder`, `mux2`, `counter` and `shift2`, including actual
Minecraft export, saved-world reopen and native GameTest. Across all 48 runs:

- 792 native GameTest samples and 1,476 output-bit comparisons.
- 18,224 physical output comparisons and 1,696 reopen comparisons.
- Expected GameTest failures for deliberately broken output wires.
- Complete native SDF annotation checks for Xcelium and Questa; native timing
  controls for the commercial simulators.

These are historical measurements of the original implementation snapshots.
They are not a claim that the reorganized checkout has rerun all 48 combinations.
The matrix's original raw logs, world archives and negative-control evidence
remain in the development workspace. The optional PDK evidence bundle serves
the earlier laboratory audits and does not include those later world archives.

Combinational examples cover all eight binary input combinations. Sequential
examples cover declared boot, reset, enable, wrap/shift and low-phase hold
sequences. No universal physical proof or transient equivalence is claimed.
Icarus's lack of native timing checks is retained in the reports.

For current checkout verification and commands to generate new evidence, see
[testing.md](testing.md). Linux packaging checks are recorded separately in
[repository-checks.json](repository-checks.json). The configured GitHub CI jobs
have not run remotely until the project is uploaded.
