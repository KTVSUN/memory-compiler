#!/usr/bin/env python3
"""daily_record.py - the permanent day-by-day record. Runs as a
Windows job at 07:05 and writes one dated section for the PREVIOUS calendar
day. No model writes it and it changes nothing else on disk. Re-running the
same date REPLACES that date's section instead of appending a second one.

Reads the append-only logs for board-morning and Runner 1, never the
`morning` block of run_status.json: the morning job overwrites that block
at 07:00, five minutes before this job runs (spec section 3.3)."""

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ops_paths as AP
import mail_state

PRUNE = {"_to_delete", "to_delete", "to delete", "__pycache__", ".git",
         "node_modules", ".venv"}
MD_FOLDER = "md"
# One line per library: (label printed in the record, root from paths.json).
LIBRARIES = [("Projects", AP.PROJECTS_DIR), ("Library", AP.P["library"]),
             ("Personal", AP.P["documents"])]
DATE8 = re.compile(r"(20\d{6})")
DATEISO = re.compile(r"(20\d\d-\d\d-\d\d)")
NOTES = []


def note(section, msg):
    NOTES.append(f"- {section}: {str(msg)[:300]}")


def cut(text, n):
    t = " ".join(str(text).split())
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0] + "..."


def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def json_lines(p, section):
    bad = 0
    try:
        lines = Path(p).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            yield json.loads(ln)
        except ValueError:
            bad += 1
    if bad:
        note(section, f"{bad} unreadable lines in {Path(p).name}")


def file_day(p, st_date):
    """Day a dated artefact belongs to: the first date in its NAME, else its
    modified date."""
    m = DATEISO.search(p.name) or DATE8.search(p.name)
    if m:
        s = m.group(1)
        try:
            return (date.fromisoformat(s) if "-" in s
                    else date(int(s[:4]), int(s[4:6]), int(s[6:8]))).isoformat()
        except ValueError:
            pass
    return st_date


# -- one walk per library -------------------------------------------------

def scan(root):
    """One walk per library, os.scandir throughout: on Windows the directory
    entry already carries the modified time, so entry.stat() costs no extra
    syscall and a cloud-only OneDrive file is not hydrated."""
    files, topics, ledgers, letters, handoffs = [], [], [], [], []
    if not root.exists():
        return files, topics, ledgers, letters, handoffs
    stack = [(str(root), False)]
    while stack:
        dirpath, in_corr = stack.pop()
        try:
            entries = list(os.scandir(dirpath))
        except OSError as e:
            note("Walk", f"{dirpath}: {e}")
            continue
        names = set()
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                names.add(e.name.lower())
                if e.name.lower() not in PRUNE:
                    stack.append((e.path, in_corr or e.name.lower() == "correspondencia"))
                continue
            if e.name.endswith(".tmp"):
                continue
            try:
                day = datetime.fromtimestamp(e.stat().st_mtime).date().isoformat()
            except OSError:
                continue
            p = Path(e.path)
            files.append((p, day))
            fl = e.name.lower()
            if e.name == "_LEDGER.md":
                ledgers.append(p)
            if in_corr:
                letters.append((p, day))
            if (fl.startswith("handoff") and fl.endswith(".md")
                    and not fl.startswith("handoff_template")):
                handoffs.append((p, day))
        if "input" in names or "output" in names:
            topics.append(Path(dirpath))
    return files, topics, ledgers, letters, handoffs


# -- markdown table parser ------------------------------------------------

def table_rows(path, need):
    """Rows of the first markdown table whose header contains every name in
    `need`. Case-insensitive. Returns (header_lowercased, rows)."""
    header, rows = None, []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        note("table", f"{path}: {e}")
        return None, rows
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            if header is not None and s:
                break
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        low = [c.lower() for c in cells]
        if header is None:
            if all(n in low for n in need):
                header = low
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    return header, rows


def cell(header, row, name):
    try:
        return row[header.index(name)]
    except (ValueError, IndexError):
        return ""


# -- the seven subsections ------------------------------------------------

