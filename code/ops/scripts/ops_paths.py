#!/usr/bin/env python3
"""ops_paths.py - the one place these scripts read their roots from. Reads
config\\paths.json next to the scripts folder; a test points OPS_PATHS_JSON at
a temporary copy. No other environment variable and no hard-coded root exists
anywhere in the scripts.

paths.json is the one per-machine file (drive letters and roots). Everything
below the roots is the same on every machine and is written once, here."""

import json
import os
from pathlib import Path, PureWindowsPath

_HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = _HERE.parent / "config" / "paths.json"

REQUIRED = ("projects", "library", "documents", "local_data")


def load(config_path=None):
    """dict of key -> Path. Raises FileNotFoundError / KeyError loudly:
    a missing config is a stop, never a default."""
    p = Path(config_path or os.environ.get("OPS_PATHS_JSON") or DEFAULT_CONFIG)
    if not p.exists():
        raise FileNotFoundError(f"paths.json not found: {p} - copy config\\paths.example.json to config\\paths.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise KeyError(f"paths.json {p} lacks keys: {', '.join(missing)}")
    out = {k: _resolve(v) for k, v in data.items() if isinstance(v, str) and k != "machine"}
    out["machine"] = data.get("machine", "")
    return out


# A session's shell runs on Linux, where the connected Windows folders appear
# as $HOME/mnt/<folder name>, the folder's own last path segment. Path() on a
# Windows string there yields a path that simply does not exist, and every
# caller then behaves as though its files were empty. Translate on POSIX; on
# Windows nothing changes. A root with no mount keeps its Windows path, and the
# script that needs it fails on the missing file.
def _resolve(value):
    if os.name == "nt":
        return Path(value)
    mount = Path.home() / "mnt" / PureWindowsPath(value).name
    return mount if mount.exists() else Path(value)


P = load()

PROJECTS_DIR = P["projects"]              # working folders, on the synced drive
LOCAL_DATA = P["local_data"]              # machine-local, outside the synced drive
BOARD_DIR = LOCAL_DATA / "Board"          # the task register and the job logs
REGISTER = BOARD_DIR / "Register"
LOG_DIR = BOARD_DIR / "logs"

# The daily record and the run evidence live on the synced drive because the
# owner reads them from either machine; they are written once a day.
WORKBOARD = PROJECTS_DIR / "Tools" / "Workboard"
RUN_STATE = WORKBOARD / "run_state.json"
RECORD_DIR = WORKBOARD / "Daily record"
DECISIONS = PROJECTS_DIR / "Tools" / "DECISIONS.md"

# The email importer's output: the same folders as program_dir, needs_you_path
# and status_path in the importer's config.json.
EMAIL_OUTPUT = PROJECTS_DIR / "Tools" / "Email memory" / "Output"
NEEDS_YOU = EMAIL_OUTPUT / "NEEDS_YOU.md"
NEEDS_YOU_STATUS = EMAIL_OUTPUT / "NEEDS_YOU_status.csv"
TOPIC_MATRIX = EMAIL_OUTPUT / "importer" / "topic_matrix.md"
