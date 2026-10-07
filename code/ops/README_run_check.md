# run_check.py: the run checker

The board header carries one circle per scheduled run, filled by this script reading a `runs.json` of expectations against the evidence each run leaves behind: a log line, a report file, or a dated stamp the run writes as its last step. Green is ran; red is failed or missing; grey is "the computer was off at that slot", judged from the board server's heartbeat log. No session's own report is ever evidence (`ARCHITECTURE.md` section 8).

## Reads

- `config\runs.json` next to the `scripts` folder (or `--register <path>`). `config/runs.example.json` has one run for each kind of evidence.
- The evidence files each run names. A path starts with a root key of `paths.json` in braces (`{projects}`, `{library}`, `{local_data}`) and may hold the date of the slot or of the day before: `{slot:%Y%m%d}`, `{prev:%Y-%m-%d}`.
- `<local_data>\Board\logs\heartbeat.log`: one ISO timestamp per line, written every few minutes by whatever stays running on the PC. A slot with no heartbeat near it means the computer was off.
- `<projects>\Tools\Workboard\run_stamps\<run id>\YYYYMMDD.json` for runs of type `stamp`: `{"status": "ok", "produced": ["<path>", ...]}`.

## A run in `runs.json`

| Field | Meaning |
|---|---|
| `id`, `label` | The name in the output and under the circle. |
| `needs_machine` | `true` when the run cannot happen with the PC off. Only then can its state be `off`. |
| `cadence` | `{"kind": "daily", "days": [0..6], "time": "HH:MM"}` (0 is Monday), `{"kind": "weekly", "weekday": n, "time": ...}` or `{"kind": "monthly", "day": n, "time": ...}`. |
| `settle_min` | Minutes after the slot before the run is judged. |
| `probe` | Where the evidence is. |
| `fail_probe` | Optional second place that can turn "nothing found" into "failed". |

| Probe `type` | Evidence |
|---|---|
| `jsonlines` | A line of a log holding `{"<key>": {"<date_field>": ..., "<ok_field>": "<ok_value>"}}` dated on the slot's day. |
| `jsonlines_steps` | A line holding one block per step in `steps`, each with `ok_field` equal to `ok_value`. |
| `json_key` | An object inside one JSON file, found by a dotted `key`, optionally matched on `match_field`. |
| `md_section` | A heading in a Markdown file. |
| `files` | Every path exists and is at least `min_bytes`. |
| `stamp` | The stamp file of the slot's day, or of one of the `window_days` after it. |

## States

`ok`, `failed`, `missing` (no evidence, and the PC was on or is not needed), `off` (no evidence and no heartbeat), `pending` (no slot is due yet), `error` (the entry itself could not be judged).

## Writes

`<projects>\Tools\Workboard\run_check.json`, unless `--no-write`. The board renderer, which is not in this repository, calls `evaluate()` and `strip_html()` to draw the strip.

## Command line

```
python run_check.py [--json] [--now YYYY-MM-DDTHH:MM:SS] [--no-write] [--register <runs.json>]
```

Prints one line per run (state, id, slot, evidence) and a `SUMMARY:` line. A probe that raises becomes that run's state `error`; the script itself does not fail.
