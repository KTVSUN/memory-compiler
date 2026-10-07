#!/usr/bin/env python3
"""run_check.py — the Runs strip judge. Reads runs.json plus the
evidence files it names and decides, per run, whether its last due slot
left the footprint it was supposed to. Stdlib only. Never raises out of
evaluate(): any exception inside one run's probe becomes that run's state
`error` with the exception text; an unreadable register becomes a single
`error` row named "runs.json". Described in ARCHITECTURE.md section 8
(the run strip)."""

import argparse
import datetime as _dt
import json
import os
import sys
import time as _time
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import ops_paths as AP

DEFAULT_REGISTER = AP._HERE.parent / "config" / "runs.json"
HEARTBEAT_LOG = AP.LOG_DIR / "heartbeat.log"
OUT_PATH = AP.WORKBOARD / "run_check.json"

_ROOT_KEYS = ("projects", "library", "local_data")
UTC_OFFSET_HOURS = 0  # the owner's fixed offset from UTC, no daylight saving: the importer's value

_MARK = {"ok": "●", "failed": "●", "missing": "●",
         "off": "○", "pending": "○", "error": "●"}
_COLOUR = {"ok": "#3fb950", "failed": "#f85149", "missing": "#f85149",
           "off": "#8b949e", "pending": "#8b949e", "error": "#d29922"}
_SUFFIX = {"failed": " (failed)", "missing": " (missing)", "off": " (computer off)"}


# ── path template resolution ─────────────────────────────────────────
def resolve_template(template, slot=None, prev=None):
    """'{local_data}\\Board\\logs\\x.log' -> real Path, translated for the
    session mount the same way ops_paths.P already is. slot/prev format
    date fields inside the remainder ({slot:%Y%m%d} etc)."""
    root_key = None
    rest = template
    for k in _ROOT_KEYS:
        prefix = "{" + k + "}"
        if template.startswith(prefix):
            root_key = k
            rest = template[len(prefix):]
            break
    rest = rest.format(slot=slot, prev=prev)
    rest = rest.lstrip("\\/")
    parts = [p for p in rest.replace("\\", "/").split("/") if p]
    base = AP.P[root_key] if root_key else Path("/")
    return base.joinpath(*parts) if parts else base


def _fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


# ── due slot ──────────────────────────────────────────────────────────
def _slots_matching(cadence, day):
    kind = cadence["kind"]
    if kind == "daily":
        return day.weekday() in cadence["days"]
    if kind == "weekly":
        return day.weekday() == cadence["weekday"]
    if kind == "monthly":
        return day.day == cadence["day"]
    raise ValueError(f"unknown cadence kind: {kind}")


def due_slot(cadence, settle_min, now):
    """Latest slot with slot + settle_min <= now, searched back 40 days.
    None if no such slot exists."""
    hh, mm = (int(x) for x in cadence["time"].split(":"))
    latest = None
    d = (now - _dt.timedelta(days=40)).date()
    end = now.date()
    while d <= end:
        if _slots_matching(cadence, d):
            slot_dt = _dt.datetime.combine(d, _dt.time(hh, mm))
            if slot_dt + _dt.timedelta(minutes=settle_min) <= now:
                if latest is None or slot_dt > latest:
                    latest = slot_dt
        d += _dt.timedelta(days=1)
    return latest


def next_slot(cadence, now):
    """First slot strictly after now, searched forward up to 40 days —
    only used for the pending evidence line."""
    hh, mm = (int(x) for x in cadence["time"].split(":"))
    d = now.date()
    for _ in range(41):
        if _slots_matching(cadence, d):
            slot_dt = _dt.datetime.combine(d, _dt.time(hh, mm))
            if slot_dt > now:
                return slot_dt
        d += _dt.timedelta(days=1)
    return None


# ── heartbeat ─────────────────────────────────────────────────────────
def heartbeat_in_window(slot, settle_min):
    """(found: bool, note: str). Missing/empty file: (False, 'no heartbeat file')."""
    if not HEARTBEAT_LOG.is_file():
        return False, "no heartbeat file"
    try:
        lines = HEARTBEAT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False, "no heartbeat file"
    if not lines:
        return False, "no heartbeat file"
    lo = slot - _dt.timedelta(minutes=10)
    hi = slot + _dt.timedelta(minutes=settle_min)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            t = _dt.datetime.fromisoformat(line)
        except ValueError:
            continue
        if lo <= t <= hi:
            return True, f"heartbeat at {t.isoformat(timespec='minutes')}"
    return False, f"no heartbeat between {lo.isoformat(timespec='minutes')} and {hi.isoformat(timespec='minutes')}"


