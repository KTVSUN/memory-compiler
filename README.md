# A working memory for an AI assistant that runs a small business

This repository documents, and partly ships, the system one person uses to run several small businesses with Claude as the day-to-day assistant: project folders on a synced drive, a Windows PC that works overnight, and an hourly email importer. It has been in daily use since mid 2026 and is rebuilt from scratch when a PC is replaced.

It is written for people who have the same problem: an assistant that is useful inside one conversation and forgets everything between two of them.

## The problem

A conversation with an AI assistant is a good place to work and a bad place to store anything. Facts drift, corrections are lost, the assistant reasserts a figure you fixed two weeks ago, and nothing that happened in a chat is visible to the next one. The usual answer is more memory: bigger context, summaries of past chats, a vector store. We went the other way.

## The idea, in five sentences

1. **Files own the truth; the chat owns nothing.** Documents live in a library of folders, decisions in a decision log, tasks in a register, defects in a defects file. If a fact is not in a file, it does not exist.
2. **Each fact has exactly one owner.** A client's contract terms live in one workbook, a lot price in another, an email's state in the mail ledger. Everything else points at the owner instead of copying the value.
3. **What a session reads at start is small and fixed; archives grow without limit and are only searched.** A session opens on a two-sentence state and a short menu, never on a report.
4. **Humans decide, machines propose.** No job ever creates a task, files a document or changes a rule on its own. It writes a proposal row and a person ticks it.
5. **If the assistant reads it and it is not a project document, it lives in one git repository**: skills, scheduled prompts, scripts, the operating manual and the one-click installer. A machine is rebuilt by cloning that repository and double-clicking one file.

## What runs where

| Layer | Holds | Examples |
|---|---|---|
| Canonical truth | current facts, editable, one owner each | `DECISIONS.md` (why, not only what), `CONTEXT.md` (glossary), `LOG.md` (dated facts), a `_LEDGER.md` per library zone, the task register |
| History | what happened, when | one handoff per topic per session (deltas only), a daily record written by a script, a chat archive |
| Evidence | unaltered sources | the document library, email threads saved verbatim with their attachments |
| Generated | disposable, rebuilt nightly | the task board, a search index, the "needs you" mail list, a run-health strip |
| Tooling | everything the assistant reads to do its job | the `ops` git repository: skills, prompts, scripts, manual, installer |

## A day

- **07:00** the PC wakes itself; the board recomputes, mirrors tasks to a phone app both ways, and renders. **07:05** a script appends yesterday's section to the daily record (sessions closed, documents filed, decisions taken, tasks done, jobs run), without any model.
- **Every hour** the email importer closes the blind spot the rest of the system had: a memory built only from work sessions misses the half of a small business that happens by email (a supplier's revised quote, a client agreeing to a date, the accountant's answer, the owner's own reply committing to something), so sessions planned around superseded quotes and chased replies that had already arrived. The importer reads new mail, asks a model two questions per thread (which topic folder, and what the thread asks of the owner), saves the thread and attachments into that folder's `Input\Emails\`, appends a knowledge note to the project log when there is one, and rewrites one cross-project **needs-you** list. The only change it makes in the mailbox is one label.
- **During the day** the owner works in sessions opened on a project folder. `/start` requests the folders in one window and prints a menu: kickoff ready, open work, waiting on someone, plan, blocking items, mail on this topic, something new. Decisions are written to the log the turn they are taken. `/handoff` closes: every open item of the previous handoff reappears as open, done with proof, or dropped with a reason; every "waiting for a reply" line is checked against the mail ledger before it is written.
- **18:00 to 22:00** jobs regenerate manifests, purge the quarantine folder, propose filing for dropped-in documents, re-point ledger lines whose file was moved by hand (by content hash), rebuild the index, and put the PC to sleep. A header strip on the board shows one circle per job, filled only from evidence the job leaves behind, never from a session's own report.

## What is in this repository

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)**: the full description. Layers, the library and filing rules, the session bookends, the task layer, the email layer, the unattended jobs, the repository and reinstall, and what we abandoned since the first version and why.
- **[`templates/`](templates/)**: the handoff template (8 KB cap, supersedes diff), the decision log header, the project log format, the needs-you list format.
- **[`code/`](code/)**: the scripts themselves, as they run, with everything about the owner taken out: the email importer with an example config, an example topic matrix and example prompts, and four scripts with no model call (the mail-state reader, the daily record, the run checker, the topic menu). Each has a README saying what it reads and writes.
- **[`legacy/`](legacy/)**: the first version of this repository (August 2026): a close-time validator script, `memory_check.py`, with its templates and a worked example. It still works on its own. We stopped using it; `ARCHITECTURE.md` section 10 says why.

No business data, no personal data, no credentials. The code in [`code/`](code/) is a copy made by a script from the live files: addresses, Gmail label names, project codes, folder paths, the two prompts and every name are replaced by invented examples, and a second script searches every file for them, and for anything shaped like an email address, a Windows path, a host name or an API key, before each push. The publish step refuses to push when that search finds something. The installer, the task board and the skills are described in `ARCHITECTURE.md`, not shipped.

## Status and license

Reference documentation of a live, single-operator system, genericised for sharing. Not a product. MIT, see [`LICENSE`](LICENSE).
