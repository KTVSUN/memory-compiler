# How the system works, in full

Version 2.0, October 2026. Supersedes the August 2026 description (now in `legacy/`). Written from the live operating manual, decision log and specs, with names, paths, addresses and business facts removed. Where a number is given (a cap, a schedule, a threshold) it is the value in use today, not a recommendation.

Contents

1. What it is
2. Principles
3. The layers
4. The library and filing
5. Sessions: open, work, close
6. The task layer: register, board, intake, plans
7. The email layer
8. Unattended jobs and how we know they ran
9. The repository and the one-click reinstall
10. What changed since version 1, and why
11. What is deliberately not built
12. A build order for someone starting

---

## 1. What it is

One person runs several small businesses (a real estate development, two holiday rentals, a few side projects) with Claude as the assistant, through Cowork sessions opened on a project folder. The folders sit on a synced drive (OneDrive) so they are the same on the desktop and the laptop. One Windows desktop also runs unattended jobs: it wakes at 07:00, works through the evening, and sleeps at 22:00.

The system is everything that lets a session on Tuesday know what a session on Monday did, what a job did overnight, what arrived by email in between, and what the owner still has to decide, without the owner retelling it. It is a set of files and conventions, about forty scripts and skills, one git repository, and one installer.

Scale, for calibration: three libraries holding roughly a hundred topic folders, a decision log at 147 numbered rows after two months, a task register of a few dozen open tasks, an email ledger of about 700 thread verdicts after one week of hourly runs, and two to twenty sessions a day.

## 2. Principles

**Files own truth. A conversation owns nothing.** Documents in the library, decisions in `DECISIONS.md`, tasks in the register, defects in `DEFECTS.md`, email state in the mail ledger. A session that learns something writes it to the file that owns it, in the turn it happens. What is not written does not survive the chat.

**Each fact has one owner.** A buyer's terms live in one workbook, read once from the contract at entry. Lot prices and status live in another. Permits live in the permits folder. An email's state (sent, arrived, waiting) lives in the mail ledger. A discrepancy between the owner and its source is traced and fixed in the owner, never worked around in a draft. Everything else points at the owner by path or by ID instead of copying the value.

**Authored memory, not captured memory, with one scoped exception.** Nothing hoovers up chat transcripts into a store. The exception is the email layer: a model does read incoming mail and judge it. But its judgements only go into append-only archives (thread files, a ledger, a project log) and a proposal list; they never touch canonical truth, never create a task, never move a filed document.

**What a session reads at start is fixed in size. Archives grow without limit and are only searched.** The start read is a two-sentence state, a short menu, and three mail counts. The thread archive, the ledger, the daily record and the decision log are not read at start; they are searched when a question needs them. A condensed per-topic brief is allowed only after a month of material exists and only in a session where a human is present.

**Every rule has a validator, a template slot or a script. A rule with none is a wish.** Conventions are executed by a language model under token pressure at the end of a long session. Where a rule can be mechanical (a path checker, a hash re-point, a run-health check, a file-verify step) it is a script that runs overnight or before a message is sent. Where it cannot, it is a mandatory blank in a skeleton the session has to fill.

**Mail state beats memory.** For any statement that something was sent, arrived, is awaited or is to be sent, the latest ledger row for that thread and the thread file it names are the truth over a handoff, a daily-record line, a register row or a task. Every reader that could contradict it (session start, session close, the weekly report) reads the ledger through one script.

**Ask, don't report.** A session start does not show what it read. It asks what the owner wants to do, one line per choice, and reads in full only what goes with the answer.

**Humans decide, machines propose.** No job and no session creates a task for the owner, files a document, changes a rule or deletes a file on its own initiative. Intake writes proposal rows; the owner approves on the board. A tool defect found mid-session goes into `DEFECTS.md` as one line and is fixed in a declared build session, never on the spot.

**Nothing runs in the owner's face.** Every job runs hidden (a command window opening on a PC reads as a virus). The owner's step is removed, not documented: when something has to happen on the machine, the deliverable is one double-clickable file, not instructions.

## 3. The layers