def handoff_fields(p):
    txt = Path(p).read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^-\s*\*\*Chat:\*\*\s*"?([^"\n·]+)"?', txt, re.M)
    title = m.group(1).strip().strip('"').strip() if m else p.stem
    m = re.search(r"^#\s*HANDOFF\s*[—-]\s*(.+)$", txt, re.M | re.I)
    topic = m.group(1).strip() if m else ""
    m = re.search(r"\*\*Topic folder:\*\*\s*`([^`]+)`", txt)
    folder = m.group(1).strip() if m else str(p.parent.parent.parent)
    m = re.search(r"^##\s*CURRENT STATE\s*$(.*?)(?=^##\s|\Z)", txt, re.M | re.S | re.I)
    state = " ".join(m.group(1).split()) if m else ""
    if not state:
        note("Sessions closed", f"no CURRENT STATE paragraph in {p.name}")
    return title, topic, folder, state


def sec_sessions(day, handoffs):
    out = []
    for p, mday in sorted(handoffs):
        if file_day(p, mday) != day:
            continue
        title, topic, folder, state = handoff_fields(p)
        head = f"- **{title}**"
        if topic:
            head += f" · {topic}"
        head += f" · `{folder}`"
        out.append(head + ("\n  " + state if state else ""))
    return out


def sec_documents(day, ledgers):
    out = []
    for lib, root, p in ledgers:
        header, rows = table_rows(p, ("filename", "date entered"))
        if not header:
            continue
        zone = str(p.parent.relative_to(root)) if p.parent != root else "(root)"
        for r in rows:
            if cell(header, r, "date entered").strip("` ")[:10] != day:
                continue
            fn = cell(header, r, "filename").strip("` ")
            summ = cut(cell(header, r, "summary"), 160)
            out.append(f"- {lib} · {zone} · `{fn}`" + (f" — {summ}" if summ else ""))
    return out


def sec_decisions(day):
    header, rows = table_rows(AP.DECISIONS, ("id", "date"))
    if not header:
        note("Decisions", f"no table with id and date in {AP.DECISIONS}")
        return []
    out = []
    for r in rows:
        if cell(header, r, "date").strip("` ")[:10] != day:
            continue
        out.append(f"- **{cell(header, r, 'id')}** — {cut(cell(header, r, 'decision'), 200)}")
    return out


def sec_tasks(day):
    done, added = [], []
    try:
        with open(AP.REGISTER / "tasks.csv", newline="", encoding="utf-8",
                  errors="replace") as f:
            for r in csv.DictReader(f):
                # INTAKE- rows are filing proposals, not tasks (spec 3.9).
                if (r.get("id") or "").startswith("INTAKE-"):
                    continue
                if (r.get("done_on") or "").strip()[:10] == day:
                    done.append(f"{r.get('id','')} {r.get('title','')}")
                if (r.get("created_on") or "").strip()[:10] == day:
                    added.append(f"{r.get('id','')} {r.get('title','')}")
    except OSError as e:
        note("Tasks", e)
    return done, added


def sec_letters(day, letters):
    out = []
    for lib, p, mday in sorted(letters):
        if mday != day:
            continue
        out.append(f"- {lib} · `{p.parent}` · `{p.name}`")
    return out


def sec_mail(day):
    """Mail the importer judged on `day`, one line per thread, from the
    importer's ledger through mail_state.mail_rows. Threads the owner marked
    done are left out; snoozed ones stay,
    because a snooze postpones attention and does not change what arrived."""
    out = []
    for r in mail_state.mail_rows(day, day, include_done=True):
        if r["run_ts"][:10] != day or str(r["state"]).startswith("done by"):
            continue
        out.append(f'- {r["topic_final"]} · "{" ".join(r["subject"].split())}"'
                   f' · last from {r["from_latest"]} {r["last_date"]}'
                   f' · {r["state"]} · {cut(r["demand_reason"], 160)}'
                   f' · `{r["thread_file"] or "-"}`')
    return out


def _hhmm(ts):
    ts = str(ts)
    suffix = " (UTC)" if ts.endswith("Z") else ""
    return (ts[11:16] or "??:??") + suffix