# ── jsonlines reading ─────────────────────────────────────────────────
def _read_json_objects(path):
    """Yield dict objects parsed from lines of `path`; non-JSON lines
    (Python tracebacks between JSON lines) are skipped silently."""
    p = Path(path)
    if not p.is_file():
        return
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def _date10(s):
    """Date part of an ISO timestamp, in the owner's local time. A timestamp that
    carries Z or an offset (cloud runs write UTC, so an evening run can carry
    the next day's date) is converted to local time first; a naive one is taken
    as local already."""
    s = s or ""
    try:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s[:10]
    if dt.tzinfo is not None:
        dt = dt.astimezone(_dt.timezone(_dt.timedelta(hours=UTC_OFFSET_HOURS)))
    return dt.strftime("%Y-%m-%d")


def _same(a, b):
    """Status values compared without case: runs write ok/OK/Ok."""
    return str(a).strip().lower() == str(b).strip().lower()


# ── probes ────────────────────────────────────────────────────────────
def probe_jsonlines(probe, slot, prev, run_id):
    path = resolve_template(probe["path"], slot, prev)
    key = probe["key"]
    date_field = probe["date_field"]
    ok_field = probe["ok_field"]
    ok_value = probe["ok_value"]
    slot_date = slot.strftime("%Y-%m-%d")
    best = None
    for obj in _read_json_objects(path):
        block = obj.get(key)
        if not isinstance(block, dict):
            continue
        if _date10(block.get(date_field)) == slot_date:
            best = block
    if best is None:
        return "not_found", f"{path}: no {key!r} line dated {slot_date}", ""
    if _same(best.get(ok_field), ok_value):
        return "found_ok", f"{path} line dated {slot_date}, {ok_field} {ok_value}", ""
    detail = best.get("error") or best.get("step") or ""
    return "found_failed", f"{path} line dated {slot_date}, {ok_field}={best.get(ok_field)!r}", str(detail)[:200]


def probe_jsonlines_steps(probe, slot, prev, run_id):
    path = resolve_template(probe["path"], slot, prev)
    steps = probe["steps"]
    date_field = probe["date_field"]
    ok_field = probe["ok_field"]
    ok_value = probe["ok_value"]
    slot_date = slot.strftime("%Y-%m-%d")
    best = None
    for obj in _read_json_objects(path):
        for step in steps:
            block = obj.get(step)
            if isinstance(block, dict) and _date10(block.get(date_field)) == slot_date:
                best = obj
                break
    if best is None:
        return "not_found", f"{path}: no line with a step dated {slot_date}", ""
    missing_step = None
    for step in steps:
        block = best.get(step)
        if not isinstance(block, dict) or not _same(block.get(ok_field), ok_value):
            missing_step = step
            break
    if missing_step is None:
        return "found_ok", f"{path} line dated {slot_date}, all steps {ok_value}", ""
    block = best.get(missing_step) or {}
    detail = block.get("error") or block.get("detail") or "missing"
    return "found_failed", f"{path} line dated {slot_date}, step {missing_step!r} not {ok_value}", f"{missing_step}: {detail}"[:200]


def probe_json_key(probe, slot, prev, run_id):
    path = resolve_template(probe["path"], slot, prev)
    p = Path(path)
    if not p.is_file():
        return "not_found", f"{path}: file not found", ""
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except ValueError as e:
        return "not_found", f"{path}: unreadable JSON ({e})", ""
    key = probe.get("key") or ""
    obj = data
    if key:
        for part in key.split("."):
            if not isinstance(obj, dict):
                obj = None
                break
            obj = obj.get(part)
    if not isinstance(obj, dict):
        return "not_found", f"{path}: key {key!r} not found", ""
    match_field = probe.get("match_field")
    if match_field:
        if obj.get(match_field) != probe.get("match_value"):
            return "not_found", f"{path}: {match_field} != {probe.get('match_value')!r}", ""
    date_field = probe["date_field"]
    slot_date = slot.strftime("%Y-%m-%d")
    if _date10(obj.get(date_field)) != slot_date:
        return "not_found", f"{path}: {date_field} not dated {slot_date}", ""
    ok_field = probe["ok_field"]
    ok_value = probe["ok_value"]
    if _same(obj.get(ok_field), ok_value):
        return "found_ok", f"{path} key {key!r} dated {slot_date}, {ok_field} {ok_value}", ""
    detail = obj.get("error") or obj.get("detail") or obj.get("notes") or ""
    return "found_failed", f"{path} key {key!r} dated {slot_date}, {ok_field}={obj.get(ok_field)!r}", str(detail)[:200]