| Layer | Function | What is in it |
|---|---|---|
| **A. Canonical** | Current truth. Editable. One owner per fact. | `DECISIONS.md` per project; `CONTEXT.md` per project (glossary, durable facts only); `LOG.md` per project (dated facts, append-only); a `_LEDGER.md` per library zone; the task register (CSV); `TOMBSTONES.md` (rejected claims); `ROUTING_EXCEPTIONS.md` (document-to-consequence routes inference missed); `DEFECTS.md` (tool faults); `MISTAKES.md` (the owner's corrections of the assistant); the owner's preferences text |
| **B. History** | What happened, when | one handoff per topic per session, written as deltas against the previous one; the daily record (one dated section per day, by script, no model); the chat archive; the email ledger |
| **C. Evidence** | Unaltered sources | the document library; email thread files and attachments saved verbatim; manifest rows that say what each generated document depends on |
| **D. Generated** | Disposable; rebuilt nightly or hourly | the task board (HTML), the derived search index (SQLite), the needs-you list, the run-health strip, the topic menu |
| **E. Tooling** | Everything the assistant reads to do its job | the `ops` git repository: skills, scheduled-task prompts, scripts, templates, the operating manual, the installer, per-machine config |

The governing sentence of layer E: *if the assistant reads it and it is not a project document, it lives in the repository.* The repository is the source and the assistant's account is a deployment target: a skill is edited in the repository and pushed to the account from that file, never edited in the account's cache; a scheduled prompt is edited in the repository and pasted into the task.

### 3.1 The canonical files, briefly

- **`DECISIONS.md`**: append-only table, `D-NNN | decision | why | date | evidence | supersedes | status`. Written in the turn the decision is taken, never at the close. The why is the point; a handoff carries one line plus the D-number, never the rationale. A reversal is a new row naming the old one. A change to a tool that alters a rule carries its D-number in the commit message.
- **`CONTEXT.md`**: glossary and durable facts, sectioned (what the project is; entities and people; documents; concepts; platform terms; numbered references). Test for every line: if it would be false in a month, it belongs in a handoff, not here.
- **`LOG.md`**: dated, topic-tagged facts with a source line, append-only. Human-written entries (a WhatsApp transcript, a call note) and machine-written entries (knowledge notes from the email importer) share the format. The start read ignores it; it is searched.
- **`_LEDGER.md`** (one per zone): the row that makes a document definitive. A file in a topic's `Output\` with no ledger row is work product, not a filed document. Rows point at files by path; a nightly job re-points rows whose file moved.
- **The task register**: CSV files under a machine-local folder (never in the synced drive, because the sync client fights a file rewritten many times a day), copied nightly to the synced drive for backup.
- **`TOMBSTONES.md`**: `T-NNN | claim | rejected value | replacement | date | reason | source`. Replacement is a pointer (a D-number) wherever possible, not a copied value. Add-only.
- **`DEFECTS.md`** (in the repository): one line per tool fault, stale document or naming slip noticed during a session, said nowhere in chat. Triaged by the monthly build session.
- **`MISTAKES.md`**: one line per mistake the owner pointed out (date, chat, tag, what was done, what the rule says), written the same turn, no apology paragraph. Counted weekly by a job; repeated tags turn into a change of the preferences text.

## 4. The library and filing

A **library** is a folder tree for one business. A **zone** is a folder holding a `_LEDGER.md` (Financing, Legal, Infrastructure, Accounting). A **topic** is a folder holding `Input\`, `Output\` and `Work folder\`; a folder may be both zone and topic. Projects too small for a library are plain topic folders under one `Projects\` root.

Inside a topic:

- `Input\` holds source material: received documents, and `Input\Emails\` written by the importer. A session fills it for its own work; no job ever moves anything into or out of it.
- `Output\` root holds deliverables only. Everything else the assistant makes (scripts, data, renders, intermediate files) goes in `Output\_work\<what it is> - YYYYMMDD\`. The assistant's own Markdown (handoffs, specs, notes) goes in `Output\md\`. Letters go in `Correspondencia\`, numbered by date.
- `Work folder\` belongs to the owner. The assistant writes, moves and renames nothing there unless told to in the session.
- `_to_delete\` is quarantine: a superseded version goes there with a row in `_quarantine.csv`, and a job purges it after 14 days. Nothing is deleted directly, by anyone.

**Filing is two acts, never a move.** The file gets its permanent name, `Author - Topic - YYYYMMDD[ - Comment].ext` (Author is the organisation for anything received, a person only when known by name, the owner's initials for the owner's own or assistant-made work), and a row goes into the zone ledger. Native formats are never converted. Tidying moves files and never rewrites them.

**Intake.** External documents are dropped into one `_INTAKE\` folder or a cloud-drive inbox. An evening job reads them and writes proposal rows (zone, proposed name, destination); each becomes a card on the board with a zone dropdown and a filename box. The owner approves or parks. A proposal whose name fails the naming check never reaches the board as approvable; the reason is written into the row and it is re-proposed next run. A file that reappears with the same bytes as a pending row whose file is gone is a move, not a duplicate.

**Hand moves are expected.** The owner reorganises folders by hand. A nightly job snapshots both libraries by content hash and re-points every ledger row, manifest row and baseline row whose path is gone to the file's new location, by hash first and by name and folder as tie-breaks. Files the owner adds by hand to a zone's active area get an automatic ledger row marked "auto-added, unreviewed" that night, with a proposed convention name; the rename happens only on the owner's yes.

**Consequence routing.** Filing a document can have consequences elsewhere (a new supplier quote belongs in the cost-comparison workbook; a signed contract changes a lot's status). Routes the destination makes obvious are inferred. A route inference missed once, and the owner had to point out, goes into `ROUTING_EXCEPTIONS.md` so it is never missed again. The file is not seeded with obvious routes.

## 5. Sessions: open, work, close

### 5.1 Open: `/start`

1. **Folders, one window.** The session requests every folder it will need in one approval dialog, by real path, before writing a word. If the request is refused, the first line of the reply says who refused (the owner or the app's automatic check), lists the missing paths, and the step that needs them is marked waiting, never skipped or replaced by a home-made version.
2. **Topic menu, by script, in about one second.** A script lists topic folders dated by their newest handoff file name, active first, with topics untouched for 30 days behind one line (`+ N dormant, say all`). No file walk, no subagent, no narration.
3. **Gather silently.** The current handoff (highest date, then suffix), every open item in it (following "unchanged, see previous" pointers until all are found), the plan summary from the register, a count of blocking items and housekeeping findings, and three mail counts for this topic from the mail-state script (need you, waiting on them, new since the last handoff).
4. **The menu, and nothing else.**

```
<Topic>
1. Kickoff ready: <one line>
2. Open work, no kickoff: <one line per item>
3. Waiting on someone else: <person>: <what is awaited>, then <what it unlocks>
   (a line becomes "replied on <date>" when the mail ledger shows the counterparty wrote last)
4. Plan <name>: next step <one line>. Go on with it?
5. Blocking items and housekeeping (<count>). Deal with those?
6. Mail on this topic: <n> need you, <n> waiting on them, <n> new since the last handoff. Look at them first?
7. Something new.
Which one?
```

An empty line is not written; the rest is renumbered. No current-state paragraph, no plan block, no files-read list. A kickoff written in a handoff is not authorisation; the owner's go-ahead in this session is. After the pick the session proposes a chat title in a fixed format (`PROJECT -- SUBTOPIC: description`) so chats sort and read apart from scheduled runs.

### 5.2 During the session

- A decision goes to `DECISIONS.md` the turn it is taken, with its why.
- A tool fault, stale doc or naming slip goes to `DEFECTS.md`, one line, said nowhere in chat.
- A trap (how a tool or site behaves) goes to the assistant's project memory.
- A mistake the owner points out goes to `MISTAKES.md` the same turn; the reply is the log line plus the fix.
- Before saying a file is saved, fixed or works, the session runs a verify script on it with a phrase only the new version contains, and quotes the PASS line. Before sending a message that contains paths, it runs a path checker (resolves, has a drive letter, not a retired alias, runnable files written so they paste into a shell).
- A build session is declared as such. **BUILD-DESIGN** (architect, strongest model) reads widely and writes a spec an executant can follow without thinking: every path, field, value, acceptance check, and "if X is missing, stop and ask". **BUILD-IMPLEMENT** (any model) reads only the files the kickoff lists, does exactly what the spec says, stops and reports where the spec is silent, and never presents an invention as if it came from the spec. No tool is changed outside a build session.

### 5.3 Close: `/handoff`

1. **Supersedes diff.** Open the previous handoff. Every OPEN item there reappears as OPEN (carried at most once), DONE with the file that proves it, or DROPPED with why. An item carried unchanged for the second time is not carried: it becomes the single allowed question (drop it, or make it a dated task).
2. **Mail check.** Run the mail-state script for this topic since the previous handoff. Every open item or next step that names a reply, a document someone must send, a payment or a signature is matched to a thread (by counterparty address or surname). If the counterparty wrote last, the item is not waiting: it is rewritten from the row or marked done with the thread file as proof. Rows that match no item and need the owner are added as open items. The handoff never says "once it is sent" about a mail the ledger shows as sent.
3. **The handoff**, under an 8 KB cap, in the topic's `Output\md\`, named `HANDOFF - <topic> YYYYMMDD<suffix>.md`. Blocks: kickoff prompt for the next session (or `No new session needed.`); header; **current state in two sentences at most, what is true now and what comes next, never what the session did**; the authoritative current set, by path; decisions with D-number and one-line why; open items as deltas (closed since, new since, dropped, "unchanged: n items, see previous"). See `templates/HANDOFF_TEMPLATE.md`.
4. **The kickoff gate.** The default is no kickoff; a kickoff costs the owner about an hour. One is written only if the owner asked for a next session, or critical work was identified, not done, and cannot be finished in this chat, or a design spec is final (which counts as the yes for the implementing session). Never for validation work, never for waiting on other people, never for continuity. A kickoff names the model and why, the session type if it builds, the files to read in order, the actions each with a `Must fit with:` line naming the files and live systems it must agree with, stop conditions and out-of-scope. It is printed once, complete, at the close, and stored verbatim in the handoff and in one labelled task in the phone app that the next session deletes when it opens.
5. **Tasks are proposed, never assigned.** The session creates no task for the owner unless the owner asked for it in this session. Everything it thinks should be done is a numbered proposal at the end of the close message, and dies there if not picked up. (This rule exists because the owner once woke to 47 cards written by sessions the evening before, could not tell what they were, and did none of them.)
6. **Plan**, chat title, and one numbered list holding at most a phase-status proposal, the offered tasks, and one question only if it blocks the next session's first action. Nothing is asked after the list.

No process-register update, no `CONTEXT.md` sweep, no health checker, no manifest run at the close. What survives of those runs as a script overnight.

## 6. The task layer: register, board, intake, plans

**Register.** CSV files on the local disk: tasks, plans, phases, proposals, run status. A task is added when the owner types it or confirms it. Fields a rule needs (zone, due, plan and phase, created-by) are columns; everything else is body text. The register is backed up nightly to the synced drive and restored by the installer on a new PC.

**Board.** A local web page rendered by a small server at log-on and re-rendered by the morning job and after every board action. Lanes: overdue, due, mail (needs you, expected replies), waiting on others, mail waiting on others, blocked on you (proposals), done. Cards carry buttons (done, park, snooze, correct topic, open thread, open in mail), and the mail lanes carry tick boxes with a "done ticked" button, because the owner clears a week of information mail in one click. A header strip shows run health (section 8) and the memory sizes line (section 7). A watchdog restarts the server every five minutes if its health endpoint does not answer.

**Phone mirror.** The morning job mirrors the register to a commercial task app both ways: register rows become tasks in the project's list; tasks the owner adds on the phone become register rows at the next pull; a task deleted on the phone sets its row to dropped with a dated line saying so. One task never stops the run: an update refused by the app is logged and the rest is saved. Session machinery (kickoff tasks, chain markers a scheduled run will tick off) carries a label the sync skips, so it never becomes a register row.

**Intake** is described in section 4: proposals only, the owner is the gate.

**Plans.** Multi-session work is a plans layer inside the register (`plans.csv`, `phases.csv`, tasks linked by plan and phase), mirrored to the phone app as sections. No per-folder roadmap file: two truths were rejected. Plans are declared only on the owner's explicit word; phase-status changes are proposed at a close, never applied.

Titles everywhere follow a plain-language standard: one imperative line, everyday words, no register or ledger code, with an allow-list for the few abbreviations the owner uses himself.

## 7. The email layer

Added in October 2026, and the piece that made the rest complete. Until then every layer above was fed only by what happened inside work sessions, and half of what happens in a small business happens by email: a supplier revises a quote, a client agrees to a date, the accountant answers a tax question, the bank blocks an account, the owner commits to something in a reply. None of it reached the memory unless the owner repeated it in a session, which he rarely did because it felt obvious. Sessions planned around a quote superseded by email three days earlier and asked the owner to chase replies already in his inbox.

The aim, then: work email becomes part of each project's memory, filed next to the documents it concerns and linked to the same decisions and open items, without the owner living in the inbox; and the question "did they reply?" is answered from evidence, never from a handoff's recollection. A session that opens on a topic now sees the last handoff and the mail that arrived since, side by side.

### 7.1 Shape

A Python program runs hidden every hour on one Windows PC, started by Task Scheduler, with a one-click "sweep now" file for manual runs. It reads the owner's mailbox through the Gmail API with its own OAuth client, grouped by thread, with a 48-hour overlap so a missed hour loses nothing. It skips mail carrying labels the owner uses for noise and for pipelines that have their own readers (bank alerts, invoice inboxes, newsletters). It is not a scheduled task of the assistant and not a third-party automation: the plumbing is deterministic and belongs in a script; only the judgement is a model call.

A one-PC guard: the installer writes the host name into the config; the program exits silently on any other machine. Secrets (OAuth client, refresh token, API key) live in a local folder outside the synced drive and are backed up only in a password manager.

### 7.2 The destination list

One Markdown file, the **topic matrix**, maps every topic folder of every library to a code: `PROJECT/Zone/Topic`, a project's `/ROOT` for mail that belongs to the project but no topic, and four buckets for mail that belongs to no folder (personal bank, government, other work, noise). Lines carry optional flags: `pipeline=<name>` for mail another job consumes (supplier invoices, booking and payout mail, the monthly escrow statement, a weekly pricing report), and `path=` when the folder name does not follow the pattern. The grammar is strict; a parse error or a missing destination folder stops the run with the line number. The owner adds a topic by adding a line.

### 7.3 Two model calls per thread

**Stage A, sorting**, batched 25 threads per call on headers plus the first thousand characters of the latest message: one destination code per thread, a confidence (H/M/L) and a reason in twelve words. The system prompt holds the matrix, a dozen rules learned from a 30-day backtest (what is noise, what alias address implies what code, where booking mail for each property goes), and the owner's last fifty corrections as "sender, subject, correct code".

**Stage B, judgement**, one thread per call on the full text and the extracted text of attachments (PDF, Word, Excel, XML; images and scans are listed as not read): confirm or change the topic; the **demand** verdict, exactly one of **NEEDS-YOU** (a decision, approval, payment, signature, answer or security action is pending from the owner and nobody else can take it, and the latest message is not his), **FOLLOW-UP** (the owner asked a named counterparty to send, sign, pay, confirm or decide something and the answer has not come), **INFO** or **NOISE**; a **knowledge** verdict (does the thread state a position, rule, figure or decision a future reader of this topic should know without reopening the mail, written as one to three sentences with the figure itself); an **expected event** when the owner's own message asks a counterparty for something a pipeline consumes; and a **pipeline item** flag when the thread itself is the thing a pipeline consumes.

Calibration came from a 30-day backtest workbook of real threads the owner corrected by hand. Acceptance was 95 percent of threads in the right project and no needs-you thread lost among the owner's corrections; the small model failed it, the mid model passed on topic and missed on demand, the large model passed on the third replay and is the one in use. A code not in the matrix is a parse failure that retries once, never a near match.

### 7.4 What is written, per thread, in this order

1. The **thread file**, `Input\Emails\Emails\YYYYMMDD_<subject-slug>_<thread id>.md` in the destination topic: subject, date range, participants, saved attachments, the importer's verdict line, then one section per message with verbatim plain-text body, quoted tails replaced by `[quoted thread omitted]`. Regenerated whole when the thread gains a message.
2. **Attachments** next to it, original bytes, date-prefixed; inline images under 20 kB are skipped.
3. A **manifest** row per message in `Input\Emails\manifest_emails.csv`, append-only; existing hand-made manifests are read so nothing is duplicated.
4. One row in the **ledger**, `ledger.csv`, append-only: run time, thread, dates, sender, subject, alias address, Stage A code, final code, confidence, pipeline, demand, reason, knowledge yes/no, item numbers, thread file path, attachments saved and not read, message count, language. The ledger is the only file a session needs to answer "what happened to thread X"; the program's SQLite state is a cache rebuildable from the ledger and the folders.
5. A **knowledge note** appended to the project's `LOG.md` in that file's own format (date, topic tag, source, fact, triggers, path of the thread file, run and ledger row), queued and written in one write per log at the end of the run, and only when the file has been quiet for five minutes, so it never collides with a session or the sync client.
6. An **expected event** row when the owner asked for something a pipeline consumes, with the pipeline, what is expected and from whom.
7. Only then are the message IDs marked processed. A failure at any step leaves the thread unprocessed, writes a retry row with the error text, and moves on.

Pipeline threads get a ledger row only (demand `PIPELINE`), no file: their reader will fetch them itself. Bucket threads are judged on headers and snippet only, get a ledger row, and reach the needs-you list with no file path (a card-in-arrears notice must reach the owner even though it is filed nowhere). Noise gets a ledger row, so the replay can be measured.

### 7.5 The needs-you list and the way back

At the end of every run the program rewrites one cross-project **`NEEDS_YOU.md`**: a counts line (`n need you, n waiting on others, n expected replies`), then three tables (needs you; waiting on others; expected replies), each row with a permanent number (`NY-0007`, `EX-0002`, assigned once per thread, never reused), topic, date, counterparty, subject, what to do in 90 characters, and the thread file path. The Gmail label `__Needs you` mirrors the first table and is the only change the program makes in the mailbox.

The way back is one CSV the program only reads: **`NEEDS_YOU_status.csv`**, columns `ts, item, action, value, chat, note`, actions `done`, `snooze <date>`, `correct <topic code>`, `reopen`. Sessions append a row when the owner says `done NY-0007` in any chat; the board's buttons and tick boxes append rows; the owner never edits `NEEDS_YOU.md` by hand. Last row per item wins. A correction moves the thread file and attachments to the new topic on the next run, appends manifest rows there, writes a ledger row with reason `refiled by correction`, and joins Stage A's correction list, so the same sender is sorted right next time. An item marked done comes back if the thread gets a newer verdict that still needs the owner.

### 7.6 Readers

- **`/start`** shows one line: mail on this topic, with the three counts. On yes it prints the rows in three groups with each thread file's path. It drafts no reply and logs no task from a mail row unless asked.
- **`/handoff`** runs the mail check of section 5.3 before writing open items.
- **The board** has two read-only mail lanes fed from `NEEDS_YOU.md`, with tick boxes.
- **The daily record** has a mail section.
- **The weekly report** reads the ledger for "what moved" and "waiting on others".
- **The "mail" command** in any session prints `NEEDS_YOU.md` verbatim.

All of them read through one script, the mail-state reader, which maps a topic folder to its matrix codes and prints counts, lines or JSON for a date range. One reader, one truth.

### 7.7 Growth

Nothing in the email memory expires. The needs-you list keeps no age flag. Every run writes a `sizes:` line (ledger rows and MB, each project log in KB, item count) into the heartbeat file, and that line is meant for the board header. A per-topic brief condensed from the ledger is allowed after a month, in a human-present session only.

## 8. Unattended jobs and how we know they ran

Two kinds. **Windows jobs** (Task Scheduler on the desktop, all hidden, registered by the installer with today's triggers, able to wake the PC and to catch up a missed run): the board server at log-on; a watchdog every five minutes; the morning job at 07:00 (recompute, phone mirror, render); the daily record at 07:05; the evening runner at 18:00 (manifest, purge, phone markers, register backup); the email importer hourly; the ledger re-point at 20:00; the index rebuild at 21:00; sleep at 22:00. Exactly one Windows job calls a model: the importer.

**Cloud scheduled tasks** of the assistant, each with a spec file in the repository (name, schedule, folders, model, verbatim prompt, and a brief to paste when recreating it): the intake sweep on weekday evenings, the rental books every evening, a monthly tax sweep, a weekly pricing watch, the weekly report draft on Friday, the mistake-log count on Monday, a weekly rebuild of the skill catalogue, and two reminders. Every recurring task is named `TASK -- <project>: <what it does>` so its run chats sort together and read apart from real sessions.

**The daily record.** A script, no model, appends one dated section per day to one file per month: for each session that closed, the chat title, topic and the handoff's current-state paragraph verbatim; documents filed that day from every ledger; decision rows added; tasks done and added; letters placed; mail that needed the owner; jobs run; and one line naming any topic whose folder changed with no handoff. Re-running a date replaces that date's section.

**The weekly report.** A skill in draft mode on Friday reads only the daily record and the handoffs it names and writes one draft for all readers (partner and financiers alike), with a "sources used and left out" block; the owner amends and approves it on Monday, and the approved copy is filed with a ledger row. Every line says what it gives the reader and when, never how it was done; no model internals, no checks.

**The run strip.** The board header carries one circle per scheduled run, filled by a script reading a `runs.json` of expectations against the evidence each run leaves behind: a log line, a report file, or a dated stamp the run writes as its last step. Green is ran; red is failed or missing; grey is "the computer was off at that slot", judged from the server's heartbeat log. **No session's own report is ever evidence.** A job that did not run because the PC was off while the owner travelled is normal, and is neither reported nor investigated.

An unattended run never edits a script, spec or skill. A fault goes into its report; the fix is a numbered proposal for a session the owner is in.

## 9. The repository and the one-click reinstall

One git repository, cloned outside the synced drive on each machine (a `.git` folder inside a sync client's tree is a corruption risk), with a private remote. Contents: every skill as its source file; every scheduled-task prompt as a spec file; the Windows scripts and their hidden launchers; the installer; the handoff template; the filing doctrine; the operating manual (`HOW WE WORK.md`, ten sections, changes only when a decision changes it); `DEFECTS.md`; a `config\` folder holding the one per-machine file (`paths.json`, drive letters and roots), the run expectations, the title allow-list, and example secret files.

Rules: every change is a commit; a commit that changes a rule carries its D-number; after the first stable tag the repository is frozen for thirty days except for a fix that names the failing case first; the acceptance test for "stable" is a clean reinstall on the second machine from the repository alone.

**Reinstall**, on a new Windows PC, in order:

1. The sync client with the libraries set to "always keep on this device" (scripts break on cloud-only placeholder files); the cloud-drive mirror for the inbox folders.
2. Git, and `git clone <private remote> C:\<local>\ops`.
3. The password manager open at its three entries (OAuth client file, API key, task-app token).
4. Double-click `INSTALL - <system>.bat`. It asks for administrator rights, then runs eleven steps, printing one check line per step and stopping on the first FAILED: find or install Python and the packages; write `paths.json` from the drive letters it finds; ask for the three secrets and write them to the local secrets folder; restore the task register from last night's backup; register every Windows job with its trigger, wake setting and hidden launcher; set "allow wake timers" on; start the board server and check its health endpoint; print the job table.
5. In the assistant's desktop app: sign in; paste the preferences text if the box is empty; open the project folder and approve its folders once "for all future runs"; save any missing skill from the repository file; reconnect connectors; for each cloud task whose spec says it needs this computer, paste its brief into a chat in the right project and delete the old task.
6. Smoke test: `/start` prints the menu; the board opens; the next morning the run strip is green.

The second machine answers NO to the importer question (one importer PC) and gets its own `paths.json`.

## 10. What changed since version 1, and why

Version 1 (August 2026, now `legacy/`) was a **compiler**: a script that validated four canonical files at session close (`CONTEXT.md`, `OPEN_ITEMS.md`, `DECISIONS.md`, `TOMBSTONES.md`), held a session ledger with a single-writer lock, generated recovery candidates for crashed sessions, and ran retrieval tests. It was correct and it was abandoned within a month. What happened:

- **The close-time check moved to overnight scripts.** A validation that runs when the model is tired and the owner is waiting gets skipped, argued with, or run on half the files. The same checks (orphans, ghosts, stale pointers, missing ledger rows, run health) now run as Windows jobs on their own schedule and write reports nobody has to read unless a circle is red. The close does less, not more.
- **`OPEN_ITEMS.md` was never built; the register and the handoff deltas took its place.** Open work turned out to be two different things: business tasks the owner does (register, with a phone mirror and a board) and in-flight session state (the handoff's deltas block). One file for both would have been a second register. The supersedes diff survived unchanged and does the compiler's "no item left in limbo" job by template slot instead of validator.
- **The decision log became the spine; tombstones stayed but shrank in role.** With every decision written the turn it is taken, with its why and its supersedes pointer, most "do not reassert this" cases are answered by the latest D-row. Tombstones remain for rejected claims that no decision owns (a wrong cause attributed to a failure, a retired path style).
- **Memory became a federation of owners, not four files.** The one-owner rule (section 2) replaced the idea that canonical truth is a short list of Markdown files. Workbooks, the register, the ledger and the library's ledgers are canonical for what they own.
- **The email layer was added, and with it one place where a model writes memory.** It was accepted because its writes are append-only archives and proposals, calibrated against a human-corrected backtest, correctable by a one-line status row, and read through one script that every other reader must use.
- **Session start became a menu.** The start used to read and report; the owner skimmed and missed the one line that needed an answer. It now asks.
- **Tooling went under git and got an installer.** Truth about *how the system works* used to live in six or seven kinds of places (skill caches, pasted prompts, process-register rows, a PDF guide). A skill rule was lost to a stale-cache overwrite; two prompt revisions were never pasted and nobody noticed for four days. The repository fixed the authority question; the installer made the acceptance test ("reinstall from scratch") runnable.
- **The owner's working rules got their own loop.** A preferences text with five questions to answer before every message, a mistake log written the same turn, a weekly count of repeated tags, and a rule that a change to the preferences arrives as the full merged text. This is memory about how to work with this person, and it turned out to need the same discipline as memory about the business.
- **Deleting was banned.** Everything superseded goes to quarantine with a record and a 14-day purge. Sessions cannot delete on the owner's disk; a job can, after the delay.

Kept from version 1, unchanged in spirit: files own truth; authored not captured; the four layers plus tooling; the handoff cap and the supersedes diff; pointers over copied values; "every rule has a validator or a template slot"; sync is transport, never authority.

## 11. What is deliberately not built

- A fact-ID system for individual figures (`PROJECT:F-014`, cited by ID everywhere). The one-owner rule plus "point at the workbook" covers it at this scale.
- Staged `_pending/` writes applied atomically at close. No half-closed session has corrupted a canonical file; the handoff and the same-turn decision rows are the crash insurance.
- A per-topic condensed brief from the mail ledger. Waits for a month of ledger.
- Age flags or expiry on the needs-you list. The owner ticks; the machine keeps.
- A vector store or RAG over chats. The problem was never recall of fuzzy past conversations; it was the confident reassertion of a corrected fact, and that is a question of ownership, not of search.
- Tasks created from mail or intake by the machine. Tried, reversed, and now a hard rule.

## 12. A build order for someone starting

Each step is useful on its own before the next depends on it.

1. The library convention: zones with a ledger, topics with `Input\`, `Output\`, `Work folder\`, quarantine instead of delete, the naming rule.
2. `DECISIONS.md`, written the same turn, with the why.
3. The handoff template with the cap and the supersedes diff, and a `/handoff` skill that enforces the kickoff gate and "tasks proposed, never assigned".
4. A `/start` skill that requests folders in one window and prints a menu.
5. A task register as CSV on the local disk, a rendered board, and a phone mirror.
6. The daily record script. No model.
7. The git repository for everything the assistant reads, with the operating manual inside it.
8. Overnight hygiene jobs: purge, re-point by hash, index, run-health strip.
9. The email importer, in this order: backtest workbook corrected by hand, acceptance threshold, two-stage prompts, the ledger, the needs-you list, the status file, the label; then the mail check at close, the start line, the board lanes.
10. The installer, and a real reinstall on a second machine as the acceptance test.
11. The working-rules loop: preferences text, mistake log, weekly count.

Git deliberately comes after the files and before the jobs: an audit trail shows the wreck afterwards; conventions and scripts prevent it; but once scripts exist in three places, nothing else settles which copy is true.
