# The ops scripts

Four scripts with no model call and no package beyond the standard library. They read what the importer, the sessions and the jobs leave behind.

| Script | What it does | README |
|---|---|---|
| `scripts/mail_state.py` | The mail-state reader: maps a topic folder to its matrix codes and prints counts, lines or JSON for a date range | [README_mail_state.md](README_mail_state.md) |
| `scripts/daily_record.py` | Appends one dated section per day to one file per month | [README_daily_record.md](README_daily_record.md) |
| `scripts/run_check.py` | Judges each scheduled run from the evidence it leaves behind | [README_run_check.md](README_run_check.md) |
| `scripts/start_topics.py` | Prints the topic menu of `/start` | [README_start_topics.md](README_start_topics.md) |

## The one per-machine file

`scripts/ops_paths.py` is the one place the first three scripts read their roots from. It reads `config\paths.json` next to the `scripts` folder; copy `config/paths.example.json` to `config/paths.json` and write your roots. A missing file or key is a stop, never a default.

| Key | What it is | Example |
|---|---|---|
| `projects` | Working folders on the synced drive. `Tools\Workboard\` and `Tools\Email memory\Output\` are looked for under it. | `C:\MemoryDemo\Projects` |
| `library` | A library root: zones with a `_LEDGER.md`, topics with `Input\` and `Output\`. | `C:\MemoryDemo\Library\Development` |
| `documents` | A second library root, for personal documents. | `C:\MemoryDemo\Library\Personal` |
| `local_data` | A folder outside the synced drive: the task register (`Board\Register\`) and the job logs (`Board\logs\`). | `C:\MemoryDemo\local` |
| `machine` | A name for this machine. Not read by these scripts. | `desktop` |

To add a library, add a key to `paths.json`, a line to `LIBRARIES` in `daily_record.py`, and the key to `_ROOT_KEYS` in `run_check.py` if a run's evidence lives there.

In a Linux shell where the Windows folders are mounted as `~/mnt/<folder name>`, `ops_paths.py` translates each root to its mount. On Windows nothing changes.

`config/runs.example.json` is the example for `run_check.py`: one run for each kind of evidence.

`UTC_OFFSET_HOURS` at the top of `mail_state.py` and `run_check.py` must be the importer's value.