def probe_md_section(probe, slot, prev, run_id):
    path = resolve_template(probe["path"], slot, prev)
    heading = probe["heading"].format(slot=slot, prev=prev)
    p = Path(path)
    if not p.is_file():
        return "not_found", f"{path}: file not found", ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "not_found", f"{path}: unreadable", ""
    for line in text.splitlines():
        if line == heading or line.startswith(heading + " "):
            return "found_ok", f"{path}: heading {heading!r} found", ""
    return "not_found", f"{path}: heading {heading!r} not found", ""


def probe_files(probe, slot, prev, run_id):
    min_bytes = probe.get("min_bytes", 0)
    for template in probe["paths"]:
        path = resolve_template(template, slot, prev)
        p = Path(path)
        if not p.is_file() or p.stat().st_size < min_bytes:
            return "not_found", f"{path}: missing or under {min_bytes} bytes", ""
    return "found_ok", f"all {len(probe['paths'])} file(s) present, each >= {min_bytes} bytes", ""


def probe_stamp(probe, slot, prev, run_id):
    # window_days: a Cowork task that fires late (computer asleep at the slot)
    # still counts if its stamp lands within that many days after the slot.
    path = None
    for k in range(int(probe.get("window_days") or 0) + 1):
        cand = AP.WORKBOARD / "run_stamps" / run_id / f"{(slot + _dt.timedelta(days=k)).strftime('%Y%m%d')}.json"
        if cand.is_file():
            path = cand
            break
    if path is None:
        path = AP.WORKBOARD / "run_stamps" / run_id / f"{slot.strftime('%Y%m%d')}.json"
        return "not_found", f"{path}: no stamp", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError) as e:
        return "not_found", f"{path}: unreadable stamp ({e})", ""
    status = data.get("status")
    produced = data.get("produced") or []
    if status == "ok":
        missing = [pr for pr in produced if not Path(pr).exists()]
        if not missing:
            return "found_ok", f"{path}: status ok, {len(produced)} produced path(s) present", ""
        return "found_failed", f"{path}: produced path missing", missing[0]
    note = data.get("note") or f"status {status!r}"
    return "found_failed", f"{path}: status {status!r}", str(note)[:200]


_PROBES = {
    "jsonlines": probe_jsonlines,
    "jsonlines_steps": probe_jsonlines_steps,
    "json_key": probe_json_key,
    "md_section": probe_md_section,
    "files": probe_files,
    "stamp": probe_stamp,
}


def run_probe(probe, slot, prev, run_id):
    ptype = probe.get("type")
    fn = _PROBES.get(ptype)
    if fn is None:
        raise ValueError(f"unknown probe type: {ptype!r}")
    return fn(probe, slot, prev, run_id)


# ── per-run evaluation ────────────────────────────────────────────────
def evaluate_run(run, now):
    run_id = run["id"]
    label = run.get("label", run_id)
    cadence = run["cadence"]
    settle_min = run["settle_min"]
    needs_machine = bool(run.get("needs_machine"))

    slot = due_slot(cadence, settle_min, now)
    if slot is None:
        nxt = next_slot(cadence, now)
        return {"id": run_id, "label": label, "state": "pending",
                "slot": "", "evidence": f"next slot {_fmt_dt(nxt)}", "detail": ""}

    prev = slot.date() - _dt.timedelta(days=1)
    slot_str = slot.strftime("%Y-%m-%dT%H:%M")

    result, evidence, detail = run_probe(run["probe"], slot, prev, run_id)

    if result == "not_found" and "fail_probe" in run:
        fp_result, fp_evidence, fp_detail = run_probe(run["fail_probe"], slot, prev, run_id)
        if fp_result == "found_failed":
            return {"id": run_id, "label": label, "state": "failed",
                    "slot": slot_str, "evidence": fp_evidence, "detail": fp_detail}

    if result == "found_ok":
        return {"id": run_id, "label": label, "state": "ok",
                "slot": slot_str, "evidence": evidence, "detail": ""}
    if result == "found_failed":
        return {"id": run_id, "label": label, "state": "failed",
                "slot": slot_str, "evidence": evidence, "detail": detail}

    # not_found: missing (cloud run, or machine on) vs off (machine off)
    if not needs_machine:
        return {"id": run_id, "label": label, "state": "missing",
                "slot": slot_str, "evidence": evidence, "detail": ""}
    hb_found, hb_note = heartbeat_in_window(slot, settle_min)
    state = "missing" if hb_found else "off"
    return {"id": run_id, "label": label, "state": state,
            "slot": slot_str, "evidence": f"{evidence}; {hb_note}", "detail": ""}


