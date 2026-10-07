# start_topics.py: the topic menu

The topic menu of `/start`, by script, in about one second. It lists topic folders dated by their newest handoff file name, active first, with topics untouched for 30 days behind one line (`+ N dormant, say all`). No file walk (`ARCHITECTURE.md` section 5.1).

It runs in the assistant session's Linux shell, where each connected Windows folder is mounted as `~/mnt/<folder name>`. On Windows itself it finds no `~/mnt` and prints `(not connected: <label>)` for each root.

## Reads

- The folders named in `ROOTS`, two levels deep. A topic is a folder that holds both `Input` and `Output`.
- In each topic, the names of the files in `Output\md\` and `Output\`: the newest `HANDOFF - <anything> YYYYMMDD.md` (an optional letter after the date) dates the topic. With no handoff, the folder's own modification time is used.

It writes nothing.

## No config file

Four constants at the top of the script: `ROOTS` (folder name under `~/mnt`, label in the menu), `SKIP` (folder names never listed), `DORMANT_DAYS` (30) and `RECENT` (the 5 latest topics come first, newest first; the rest follow alphabetically).

## Command line

```
python3 start_topics.py [all]
```

`all` also lists the dormant topics. The output ends with `Which topic? Reply with the number.`
