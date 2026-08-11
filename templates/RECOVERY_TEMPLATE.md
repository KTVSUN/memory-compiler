# RECOVERY TEMPLATE

> A recovery doc exists because a session's ledger entry was left `OPEN` past the staleness
> threshold (crash, forgotten close, killed process) — `memory_check.py --recovery-scan` detects
> this and creates the skeleton below automatically as `_sessions/recovery/<session-id>.json` plus
> this human-readable companion `RECOVERY - <project> - <session>.md`. **Every line is a
> candidate, not a fact.**

## THE RULE

Every line in this document is marked **CANDIDATE — NOT CANONICAL** until a session reconciles it
into `CONTEXT.md` / `OPEN_ITEMS.md` / `TOMBSTONES.md` / `DECISIONS.md` and runs
`memory_check.py --resolve-recovery <session-id>`. Until resolved, this file **hard-blocks** any
new writing session on this project (`memory_check.py --open` refuses) — not a warning an
impatient session can skip.

**Raw conversation dumps are explicitly rejected.** Pasting a transcript here defeats the purpose
— recovery candidates must be distilled facts/decisions/items, the same discipline as a normal
handoff, not a data dump that reintroduces unauthored, "captured" memory.

## WHO FILLS THIS IN

`memory_check.py` only creates the skeleton (it has no transcript access). A human, or an agent
with transcript access, populates the `candidates` block below from the actual session content
before anyone reconciles it.

## SKELETON

```markdown
# RECOVERY — <project> — <session-id>

- **Detected:** <ISO timestamp> · **Session started:** <ISO timestamp> · **Age at detection:** <N hours>
- **Source ledger entry:** `_sessions/<session-id>.json`
- **Status:** UNRESOLVED

## CANDIDATE FACTS — CANDIDATE — NOT CANONICAL
- <fact> — <where in the session it came from, one line, no full quotes>

## CANDIDATE DECISIONS — CANDIDATE — NOT CANONICAL
- <decision + why, one line>

## CANDIDATE CORRECTIONS — CANDIDATE — NOT CANONICAL
- <a value this session appeared to reject, and what replaced it — tombstone candidate>

## CANDIDATE OPEN-ITEM CHANGES — CANDIDATE — NOT CANONICAL
- <item opened/closed/blocked, with the status it should move to>

## TOUCHED FILES — CANDIDATE — NOT CANONICAL
- <file path> — <what changed, best guess>

## RECONCILIATION
- Resolved by: <session/chat> · Date: <date>
- What was kept / dropped / merged into canonical files, one line each.
```

## THE CLOSE, for a reconciling session

1. Read `_sessions/recovery/<session-id>.json` and its `.md` companion.
2. For each candidate, either promote it into the right canonical file (with evidence) or
   explicitly drop it with a reason — same OPEN/DONE/DROPPED discipline as `OPEN_ITEMS.md`.
3. Run `memory_check.py --resolve-recovery <session-id> --note "<one line>"` — this clears the
   hard block.
4. Proceed with a normal `--open` for the actual work.
