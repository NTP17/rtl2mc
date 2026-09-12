# PDK laboratory

The laboratory code is retained in `redstone_pdk/`, `pdk.py`, `instrumentation/`
and the supporting `tools/` commands. It generated the component measurements,
bounded event model, cell admissions, connection contracts and canonical EDA
views used during RTL2MC development.

```sh
python pdk.py --help
python pdk.py catalog
python pdk.py fixtures
```

`python pdk.py validate` reanalyzes the recorded measurements and verifies model
and artifact hashes. It requires the optional corpus, restored as described in
[testing.md](testing.md). Missing evidence is an error, not a passing validation.

The source repository retains the contracts and views. The optional local
archive retains original observations, command replies, saved harness source
and instrumentation artifacts required for those audits. It preserves their
bytes, including original provenance in logs, and is separate from the clean
Git source tree.

To make new measurements, use `python pdk.py doctor`, `python pdk.py setup`, and
the commands shown by `python pdk.py --help`. Lab setup is separate from the
modern `rtl2mc.py` world-builder cache. Its server requires explicit Minecraft
EULA acceptance. The observation agent in `instrumentation/` is only for the
historical engine-trace investigation; the native GameTest path uses unmodified
engine classes and does not load that agent.
