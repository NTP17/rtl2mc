# PDK EDA integration

The retained [buffer-network report](buffer-networks.md) describes the original
component-level admission. Its canonical [view manifest](../views/buffer-network/manifest.json)
and [generator](../redstone_pdk/connection_views.py) cover Liberty, functional,
specify and portable timing views, layouts and stimulus guards.

The [network checker](../tools/check_network_eda.py) checks topology preservation
and recorded signal behavior. Its original results are in the optional lab
bundle as `validation/network-eda/report.json`. Restore that corpus before
running historical project validation; see [testing.md](testing.md).

For the current RTL-to-world command, DC/Genus/Yosys selection and the four
simulation backends, use [toolchains.md](toolchains.md) and the
[detailed CLI guide](rtl2mc.md). Component admission and full-circuit physical
regression are separate requirements.
