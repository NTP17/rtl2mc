# Contributing

Run from a source checkout with Python 3.12 or newer:

```sh
python tools/check_repository.py
python tools/test.py
```

Use a small RTL reproducer for mapping or simulator issues. Record the tool
versions, selected synthesis/simulation pair, Minecraft version, command and
failing stage. Keep generated outputs under `builds/` and attach only the
relevant diagnostics after removing machine credentials.

For changes to geometry, routing, timing or sequential behavior, also run an
affected example through export and native GameTest. A successful Python unit
test does not qualify a Minecraft circuit. Preserve negative controls and
require positive pass markers as well as expected tool exit status.

The PDK's recorded admissions pin exact source and artifact hashes. A changed
model must receive new qualification evidence; do not simply replace hashes to
make an old measurement appear current. See [testing](docs/testing.md).

New source files use LF. `.gitattributes` preserves byte-pinned data and source
files across Windows and Linux; command launchers use CRLF on checkout. Avoid
bulk formatting of historical PDK code or generated views.

Describe the problem, resulting behavior and relevant validation in pull
requests. Keep raw worlds, downloaded tools and local acceptance/configuration
files out of commits.

Unless explicitly stated otherwise, contributions intentionally submitted for
inclusion in RTL2MC are under [Apache-2.0](LICENSE), as described in Section 5
of the license. Retain applicable third-party attribution and license notices.
For new source files, include `SPDX-License-Identifier: Apache-2.0` in a comment
using the language's syntax. Repository-level attribution is recorded in
[NOTICE](NOTICE).
