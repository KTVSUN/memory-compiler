# memory-compiler

A small, dependency-free system for giving an AI coding/writing agent (Claude, ChatGPT, whatever)
**persistent, validated memory** of a long-running project — across sessions, across restarts,
and optionally across machines that sync through a shared folder.

The core idea: treat memory like source code, not like a chat log. A handful of canonical
Markdown files hold current truth. A script — the **Memory Compiler** — validates them, catches
contradictions, and refuses to let a session close cleanly while something is broken.

## The problem this solves

If you've used an AI agent on the same project across many sessions, you've probably hit this:
the agent confidently reasserts a fact you corrected two weeks ago, because it pulled it from an
old document instead of your last correction. Or two sessions on different machines both edit the
same "current state" file and one silently clobbers the other. Or a session crashes mid-task and
the next one has no idea what it was in the middle of.

Most fixes for this reach for more memory — bigger context windows, a vector database of past
chats, RAG over transcripts. This does the opposite: it assumes most of what happens in a session
should be **thrown away**, and the small amount that should persist should be **written
deliberately, validated mechanically, and provably correctable** when it turns out wrong.

## What's in here

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — the full design: four memory layers, the canonical
  file spec, the session open/close lifecycle, concurrency handling, multi-machine sync, and the
  design decisions worth knowing about before you adapt this. Start here if you want to understand
  *why*, not just copy files.
- **[`memory_check.py`](memory_check.py)** — the compiler. Validates the canonical files,
  regenerates disposable summary views, runs retrieval tests, and manages a session ledger with a
  single-writer lock and crash recovery. Zero third-party dependencies.
- **[`templates/HANDOFF_TEMPLATE.md`](templates/HANDOFF_TEMPLATE.md)** — the end-of-session
  writeup template, with a hard size cap and a "supersedes diff" discipline that catches items
  quietly dropped instead of resolved.
- **[`templates/RECOVERY_TEMPLATE.md`](templates/RECOVERY_TEMPLATE.md)** — what gets generated
  automatically when a session crashes without closing properly.
- **[`examples/`](examples/)** — a small worked example (a freelancer's client rebrand project)
  showing what populated `CONTEXT.md`, `OPEN_ITEMS.md`, `DECISIONS.md`, `TOMBSTONES.md`, and
  `memory_tests.yaml` actually look like.

## The four files that matter

| File | Holds | Rule |
|---|---|---|
| `CONTEXT.md` | Who/what things mean, durable facts | Every mutable fact needs a date + evidence pointer |
| `OPEN_ITEMS.md` | The live work-state ledger | Permanent IDs; every item must resolve to OPEN / BLOCKED / DONE / DROPPED |
| `DECISIONS.md` | Append-only decision log | Every decision carries its *why*, not just its *what* |
| `TOMBSTONES.md` | Rejected/superseded values | Add-only; prevents an old document's stale fact from getting reasserted |

Everything else — handoffs, session ledgers, generated indexes — exists to keep these four honest.

## Quick start

```bash
# 1. Drop memory_check.py in your project root (or point --topic-dir / $MEMORY_TOPIC_DIR at it)
cp memory_check.py /path/to/your/project/
cd /path/to/your/project/

# 2. Seed the four canonical files (copy the skeletons from examples/, then empty them out)
cp path/to/examples/*.md .
# ...edit them down to your actual project's facts...

# 3. At the start of a session
python3 memory_check.py --open my-session-1 --machine laptop

# 4. Work normally — edit CONTEXT.md / OPEN_ITEMS.md / DECISIONS.md / TOMBSTONES.md as you go

# 5. At the end of a session
python3 memory_check.py --close my-session-1
```

`--close` runs the full pipeline (validate → concurrency check → rebuild generated views → run
`memory_tests.yaml`) and only seals the session if everything passes. If it doesn't, it tells you
exactly which file/row/test is the problem — nothing seals silently broken.

If a session crashes without closing:

```bash
python3 memory_check.py --recovery-scan          # finds stale OPEN sessions, writes a candidate
# ...a human or another agent fills in the candidate facts from the transcript...
python3 memory_check.py --resolve-recovery my-session-1 --note "reconciled into OPEN_ITEMS.md"
```

## Wiring it into your agent

This repo is deliberately just the compiler and the file conventions — it doesn't assume any
particular agent, IDE, or chat tool. To actually use it day to day, you want your agent's
"session start" behavior to run `--open` (and `--recovery-scan`) and its "session end" behavior
(a slash command, a magic word, whatever you use) to run `--close`. `ARCHITECTURE.md` §4 describes
the lifecycle those two hooks need to implement; the glue code is yours to write for whatever
agent harness you're on.

## Status

This is a reference implementation, not a maintained product — pulled out of a real project and
genericized for sharing. It covers validation, the session ledger, single-writer locking, crash
recovery, generated views, and retrieval tests. It deliberately does **not** include a fact-ID
system for individual numeric claims, staged (`_pending/`) writes, or a git audit mirror — see
`ARCHITECTURE.md` §5 for why each is left as an opt-in extension rather than baked in.

Issues and forks welcome if you adapt this for your own setup.

## License

MIT — see [`LICENSE`](LICENSE).
