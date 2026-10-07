# Code

The scripts that `ARCHITECTURE.md` describes in sections 5.1, 7 and 8, as they run on the author's PC, with everything about the owner taken out: addresses, Gmail label names, project codes, folder paths, the two model prompts, the time zone and the names of people and companies. What was taken out now sits in example files you copy and fill in.

| Folder | What it is | Described in |
|---|---|---|
| [`importer/`](importer/) | The hourly email importer: one Python file, a config file, the topic matrix and two prompt files | `ARCHITECTURE.md` section 7 |
| [`ops/`](ops/) | Four small scripts with no model call: the mail-state reader, the daily record, the run checker and the topic menu | sections 7.6, 8 and 5.1 |

## What this is, and what it is not

- It is a copy made by a script from the live files, by exact replacement of listed text. A second script then searches every file for the owner's addresses, labels, codes, paths and names, and for anything shaped like an email address, a Windows path with a drive letter, a host name or an API key. The publish step refuses to push when that search finds something.
- It is not a product. Nothing here installs itself. The author's installer, the hidden launchers for Task Scheduler and the task board are not included; each README gives the commands they wrap.
- The importer runs on Windows only (absolute Windows paths in the matrix, Task Scheduler for the hourly run). The four `ops` scripts also run in a Linux shell where the Windows folders are mounted under `~/mnt/<folder name>`, which is how an assistant session reaches them.
- The example values are invented: the mailbox `owner@example.com`, folders under `C:\MemoryDemo\`, and the project `DEV` with the pipeline `escrow-extract`, which `templates/NEEDS_YOU_EXAMPLE.md` already uses.

## Where to start reading

1. `importer/topic_matrix.example.md`: the destination list.
2. `importer/prompts/`: the two prompts. The judgement is there, not in the code.
3. `importer/email_importer.py`: `Importer.commit` is the write order of `ARCHITECTURE.md` section 7.4.
4. `ops/scripts/mail_state.py`: the one reader every other reader of mail state goes through.

## One value to set in three files

The live system runs in one fixed time zone with no daylight saving. The offset is a constant, `UTC_OFFSET_HOURS`, at the top of `importer/email_importer.py`, `ops/scripts/mail_state.py` and `ops/scripts/run_check.py`. It is `0` here. Set the same number in the three files.
