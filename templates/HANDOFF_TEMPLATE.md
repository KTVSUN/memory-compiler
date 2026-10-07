# HANDOFF TEMPLATE, v2 (October 2026)

> **Hard cap: 8 KB.** Read at the start of every later session on this topic.
> **The test for every line: would the next session act differently without it?** If not, cut it.

## WHAT GOES IN, five blocks, in this order

**0. Kickoff prompt for next session.** Fenced block at the top (`Model:` and why, `Session type:` only when the next session builds or changes a tool, the files to read in order, the actions each with a `Must fit with:` line, stop conditions, out of scope). Written ONLY when the kickoff gate passes: the owner asked for a next session, or critical work was identified, not done, and cannot be finished in the current chat, or a design spec is final. Validation work and waiting on other people are never grounds for a kickoff. Otherwise this block reads `No new session needed.`

**1. Header (4 lines max).** Chat title, date, topic folder (full path), what it supersedes and sibling handoffs from the same session.

**2. Current state (two sentences at most).** What is true now and what comes next. Never what this session did; the owner was there. Copied verbatim by the daily record.

**3. The authoritative current set.** The live files, by full path. If two versions exist, say which wins and retire the other to quarantine.

**4. Decisions + why.** One line per decision with its D-number from `DECISIONS.md` and a one-line why. The full rationale lives in the decision log, not here. Every material claim names its source ("per the July statement", "verified on disk <date>").

**5. Open items, as deltas** against the previous handoff: CLOSED SINCE (file that proves it), NEW SINCE (with its next concrete step), DROPPED (why). An untouched item is not retyped; write `unchanged: n items, see <previous handoff>`. This block holds only this topic's in-flight work. A business action the owner must take is proposed as a task and created only on the owner's yes; a tool defect goes to `DEFECTS.md`; library hygiene goes nowhere by hand (the nightly checker regenerates it). An item carried unchanged twice is proposed as drop or task at the close, never carried a third time.

## WHAT STAYS OUT
Traps (they go to the assistant's project memory). Session narrative. Anything already in `CONTEXT.md`. Figures that live in a workbook (point at the file). Quotations where a path does the job. Maintenance findings (`DEFECTS.md`). The full rationale of a decision (`DECISIONS.md`). A files-read list. Credentials, always.

## THE CLOSE, in order
1. Decisions and defects were written in the turn they happened; if one was missed, write it now.
2. Run the mail check: every open item that names a reply, a document someone must send, a payment or a signature is checked against the mail ledger before it is written.
3. Run the supersedes diff (block 5).
4. Write the handoff under the cap: `HANDOFF - <topic> YYYYMMDD<suffix>.md` in `<topic>\Output\md\`; latest date, then suffix, wins.
5. Run the plan summary; propose at most one phase-status change.
6. Propose the chat title. One numbered list. Ask nothing after it.

## SKELETON, copy this

```markdown
# HANDOFF: <topic>

## Kickoff prompt for next session
No new session needed.

- **Chat:** "<title>" · **Date:** <YYYY-MM-DD> · **Topic folder:** `<full path>`
- **Supersedes:** <file, or nothing> · **Siblings this session:** <files, or none>

## CURRENT STATE
<two sentences at most: what is true now, what comes next>

## AUTHORITATIVE CURRENT SET
- `<full path>`: <what it is, what it governs>

## DECISIONS + WHY
- **D-NNN <short name>**: <one-line why>

## OPEN ITEMS, deltas against <previous handoff>
- CLOSED SINCE: <item>, <file that proves it>
- NEW SINCE: <item>, next step: <step>
- DROPPED: <item>, <why>
- unchanged: <n> items, see <previous handoff>
```
