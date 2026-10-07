# legacy: version 1 (August 2026)

The first public version of this repository, kept as it was. It still runs on its own: `memory_check.py` has no third-party dependencies and validates four canonical Markdown files at session close, keeps a session ledger with a single-writer lock, generates recovery candidates for sessions that crashed before closing, and runs retrieval tests from `memory_tests.yaml`.

- `README_v1.md` and `ARCHITECTURE_v1.md`: the original description.
- `memory_check.py`: the compiler.
- `templates/HANDOFF_TEMPLATE_v1.md`, `templates/RECOVERY_TEMPLATE.md`: the original templates.
- `examples/`: a small worked example (a freelancer's client rebrand).

We stopped using the compiler within a month. The reasons are in the current `ARCHITECTURE.md`, section 10: the close-time check moved to overnight scripts, `OPEN_ITEMS.md` was never built because open work split into a task register and handoff deltas, and canonical truth became a federation of owners rather than four files. If you want a self-contained validator with no scheduler behind it, this folder is still the simplest thing here that works.
