#!/usr/bin/env python3
"""mail_state.py - the state of the work mail on a topic, read from the Email
memory importer's ledger (ARCHITECTURE.md section 7.6: one reader, one truth).

Reads, never writes:
  AP.EMAIL_OUTPUT / importer / ledger.csv       (importer spec section 7)
  AP.TOPIC_MATRIX                               (importer spec section 3)
  AP.NEEDS_YOU_STATUS                           (importer spec section 8.2)
  AP.EMAIL_OUTPUT / importer / RUN_STATUS.md    (line last_success)

Standard library and ops_paths only. Exit codes: 0 rows printed (zero rows
is still 0), 2 one line on stderr for a missing ledger, a matrix that does not
parse, or a --topic folder that maps to no code. Never a traceback."""

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ops_paths as AP

UTC_OFFSET_HOURS = 0  # the owner's fixed offset from UTC, no daylight saving: the importer's value
LOCAL_TZ = timezone(timedelta(hours=UTC_OFFSET_HOURS))
LEDGER_COLUMNS = ("run_ts,thread_id,last_message_id,first_date,last_date,"
                  "from_latest,subject,delivered_to,topic_stage_a,topic_final,"
                  "confidence,pipeline,demand,demand_reason,knowledge,ny_id,"
                  "expected_event_id,thread_file,attachments_saved,"
                  "attachments_not_read,message_count,language").split(",")
# Spec 3.3 rule 3 says a row also counts when the DATE of its run_ts is in the
# window, "a reply judged on the day after it arrived". Read literally that
# pulls in every thread judged on the 2026-10-02 backlog run (506 rows), so the
# spec's own acceptance checks 1 and 3 cannot pass. Default taken: the run day
# counts only when it is at most this many days after the thread's last_date.
JUDGED_LAG_DAYS = 1
STATE_WORD = {"NEEDS-YOU": "needs the owner",
              "FOLLOW-UP": "waiting on them, the owner wrote last",
              "INFO": "for the record"}


class MailStateError(Exception):
    """One-line failure; the command line prints it on stderr and exits 2."""


def _now():
    return datetime.now(LOCAL_TZ)


def _day(value):
    s = str(value).strip()[:10]
    try:
        date.fromisoformat(s)
    except ValueError:
        raise MailStateError(f"bad date: {value}")
    return s


def _lag_days(last_date, run_ts):
    try:
        return (date.fromisoformat(run_ts[:10]) - date.fromisoformat(last_date[:10])).days
    except ValueError:
        return 10 ** 6


def _norm_folder(p):
    return str(p).strip().replace("/", "\\").rstrip("\\").lower()


# -- topic_matrix.md (grammar of importer spec section 3) ------------------

