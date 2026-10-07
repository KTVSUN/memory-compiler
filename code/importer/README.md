# The email importer

A Python program that runs hidden every hour on one Windows PC. It reads the owner's mailbox through the Gmail API with its own OAuth client, grouped by thread, with a 48-hour overlap so a missed hour loses nothing. It asks a model two questions per thread (which topic folder, and what the thread asks of the owner), saves the thread and its attachments into that folder's `Input\Emails\`, appends a knowledge note to the project log when there is one, and rewrites one cross-project needs-you list. The only change it makes in the mailbox is one label. `ARCHITECTURE.md` section 7 is the full description.

## Files

| File | What it is |
|---|---|
| `email_importer.py` | The program. Standard library plus the packages in `requirements.txt`. |
| `config.example.json` | Everything that is not a destination. Copy to `config.json` next to the program. |
| `topic_matrix.example.md` | The destination list. Copy to `topic_matrix.md` in the folder `program_dir` names. |
| `prompts/stage_a_system.example.txt` | System prompt of Stage A, sorting. Copy to `prompts\stage_a_system.txt` under `program_dir`. |
| `prompts/stage_b_system.example.txt` | System prompt of Stage B, judgement. Copy to `prompts\stage_b_system.txt` under `program_dir`. |
| `requirements.txt` | The package versions in use. |

## What it reads

- The mailbox, through the Gmail API: every message after the last successful run minus `overlap_hours`, minus what `gmail_query_exclusions` leaves out (the owner's labels for noise and for mail other jobs read).
- `config.json`, `topic_matrix.md` and the two prompt files. A parse error in the matrix, a destination folder that does not exist or a missing prompt file stops the run with one line saying which.
- `NEEDS_YOU_status.csv` (`status_path`): the way back. Columns `ts, item, action, value, chat, note`; actions `done`, `snooze <date>`, `correct <topic code>`, `reopen`; last row per item wins. The program only reads it, except for one case: a thread whose label the owner removed by hand in Gmail gets a `done` row.
- In `secrets_dir`, outside any synced drive: `credentials.json` (the OAuth client), `token.json` (written by `--auth`), `anthropic_key.txt` (the API key, one line).
- Existing `manifest*.csv` files in a destination's `Input\Emails\`, so nothing is listed twice.

## What it writes, per thread, in this order

1. Attachments, original bytes, date-prefixed, in `<topic>\Input\Emails\Emails\`. Inline images under 20 kB are skipped.
2. The thread file `YYYYMMDD_<subject-slug>_<thread id>.md` in the same folder: subject, date range, participants, saved attachments, the verdict line, then one section per message with the plain-text body. Regenerated whole when the thread gains a message.
3. One row per message in `<topic>\Input\Emails\manifest_emails.csv`, append-only.
4. An expected-event row in `expected_events.csv` when the owner asked a counterparty for something a pipeline consumes.
5. One row in `ledger.csv`, append-only: the only file needed to answer "what happened to thread X".
6. A knowledge note queued for the project's `LOG.md` (`project_logs`), written in one write per log at the end of the run and only when that file has been quiet for `log_md_quiet_minutes`.
7. Only then are the message ids marked processed in `state.sqlite`. A failure at any step leaves the thread unprocessed and writes a row with the error text in `retry.csv`.

Pipeline threads get a ledger row only. Bucket threads (`BANK-PERSONAL`, `GOVT`, `OTHER-WORK`) are judged on headers and snippet, get a ledger row and reach the needs-you list with no file. Noise gets a ledger row.

At the end of every run it rewrites `NEEDS_YOU.md` (`needs_you_path`) and `RUN_STATUS.md` (the heartbeat, with a `sizes:` line), and adds or removes the Gmail label `gmail_label_name` so that it mirrors the first table of `NEEDS_YOU.md`. `run.log` and `state.sqlite` are in `secrets_dir`; the state is a cache that `--rebuild-state` rebuilds from the ledger and the manifests.

## Setting it up

1. Python 3.11 or newer on Windows, then `python -m pip install -r requirements.txt`.
2. In Google Cloud: a project with the Gmail API enabled and an OAuth client of type "Desktop app". Save its JSON as `credentials.json` in the folder you will name in `secrets_dir`. Publish the consent screen: an app left in testing loses its token after seven days. The program asks for the scope `gmail.modify`, which it needs to add and remove its one label.
3. An Anthropic API key, saved as one line in `anthropic_key.txt` in the same folder.
4. Copy the four example files as the table above says and edit them: your mailbox and aliases, your folders, your topics, and your own rules in the two prompts. Every destination folder of the matrix must exist.
5. `python email_importer.py --selftest` lists every code with its folder and stops before Gmail while `token.json` is missing.
6. `python email_importer.py --write-hostname` writes this PC's name into `config.json`. The program exits silently on any other machine.
7. `python email_importer.py --auth` opens the browser for the Google sign-in and writes `token.json`.
8. Try it without writing anything: `python email_importer.py --replay 2026-01-01 2026-01-08 --dry-run --out replay.csv` judges a week of mail and writes only that CSV.
9. Schedule it hourly and hidden, with `pythonw.exe` so no window opens:

```
schtasks /Create /F /SC HOURLY /MO 1 /ST 06:05 /TN "Email memory importer" /TR "\"C:\MemoryDemo\python\pythonw.exe\" \"C:\MemoryDemo\Projects\Tools\Email memory\Output\importer\email_importer.py\"" /RL LIMITED
```

## Command line

`(no arguments)` the hourly run · `--now` the same · `--then-open` open `NEEDS_YOU.md` at the end · `--auth` Google sign-in · `--write-hostname` · `--selftest` · `--rebuild-state` · `--replay FROM TO --dry-run --out <csv>` judge a date range from scratch, write only the CSV · `--dry-run` with a normal run: judge everything, write only `--out` and `run.log` · `--ledger <csv>` with `--dry-run`: read this copy of the ledger · `--config <path>` another config file.

## `config.json`

Unknown keys and missing keys are both an error at start.

| Key | Meaning |
|---|---|
| `importer_pc` | Host name of the one PC allowed to run it. Written by `--write-hostname`; leave it empty in a file you share. |
| `mailbox`, `aliases` | The owner's address and the alias addresses delivered to the same mailbox. A message from one of them counts as the owner's. |
| `gmail_query_exclusions` | Appended to every Gmail search. |
| `start_date`, `overlap_hours` | Where the first run starts; how far each later run looks back. |
| `secrets_dir`, `program_dir`, `needs_you_path`, `status_path` | Absolute Windows paths. |
| `anthropic_model` | The model both stages call. |
| `stage_a_batch_size`, `stage_a_snippet_chars` | Stage A: threads per call, characters of the latest message shown. |
| `stage_b_body_chars_per_message`, `stage_b_attachment_chars_each`, `stage_b_total_chars` | Stage B: the caps on what one call is shown. |
| `attachment_max_mb`, `zip_depth` | Larger attachments are listed, not saved; ZIP files are opened one level. |
| `stale_days` | Kept for compatibility. Nothing on the needs-you list goes stale. |
| `log_md_quiet_minutes` | How long a `LOG.md` must have been untouched before a note is appended. |
| `gmail_label_enabled`, `gmail_label_name` | The one label. |
| `pipelines` | Name and one-line description of each job that reads its own mail. The description is shown to the model. |
| `conditional_pipelines` | Pipelines whose matrix code is a pipeline code only when Stage B says the thread is the item that pipeline consumes; other mail on that code is filed normally. |
| `project_logs` | Project code to the path of its `LOG.md`. |
| `project_log_titles` | Optional project code to the title of a `LOG.md` the program creates; the folder name is used otherwise. |

## `topic_matrix.md`

The grammar is strict. Anything else on a line stops the run with the line number.

```
# <free title line>                                    (ignored)
## <PROJECTCODE> = <free description>                  (starts a project block)
Root: <absolute Windows path>                          (once per block, except the NOBUCKET block)
- <CODE> — <one-line meaning> [| pipeline=<name>] [| path=<absolute Windows path>]
<blank lines and lines starting with "Owner:" or "Aliases:" are ignored>
```

- `<CODE>` is `PROJECTCODE/Segment/Segment` using the exact folder names, or `PROJECTCODE/ROOT`, or the bare project code, or a bucket code inside the `## NOBUCKET` block, which has no `Root:`. The code `NOISE` must exist.
- The destination folder is `Root` plus the segments after the project code, unless `path=` gives another folder.
- `PROJECTCODE/ROOT` files into `Root\Knowledge stack\Input\Emails\`.
- `pipeline=` marks a code another job reads: a ledger row only, no file, no needs-you line, no knowledge note.

## The two prompts

Stage A must keep the placeholders `{MATRIX}` (replaced by the matrix lines) and `{CORRECTIONS}` (the owner's last fifty corrections as `sender | subject | correct code`). Stage B must keep `{TOPIC}` and `{PIPELINES}`. The answer formats at the end of each prompt are what the program parses: leave them as they are.

The example prompts are the live ones with the owner's own rules replaced by a few invented rules of the same kinds: what is noise, what an alias address implies, which sender goes to which code. The live Stage A prompt holds a dozen such rules, learned from a 30-day backtest of real threads corrected by hand. Yours will be different; a backtest is how you find them (`--replay`).
