# Memory Architecture — treating an AI agent's memory as source code

## 1. Philosophy

Treat the memory stack as source code. You and the AI author a small set of canonical Markdown
files; a deterministic **Memory Compiler** (`memory_check.py`) validates state transitions, checks
for rejected-value collisions, builds disposable views, runs retrieval tests, and manages a
session ledger. Authored memory, not captured memory: automatic capture (transcript dumps, chat
history) may produce *candidates*, never canonical truth.

Governing rule:

> **Markdown owns truth. Handoffs own history. Sources own evidence. Generated indexes own
> retrieval convenience. Scripts own enforcement. Your sync layer owns synchronization — never
> authority.**

Operating constraint: **every rule must have either a validator or a template slot.** These
conventions are executed by an LLM session under token pressure at close time; a rule enforced by
neither a mechanical check nor a mandatory blank in a skeleton is a wish, and will be skipped
eventually.

### Why this exists

Long-running AI-assisted projects accumulate context the same way long-running software projects
accumulate state: some of it belongs in a database (current truth), some in a changelog (what
happened), some in a cache (fast to read, safe to throw away and rebuild). Most "give the AI
memory" setups collapse all three into one pile — a growing stack of chat summaries, or a vector
store of transcript fragments — and then have no way to tell a fact that's still true from one
that was corrected three sessions ago. This architecture is the result of forcing that pile back
into layers, and writing a script that actually enforces the boundaries instead of trusting the
next session to remember the convention.

## 2. The four layers

| Layer | Function | Contents |
|---|---|---|
| **A — Canonical** | Current truth, editable | `CONTEXT.md`, `OPEN_ITEMS.md`, `DECISIONS.md`, `TOMBSTONES.md` |
| **B — History** | What happened, when | session handoffs (deltas), chat archives, session ledger |
| **C — Evidence** | Unaltered sources | source documents, exports, contracts, spreadsheets — whatever the project's raw inputs are |
| **D — Generated** | Disposable, rebuildable | indexes, dashboards, test results, health reports — each stamped "GENERATED VIEW — NOT AUTHORITATIVE. Rebuild from canonical memory. Do not edit manually." |

## 3. Canonical file specification (Layer A)

**3.1 `CONTEXT.md`** — entities, relationships, naming traps, durable constraints, and material
current facts. Mutable current facts are allowed **only** with an `as_of` date + evidence pointer;
the compiler can flag any `as_of` older than a configurable threshold. Evidence is tiered:
pointers mandatory for figures, legal facts, measurements and commitments; lightweight or omitted
for definitions and operational observations. No general trust tags; the only marker is
`candidate`, applied exclusively to recovery-sourced entries (§4.4) — a demonstrated failure
reopens that decision.

**3.2 `OPEN_ITEMS.md`** — the live work-state ledger, permanent IDs. State moves *out* of the
handoff and into this file. Every prior active ID must end each close as OPEN / BLOCKED / DONE
(with evidence) / DROPPED (with reason). The compiler rejects a close that leaves an ID in none of
the four states.

**3.3 `DECISIONS.md`** — append-only register, permanent IDs:
`D-NNN · decision · why · date · evidence · supersedes · status`. Handoffs carry one line + the
D-ID, never the full rationale chain.

**3.4 `TOMBSTONES.md`** — "Rejected / Superseded Claims" registry. Structured, add-only:
`T-NNN · fact/key · rejected value · replacement · date · reason · source`. **Replacement is a
pointer wherever possible** (a fact-ID or a D-ID), not a copied value — a copied replacement
becomes the next stale fact when it changes. Consulted mechanically by the compiler on every close
and every outbound deliverable; read by every session at open, before old evidence can tempt
reassertion.

## 4. Session lifecycle

### 4.1 Open

1. Resolve scope — which project, always, first.
2. Preflight: canonical files exist · sync is up to date · no sync-conflict-copy files · no
   unresolved recovery candidate (hard block, see §4.4) · no other OPEN writing session on this
   project (see §4.2).
