#!/usr/bin/env python3
"""memory_check.py — the Memory Compiler.

A reference implementation of the "memory as source code" architecture described in
ARCHITECTURE.md. It treats a small set of canonical Markdown files as the single source of
truth for an AI agent's persistent memory of a project, and mechanically enforces the rules
that keep that memory trustworthy across sessions, restarts, and (optionally) multiple
machines syncing through a shared folder (Dropbox, OneDrive, git, whatever you use).

What it does, mapped to the architecture doc:
  - OPEN_ITEMS.md   structural validation (permanent IDs, legal status transitions)
  - DECISIONS.md    structural validation (permanent IDs, required fields)
  - TOMBSTONES.md   structural validation + collision check against the other canonical files
  - Session ledger  open (baseline hashes, conflict-copy check, canonical-files-exist check)
  - Single-writer-per-topic lock, compiler-version check, atomic ledger writes
  - Close pipeline: validate -> concurrency -> build -> test -> seal
      - Build regenerates the generated (disposable) views
      - Test runs memory_tests.yaml positive/negative retrieval assertions
  - Failed-close recovery: stale-OPEN detection, candidate-skeleton generation, hard block

Deliberately NOT implemented here (see ARCHITECTURE.md for why each is optional/deferred):
  - A fact-ID / evidence-pointer system for individual numeric claims — the doc suggests
    piloting this only in one topic before adopting it everywhere.
  - `_pending/` staged writes — only worth the complexity if half-closed sessions start
    corrupting canonical files in practice.
  - A git audit mirror — validation prevents corruption; an audit trail only shows it
    afterwards, so it's the last thing worth building, not the first.
  - Any wiring into a specific "morning brief" or "session start" skill/command — that's
    glue code for whatever agent harness you use, not part of the compiler itself.

Usage (run from anywhere; by default the topic root is this script's own directory — see
--topic-dir / MEMORY_TOPIC_DIR to point it at a project root the script doesn't live in):
  python3 memory_check.py                        # validate only
  python3 memory_check.py --strict                # validate; nonzero exit on any hard failure
  python3 memory_check.py --build                 # regenerate the generated views
  python3 memory_check.py --test                  # run memory_tests.yaml
  python3 memory_check.py --open <sid> [--machine M]
  python3 memory_check.py --close <sid>           # validate -> concurrency -> build -> test -> seal
  python3 memory_check.py --status                # ledger entries for this topic
  python3 memory_check.py --recovery-scan [--recovery-threshold-hours N]   # default 24
  python3 memory_check.py --resolve-recovery <sid> [--note "..."]

No third-party dependencies on purpose — the machine running this at 11pm on a crashed
session shouldn't also need a working virtualenv.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import pathlib

MD = pathlib.Path(__file__).resolve().parent
TOPIC = pathlib.Path(os.environ.get("MEMORY_TOPIC_DIR", str(MD))).resolve()
SESSIONS_DIR = TOPIC / "_sessions"
RECOVERY_DIR = SESSIONS_DIR / "recovery"
GENERATED_DIR = TOPIC / "_generated"
GENERATED_ROLLUP_DIR = TOPIC / "_rollup"  # optional cross-project view; see ARCHITECTURE.md §7

COMPILER_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"
DEFAULT_RECOVERY_THRESHOLD_HOURS = 24

LAYER_A_FILES = ["CONTEXT.md", "OPEN_ITEMS.md", "TOMBSTONES.md", "DECISIONS.md"]

OPEN_ITEMS_STATUSES = {"OPEN", "BLOCKED", "DONE", "DROPPED"}
EVIDENCE_REQUIRED_STATUSES = {"DONE", "DROPPED"}
DECISION_STATUSES = {"Active", "Superseded"}

GENERATED_STAMP = "GENERATED VIEW — NOT AUTHORITATIVE. Rebuild from canonical memory. Do not edit manually."


# ---------------------------------------------------------------------------
# Markdown table parsing (minimal, no dependencies)
# ---------------------------------------------------------------------------

def parse_table(text):
    """Return (header_cells, [row_cells...]) for the first pipe-table found, or (None, [])."""
    lines = text.splitlines()
    header = None
    rows = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("|") and stripped.endswith("|") and header is None:
                header = [c.strip() for c in stripped.strip("|").split("|")]
                in_table = True
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            break  # table ended
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue  # header-separator row
        rows.append(cells)
    return header, rows


# ---------------------------------------------------------------------------
# Minimal YAML-subset reader for memory_tests.yaml (no PyYAML dependency — see
# module docstring on why this stays dependency-free). Only supports: a
# top-level "tests:" key, a list of "- id: ..." blocks, each with indented
# "key: value" lines, values optionally double-quoted.
#
# Gotcha: "#" always starts a comment, even inside a quoted value, since this is a line-based
# strip, not a real YAML tokenizer. Don't put "#" in an expect_contains/expect_not_contains value
# (write hex colors as "1E3A5F", not "#1E3A5F").
# ---------------------------------------------------------------------------

def parse_simple_yaml_tests(text):
    tests = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.strip() == "tests:":
            continue
        m = re.match(r"^\s*-\s+(\w+):\s*(.*)$", line)
        if m and (line.startswith("  - ") or line.startswith("- ")):
            if current is not None:
                tests.append(current)
            current = {}
            key, val = m.group(1), m.group(2)
            current[key] = _unquote(val)
            continue
        m2 = re.match(r"^\s+(\w+):\s*(.*)$", line)
        if m2 and current is not None:
            key, val = m2.group(1), m2.group(2)
            current[key] = _unquote(val)
            continue
    if current is not None:
        tests.append(current)
    return tests


def _unquote(val):
    val = val.strip()
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        inner = val[1:-1]
        return inner.replace('\\\\', '\\').replace('\\"', '"')
    return val


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_open_items():
    findings = []
    path = TOPIC / "OPEN_ITEMS.md"
    if not path.exists():
        return [("ask", "OPEN_ITEMS.md missing at topic root")]
    text = path.read_text(encoding="utf-8")
    header, rows = parse_table(text)
    if header is None:
        findings.append(("ask", "OPEN_ITEMS.md: no table found — cannot validate"))
        return findings
    expected = ["ID", "Item", "Status", "Opened", "Evidence / Reason", "Notes"]
    if header != expected:
        findings.append(("ask", f"OPEN_ITEMS.md: header {header} does not match expected {expected}"))

    seen_ids = set()
    for row in rows:
        if len(row) < 3:
            findings.append(("ask", f"OPEN_ITEMS.md: malformed row {row}"))
            continue
        rid, item, status = row[0], row[1], row[2]
        evidence = row[4] if len(row) > 4 else ""
        if not rid:
            findings.append(("ask", f"OPEN_ITEMS.md: row missing ID — {row}"))
            continue
        if rid in seen_ids:
            findings.append(("ask", f"OPEN_ITEMS.md: duplicate ID {rid} — permanent IDs may not repeat"))
        seen_ids.add(rid)
        if status not in OPEN_ITEMS_STATUSES:
            findings.append(("ask", f"OPEN_ITEMS.md: item {rid} has illegal status '{status}' "
                                     f"(must be one of {sorted(OPEN_ITEMS_STATUSES)})"))
        if status in EVIDENCE_REQUIRED_STATUSES and not evidence.strip():
            findings.append(("ask", f"OPEN_ITEMS.md: item {rid} is {status} but Evidence / Reason "
                                     f"is empty — a close cannot leave this unresolved"))
    if not findings:
        findings.append(("ok", f"OPEN_ITEMS.md: {len(rows)} item(s), all IDs unique, all statuses legal"))
    return findings


def validate_tombstones():
    findings = []
    path = TOPIC / "TOMBSTONES.md"
    if not path.exists():
        return [("ask", "TOMBSTONES.md missing at topic root")]
    text = path.read_text(encoding="utf-8")
    header, rows = parse_table(text)
    if header is None:
        findings.append(("ask", "TOMBSTONES.md: no table found — cannot validate"))
        return findings
    expected = ["ID", "Fact / Key", "Rejected value", "Replacement", "Date", "Reason", "Source"]
    if header != expected:
        findings.append(("ask", f"TOMBSTONES.md: header {header} does not match expected {expected}"))

    seen_ids = set()
    for row in rows:
        if len(row) < len(expected):
            findings.append(("ask", f"TOMBSTONES.md: malformed row (expected {len(expected)} cols) {row}"))
            continue
        tid = row[0]
        if not tid:
            findings.append(("ask", f"TOMBSTONES.md: row missing ID — {row}"))
            continue
        if tid in seen_ids:
            findings.append(("ask", f"TOMBSTONES.md: duplicate ID {tid} — permanent IDs may not repeat"))
        seen_ids.add(tid)
        if any(not c.strip() for c in row):
            findings.append(("ask", f"TOMBSTONES.md: {tid} has an empty column — every field is mandatory"))
    if not findings:
        findings.append(("ok", f"TOMBSTONES.md: {len(rows)} tombstone(s), all IDs unique, all fields present"))
    return findings


def validate_decisions():
    findings = []
    path = TOPIC / "DECISIONS.md"
    if not path.exists():
        return [("ask", "DECISIONS.md missing at topic root")]
    text = path.read_text(encoding="utf-8")
    header, rows = parse_table(text)
    if header is None:
        findings.append(("ask", "DECISIONS.md: no table found — cannot validate"))
        return findings
    expected = ["ID", "Decision", "Why", "Date", "Evidence", "Supersedes", "Status"]
    if header != expected:
        findings.append(("ask", f"DECISIONS.md: header {header} does not match expected {expected}"))

    seen_ids = set()
    for row in rows:
        if len(row) < len(expected):
            findings.append(("ask", f"DECISIONS.md: malformed row (expected {len(expected)} cols) {row}"))
            continue
        did, decision, why, date, evidence, supersedes, status = row[:7]
        if not did:
            findings.append(("ask", f"DECISIONS.md: row missing ID — {row}"))
            continue
        if did in seen_ids:
            findings.append(("ask", f"DECISIONS.md: duplicate ID {did} — permanent IDs may not repeat"))
        seen_ids.add(did)
        if not decision.strip() or not why.strip() or not date.strip():
            findings.append(("ask", f"DECISIONS.md: {did} missing Decision/Why/Date — all three are mandatory"))
        if status not in DECISION_STATUSES:
            findings.append(("ask", f"DECISIONS.md: {did} has illegal status '{status}' "
                                     f"(must be one of {sorted(DECISION_STATUSES)})"))
        if supersedes.strip() and supersedes.strip() not in ("—", "-") and supersedes.strip() not in seen_ids:
            findings.append(("ask", f"DECISIONS.md: {did} supersedes '{supersedes}' which is not a "
                                     f"known prior ID (must reference an ID already in this file)"))
    if not findings:
        findings.append(("ok", f"DECISIONS.md: {len(rows)} decision(s), all IDs unique, all fields legal"))
    return findings


def truncation_check():
    """No canonical file may end mid-structure (dangling table row, unbalanced code fence)."""
    findings = []
    for name in LAYER_A_FILES:
        path = TOPIC / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if text.count("```") % 2 != 0:
            findings.append(("ask", f"{name}: unbalanced code fence (``` count is odd) — file may be truncated"))
        header, rows = parse_table(text)
        if header is not None:
            ncols = len(header)
            for row in rows:
                if len(row) != ncols:
                    findings.append(("ask", f"{name}: table row has {len(row)} cols, header has {ncols} "
                                             f"— possible truncation: {row}"))
        lines = [l for l in text.splitlines() if l.strip()]
        if lines and lines[-1].strip().startswith("|") and not lines[-1].strip().endswith("|"):
            findings.append(("ask", f"{name}: file ends mid-table-row"))
    if not findings:
        findings.append(("ok", "truncation check: no canonical file ends mid-structure"))
    return findings


def tombstone_collision_check():
    """Scan other canonical files for verbatim reassertion of a tombstoned rejected value."""
    findings = []
    tpath = TOPIC / "TOMBSTONES.md"
    if not tpath.exists():
        return findings
    _, trows = parse_table(tpath.read_text(encoding="utf-8"))
    rejected_values = []
    for row in trows:
        if len(row) >= 3 and row[2].strip():
            val = row[2].strip().strip("`\"")
            if len(val) >= 12:  # ignore short/generic strings, too noisy
                rejected_values.append((row[0], val))

    for name in LAYER_A_FILES:
        if name == "TOMBSTONES.md":
            continue
        path = TOPIC / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for tid, val in rejected_values:
            if val in text:
                findings.append(("ask", f"{name}: contains tombstoned value from {tid} verbatim "
                                         f"('{val[:60]}...') — check TOMBSTONES.md before reasserting"))
    if not findings:
        findings.append(("ok", "tombstone collision check: no rejected value found reasserted verbatim"))
    return findings


def run_validate():
    findings = []
    findings += validate_open_items()
    findings += validate_tombstones()
    findings += validate_decisions()
    findings += truncation_check()
    findings += tombstone_collision_check()
    return findings


# ---------------------------------------------------------------------------
# Build — regenerate Layer D (disposable, generated) views
# ---------------------------------------------------------------------------

def build_generated_index():
    GENERATED_DIR.mkdir(exist_ok=True)
    lines = [f"# INDEX.md — {TOPIC.name} (generated)", "", f"> {GENERATED_STAMP}",
             f"> Rebuilt by `memory_check.py --build` — {datetime.date.today()}.", ""]

    oi_path = TOPIC / "OPEN_ITEMS.md"
    if oi_path.exists():
        _, rows = parse_table(oi_path.read_text(encoding="utf-8"))
        counts = {}
        for row in rows:
            if len(row) >= 3:
                counts[row[2]] = counts.get(row[2], 0) + 1
        lines.append("## OPEN_ITEMS.md summary")
        lines.append(f"- Total: {len(rows)}")
        for status in sorted(OPEN_ITEMS_STATUSES):
            lines.append(f"- {status}: {counts.get(status, 0)}")
        lines.append("")

    ts_path = TOPIC / "TOMBSTONES.md"
    if ts_path.exists():
        _, rows = parse_table(ts_path.read_text(encoding="utf-8"))
        lines.append("## TOMBSTONES.md — rejected values (do not reassert)")
        for row in rows:
            if len(row) >= 3:
                lines.append(f"- **{row[0]}** ({row[1]}): `{row[2][:80]}`")
        lines.append("")

    dec_path = TOPIC / "DECISIONS.md"
    if dec_path.exists():
        _, rows = parse_table(dec_path.read_text(encoding="utf-8"))
        active = [r for r in rows if len(r) >= 7 and r[6] == "Active"]
        lines.append("## DECISIONS.md summary")
        lines.append(f"- Total: {len(rows)}, Active: {len(active)}")
        lines.append("")

    out_path = GENERATED_DIR / "INDEX.md"
    atomic_write_text(out_path, "\n".join(lines) + "\n")
    return out_path


def build_rollup_recovery_view():
    """Optional cross-project elevation (see ARCHITECTURE.md §4.4): every recovery candidate
    for this topic, surfaced in one place. If you run the compiler on several projects that
    share a parent folder, point GENERATED_ROLLUP_DIR at a shared location so unresolved
    recoveries don't get lost just because you're not currently looking at that project."""
    GENERATED_ROLLUP_DIR.mkdir(exist_ok=True)
    entries = []
    if RECOVERY_DIR.exists():
        for p in sorted(RECOVERY_DIR.glob("*.json")):
            try:
                entries.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue

    lines = ["# recovery_candidates.md (generated)", "", f"> {GENERATED_STAMP}",
              f"> Rebuilt by `memory_check.py --build` — {datetime.date.today()}. Cross-project view of "
              f"unresolved recovery candidates so they surface even if you're working other projects for "
              f"a while.", ""]
    if not entries:
        lines.append("*(no recovery candidates recorded)*")
    else:
        lines.append("| Topic | Session | Detected | Age at detection (h) | Resolved |")
        lines.append("|---|---|---|---|---|")
        for e in entries:
            lines.append(f"| {e.get('topic')} | {e.get('session')} | {e.get('detected_at')} | "
                          f"{e.get('age_hours_at_detection')} | {e.get('resolved')} |")
    out_path = GENERATED_ROLLUP_DIR / "recovery_candidates.md"
    atomic_write_text(out_path, "\n".join(lines) + "\n")
    return out_path


def run_build():
    idx = build_generated_index()
    wb = build_rollup_recovery_view()
    return [("ok", f"build: regenerated {idx.relative_to(TOPIC)}"),
            ("ok", f"build: regenerated {wb.relative_to(TOPIC) if TOPIC in wb.parents else wb}")]


# ---------------------------------------------------------------------------
# Test — memory_tests.yaml (positive/negative retrieval assertions)
# ---------------------------------------------------------------------------

def run_tests():
    findings = []
    path = TOPIC / "memory_tests.yaml"
    if not path.exists():
        return [("ask", "memory_tests.yaml missing at topic root — no retrieval tests to run")]
    tests = parse_simple_yaml_tests(path.read_text(encoding="utf-8"))
    if not tests:
        return [("ask", "memory_tests.yaml: no tests parsed — check the file's format")]

    for t in tests:
        tid = t.get("id", "?")
        ttype = t.get("type")
        fname = t.get("file")
        if not fname:
            findings.append(("ask", f"test {tid}: no 'file' specified"))
            continue
        fpath = TOPIC / fname
        if not fpath.exists():
            findings.append(("ask", f"test {tid}: target file '{fname}' does not exist"))
            continue
        content = fpath.read_text(encoding="utf-8")
        if ttype == "must_reference":
            needle = t.get("expect_contains", "")
            if needle in content:
                findings.append(("ok", f"test {tid} (must_reference, {fname}): PASS"))
            else:
                findings.append(("ask", f"test {tid} (must_reference, {fname}): FAIL — expected to find "
                                         f"'{needle}'"))
        elif ttype == "must_not_return":
            needle = t.get("expect_not_contains", "")
            if needle not in content:
                findings.append(("ok", f"test {tid} (must_not_return, {fname}): PASS"))
            else:
                findings.append(("ask", f"test {tid} (must_not_return, {fname}): FAIL — tombstoned value "
                                         f"'{needle}' found verbatim"))
        else:
            findings.append(("ask", f"test {tid}: unknown type '{ttype}'"))
    return findings


# ---------------------------------------------------------------------------
# Session ledger — open/close, concurrency and single-writer lock
# ---------------------------------------------------------------------------

def sha256_of(path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_hashes():
    return {name: sha256_of(TOPIC / name) for name in LAYER_A_FILES}


def has_conflict_copies():
    """Catches leftover sync-conflict files from Dropbox/OneDrive/Google Drive style clients,
    which all use some variant of '(conflicted copy)' / '(Conflict)' in the filename."""
    hits = []
    for p in TOPIC.rglob("*"):
        if p.is_file() and ("(conflicted copy)" in p.name or "(conflict)" in p.name.lower()):
            if "_to_delete" in p.parts:
                continue
            hits.append(str(p.relative_to(TOPIC)))
    return hits


def missing_canonical_files():
    return [name for name in LAYER_A_FILES if not (TOPIC / name).exists()]


def ledger_entries():
    if not SESSIONS_DIR.exists():
        return []
    return sorted(SESSIONS_DIR.glob("*.json"))


def open_writer_sessions(exclude_session_id=None):
    open_ids = []
    for p in ledger_entries():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") == "OPEN" and data.get("session") != exclude_session_id:
            open_ids.append(data.get("session"))
    return open_ids


def atomic_write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def atomic_write_text(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# --- recovery ----------------------------------------------------------

def stale_open_entries(threshold_hours):
    now = datetime.datetime.now(datetime.timezone.utc)
    stale = []
    for p in ledger_entries():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") != "OPEN":
            continue
        try:
            started = datetime.datetime.fromisoformat(data["started"])
        except (KeyError, ValueError):
            continue
        age_hours = (now - started).total_seconds() / 3600
        if age_hours >= threshold_hours:
            stale.append((p, data, age_hours))
    return stale


def unresolved_recovery_files():
    if not RECOVERY_DIR.exists():
        return []
    out = []
    for p in sorted(RECOVERY_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not data.get("resolved", False):
            out.append((p, data))
    return out


def render_recovery_md(entry):
    lines = [f"# RECOVERY — {entry['topic']} — {entry['session']}", "",
             f"- **Detected:** {entry['detected_at']} · **Session started:** "
             f"{entry.get('session_started', '?')} · **Age at detection:** "
             f"{entry['age_hours_at_detection']} h",
             f"- **Source ledger entry:** `{entry['source_ledger_entry']}`",
             f"- **Status:** {'RESOLVED' if entry.get('resolved') else 'UNRESOLVED'}", "",
             "## CANDIDATE FACTS — CANDIDATE — NOT CANONICAL"]
    lines += [f"- {x}" for x in entry["candidates"].get("facts", [])] or ["*(none filled in yet)*"]
    lines += ["", "## CANDIDATE DECISIONS — CANDIDATE — NOT CANONICAL"]
    lines += [f"- {x}" for x in entry["candidates"].get("decisions", [])] or ["*(none filled in yet)*"]
    lines += ["", "## CANDIDATE CORRECTIONS — CANDIDATE — NOT CANONICAL"]
    lines += [f"- {x}" for x in entry["candidates"].get("corrections", [])] or ["*(none filled in yet)*"]
    lines += ["", "## CANDIDATE OPEN-ITEM CHANGES — CANDIDATE — NOT CANONICAL"]
    lines += [f"- {x}" for x in entry["candidates"].get("open_item_changes", [])] or ["*(none filled in yet)*"]
    lines += ["", "## TOUCHED FILES — CANDIDATE — NOT CANONICAL"]
    lines += [f"- {x}" for x in entry["candidates"].get("touched_files", [])] or ["*(none filled in yet)*"]
    lines += ["", "## RECONCILIATION",
              f"- Resolved by: {entry.get('resolved_by', '—')} · Date: {entry.get('resolved_at', '—')}",
              f"- Note: {entry.get('resolution_note', '—')}", ""]
    return "\n".join(lines)


def cmd_recovery_scan(threshold_hours):
    findings = []
    stale = stale_open_entries(threshold_hours)
    if not stale:
        findings.append(("ok", f"recovery scan: no OPEN ledger entries older than {threshold_hours}h"))
    for p, data, age in stale:
        session_id = data["session"]
        recovery_json = RECOVERY_DIR / f"{session_id}.json"
        if recovery_json.exists():
            findings.append(("ok", f"recovery scan: session '{session_id}' already has a candidate — skipping"))
            continue
        RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry = {
            "session": session_id,
            "topic": TOPIC.name,
            "detected_at": now,
            "session_started": data.get("started"),
            "source_ledger_entry": str(p.relative_to(TOPIC)),
            "age_hours_at_detection": round(age, 1),
            "resolved": False,
            "candidates": {"facts": [], "decisions": [], "corrections": [],
                           "open_item_changes": [], "touched_files": []},
            "note": "CANDIDATE — NOT CANONICAL. Populate 'candidates' from the session transcript "
                    "before reconciling into canonical files, then run --resolve-recovery.",
        }
        atomic_write_json(recovery_json, entry)
        md_path = RECOVERY_DIR / f"RECOVERY - {TOPIC.name} - {session_id}.md"
        atomic_write_text(md_path, render_recovery_md(entry))
        findings.append(("ask", f"recovery candidate created for stale session '{session_id}' "
                                 f"(OPEN {age:.1f}h) — see {md_path.name}. New writing sessions on this "
                                 f"topic are hard-blocked until resolved."))
    build_rollup_recovery_view()
    return findings


def cmd_resolve_recovery(session_id, note=None, resolved_by=None):
    path = RECOVERY_DIR / f"{session_id}.json"
    if not path.exists():
        print(f"[ASK] no recovery candidate for session '{session_id}'")
        return 1
    entry = json.loads(path.read_text(encoding="utf-8"))
    if entry.get("resolved"):
        print(f"[ask] recovery candidate '{session_id}' was already resolved")
        return 0
    entry["resolved"] = True
    entry["resolved_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry["resolution_note"] = note or "(no note given)"
    entry["resolved_by"] = resolved_by or "unspecified session"
    atomic_write_json(path, entry)
    md_path = RECOVERY_DIR / f"RECOVERY - {TOPIC.name} - {session_id}.md"
    atomic_write_text(md_path, render_recovery_md(entry))

    # A crashed session's stale lock is cleared through recovery, never by simply deleting it.
    # Resolving the candidate is exactly that clearing act — seal the original stale ledger
    # entry too, distinctly marked so it's never mistaken for a normal validated close.
    ledger_path = SESSIONS_DIR / f"{session_id}.json"
    if ledger_path.exists():
        ledger_entry = json.loads(ledger_path.read_text(encoding="utf-8"))
        if ledger_entry.get("status") == "OPEN":
            ledger_entry["status"] = "CLOSED"
            ledger_entry["closed"] = entry["resolved_at"]
            ledger_entry["closed_via"] = "recovery"
            ledger_entry["closing_hashes"] = baseline_hashes()
            atomic_write_json(ledger_path, ledger_entry)
            print(f"[ok] stale ledger entry '{session_id}' sealed via recovery (closed_via: recovery, "
                  f"not a validated close) — single-writer lock released")

    build_rollup_recovery_view()
    print(f"[ok] recovery candidate '{session_id}' marked resolved — hard block cleared "
          f"(if no other unresolved candidates remain)")
    return 0


# --- open / close -----------------------------------------------------------

def cmd_open(session_id, machine=None):
    # Preflight order: canonical files exist -> conflict-copy check -> unresolved recovery
    # (hard block) -> single-writer lock.
    missing = missing_canonical_files()
    if missing:
        print(f"[ASK] canonical file(s) missing at topic root: {missing} — fix before opening a "
              f"writing session")
        return 1

    conflicts = has_conflict_copies()
    if conflicts:
        print("[ASK] sync conflict-copy file(s) present — resolve before opening a writing session:")
        for c in conflicts:
            print(f"  - {c}")
        return 1

    unresolved = unresolved_recovery_files()
    if unresolved:
        ids = [d.get("session") for _, d in unresolved]
        print(f"[ASK] unresolved recovery candidate(s) hard-block new writing sessions on this topic: "
              f"{ids} — reconcile via templates/RECOVERY_TEMPLATE.md then --resolve-recovery first")
        return 1

    others = open_writer_sessions(exclude_session_id=session_id)
    if others:
        print(f"[ASK] single-writer lock held by another OPEN session on this topic: {others} "
              f"— read-only until that ledger entry is CLOSED, or reconcile via recovery")
        return 1

    SESSIONS_DIR.mkdir(exist_ok=True)
    entry_path = SESSIONS_DIR / f"{session_id}.json"
    if entry_path.exists():
        print(f"[ASK] ledger entry for session '{session_id}' already exists — refusing to overwrite")
        return 1

    entry = {
        "session": session_id,
        "topic": TOPIC.name,
        "machine": machine or "unknown",
        "started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "OPEN",
        "compiler_version": COMPILER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "baseline_hashes": baseline_hashes(),
    }
    atomic_write_json(entry_path, entry)
    print(f"[ok] session '{session_id}' opened — writer lock held, baseline hashes recorded")
    return 0


def cmd_close(session_id):
    entry_path = SESSIONS_DIR / f"{session_id}.json"
    if not entry_path.exists():
        print(f"[ASK] no ledger entry for session '{session_id}' — cannot close what was never opened")
        return 1
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    if entry.get("status") != "OPEN":
        print(f"[ASK] session '{session_id}' is already {entry.get('status')} — nothing to close")
        return 1

    print(f"--- memory_check.py --close {session_id} ---")

    conflicts = has_conflict_copies()
    if conflicts:
        print("[ASK] sync conflict-copy file(s) present — resolve before closing:")
        for c in conflicts:
            print(f"  - {c}")
        return 1

    if entry.get("compiler_version") != COMPILER_VERSION:
        print(f"[ASK] memory tooling changed during session — opened under "
              f"{entry.get('compiler_version')}, closing under {COMPILER_VERSION}. Revalidate, don't "
              f"silently continue.")
        return 1

    current = baseline_hashes()
    baseline = entry.get("baseline_hashes", {})
    changed_by_others = [name for name in LAYER_A_FILES if baseline.get(name) != current.get(name)]

    # 1. Validate
    findings = run_validate()
    for level, msg in findings:
        print(f"[{level}] {msg}")
    if changed_by_others:
        print(f"[ASK] concurrent modification suspected — these Layer A files differ from the session's "
              f"open-time baseline: {changed_by_others}. Confirm this session made the change (expected) "
              f"vs. another writer/sync did (blocks close) before proceeding.")
        return 1
    if any(f[0] == "ask" for f in findings):
        print(f"[ASK] validation finding(s) above must be resolved before this close can seal — "
              f"ledger entry left OPEN.")
        return 1

    # 2. Concurrency already checked above (hashes, version, conflict-copies).

    # 3. Build
    build_findings = run_build()
    for level, msg in build_findings:
        print(f"[{level}] {msg}")

    # 4. Test
    test_findings = run_tests()
    for level, msg in test_findings:
        print(f"[{level}] {msg}")
    if any(f[0] == "ask" for f in test_findings):
        print(f"[ASK] memory_tests.yaml finding(s) above must be resolved before this close can seal — "
              f"ledger entry left OPEN.")
        return 1

    # 5. Audit — deliberately out of scope for this reference implementation (see the module
    #    docstring). Note that plainly rather than pretending it ran.
    print("[ok] audit: not implemented in this reference build — no audit trail was written")

    # 6. Seal
    entry["status"] = "CLOSED"
    entry["closed"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry["closing_hashes"] = current
    atomic_write_json(entry_path, entry)
    print(f"[ok] session '{session_id}' closed and sealed")
    return 0


def cmd_status():
    entries = ledger_entries()
    if not entries:
        print("no session ledger entries yet")
    for p in entries:
        data = json.loads(p.read_text(encoding="utf-8"))
        print(f"{data.get('session')}: {data.get('status')} (started {data.get('started')})")
    unresolved = unresolved_recovery_files()
    if unresolved:
        print(f"[ask] {len(unresolved)} unresolved recovery candidate(s): "
              f"{[d.get('session') for _, d in unresolved]}")
    return 0


# ---------------------------------------------------------------------------

def main():
    global TOPIC, SESSIONS_DIR, RECOVERY_DIR, GENERATED_DIR, GENERATED_ROLLUP_DIR

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic-dir", default=None,
                    help="project root to treat as the topic (default: $MEMORY_TOPIC_DIR, or this "
                         "script's own directory)")
    ap.add_argument("--strict", action="store_true", help="validate only; nonzero exit on any [ask] finding")
    ap.add_argument("--build", action="store_true", help="regenerate the generated views")
    ap.add_argument("--test", action="store_true", help="run memory_tests.yaml")
    ap.add_argument("--open", metavar="SESSION_ID", help="open a session: ledger entry + writer lock")
    ap.add_argument("--close", metavar="SESSION_ID", help="close a session: full pipeline + seal")
    ap.add_argument("--machine", default=None, help="machine label to record on --open")
    ap.add_argument("--status", action="store_true", help="list ledger entries + unresolved recovery")
    ap.add_argument("--recovery-scan", action="store_true", help="scan for stale OPEN sessions, create candidates")
    ap.add_argument("--recovery-threshold-hours", type=float, default=DEFAULT_RECOVERY_THRESHOLD_HOURS)
    ap.add_argument("--resolve-recovery", metavar="SESSION_ID", help="mark a recovery candidate resolved")
    ap.add_argument("--note", default=None, help="note for --resolve-recovery")
    ap.add_argument("--resolved-by", default=None, help="who/what resolved it, for --resolve-recovery")
    args = ap.parse_args()

    if args.topic_dir:
        TOPIC = pathlib.Path(args.topic_dir).resolve()
        SESSIONS_DIR = TOPIC / "_sessions"
        RECOVERY_DIR = SESSIONS_DIR / "recovery"
        GENERATED_DIR = TOPIC / "_generated"
        GENERATED_ROLLUP_DIR = TOPIC / "_rollup"

    if args.open:
        sys.exit(cmd_open(args.open, machine=args.machine))
    if args.close:
        sys.exit(cmd_close(args.close))
    if args.status:
        sys.exit(cmd_status())
    if args.recovery_scan:
        findings = cmd_recovery_scan(args.recovery_threshold_hours)
        for level, msg in findings:
            print(f"[{level}] {msg}")
        sys.exit(1 if any(f[0] == "ask" for f in findings) else 0)
    if args.resolve_recovery:
        sys.exit(cmd_resolve_recovery(args.resolve_recovery, note=args.note, resolved_by=args.resolved_by))
    if args.build:
        findings = run_build()
        for level, msg in findings:
            print(f"[{level}] {msg}")
        sys.exit(0)
    if args.test:
        findings = run_tests()
        for level, msg in findings:
            print(f"[{level}] {msg}")
        sys.exit(1 if any(f[0] == "ask" for f in findings) else 0)

    today = datetime.date.today()
    print(f"MEMORY CHECK — {TOPIC.name} — {today}")
    findings = run_validate()
    for level, msg in findings:
        print(f"[{level}] {msg}")
    if args.strict and any(f[0] == "ask" for f in findings):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