# ── evaluate() ────────────────────────────────────────────────────────
def evaluate(now=None, register=None, write=True):
    now = now or _dt.datetime.now()
    reg_path = Path(register) if register else DEFAULT_REGISTER

    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        runs_spec = reg.get("runs", [])
    except (OSError, ValueError) as e:
        runs_spec = None
        load_error = str(e)

    results = []
    if runs_spec is None:
        results.append({"id": "runs.json", "label": "runs.json", "state": "error",
                         "slot": "", "evidence": f"could not read {reg_path}", "detail": load_error[:200]})
    else:
        for run in runs_spec:
            run_id = run.get("id", "?")
            try:
                results.append(evaluate_run(run, now))
            except Exception as e:
                results.append({"id": run_id, "label": run.get("label", run_id), "state": "error",
                                 "slot": "", "evidence": f"exception evaluating {run_id}", "detail": str(e)[:200]})

    summary = {s: 0 for s in STATES}
    for r in results:
        summary[r["state"]] = summary.get(r["state"], 0) + 1
    summary = {k: v for k, v in summary.items() if v}

    out = {"checked_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
           "summary": summary, "runs": results}

    if write:
        _write_result(out)

    return out


STATES = ("ok", "failed", "missing", "off", "pending", "error")


def _write_result(out):
    try:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    tmp = str(OUT_PATH) + ".tmp"
    payload = json.dumps(out, indent=2, ensure_ascii=False).encode("utf-8")
    for attempt in range(3):
        try:
            with open(tmp, "wb") as f:
                f.write(payload)
            os.replace(tmp, str(OUT_PATH))
            return
        except PermissionError:
            if attempt < 2:
                _time.sleep(1.5)
            else:
                return
        except OSError:
            return


# ── strip_html ────────────────────────────────────────────────────────
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _esc_attr(s):
    return _esc(s).replace('"', "&quot;")


def strip_html(result):
    summary = result.get("summary", {})
    order = ("ok", "failed", "missing", "off", "pending", "error")
    parts = [f"{summary[k]} {k}" for k in order if summary.get(k)]
    summary_text = " · ".join(parts)

    spans = [f'<span style="font-weight:700;color:#e6edf3">Runs</span>']
    if summary_text:
        spans.append(f'<span>{_esc(summary_text)}</span>')

    for r in result.get("runs", []):
        state = r.get("state", "error")
        mark = _MARK.get(state, "●")
        colour = _COLOUR.get(state, "#d29922")
        label = r.get("label", r.get("id", ""))
        label += _SUFFIX.get(state, "")
        tooltip = f"{r.get('id','')} · slot {r.get('slot','') or '—'} · {r.get('evidence','')}"
        if r.get("detail"):
            tooltip += f" · {r['detail']}"
        spans.append(
            f'<span data-run="{_esc_attr(r.get("id",""))}" data-state="{_esc_attr(state)}" '
            f'title="{_esc_attr(tooltip)}" style="color:{colour};white-space:nowrap">'
            f'{mark} {_esc(label)}</span>'
        )

    return (
        '<div class="runs-strip" style="flex-basis:100%;display:flex;flex-wrap:wrap;'
        'align-items:center;gap:4px 14px;margin-top:6px;font-size:12px;color:#8b949e">'
        + "".join(spans) + "</div>"
    )


# ── CLI ───────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--now")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--register", help="path to a runs.json (default: config\\runs.json next to this script); "
                                        "mainly for run_check_test.py")
    args = ap.parse_args(argv)

    now = _dt.datetime.fromisoformat(args.now) if args.now else None
    result = evaluate(now=now, register=args.register, write=not args.no_write)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for r in result["runs"]:
            print(f"{r['state']:<8} {r['id']:<28} {r.get('slot','') or '-':<18} {r.get('evidence','')}")
        parts = [f"{v} {k}" for k, v in result["summary"].items()]
        print("SUMMARY: " + (", ".join(parts) if parts else "nothing to report"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