3. Write the **session ledger** entry `_sessions/<session-id>.json`: session, project, machine,
   started, `status: OPEN`, compiler + schema versions, baseline hashes of all Layer A files.
4. Read `TOMBSTONES.md`.
5. Orient from canonical files, not from the latest handoff — the handoff is history, not truth.

### 4.2 Concurrency — two mechanisms, distinct jobs

- **Baseline hashes detect stale writers.** Recorded at open, recomputed at close; any external
  change triggers an `[ask]` finding and blocks a blind overwrite. Also covers: manual edits by
  you, other automations, cross-machine changes arriving via sync.
- **Single-writer-per-project prevents the final write race.** Hashes alone can't stop it: two
  sessions can both pass the recheck, then write in sequence, and the second silently wins. Rule:
  at most one OPEN session may hold write intent on a project. A second session on the same
  project may read but may not run a writing close until the first ledger entry is CLOSED (or
  reconciled via recovery). The ledger entry *is* the lock; a crashed session's stale lock is
  cleared through §4.4 recovery, never by simply deleting the file.
- **Compiler-version check:** if compiler/schema versions changed between open and close (your
  tooling synced mid-session), that's a finding — revalidate rather than silently continue.
- Atomic writes only (temp file → validate → replace), so a sync client never uploads a
  half-written canonical file.

### 4.3 Close — the Memory Compiler (`memory_check.py --close <session-id>`)

1. **Validate** — unique IDs · resolving evidence pointers · legal open-item transitions · stale
   `as_of` flags · truncation check (no canonical file ending mid-structure) · no tombstone
   collisions in changed files.
2. **Concurrency** — recompute hashes against the ledger baseline; verify writer lock; verify
   tooling versions (§4.2).
3. **Build** — regenerate Layer D views (indexes, dashboards).
4. **Test** — run `memory_tests.yaml`: positive (`must_reference`) and negative
   (`must_not_return` for tombstoned values) retrieval assertions.
5. **Audit** *(optional, not in the reference implementation)* — snapshot changed canonical files
   to a local git mirror outside your sync tree. An audit failure should log an error but not
   block the canonical close.
6. **Seal** — set the ledger entry to `status: CLOSED`. Only a successful compiler run may do
   this.

**Handoffs migrate to structured files in stages:** don't try to retire the free-form handoff on
day one. Move a block out of the handoff only after its canonical replacement (`OPEN_ITEMS.md`,
`DECISIONS.md`, …) has survived real closes. Until then the handoff's redundancy is the airbag,
not waste. Keep a hard size cap on handoffs regardless (roughly 8 KB / 150 lines worked well) —
with an escape hatch for the rare case that genuinely needs more, flagged explicitly rather than
silently overrun.

### 4.4 Recovery (failed close)

A daily or session-start sweep finds ledger entries left OPEN past a staleness threshold and
generates `RECOVERY - <project> - <session>.md`: candidate facts, decisions, corrections,
open-item changes, touched files — every line marked `CANDIDATE — NOT CANONICAL`. Raw conversation
dumps are explicitly rejected (that would just reintroduce captured memory under a different
name). **An unresolved recovery candidate hard-blocks new writing sessions on that project** —
reconcile first, then work; a warning an impatient session can skip is not enforcement.

## 5. Design decisions worth stating explicitly

These are the calls that could reasonably go the other way — recorded here so you don't relitigate
them from scratch, and can consciously choose differently if your situation warrants it.

1. **Trust tags kept to one: `candidate`, recovery-sourced only.** More granular trust levels
   sounded appealing but nobody could agree on the boundaries, and a tag nobody maintains is worse
   than no tag.
2. **Delta-handoffs staged, not declared on day one.** Retiring the free-form handoff before its
   structured replacement has proven itself in real closes just relocates the risk.
3. **Tombstone replacements as pointers, not copied values.** A copied value is the next stale
   fact waiting to happen.
