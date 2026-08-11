# HANDOFF TEMPLATE

> **Hard cap: 8 KB (~150 lines).** A handoff is written once and read at the start of *every*
> later session on this project — it is the only artifact whose cost compounds.
> **The test for every line: would the next session act differently without it?** If not, cut it.

## WHAT GOES IN — six blocks, in this order

**1. Header (5 lines max)** — session/chat reference · date · project folder · what it
supersedes · sibling handoffs from the same session · whether `CONTEXT.md` was updated.

**2. Current state (one short paragraph)** — where the matter stands *now*. Not how it got there.

**3. The authoritative current set** — which files are live, by name. If two versions exist, say
which one wins and retire the other.

**4. Decisions + WHY** — the only block that may run long. Every decision carries its reasoning: a
decision without its *why* gets relitigated at full cost, three sessions later.
**Evidence pointers:** every material claim carries a one-line source — "per the July invoice",
"per Alex's email, 14 July", "verified empirically". A claim without a source cannot be corrected
later without guesswork. Applies to `CONTEXT.md` entries too.

**5. Open queue + blockers** — what is owed, to whom, and what is waiting on someone else.

**6. Traps** — only ones that would cost the next session real time; a trap earns its place by
having already burned someone once.

## THE SUPERSEDES DIFF — run it BEFORE writing

Open the handoff this one supersedes and walk its OPEN QUEUE and every instruction it carries.
Each one must reappear here in exactly one of three states:

- **OPEN** — carried forward, still owed;
- **DONE — with evidence** — name the artifact or file that proves it, not the intention;
- **DROPPED — with why** — someone said so, or events made it moot.

An item in none of the three states is the failure this rule exists for: a decision quietly
downgraded mid-session, described in language that reads like resolution, survives two sessions
undetected. The diff is the check.

## TOMBSTONES — when a value is REJECTED, not just superseded

If this session rejected a value — a figure proven wrong, a name retired, an approach someone said
no to, an assumption verified false — write a one-line tombstone in `TOMBSTONES.md`: value · why
rejected · date · replacement. The supersedes diff protects open *items*; tombstones protect
*values* — without one, a later session can re-derive the rejected value from an old document and
reintroduce it in a fresh deliverable. Before asserting any fact recovered from an old file, check
the tombstone registry first. Tombstones are permanent: never delete, only add.

## WHAT STAYS OUT

Session narrative (who noticed what, in what order) · anything already in `CONTEXT.md` (meanings
live there) · figures that live in a spreadsheet or database (point at the file) · full quotations
where a one-line summary plus the file reference does the same job · superseded versions of your
own reasoning.

## THE THREE LAYERS — put each fact in exactly ONE of them

| Layer | Holds |
|---|---|
| `CONTEXT.md` (project root) | what things **MEAN** — parties, documents, name traps |
| `OPEN_ITEMS.md` (project root) | **OPEN LOOPS** — the live work-state ledger, checked at every close |
| handoffs | what is **HAPPENING** — state, decisions, queue, blockers |

**If a sentence would be false in a month, it does not belong in `CONTEXT.md`.**

## THE CLOSE, in order

1. File outputs per your project's convention.
2. Run `memory_check.py --close <session-id>` and read its findings — resolve any `[ask]` before
   the close can seal.
3. Add/close entries in `OPEN_ITEMS.md` for anything this session opened or resolved.
4. Update `CONTEXT.md` — most sessions add nothing, and that is the correct outcome.
5. Did this session REJECT any value (wrong figure, retired name, refused approach, falsified
   assumption)? If yes, write its tombstone in `TOMBSTONES.md`.
6. Run the supersedes diff, then write the handoff, under the cap.

## SKELETON — copy this

```markdown
# HANDOFF — <project>

- **Session:** "<name>" · **Date:** <YYYY-MM-DD> · **Project folder:** `<path>`
- **Supersedes:** <file, or nothing> · **Siblings this session:** <files, or none>
- **CONTEXT.md:** updated / nothing owed

## CURRENT STATE
<one paragraph>

## AUTHORITATIVE CURRENT SET
- `<file>` — <what it is, what version, what it governs>

## DECISIONS + WHY
- **<decision>** — <why>

## SUPERSEDES DIFF — against <previous handoff>
- <each prior open item: OPEN / DONE — evidence / DROPPED — why>

## OPEN QUEUE / BLOCKERS
- <what is owed, to whom, waiting on what>

## TRAPS
- <only what would cost the next session real time>
```