def sec_jobs(day):
    out = []
    for obj in json_lines(AP.LOG_DIR / "board_morning.log", "Jobs run"):
        b = obj.get("morning") if isinstance(obj, dict) else None
        if not isinstance(b, dict) or not str(b.get("time", "")).startswith(day):
            continue
        d = b.get("details") or {}
        det = f"open {d.get('open','?')}, overdue {d.get('overdue','?')}, {d.get('render','')}"
        out.append((str(b.get("time")), _hhmm(b.get("time")), "board-morning",
                    b.get("status", "?"), det.strip(", ")))
    for obj in json_lines(AP.LOG_DIR / "runner1.log", "Jobs run"):
        if not isinstance(obj, dict) or "quarantine_purge" not in obj:
            continue
        steps = {k: v for k, v in obj.items() if isinstance(v, dict)}
        starts = sorted(s for s in (v.get("started_at", "") for v in steps.values()) if s)
        if not starts or not starts[0].startswith(day):
            continue
        status = "OK" if all(v.get("status") == "success" for v in steps.values()) else "FAILED"
        det = "; ".join(f"{k} {v.get('status')}" for k, v in steps.items())
        out.append((starts[0], _hhmm(starts[0]), "runner-1", status, det))
    # run_status.json carries the latest Cowork step FLAT at the top level
    # (step/status/time/details) plus one nested block per Windows job, of
    # which `morning` is read from the log instead (3.3). Both shapes count.
    st = read_json(AP.REGISTER / "run_status.json") or {}
    blocks = []
    if isinstance(st, dict):
        if st.get("step") and st.get("time"):
            blocks.append((str(st.get("step")), st))
        for key, b in st.items():
            if key != "morning" and isinstance(b, dict) and b.get("time"):
                blocks.append((str(b.get("step", key)), b))
    for name, b in blocks:
        if not str(b.get("time", "")).startswith(day):
            continue
        d = b.get("details")
        det = ("; ".join(f"{k} {v}" for k, v in d.items()
                         if not isinstance(v, (dict, list)))) if isinstance(d, dict) else str(d or "")
        out.append((str(b.get("time")), _hhmm(b.get("time")), name,
                    b.get("status", "?"), cut(det, 200)))
    rs = read_json(AP.RUN_STATE) or {}
    for name, b in rs.items():
        if name == "runner_1" or not isinstance(b, dict):
            continue
        for k, v in b.items():
            if not isinstance(v, dict):
                continue
            ts = str(v.get("started_at", ""))
            if not ts.startswith(day):
                continue
            out.append((ts, _hhmm(ts), k.replace("_", "-"), v.get("status", "?"),
                        cut(v.get("detail", ""), 200)))
    out.sort()
    return [f"- {hh} {name} — {status} — {det}".rstrip(" —")
            for _ts, hh, name, status, det in out]


def sec_topics(day, changed, topics, handoff_days):
    tops = sorted({(lib, t) for lib, t in topics}, key=lambda x: len(str(x[1])), reverse=True)
    counts = {}
    for lib, p in changed:
        for tlib, t in tops:
            if t == p or t in p.parents:
                counts[(tlib, t)] = counts.get((tlib, t), 0) + 1
                break
    out = []
    for (lib, t), n in sorted(counts.items(), key=lambda kv: str(kv[0][1])):
        if day in handoff_days.get(t, set()):
            continue
        out.append(f"- {lib} · `{t}` — {n} file" + ("s" if n != 1 else ""))
    return out


# -- assembly -------------------------------------------------------------

def block(title, lines):
    if not lines:
        return f"### {title} (0)\n- none\n"
    return f"### {title} ({len(lines)})\n" + "\n".join(lines) + "\n"


