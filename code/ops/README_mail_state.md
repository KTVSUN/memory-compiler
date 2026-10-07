# mail_state.py: the mail-state reader

Every reader of mail state goes through this script: the `/start` line, the mail check of `/handoff`, the daily record, the weekly report. It maps a topic folder to its matrix codes and prints counts, lines or JSON for a date range. One reader, one truth (`ARCHITECTURE.md` section 7.6).

## Reads, never writes

| File | Where | What for |
|---|---|---|
| `ledger.csv` | `<projects>\Tools\Email memory\Output\importer\` | One row per thread verdict. The last row per thread wins. |
| `topic_matrix.md` | same folder | To turn a topic folder or a project code into matrix codes. |
| `NEEDS_YOU_status.csv` | `<projects>\Tools\Email memory\Output\` | `done` hides a thread, `reopen` cancels that, `snooze <date>` hides it until the date. |
| `RUN_STATUS.md` | importer folder | The line `last_success`, to warn when the importer has not succeeded for 24 hours. |

## Rules

1. The last ledger row per thread wins.
2. Rows with the demand `NOISE` or `PIPELINE` are left out.
3. A thread is in the window when its last message is, or when it was judged in the window at most one day after its last message.
4. Threads marked done or snoozed are left out unless `--include-done`.
5. The state words are `needs the owner`, `waiting on them, the owner wrote last` and `for the record`.
6. Newest first.

## Command line

```
python mail_state.py [--topic <code or topic folder>]... [--project <code>]... [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                     [--format lines|md|json|counts] [--include-done]
```

Without `--since` the window is the last seven days. `--format counts` prints one line, `need=1 waiting=0 record=0 new_since=1`.

Exit code 0 when rows were printed (zero rows is still 0). Exit code 2 with one line on stderr for a missing ledger, a matrix that does not parse, or a `--topic` folder that maps to no code. Never a traceback.

Other scripts import `mail_rows(since, until, topics=None, projects=None, include_done=False)`.