4. **A fact-ID system for individual numeric claims (e.g. "this figure is `PROJECT:F-014`, cited
   by ID everywhere, never retyped") is powerful but expensive to retrofit.** Pilot it in one
   project with a lot of numbers before adopting it everywhere.
5. **`_pending/` staged writes (hold all canonical changes until the compiler applies them
   atomically) are architecturally cleaner but double the write-path complexity.** Only worth it
   if practice shows half-closed sessions actually corrupting canonical files — the ledger already
   converts a failed close into a recovery candidate rather than a silent half-write, which covers
   most of the risk cheaply.
6. **A git audit mirror is per-machine until you add a private remote.** It's not a complete
   cross-machine audit trail on day one — don't let the tooling imply otherwise.

## 6. Multi-machine synchronization

**6.1 One canonical tree.** Whatever folder you sync (OneDrive, Dropbox, a private git remote) is
the only editable working tree; the sync layer is transport, never authority. Keep the whole tree
available offline on every machine that writes to it — scripts break on cloud-only placeholder
files. Reference paths via environment variables, never hardcoded user paths, if you run this on
more than one machine.

**6.2 Shared tooling.** Scripts, templates and any process documentation live inside the
synchronized tree — every machine executes identical versions (hence the §4.2 version check).
Machine-specific things (virtualenvs, caches, `.git` metadata, lock files without cross-machine
meaning) stay local, outside the tree.

**6.3 Conflict handling.** Hash concurrency **detects** stale writers; the single-writer rule
**prevents** the final write race (§4.2 — the distinction matters). The compiler additionally
detects sync-conflict-copy files (`... (conflicted copy).md` and similar patterns) and blocks
canonical writes until you reconcile them. Two machines writing offline to the same project at the
same time is the one scenario nothing here fully protects against — avoid it by convention,
reconcile via the conflict checker on reconnect.

**6.4 Git audit mirror, outside the sync tree** *(optional)*. At each clean close: snapshot
changed canonical files to a strictly-local folder outside the synced tree, commit with a
descriptive message. Never put `.git` inside a folder your sync client also watches —
corruption/conflict risk. Multiple machines' local audit repos can later push to one private
remote for a global, off-machine history; that's optional and secondary, since the sync layer
remains the live layer either way.

## 7. Suggested build order

If you're implementing this from scratch, this ordering keeps every step usable on its own before
the next depends on it:

1. `OPEN_ITEMS.md` — move state out of ad-hoc tracking and into a validated ledger.
2. `TOMBSTONES.md` — structured, pointer replacements.
3. Compiler validation (`memory_check.py`, §4.3 step 1).
4. Session ledger + single-writer lock (§4.1–4.2).
5. Failed-close recovery with hard block (§4.4).
6. Concurrency / sync checks (hashes, version check, conflict-copy detection, atomic writes).
7. Generated index / dashboard view (Layer D).
8. `DECISIONS.md`.
9. Evidence/fact-ID pilot, scoped to one project — only if §5.4 earns its keep.
10. Memory tests (`memory_tests.yaml`, positive + negative).
11. `_pending/` staged writes — only if practice shows half-closed sessions corrupting canonical
    files.
12. Git audit mirror (+ optional private remote later).

Git deliberately near-last: an audit trail shows the wreck afterwards; validation is what prevents
it. The ledger (step 4) comes ahead of recovery (step 5) because recovery detection depends on it
existing first.

## 8. What this is not

This is not a vector database, not RAG over chat history, and not an attempt to make the AI
"remember everything." It's the opposite bet: most of what a chat produces should be thrown away,
and the small amount that should persist should be written deliberately, validated mechanically,
and correctable when it turns out wrong. If your use case is "search my past conversations for a
fuzzy match," this isn't that tool. If your use case is "stop the AI from confidently reasserting
a fact I corrected two weeks ago, across every project and every machine I use," this is the
shape that solves it.