def parse_matrix(path):
    """list of dicts: code, project, root, path_override, folder.
    The grammar is the importer's own (email_importer.parse_matrix), minus the
    check that destination folders exist."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise MailStateError(f"topic_matrix.md not readable: {e}")
    topics, seen = [], set()
    project, root = None, None

    def bad(n, line):
        raise MailStateError(f"topic_matrix.md line {n}: {line}")

    for n, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("Owner:") or s.startswith("Aliases:"):
            continue
        if s.startswith("## "):
            m = re.match(r"^## ([A-Z][A-Z0-9-]*) = (.+)$", s)
            if not m:
                bad(n, s)
            project, root = m.group(1), None
            continue
        if s.startswith("# "):
            continue
        if s.startswith("Root:"):
            if project is None or project == "NOBUCKET" or root is not None:
                bad(n, s)
            root = s[len("Root:"):].strip()
            if not re.match(r"^[A-Za-z]:\\", root):
                bad(n, s)
            continue
        if s.startswith("- "):
            if project is None:
                bad(n, s)
            m = re.match(r"^- (\S(?:.*?\S)?) — (.+)$", s)
            if not m:
                bad(n, s)
            code, rest = m.group(1), m.group(2)
            override = ""
            for tok in [p.strip() for p in rest.split(" | ")][1:]:
                if tok.startswith("path="):
                    override = tok[len("path="):].strip()
                elif not tok.startswith("pipeline="):
                    bad(n, s)
            if code in seen:
                bad(n, s)
            seen.add(code)
            if project == "NOBUCKET":
                if "/" in code or not re.match(r"^[A-Z][A-Z-]*$", code):
                    bad(n, s)
                topics.append({"code": code, "project": project, "root": "",
                               "path_override": "", "folder": ""})
                continue
            if root is None or (code != project and not code.startswith(project + "/")):
                bad(n, s)
            if override:
                folder = override
            else:
                segs = code.split("/")[1:]
                if segs == ["ROOT"]:
                    segs = []
                folder = "\\".join([root.rstrip("\\")] + segs)
            topics.append({"code": code, "project": project, "root": root,
                           "path_override": override, "folder": folder})
            continue
        bad(n, s)
    if not topics:
        raise MailStateError("topic_matrix.md line 0: no codes found")
    return topics


def _folder_to_code(topics, folder):
    want = _norm_folder(folder)
    for t in topics:
        if t["folder"] and _norm_folder(t["folder"]) == want:
            return t["code"]
    raise MailStateError(f"no topic code maps to {folder}")


def _resolve_codes(topics, topic_args, project_args):
    """List of code prefixes to match, or None meaning every Root: block."""
    wanted = []
    for arg in topic_args or []:
        if ":" in arg or "\\" in arg:
            wanted.append(_folder_to_code(topics, arg))
        else:
            wanted.append(arg.strip().rstrip("/"))
    for proj in project_args or []:
        codes = [t["code"] for t in topics if t["project"] == proj and t["root"]]
        if not codes:
            raise MailStateError(f"no topic code maps to project {proj}")
        wanted.extend(codes)
    if wanted:
        return wanted
    return [t["code"] for t in topics if t["root"]]


def _code_matches(code, wanted):
    return any(code == w or code.startswith(w + "/") for w in wanted)


# -- ledger, status file, heartbeat ----------------------------------------

def read_ledger(path):
    p = Path(path)
    if not p.exists():
        raise MailStateError(f"ledger not found at {p}")
    with open(p, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        if rd.fieldnames != LEDGER_COLUMNS:
            raise MailStateError("ledger columns differ from importer spec section 7: "
                                 + ",".join(rd.fieldnames or []))
        return list(rd)


def read_status(path):
    rows = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        pass
    return rows


def _status_for(status_rows, row, until):
    """(hidden, action, ts) after replaying the rows of this thread's ny_id and
    thread_id in file order. done hides, reopen cancels, snooze hides until its
    date, correct changes nothing here."""
    keys = {row.get("ny_id", ""), row.get("thread_id", "")} - {""}
    done_ts, snooze_until, last_action = None, "", ""
    for s in status_rows:
        if (s.get("item") or "").strip() not in keys:
            continue
        act = (s.get("action") or "").strip().lower()
        if act == "done":
            done_ts, snooze_until, last_action = s.get("ts", ""), "", "done"
        elif act == "reopen":
            done_ts, snooze_until, last_action = None, "", "reopen"
        elif act == "snooze":
            snooze_until, last_action = (s.get("value") or "").strip(), "snooze"
        elif act == "correct":
            last_action = last_action or "correct"
    if done_ts is not None:
        return "done", "done", done_ts
    if snooze_until and snooze_until > until:
        return "snoozed", "snooze", snooze_until
    return "", last_action, ""


def last_success_line():
    """The value of last_success exactly as written, or ''."""
    try:
        text = (AP.EMAIL_OUTPUT / "importer" / "RUN_STATUS.md").read_text(
            encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    m = re.search(r"^last_success:\s*(.+?)\s*$", text, re.M)
    return m.group(1) if m else ""


def importer_is_stale(value):
    m = re.match(r"(\d{4}-\d\d-\d\d) (\d\d):(\d\d)", value or "")
    if not m:
        return False
    try:
        ts = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}",
                               "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    except ValueError:
        return False
    return _now() - ts > timedelta(hours=24)


# -- the importable function (spec 3.5) ------------------------------------

def mail_rows(since, until, topics=None, projects=None, include_done=False):
    since, until = _day(since), _day(until)
    matrix = parse_matrix(AP.TOPIC_MATRIX)
    wanted = _resolve_codes(matrix, topics, projects)
    ledger = read_ledger(AP.EMAIL_OUTPUT / "importer" / "ledger.csv")
    status_rows = read_status(AP.NEEDS_YOU_STATUS)

    latest = {}
    for r in ledger:                         # rule 1: last row per thread wins
        latest[r["thread_id"]] = r
    out = []
    for r in latest.values():
        if r["demand"] in ("NOISE", "PIPELINE"):                    # rule 2
            continue
        if not _code_matches(r["topic_final"], wanted):
            continue
        if not (since <= r["last_date"][:10] <= until
                or (since <= r["run_ts"][:10] <= until
                    and _lag_days(r["last_date"], r["run_ts"]) <= JUDGED_LAG_DAYS)):
            continue                                                # rule 3
        hidden, action, ts = _status_for(status_rows, r, until)     # rule 4
        row = dict(r)
        row["status_action"] = action
        if hidden and not include_done:      # done and snoozed hide the same way
            continue
        if hidden == "done":
            row["state"] = f"done by the owner on {ts}"
        else:
            row["state"] = STATE_WORD.get(r["demand"], r["demand"].lower())  # rule 5
        out.append(row)
    out.sort(key=lambda x: (x["last_date"], x["run_ts"]), reverse=True)    # rule 6
    return out


# -- output ------------------------------------------------------------------

def _one(text):
    return " ".join(str(text or "").split())


def render(rows, fmt, since, until, topic_label, ledger_last_run):
    if fmt == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2)
    if fmt == "counts":
        need = sum(1 for r in rows if r["state"] == STATE_WORD["NEEDS-YOU"])
        wait = sum(1 for r in rows if r["state"] == STATE_WORD["FOLLOW-UP"])
        rec = sum(1 for r in rows if r["state"] == STATE_WORD["INFO"])
        new = sum(1 for r in rows if r["run_ts"][:10] >= since)
        return f"need={need} waiting={wait} record={rec} new_since={new}"
    n = len(rows)
    head = (f"Mail state · topics: {topic_label} · {since} to {until} · "
            f"{n} thread{'' if n == 1 else 's'} · ledger last run {ledger_last_run}")
    lines = [head]
    ls = last_success_line()
    if importer_is_stale(ls):
        lines.append(f"Importer last success {ls}, more than 24 hours ago.")
    if fmt == "md":
        lines = [head] + lines[1:] + [""]
        lines.append("| Date | Topic | Subject | Last from | State | What | Thread file |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in rows:
            cells = [r["last_date"], r["topic_final"], _one(r["subject"]),
                     r["from_latest"], r["state"], _one(r["demand_reason"]),
                     r["thread_file"] or "-"]
            lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
        return "\n".join(lines)
    for r in rows:
        lines.append(" | ".join([
            r["last_date"], r["topic_final"], f'"{_one(r["subject"])}"',
            f'last from {r["from_latest"]}', r["state"],
            _one(r["demand_reason"]), f'{r["message_count"]} messages',
            r["thread_file"] or "-"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Mail state from the importer ledger")
    ap.add_argument("--topic", action="append", default=[],
                    help="topic code or topic folder (full Windows path); repeatable")
    ap.add_argument("--project", action="append", default=[],
                    help="project code as written in topic_matrix.md (DEV in the example); repeatable")
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="")
    ap.add_argument("--format", choices=("lines", "md", "json", "counts"), default="lines")
    ap.add_argument("--include-done", action="store_true")
    a = ap.parse_args()
    try:
        until = _day(a.until) if a.until else _now().date().isoformat()
        since = _day(a.since) if a.since else (_now().date() - timedelta(days=7)).isoformat()
        rows = mail_rows(since, until, a.topic, a.project, a.include_done)
        ledger = read_ledger(AP.EMAIL_OUTPUT / "importer" / "ledger.csv")
        last_run = ledger[-1]["run_ts"] if ledger else "-"
        matrix = parse_matrix(AP.TOPIC_MATRIX)
        parts = _resolve_codes(matrix, a.topic, []) if a.topic else []
        parts += list(a.project)
        label = ", ".join(parts) if parts else "all"
    except MailStateError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(render(rows, a.format, since, until, label, last_run))
    sys.exit(0)


if __name__ == "__main__":
    main()
