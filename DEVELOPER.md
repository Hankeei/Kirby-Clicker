# Developer reference

Kirby Clicker v1.3 is the native Rust port. Start with:

1. [HANDOFF.md](HANDOFF.md) — functionality, usage, environment, modules, formats and releases.
2. [AGENTS.md](AGENTS.md) — working rules and required checks.
3. [TASKS.md](TASKS.md) — known limitations and ideas.
4. [native/README.md](native/README.md) — Rust development commands and verification.

The earlier Python implementation remains under app/ and main.py. Its historical
handoff is [docs/PYTHON_HANDOFF.md](docs/PYTHON_HANDOFF.md), and its optional packager
is build-python.ps1. Always use py -3.13 when testing it.

Keep user instructions in README.md free of build internals, timing equations,
DLL details and test logs. Those details belong in the handoff/developer docs.