def build(day):
    files, topics, ledgers, letters, handoffs, changed = [], [], [], [], [], []
    handoff_days = {}
    for lib, root in LIBRARIES:
        f, t, l, c, h = scan(root)
        topics += [(lib, x) for x in t]
        ledgers += [(lib, root, x) for x in l]
        letters += [(lib, p, d) for p, d in c]
        handoffs += h
        changed += [(lib, p) for p, d in f if d == day]
    for p, mday in handoffs:
        d = file_day(p, mday)
        parent = p.parent
        topic = parent.parent.parent if parent.name == MD_FOLDER else parent
        handoff_days.setdefault(topic, set()).add(d)

    parts = []
    for title, fn in (("Sessions closed", lambda: sec_sessions(day, handoffs)),
                      ("Documents filed", lambda: sec_documents(day, ledgers)),
                      ("Decisions", lambda: sec_decisions(day))):
        try:
            parts.append(block(title, fn()))
        except Exception as e:
            note(title, e)
            parts.append(block(title, []))
    try:
        done, added = sec_tasks(day)
    except Exception as e:
        note("Tasks", e)
        done, added = [], []
    parts.append("### Tasks\n"
                 f"- Done ({len(done)}): {'; '.join(done) if done else 'none'}\n"
                 f"- Added ({len(added)}): {'; '.join(added) if added else 'none'}\n")
    for title, fn in (("Letters", lambda: sec_letters(day, letters)),
                      ("Mail", lambda: sec_mail(day)),
                      ("Jobs run", lambda: sec_jobs(day)),
                      ("Topics changed with no handoff",
                       lambda: sec_topics(day, changed, topics, handoff_days))):
        try:
            parts.append(block(title, fn()))
        except Exception as e:
            note(title, e)
            parts.append(block(title, []))
    parts.append("### Notes\n" + ("\n".join(NOTES) if NOTES else "- none") + "\n")
    return f"## {day}\n\n" + "\n".join(parts)


def upsert(path, day, body):
    head = f"## {day}"
    if path.exists():
        txt = path.read_text(encoding="utf-8", errors="replace")
    else:
        txt = (f"# Daily record — {day[:7]}\n\nWritten by `daily_record.py` "
               "as one section per day, newest last. Never edited by hand: "
               "a re-run of the same date replaces that date's section.\n")
    body = body.rstrip("\n") + "\n\n"
    pat = re.compile(r"^" + re.escape(head) + r"\b.*?(?=^## \d{4}-\d\d-\d\d\b|\Z)",
                     re.M | re.S)
    # A function, never the text: the body is full of Windows paths and a
    # backslash in a replacement template is an escape sequence.
    txt = pat.sub(lambda _m: body, txt) if pat.search(txt) else txt.rstrip("\n") + "\n\n" + body
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(txt, encoding="utf-8")
    tmp.replace(path)


def rotate_logs():
    stamp = date.today().strftime("%Y%m%d")
    try:
        for p in AP.LOG_DIR.glob("*.log"):
            if p.stat().st_size > 2_000_000:
                p.replace(p.with_name(f"{p.stem}.{stamp}.log"))
    except OSError as e:
        note("Log rotation", e)


def main():
    ap = argparse.ArgumentParser(description="Daily record")
    ap.add_argument("--date", default="", help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    a = ap.parse_args()
    day = a.date or (date.today() - timedelta(days=1)).isoformat()
    try:
        date.fromisoformat(day)
    except ValueError:
        print(f"bad --date: {day}")
        sys.exit(1)
    started = datetime.now()
    body = build(day)
    if a.dry_run:
        print(body)
        sys.exit(0)
    AP.RECORD_DIR.mkdir(parents=True, exist_ok=True)
    path = AP.RECORD_DIR / f"DAILY-{day[:4]}{day[5:7]}.md"
    try:
        upsert(path, day, body)
    except OSError as e:
        print(json.dumps({"daily_record": {"date": day, "status": "failed", "error": str(e)[:300]}}))
        sys.exit(1)
    rotate_logs()
    state = {"last_written": day, "written_at": datetime.now().isoformat(timespec="seconds"),
             "file": str(path), "notes": len(NOTES),
             "scan_seconds": round((datetime.now() - started).total_seconds(), 1)}
    tmp = AP.RECORD_DIR / "daily_record_state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(AP.RECORD_DIR / "daily_record_state.json")
    print(json.dumps({"daily_record": {**state, "status": "OK"}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
