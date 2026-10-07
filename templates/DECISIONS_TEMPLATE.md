# DECISIONS: <project>

Append-only. One row per durable decision, written THE SAME TURN the decision is taken, never at the session close. Never edit or delete a row; a reversal is a new row naming the old one in **Supersedes**. A commit that changes a tool because of a row carries the D-number in its message.

What goes in: decisions that change what future sessions or jobs do (an approved parameter, a naming or filing rule, a scope cut, a retired approach, "we chose X over Y", a calibration of a model prompt). What stays out: task completions, status, anything that is already a deliverable. If the why needs more than two lines, it lives in a spec or handoff and the row points at it.

| ID | Decision | Why | Date | Evidence | Supersedes | Status |
|---|---|---|---|---|---|---|
| D-001 | <what was decided, in one or two sentences, with the values> | <the reason, in the owner's words where possible> | YYYY-MM-DD | <chat title, file path, section> | <D-number, or empty> | Active |
| D-002 | <...> | <...> | YYYY-MM-DD | <...> | D-001 | Active |

Status values: `Active`, `Superseded by D-NNN`, `Dropped`.
