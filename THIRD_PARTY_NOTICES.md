# External tools and assets

RTL2MC's original code and project-authored assets use [Apache-2.0](LICENSE).
The dependencies listed below retain their respective upstream terms.

RTL2MC invokes external programs. Their executables, licenses and downloaded
assets are not part of this source tree. Download URLs and checksums are kept
in project metadata or resolved by the installer.

| Dependency | Role | Upstream |
|---|---|---|
| Minecraft Java 1.21.1 server and server mappings | World execution and native GameTest | [Minecraft](https://www.minecraft.net/), [EULA](https://aka.ms/MinecraftEULA) |
| Eclipse Temurin Java | Server and harness runtime | [Adoptium](https://adoptium.net/) |
| Eclipse JDT ECJ 3.39.0 | Compile the GameTest Java harness | [Eclipse JDT](https://eclipse.dev/jdt/) |
| Yosys / YoWASP Yosys | Synthesis, import and equivalence | [Yosys](https://github.com/YosysHQ/yosys), [YoWASP](https://github.com/YoWASP/yosys) |
| Icarus Verilog | Four-state simulation | [Icarus](https://github.com/steveicarus/iverilog) |
| Synopsys DC, Library Compiler and VCS | Optional licensed synthesis/simulation | [Synopsys](https://www.synopsys.com/) |
| Cadence Genus and Xcelium | Optional licensed synthesis/simulation | [Cadence](https://www.cadence.com/) |
| Siemens Questa | Optional licensed simulation | [Siemens EDA](https://eda.sw.siemens.com/) |
| ASM 9.7.1 | Optional historical laboratory trace agent | [ASM](https://asm.ow2.io/) |

The native GameTest flow does not use the historical trace agent. It compiles
the repository's Java harness and loads unmodified engine classes. This project
is not an official Minecraft product and is not associated with Mojang or Microsoft.

Bootstrap paths may also obtain micromamba, conda-forge or MSYS2 packages and
their dependencies. Inspect the displayed installation plan and upstream terms
before installing. Minecraft EULA acceptance is stored locally and is never
distributed as part of this repository.
