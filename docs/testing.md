# Testing

## Self-contained checks

From the repository root, with Python 3.12 or newer:

```sh
python tools/check_repository.py
python tools/test.py
```

These tests need no Minecraft server, licensed EDA tools, network connection or
historical results directory. They exercise parsing, graph rejection, geometry,
timing protocols, simulation diagnostics, reference models and artifact handling.
`python -m unittest discover -s tests -v` also runs this suite.

The [GitHub Actions workflow](../.github/workflows/ci.yml) defines Linux and
Windows jobs for Python 3.12 and 3.13. It uses the documented
[checkout](https://github.com/actions/checkout) and
[setup-python](https://github.com/actions/setup-python) actions. Remote CI results
will exist only after the repository is uploaded and the workflow runs.

## Export and native GameTest

Provision the chosen tool pair and Minecraft through the main CLI, then install
the two pinned GameTest build dependencies:

```sh
python tools/setup_gametest.py --install
python rtl2mc.py run -f examples/rtl/adder.f --synth yosys --sim icarus --out builds/adder
python tools/check_gametest.py builds/adder --out builds/adder-gametest --negative-control
```

Existing local EULA acceptance is required for the last two commands. The
GameTest harness checks placed block types and orientation/delay/mode, saved
outputs, settled outputs and sequential low-phase retention. Reference models
currently exist for `adder`, `mux2`, `counter` and `shift2`. A new design needs
an independent oracle before this example GameTest runner can check it.

An intentionally removed output wire must cause the expected native assertion
and a failing XML testcase. The wrapper reports that deliberate failure as a
successful negative control. Do not interpret its native exit code alone as
a failed positive circuit.

## Tool matrix

Configure available tools as described in [toolchains.md](toolchains.md), then:

```sh
python tools/run_tool_matrix.py --synth yosys --sim icarus --out builds/open-matrix --jobs 1
python tools/check_tool_matrix.py builds/open-matrix
```

The following runs the full 3 synthesis × 4 simulation × 4 design matrix:

```sh
python tools/run_tool_matrix.py --out builds/full-matrix --jobs 3
python tools/check_tool_matrix.py builds/full-matrix --snapshot validation/full-matrix
```

Every selected combination produces its own world, source/routed simulation,
save/reopen checks and native GameTest evidence. Three jobs can consume several
GiB of memory and substantial disk space. Start with one job on smaller hosts.
The complete flow creates many world copies; keep those generated files out of Git.

`--resume` reuses only passing jobs whose source, implementation, configuration,
GameTest source and world archive still match. A source-tree relocation or edit
can invalidate reuse. Archived results are not automatically accepted as current.

Icarus cannot provide native SDF TIMINGCHECK coverage. VCS, Xcelium and Questa
run native timing controls; Xcelium and Questa also require complete annotation
counts. All flows require positive markers and reject unexpected diagnostics.

## Optional historical evidence audits

The separate `rtl2mc-lab-evidence.zip` prepared alongside this repository holds
the original PDK measurement corpus and two early mapped-build artifacts. It
is not required for the main CLI or self-contained tests and is not committed.
Its exact membership and checksum are recorded in
[lab-evidence.json](../tests/fixtures/lab-evidence.json).

If you have that bundle, restore it from its actual location:

```sh
python tools/restore_lab_evidence.py ../rtl2mc-lab-evidence.zip
python tools/test.py --with-evidence
python pdk.py validate
```

Restoration checks the archive and every member before writing, and refuses to
replace different existing files. It writes only ignored `results/`, `builds/`
and `validation/` directories. The 15 additional tests reanalyze original
measurements; they do not launch Minecraft or count as new physical runs.
`--with-evidence` fails clearly if the corpus has not been restored.

The optional lab bundle is distinct from the later 48-run tool matrix: that
matrix's raw logs and world saves remain in the original working archive.
The source repository includes a [derived summary](validation-summary.json).
