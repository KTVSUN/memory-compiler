# daily_record.py: the daily record

A script, no model. It appends one dated section per day to one file per month: for each session that closed, the chat title, topic and the handoff's current-state paragraph verbatim; documents filed that day from every ledger; decision rows added; tasks done and added; letters placed; the mail the importer judged that day; jobs run; and one line naming any topic whose folder changed with no handoff. Re-running a date replaces that date's section (`ARCHITECTURE.md` section 8).

It runs as a Windows job at 07:05 and writes the section of the previous calendar day.

## Reads

| What | Where | Used for |
|---|---|---|
| Every folder of every library in `LIBRARIES` | the roots of `paths.json` | One walk per library: the files changed that day, the topic folders (a folder holding `Input` or `Output`), the `_LEDGER.md` files, the files under any `Correspondencia` folder, the handoff files (`HANDOFF*.md`). Folders named `_to_delete`, `.git`, `__pycache__`, `node_modules`, `.venv` are skipped. |
| Handoff files | found by the walk | The line `- **Chat:** "<title>"`, the heading `# HANDOFF — <topic>`, the topic folder, and the paragraph under `## CURRENT STATE`. |
| `_LEDGER.md` | found by the walk | The first table with the columns `filename` and `date entered`; the column `summary` is printed when present. |
| `DECISIONS.md` | `<projects>\Tools\` | The first table with the columns `id` and `date`; the column `decision` is printed. |
| `tasks.csv` | `<local_data>\Board\Register\` | Columns `id`, `title`, `done_on`, `created_on`. Rows whose id starts with `INTAKE-` are filing proposals, not tasks, and are left out. |
| The mail ledger | through `mail_state.py` | Threads judged that day and not marked done. |
| `board_morning.log`, `runner1.log` | `<local_data>\Board\logs\` | One JSON object per line, written by the morning job and the evening runner. |
| `run_status.json`, `run_state.json` | `<local_data>\Board\Register\`, `<projects>\Tools\Workboard\` | The last status each scheduled run wrote. |

## Writes

- `<projects>\Tools\Workboard\Daily record\DAILY-YYYYMM.md`: the section `## YYYY-MM-DD` with nine blocks (Sessions closed, Documents filed, Decisions, Tasks, Letters, Mail, Jobs run, Topics changed with no handoff, Notes).
- `daily_record_state.json` next to it: the last date written and how long the walk took.
- It renames any `*.log` over 2 MB in the logs folder to `<name>.<date>.log`.
- One JSON line on standard output, `{"daily_record": {..., "status": "OK"}}`. The launcher that starts the job appends that line to `daily_record.log`, which is what `run_check.py` reads.

It changes nothing else on disk.

## Command line

```
python daily_record.py [--date YYYY-MM-DD] [--dry-run]
```

`--date` defaults to yesterday. `--dry-run` prints the section and writes nothing.
