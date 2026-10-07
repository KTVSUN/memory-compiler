#!/usr/bin/env python3
"""Email memory importer, public copy (described in ARCHITECTURE.md, section 7).

Reads the new Gmail of one mailbox, sorts threads into the topic matrix with two
model calls per thread, writes thread files, manifests, a ledger, knowledge notes
to LOG.md and NEEDS_YOU.md, and keeps one Gmail label in step with that list.

Nothing about the owner is in this file. It is in config.json, topic_matrix.md
and the two prompt files of the prompts folder: copy the .example files and edit
them. Comments that cite "spec" refer to the author's private build spec.
"""
import argparse
import base64
import csv
import hashlib
import html
import io
import json
import logging
import logging.handlers
import os
import re
import socket
import sqlite3
import sys
import tempfile
import time
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

if sys.stdout is None:  # pythonw.exe has no console
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

UTC_OFFSET_HOURS = 0  # the owner's fixed offset from UTC, no daylight saving: set yours here
LOCAL_TZ = timezone(timedelta(hours=UTC_OFFSET_HOURS))
HERE = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

CONFIG_KEYS = [
    "importer_pc", "mailbox", "aliases", "gmail_query_exclusions", "start_date",
    "overlap_hours", "secrets_dir", "program_dir", "needs_you_path", "status_path",
    "anthropic_model", "stage_a_batch_size", "stage_a_snippet_chars",
    "stage_b_body_chars_per_message", "stage_b_attachment_chars_each",
    "stage_b_total_chars", "attachment_max_mb", "zip_depth", "stale_days",
    "log_md_quiet_minutes", "gmail_label_enabled", "gmail_label_name", "pipelines",
    "project_logs", "conditional_pipelines", "project_log_titles",
]
# Pipelines whose matrix code only applies when Stage B says pipeline_item are listed
# in config.json, key conditional_pipelines (spec section 3).

LEDGER_COLS = [
    "run_ts", "thread_id", "last_message_id", "first_date", "last_date", "from_latest",
    "subject", "delivered_to", "topic_stage_a", "topic_final", "confidence", "pipeline",
    "demand", "demand_reason", "knowledge", "ny_id", "expected_event_id", "thread_file",
    "attachments_saved", "attachments_not_read", "message_count", "language",
]
MANIFEST_COLS = ["thread_id", "message_id", "date", "from", "to", "cc", "subject",
                 "attachment_count", "attachment_filenames", "attachment_ids"]
EX_COLS = ["ex_id", "created_ts", "thread_id", "topic_code", "pipeline", "expected",
           "from", "asked_on", "status", "fulfilled_ts", "fulfilled_message_id"]
RETRY_COLS = ["first_failed_ts", "last_failed_ts", "attempts", "thread_id", "message_id",
              "step", "error"]
STATUS_COLS = ["ts", "item", "action", "value", "chat", "note"]

LOG_HEADER = """Dated facts tied to this project that are not documents: a remark in a call, a voice message, a rule stated in an email, a figure someone confirmed. Append-only, newest last. Two writers share the format: a session (on "log this" or "file this") and the email importer (knowledge notes). Not read at session start; searched when a question needs it.

Format:

```
## YYYY-MM-DD — [Topic/Subtopic]
- Source: who, via what channel (for mail: the sender, via email, thread "<subject>")
- Fact: the information, compressed but complete, with the figure or rule itself
- Triggers: pending action and who owns it, or "none"
- Detail note: path of the thread file or note, relative to this file (optional)
- Importer: run YYYY-MM-DD HH:MM, ledger row N (machine entries only)
```

---
"""

# The two system prompts are the owner's own text and live in files, not here:
# <program_dir>\prompts\stage_a_system.txt and stage_b_system.txt (copy the two
# .example files and edit them). Stage A must keep the placeholders {MATRIX} and
# {CORRECTIONS}; Stage B must keep {TOPIC} and {PIPELINES}.
PROMPT_PLACEHOLDERS = {"stage_a_system.txt": ("{MATRIX}", "{CORRECTIONS}"),
                       "stage_b_system.txt": ("{TOPIC}", "{PIPELINES}")}


def load_prompt(cfg, name):
    p = Path(cfg["program_dir"]) / "prompts" / name
    try:
        text = p.read_text(encoding="utf-8-sig").rstrip("\n")
    except OSError:
        raise ImporterError("prompt file missing: %s (copy %s next to it and edit it)"
                            % (p, name.replace(".txt", ".example.txt")))
    for ph in PROMPT_PLACEHOLDERS[name]:
        if ph not in text:
            raise ImporterError("prompt file %s lacks the placeholder %s" % (p, ph))
    return text


RETRY_LINE = "Your previous answer was not valid JSON. Answer with the JSON only."


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
class ImporterError(Exception):
    pass


class MatrixError(ImporterError):
    def __init__(self, line_no, msg):
        super().__init__(f"topic_matrix.md line {line_no}: {msg}")
        self.line_no = line_no


class ModelFormatError(ImporterError):
    pass


def now_local():
    return datetime.now(LOCAL_TZ)


def ts_local(dt=None):
    return (dt or now_local()).strftime("%Y-%m-%d %H:%M")


_log_handler = None


def setup_log(secrets_dir):
    global _log_handler
    try:
        Path(secrets_dir).mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(
            Path(secrets_dir) / "run.log", maxBytes=5 * 1024 * 1024, backupCount=4,
            encoding="utf-8")
        h.setFormatter(logging.Formatter("%(message)s"))
        _log_handler = logging.getLogger("emi")
        _log_handler.setLevel(logging.INFO)
        _log_handler.handlers = [h]
    except Exception:
        _log_handler = None


def log(level, step, msg):
    msg = str(msg).replace("\r", " ").replace("\n", " ")
    line = "%s | %s local | %s | %s | %s" % (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        now_local().strftime("%H:%M"), level, step, msg)
    if _log_handler:
        try:
            _log_handler.info(line)
        except Exception:
            pass
    try:
        print(line)
    except Exception:
        pass


def atomic_write(path, text, bom=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def read_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path, cols, rows):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists() or p.stat().st_size == 0
    with open(p, "w" if new else "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        if new:
            w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def write_csv(path, cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    atomic_write(path, buf.getvalue(), bom=True)


def slugify(subject):
    s = subject or ""
    while True:
        n = re.sub(r"^\s*(re|fw|fwd|rv)\s*:\s*", "", s, flags=re.I)
        if n == s:
            break
        s = n
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:60].strip("-")) or "no-subject"


def addr_list(header_value):
    from email.utils import getaddresses
    return [a.lower() for _, a in getaddresses([header_value or ""]) if a]


def domain_of(addr):
    return addr.split("@")[-1].lower().strip() if "@" in addr else addr.lower().strip()


def cell(s):
    return str(s or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6",
             "ul", "ol", "blockquote", "section", "article", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(s):
    p = _HTMLText()
    try:
        p.feed(s)
        p.close()
    except Exception:
        return html.unescape(re.sub(r"<[^>]+>", "", s))
    t = "".join(p.out)
    t = re.sub(r"[ \t\r\f\v]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ----------------------------------------------------------------------------
# config and matrix
# ----------------------------------------------------------------------------
def load_config(path=None):
    path = Path(path or HERE / "config.json")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        raise ImporterError(f"config.json: {e}")
    unknown = [k for k in cfg if k not in CONFIG_KEYS]
    if unknown:
        raise ImporterError("config.json: unknown key(s): " + ", ".join(unknown))
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if missing:
        raise ImporterError("config.json: missing key(s): " + ", ".join(missing))
    return cfg


class Topic:
    def __init__(self, code, meaning, project, root, pipeline, path_override, line_no):
        self.code = code
        self.meaning = meaning
        self.project = project
        self.root = root
        self.pipeline = pipeline
        self.path_override = path_override
        self.line_no = line_no
        self.segments = code.split("/")[1:] if "/" in code else []
        self.bucket = project == "NOBUCKET"

    @property
    def folder(self):
        """Destination folder T (Input\\Emails\\ is created under it); None for buckets."""
        if self.bucket:
            return None
        if self.path_override:
            return Path(self.path_override)
        if self.segments == ["ROOT"]:
            return Path(self.root) / "Knowledge stack"
        return Path(self.root).joinpath(*self.segments)

    @property
    def check_folder(self):
        """Folder that must exist at start (ROOT codes: the project root, because
        Knowledge stack\\Input\\Emails\\ is created when missing, spec section 3)."""
        if self.bucket:
            return None
        if self.segments == ["ROOT"] and not self.path_override:
            return Path(self.root)
        return self.folder

    @property
    def label(self):
        """Topic/Subtopic for the LOG.md heading (code without the project code)."""
        if self.segments:
            return "/".join(self.segments)
        return self.code


class Matrix:
    def __init__(self, topics):
        self.topics = topics
        self.by_code = {t.code: t for t in topics}

    def lines_for_prompt(self):
        return "\n".join(f"- {t.code} — {t.meaning}" for t in self.topics)


def parse_matrix(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    topics, seen = [], {}
    project, root = None, None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith("Owner:") or s.startswith("Aliases:"):
            continue
        if s.startswith("## "):
            m = re.match(r"^## ([A-Z][A-Z0-9-]*) = (.+)$", s)
            if not m:
                raise MatrixError(n, "bad project header: " + s)
            project, root = m.group(1), None
            continue
        if s.startswith("# "):
            continue
        if s.startswith("Root:"):
            if project is None or project == "NOBUCKET":
                raise MatrixError(n, "Root outside a project block: " + s)
            if root is not None:
                raise MatrixError(n, "second Root in block " + project)
            root = s[len("Root:"):].strip()
            if not re.match(r"^[A-Za-z]:\\", root):
                raise MatrixError(n, "Root is not an absolute Windows path: " + root)
            continue
        if s.startswith("- "):
            if project is None:
                raise MatrixError(n, "code line before any project block")
            m = re.match(r"^- (\S(?:.*?\S)?) — (.+)$", s)
            if not m:
                raise MatrixError(n, "code line has no ' — ' separator: " + s)
            code, rest = m.group(1), m.group(2)
            parts = [p.strip() for p in rest.split(" | ")]
            meaning, pipeline, path_override = parts[0], "", ""
            for tok in parts[1:]:
                if tok.startswith("pipeline="):
                    pipeline = tok[len("pipeline="):].strip()
                elif tok.startswith("path="):
                    path_override = tok[len("path="):].strip()
                else:
                    raise MatrixError(n, "unknown token after '|': " + tok)
            if project == "NOBUCKET":
                if "/" in code or not re.match(r"^[A-Z][A-Z-]*$", code):
                    raise MatrixError(n, "bucket code expected: " + code)
            else:
                if root is None:
                    raise MatrixError(n, "code line before Root: in block " + project)
                if code != project and not code.startswith(project + "/"):
                    raise MatrixError(n, f"code {code} does not start with {project}")
            if code in seen:
                raise MatrixError(n, f"duplicate code {code} (first on line {seen[code]})")
            seen[code] = n
            if path_override and not re.match(r"^[A-Za-z]:\\", path_override):
                raise MatrixError(n, "path= is not an absolute Windows path")
            topics.append(Topic(code, meaning, project, root, pipeline, path_override, n))
            continue
        raise MatrixError(n, "unrecognised line: " + s)
    if not topics:
        raise MatrixError(0, "no codes found")
    for must in ("NOISE",):
        if must not in seen:
            raise MatrixError(0, f"code {must} missing")
    for t in topics:
        cf = t.check_folder
        if cf is not None and not Path(cf).is_dir():
            raise MatrixError(t.line_no, f"destination folder missing for {t.code}: {cf}")
    return Matrix(topics)


# ----------------------------------------------------------------------------
# state (sqlite)
# ----------------------------------------------------------------------------
class State:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS processed(message_id TEXT PRIMARY KEY, thread_id TEXT, run_ts TEXT);
        CREATE TABLE IF NOT EXISTS threads(thread_id TEXT PRIMARY KEY, fingerprint TEXT, topic_final TEXT,
            demand TEXT, ny_id TEXT, last_run_ts TEXT);
        CREATE TABLE IF NOT EXISTS deferred_notes(id INTEGER PRIMARY KEY, log_path TEXT, note_text TEXT, created_ts TEXT);
        CREATE TABLE IF NOT EXISTS runs(run_ts TEXT PRIMARY KEY, ok INTEGER, listed INTEGER, new_messages INTEGER,
            threads_judged INTEGER, filed INTEGER, needs_you INTEGER, errors INTEGER);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()

    def meta_get(self, k, default=None):
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
        return r[0] if r else default

    def meta_set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (k, str(v)))
        self.db.commit()

    def next_id(self, prefix):
        n = int(self.meta_get(prefix + "_counter", "0")) + 1
        self.meta_set(prefix + "_counter", n)
        return "%s-%04d" % (prefix, n)

    def is_processed(self, mid):
        return self.db.execute("SELECT 1 FROM processed WHERE message_id=?", (mid,)).fetchone() is not None

    def mark_processed(self, thread_id, mids, run_ts):
        self.db.executemany("INSERT OR IGNORE INTO processed(message_id,thread_id,run_ts) VALUES(?,?,?)",
                            [(m, thread_id, run_ts) for m in mids])
        self.db.commit()

    def thread_get(self, tid):
        r = self.db.execute("SELECT thread_id,fingerprint,topic_final,demand,ny_id,last_run_ts FROM threads "
                            "WHERE thread_id=?", (tid,)).fetchone()
        if not r:
            return None
        return dict(zip(["thread_id", "fingerprint", "topic_final", "demand", "ny_id", "last_run_ts"], r))

    def thread_set(self, tid, fingerprint, topic_final, demand, ny_id, run_ts):
        self.db.execute("INSERT OR REPLACE INTO threads VALUES(?,?,?,?,?,?)",
                        (tid, fingerprint, topic_final, demand, ny_id, run_ts))
        self.db.commit()

    def thread_by_ny(self, ny):
        r = self.db.execute("SELECT thread_id FROM threads WHERE ny_id=?", (ny,)).fetchone()
        return r[0] if r else None


# ----------------------------------------------------------------------------
# Gmail
# ----------------------------------------------------------------------------
class Gmail:
    def __init__(self, secrets_dir):
        tok = Path(secrets_dir) / "token.json"
        if not tok.exists():
            raise ImporterError("Gmail sign-in needed: token.json is missing in %s. "
                                "Run: python email_importer.py --auth" % secrets_dir)
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google.auth.exceptions import RefreshError
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
        if not creds.valid:
            try:
                creds.refresh(Request())
                tok.write_text(creds.to_json(), encoding="utf-8")
            except RefreshError:
                raise ImporterError("Google token expired or revoked. Run: python email_importer.py --auth")
        self.svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._label_id = None

    def _exec(self, req):
        """Spec 11: retry on 429 and 5xx. Gmail also signals its per-minute quota with
        403 rateLimitExceeded / userRateLimitExceeded; those wait and retry too, up to
        6 times (10, 20, 40, 60, 60, 60 s), because the first run over a month hits it."""
        from googleapiclient.errors import HttpError
        waits = [10, 20, 40, 60, 60, 60]
        for attempt in range(len(waits) + 1):
            try:
                time.sleep(0.05)  # about 20 calls a second at most, well under the quota
                return req.execute()
            except HttpError as e:
                status = getattr(e.resp, "status", 0)
                text = str(e)
                rate = status == 403 and ("rateLimitExceeded" in text or "userRateLimitExceeded" in text)
                if (status in (429, 500, 502, 503, 504) or rate) and attempt < len(waits):
                    log("WARN", "gmail", "HTTP %s, waiting %d s before retry" % (status, waits[attempt]))
                    time.sleep(waits[attempt])
                    continue
                raise

    def list_message_ids(self, query):
        out, tok = [], None
        while True:
            r = self._exec(self.svc.users().messages().list(
                userId="me", q=query, pageToken=tok, maxResults=500))
            out += [(m["id"], m["threadId"]) for m in r.get("messages", [])]
            tok = r.get("nextPageToken")
            if not tok:
                return out

    def get_thread(self, tid):
        return self._exec(self.svc.users().threads().get(userId="me", id=tid, format="full"))

    def get_attachment(self, mid, aid):
        r = self._exec(self.svc.users().messages().attachments().get(userId="me", messageId=mid, id=aid))
        return b64d(r.get("data", ""))

    def profile(self):
        return self._exec(self.svc.users().getProfile(userId="me"))

    def label_id(self, name, create=True):
        if self._label_id:
            return self._label_id
        r = self._exec(self.svc.users().labels().list(userId="me"))
        for l in r.get("labels", []):
            if l["name"] == name:
                self._label_id = l["id"]
                return self._label_id
        if not create:
            return None
        r = self._exec(self.svc.users().labels().create(userId="me", body={
            "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}))
        self._label_id = r["id"]
        return self._label_id

    def threads_with_label(self, lid):
        out, tok = set(), None
        while True:
            r = self._exec(self.svc.users().threads().list(userId="me", labelIds=[lid], pageToken=tok,
                                                           maxResults=500))
            out |= {t["id"] for t in r.get("threads", [])}
            tok = r.get("nextPageToken")
            if not tok:
                return out

    def modify_thread(self, tid, add=None, remove=None):
        self._exec(self.svc.users().threads().modify(userId="me", id=tid, body={
            "addLabelIds": add or [], "removeLabelIds": remove or []}))


def b64d(s):
    if not s:
        return b""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _decode_part(part):
    data = b64d(part.get("body", {}).get("data", ""))
    cs = "utf-8"
    for h in part.get("headers", []):
        if h["name"].lower() == "content-type":
            m = re.search(r'charset="?([\w-]+)', h["value"], re.I)
            if m:
                cs = m.group(1)
    try:
        return data.decode(cs, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def walk_parts(part):
    yield part
    for p in part.get("parts", []) or []:
        yield from walk_parts(p)


def parse_message(m):
    """Gmail message resource -> dict."""
    hdr = {}
    for h in m.get("payload", {}).get("headers", []):
        hdr.setdefault(h["name"].lower(), h["value"])
    plain, htmls, atts = [], [], []
    for p in walk_parts(m.get("payload", {})):
        mime = p.get("mimeType", "")
        fn = p.get("filename") or ""
        body = p.get("body", {})
        if fn and (body.get("attachmentId") or body.get("data")):
            size = int(body.get("size", 0) or 0)
            if mime.startswith("image/") and size < 20000:
                continue  # signature or logo, not saved (spec 6.3)
            atts.append({"name": fn, "id": body.get("attachmentId", ""), "mime": mime, "size": size,
                         "inline_data": body.get("data", "")})
        elif mime == "text/plain" and body.get("data"):
            plain.append(_decode_part(p))
        elif mime == "text/html" and body.get("data"):
            htmls.append(_decode_part(p))
    text = "\n".join(plain).strip() if plain else html_to_text("\n".join(htmls)) if htmls else ""
    dt = datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)
    labels = m.get("labelIds", [])
    return {
        "id": m["id"], "thread_id": m["threadId"], "dt": dt, "subject": hdr.get("subject", ""),
        "from": hdr.get("from", ""), "to": hdr.get("to", ""), "cc": hdr.get("cc", ""),
        "delivered_to": hdr.get("delivered-to", ""), "body": text, "atts": atts,
        "snippet": m.get("snippet", ""), "labels": labels, "sent": "SENT" in labels,
    }


def parse_thread(t):
    msgs = sorted((parse_message(m) for m in t.get("messages", [])), key=lambda x: x["dt"])
    return {"id": t["id"], "messages": msgs, "subject": msgs[0]["subject"] if msgs else "",
            "fingerprint": ",".join(sorted(m["id"] for m in msgs))}


# ----------------------------------------------------------------------------
# thread file, manifest
# ----------------------------------------------------------------------------
QUOTE_RE = re.compile(r"^(On .{5,200}wrote:|El .{5,200}escribi[oó]:|Le .{5,200}a [eé]crit\s*:|-{2,}\s*Original Message\s*-{2,}|>.*)$",
                      re.I)


def _norm(s):
    return re.sub(r"[\s>]+", " ", s).strip().lower()


def strip_quoted(bodies_so_far, body):
    """Replace a quoted tail that merely repeats a message already transcribed above."""
    if not bodies_so_far:
        return body
    lines = body.split("\n")
    for i, ln in enumerate(lines):
        if QUOTE_RE.match(ln.strip()):
            tail = "\n".join(lines[i:])
            nt = _norm(tail)
            prev = " ".join(_norm(b) for b in bodies_so_far)
            core = re.sub(r"^(on .{5,200}wrote:|el .{5,200}escribi.{1,2}:)", "", nt).strip()
            if core and core in prev:
                return "\n".join(lines[:i]).rstrip() + ("\n" if i else "") + "[quoted thread omitted]"
            return body
    return body


def render_thread(th, saved_line=None, verdict_line=None, max_body=None):
    msgs = th["messages"]
    people = []
    for m in msgs:
        for h in (m["from"], m["to"], m["cc"]):
            for a in addr_list(h):
                if a not in people:
                    people.append(a)
    out = ["# " + (th["subject"] or "(no subject)"), "",
           "**Date range:** %s to %s" % (msgs[0]["dt"].strftime("%Y-%m-%d"), msgs[-1]["dt"].strftime("%Y-%m-%d")),
           "**Thread ID:** " + th["id"],
           "**Participants:** " + ", ".join(people)]
    if saved_line is not None:
        out.append("**Saved attachments:** " + saved_line)
    if verdict_line is not None:
        out.append("**Importer verdict:** " + verdict_line)
    out += ["", "---", ""]
    prev = []
    for i, m in enumerate(msgs, 1):
        out.append("## Message %d — %s — From: %s — To: %s — Cc: %s" % (
            i, m["dt"].strftime("%Y-%m-%d %H:%M"), ", ".join(addr_list(m["from"])) or m["from"],
            ", ".join(addr_list(m["to"])), ", ".join(addr_list(m["cc"]))))
        out.append("**Message ID:** " + m["id"])
        if m["atts"]:
            out.append("**Attachments:** " + "; ".join(
                "%s (%s)" % (a["name"], att_kind(a["name"], a["mime"])) for a in m["atts"]))
        out.append("")
        body = strip_quoted(prev, m["body"])
        prev.append(m["body"])
        if max_body and len(body) > max_body:
            body = body[:max_body] + "\n[truncated]"
        out += [body, "", "---", ""]
    return "\n".join(out)


def manifest_rows(th):
    rows = []
    for m in th["messages"]:
        rows.append({
            "thread_id": th["id"], "message_id": m["id"], "date": m["dt"].strftime("%Y-%m-%d %H:%M"),
            "from": ", ".join(addr_list(m["from"])), "to": ", ".join(addr_list(m["to"])),
            "cc": ", ".join(addr_list(m["cc"])), "subject": th["subject"],
            "attachment_count": len(m["atts"]),
            "attachment_filenames": ";".join(a["name"] for a in m["atts"]),
            "attachment_ids": ";".join(a["id"] for a in m["atts"]),
        })
    return rows


def known_manifest_ids(emails_dir):
    ids = set()
    d = Path(emails_dir)
    if d.is_dir():
        for p in d.glob("manifest*.csv"):
            try:
                ids |= {r.get("message_id", "") for r in read_csv(p)}
            except Exception:
                pass
    return ids


# ----------------------------------------------------------------------------
# attachments
# ----------------------------------------------------------------------------
ATT_KINDS = {".pdf": "PDF", ".xlsx": "Excel", ".xls": "Excel", ".csv": "CSV", ".docx": "Word", ".doc": "Word",
             ".pptx": "PowerPoint", ".xml": "XML", ".zip": "ZIP", ".jpg": "image", ".jpeg": "image",
             ".png": "image", ".gif": "image", ".heic": "image", ".txt": "text", ".ics": "calendar invite"}


def att_kind(name, mime):
    """Readable type for the Attachments line of a thread file (Gmail attachment ids stay in
    the manifest CSV only)."""
    ext = os.path.splitext(name or "")[1].lower()
    if ext in ATT_KINDS:
        return ATT_KINDS[ext]
    if (mime or "").startswith("image/"):
        return "image"
    return ext[1:].upper() if ext else (mime or "file")


def extract_text(name, mime, data, cfg, zip_depth_left):
    """Return (text or None, reason or None). Table of spec 6.3."""
    ext = Path(name).suffix.lower()
    try:
        if ext == ".pdf" or mime == "application/pdf":
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in r.pages]
            txt = "\n".join(pages)
            if not pages or len(txt.strip()) / max(len(pages), 1) < 40:
                return None, "scanned PDF, no text layer"
            return txt, None
        if ext == ".docx":
            import docx
            d = docx.Document(io.BytesIO(data))
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append("\t".join(c.text for c in row.cells))
            return "\n".join(parts), None
        if ext == ".doc":
            return None, "legacy .doc"
        if ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:3]:
                parts.append("[sheet %s]" % ws.title)
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 200:
                        break
                    parts.append("\t".join("" if v is None else str(v) for v in row))
            return "\n".join(parts), None
        if ext == ".xls":
            return None, "legacy .xls"
        if ext == ".xml" or mime in ("text/xml", "application/xml"):
            return data.decode("utf-8", errors="replace"), None
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".heic") or mime.startswith("image/"):
            return None, "image"
        if ext == ".zip" or mime == "application/zip":
            return None, "zip"  # handled by the caller
    except Exception as e:
        return None, "read error: %s" % str(e).splitlines()[-1][:80]
    return None, "type %s" % (ext or mime or "unknown")


def build_attachments(gmail, th, cfg):
    """Download attachments of all messages; returns list of dicts with name, saved_name, text, reason."""
    out = []
    maxb = cfg["attachment_max_mb"] * 1024 * 1024
    for m in th["messages"]:
        ymd = m["dt"].strftime("%Y%m%d")
        for a in m["atts"]:
            rec = {"orig": a["name"], "mime": a["mime"], "msg_id": m["id"], "ymd": ymd, "size": a["size"],
                   "saved_name": "%s_%s" % (ymd, a["name"]), "data": None, "text": None, "reason": None,
                   "save": True}
            if a["size"] > maxb:
                rec.update(save=False, reason="not saved: %.1f MB over limit" % (a["size"] / 1048576))
                out.append(rec)
                continue
            data = b64d(a["inline_data"]) if (a["inline_data"] and not a["id"]) else gmail.get_attachment(m["id"], a["id"])
            rec["data"] = data
            rec["size"] = len(data)
            txt, reason = extract_text(a["name"], a["mime"], data, cfg, cfg["zip_depth"])
            if reason == "zip":
                out.append(rec)
                rec["text"], rec["reason"] = None, None
                out.extend(zip_members(rec, data, cfg))
                if not any(x.get("parent") is rec for x in out):
                    pass
                continue
            rec["text"], rec["reason"] = txt, ("not read: " + reason) if reason else None
            out.append(rec)
    return out


def zip_members(zrec, data, cfg):
    res = []
    stem = Path(zrec["orig"]).stem
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        zrec["reason"] = "not read: bad zip"
        return res
    if any(i.flag_bits & 0x1 for i in zf.infolist()):
        zrec["reason"] = "not read: encrypted zip"
        return res
    zrec["reason"] = None
    maxb = cfg["attachment_max_mb"] * 1024 * 1024
    for info in zf.infolist():
        if info.is_dir():
            continue
        base = Path(info.filename).name
        rec = {"orig": "%s/%s" % (zrec["orig"], info.filename), "mime": "", "msg_id": zrec["msg_id"],
               "ymd": zrec["ymd"], "size": info.file_size, "data": None, "text": None, "reason": None,
               "save": True, "parent": zrec, "saved_name": "%s_%s_%s" % (zrec["ymd"], stem, base)}
        if info.file_size > maxb:
            rec.update(save=False, reason="not saved: %.1f MB over limit" % (info.file_size / 1048576))
            res.append(rec)
            continue
        try:
            d = zf.read(info)
        except Exception as e:
            rec.update(save=False, reason="not read: %s" % str(e).splitlines()[-1][:60])
            res.append(rec)
            continue
        rec["data"], rec["size"] = d, len(d)
        txt, reason = extract_text(base, "", d, cfg, 0)
        if reason == "zip":
            reason = "nested zip"
        rec["text"], rec["reason"] = txt, ("not read: " + reason) if reason else None
        res.append(rec)
    return res


def save_attachments(att_recs, emails_dir):
    """Write attachment bytes next to the thread files. Returns list of final saved names (set in rec)."""
    d = Path(emails_dir)
    d.mkdir(parents=True, exist_ok=True)
    for r in att_recs:
        if not r["save"] or r["data"] is None:
            continue
        name = r["saved_name"]
        p = d / name
        h = hashlib.sha1(r["data"]).hexdigest()
        if p.exists() and hashlib.sha1(p.read_bytes()).hexdigest() != h:
            name = "%s_%s_%s" % (r["ymd"], r["msg_id"][-6:], name.split("_", 1)[1] if "_" in name else name)
            p = d / name
        if not p.exists() or hashlib.sha1(p.read_bytes()).hexdigest() != h:
            p.write_bytes(r["data"])
        r["saved_name"] = name


def attachments_prompt_block(att_recs, cfg):
    blocks = []
    for r in att_recs:
        head = "### Attachment: %s (%s, %.0f kB)" % (r["orig"], r["mime"] or "?", r["size"] / 1024)
        if r["text"] is not None:
            blocks.append(head + "\n" + r["text"][:cfg["stage_b_attachment_chars_each"]])
        else:
            blocks.append(head + "\n[%s]" % (r["reason"] or "not read: unknown"))
    return blocks


# ----------------------------------------------------------------------------
# Claude
# ----------------------------------------------------------------------------
class Claude:
    def __init__(self, cfg):
        import anthropic
        key_file = Path(cfg["secrets_dir"]) / "anthropic_key.txt"
        if not key_file.exists():
            raise ImporterError("anthropic_key.txt missing in " + cfg["secrets_dir"])
        key = key_file.read_text(encoding="utf-8").strip()
        self.client = anthropic.Anthropic(api_key=key)
        self.model = cfg["anthropic_model"]

    def raw(self, system, user, max_tokens):
        r = self.client.messages.create(model=self.model, max_tokens=max_tokens,
                                        system=system, messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")

    def json_call(self, system, user, max_tokens, validate):
        last = None
        for attempt in (0, 1):
            u = user if attempt == 0 else user + "\n\n" + RETRY_LINE
            text = self.raw(system, u, max_tokens)
            try:
                obj = parse_json(text)
                validate(obj)
                return obj
            except ModelFormatError as e:
                log("WARN", "claude", "%s; answer began: %s" % (e, text[:300]))
                last = e
        raise last


def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        for o, c in (("[", "]"), ("{", "}")):
            i, j = t.find(o), t.rfind(c)
            if i != -1 and j > i:
                try:
                    return json.loads(t[i:j + 1])
                except Exception:
                    pass
    raise ModelFormatError("answer is not valid JSON")


def corrections_text(state_rows, lookup):
    rows = []
    last = {}
    for r in state_rows:
        if (r.get("action") or "").strip() in ("done", "snooze", "correct", "reopen"):
            last[(r.get("item") or "").strip()] = r
    for item, r in last.items():
        if r["action"].strip() == "correct" and r.get("value", "").strip():
            info = lookup(item)
            if info:
                rows.append((r.get("ts", ""), "%s | %s | %s" % (info[0], info[1], r["value"].strip())))
    rows.sort(key=lambda x: x[0])
    rows = rows[-50:]
    return "\n".join(x[1] for x in rows) if rows else "none"


def stage_a(claude, cfg, matrix, threads, corrections, failures=None):
    """Returns {thread_id: answer}. Threads whose answer stays unusable after splitting
    are put in failures {thread_id: error} (a dict the caller passes in)."""
    if failures is None:
        failures = {}
    system = load_prompt(cfg, "stage_a_system.txt").replace("{MATRIX}", matrix.lines_for_prompt()).replace("{CORRECTIONS}", corrections)
    results = {}
    codes = set(matrix.by_code)
    n = cfg["stage_a_batch_size"]

    def validate_for(ids):
        def validate(obj):
            if not isinstance(obj, list) or len(obj) != len(ids):
                raise ModelFormatError("Stage A answer is not an array of the right length")
            for o, tid in zip(obj, ids):
                if not isinstance(o, dict) or o.get("thread_id") != tid:
                    raise ModelFormatError("Stage A thread_id mismatch")
                if o.get("topic_code") not in codes:
                    raise ModelFormatError("Stage A code not in matrix: %r" % o.get("topic_code"))
                if o.get("confidence") not in ("H", "M", "L"):
                    raise ModelFormatError("Stage A bad confidence")
        return validate

    for i in range(0, len(threads), n):
        batch = threads[i:i + n]
        payload = []
        for th in batch:
            ms = th["messages"]
            senders = []
            for m in ms:
                for a in addr_list(m["from"]):
                    if a not in senders:
                        senders.append(a)
            last = ms[-1]
            payload.append({
                "thread_id": th["id"], "date": ms[0]["dt"].strftime("%Y-%m-%d"), "from": senders,
                "to": sorted({a for m in ms for a in addr_list(m["to"])}),
                "cc": sorted({a for m in ms for a in addr_list(m["cc"])}),
                "delivered_to": delivered_alias(th, cfg), "subject": th["subject"],
                "message_count": len(ms), "last_from_owner": is_from_owner(last, cfg),
                "snippet": (last["body"] or last["snippet"])[:cfg["stage_a_snippet_chars"]],
            })
        for o in _stage_a_batch(claude, system, payload, validate_for, failures):
            results[o["thread_id"]] = o
    return results


def _stage_a_batch(claude, system, payload, validate_for, failures):
    """One Stage A call; if the answer cannot be used, split the batch in two and try
    each half, down to one thread. A single thread that still fails goes to failures."""
    try:
        return claude.json_call(system, json.dumps(payload, ensure_ascii=False), 4000,
                                validate_for([p["thread_id"] for p in payload]))
    except ModelFormatError as e:
        if len(payload) == 1:
            failures[payload[0]["thread_id"]] = str(e)
            return []
        mid = len(payload) // 2
        log("WARN", "stage A", "batch of %d failed (%s), splitting" % (len(payload), e))
        return (_stage_a_batch(claude, system, payload[:mid], validate_for, failures) +
                _stage_a_batch(claude, system, payload[mid:], validate_for, failures))


def stage_b(claude, cfg, matrix, th, code, att_recs, headers_only=False):
    topic = matrix.by_code[code]
    pipes = "\n".join("%s: %s" % (k, v) for k, v in cfg["pipelines"].items())
    system = (load_prompt(cfg, "stage_b_system.txt").replace("{TOPIC}", "%s (%s)" % (code, topic.meaning))
              .replace("{PIPELINES}", pipes))
    if headers_only:
        m = th["messages"][-1]
        user = "Subject: %s\nFrom: %s\nTo: %s\nDate: %s\nMessages in thread: %d\nSnippet: %s" % (
            th["subject"], m["from"], m["to"], m["dt"].strftime("%Y-%m-%d %H:%M"), len(th["messages"]),
            m["snippet"])
        user = "**Thread ID:** %s\n%s" % (th["id"], user)
    else:
        body = render_thread(th, max_body=cfg["stage_b_body_chars_per_message"])
        blocks = attachments_prompt_block(att_recs, cfg)
        total = cfg["stage_b_total_chars"]
        user = body
        for b in blocks:
            if len(user) + len(b) + 2 > total:
                b = b[:max(0, total - len(user) - 2)]
            user += "\n\n" + b
            if len(user) >= total:
                break
        if len(user) > total:
            # keep the latest messages in full first: drop from the start of the body
            user = user[:200] + "\n[...earlier text cut...]\n" + user[-(total - 230):]
    codes = set(matrix.by_code)

    def validate(o):
        if not isinstance(o, dict):
            raise ModelFormatError("Stage B answer is not an object")
        if o.get("demand") not in ("NEEDS-YOU", "FOLLOW-UP", "INFO", "NOISE"):
            raise ModelFormatError("Stage B bad demand: %r" % o.get("demand"))

    o = claude.json_call(system, user, 1500, validate)
    if o.get("topic_code") not in codes:
        log("WARN", "stage B", "thread %s: code %r not in matrix, Stage A code %s kept" % (th["id"], o.get("topic_code"), code))
        o["topic_code"], o["topic_changed"] = code, False
    o.setdefault("topic_changed", False)
    o.setdefault("demand_reason", "")
    o.setdefault("needs_you_line", "")
    k = o.get("knowledge") or {}
    o["knowledge"] = {"present": bool(k.get("present")), "fact": k.get("fact", "") or "", "source": k.get("source", "") or ""}
    e = o.get("expected_event") or {}
    o["expected_event"] = {"present": bool(e.get("present")), "pipeline": e.get("pipeline", "") or "",
                           "expected": e.get("expected", "") or "", "from": e.get("from", "") or ""}
    o["pipeline_item"] = bool(o.get("pipeline_item"))
    o.setdefault("language", "")
    return o


def is_from_owner(m, cfg):
    mine = {cfg["mailbox"].lower()} | {a.lower() for a in cfg["aliases"]}
    return m["sent"] or any(a in mine for a in addr_list(m["from"]))


def delivered_alias(th, cfg):
    aliases = {a.lower() for a in cfg["aliases"]}
    for m in th["messages"]:
        for a in addr_list(m["delivered_to"]):
            if a in aliases:
                return a
    for m in th["messages"]:
        for a in addr_list(m["to"]) + addr_list(m["cc"]):
            if a in aliases:
                return a
    return ""


# ----------------------------------------------------------------------------
# the importer
# ----------------------------------------------------------------------------
class Importer:
    def __init__(self, cfg, dry_run=False, out_csv=None, ledger=None):
        self.cfg = cfg
        self.dry = dry_run
        self.out_csv = out_csv
        self.secrets = Path(cfg["secrets_dir"])
        self.prog = Path(cfg["program_dir"])
        self.ledger_path = Path(ledger) if ledger else self.prog / "ledger.csv"
        self.ex_path = self.prog / "expected_events.csv"
        self.retry_path = self.prog / "retry.csv"
        self.status_md = self.prog / "RUN_STATUS.md"
        self.needs_path = Path(cfg["needs_you_path"])
        self.status_csv = Path(cfg["status_path"])
        self.matrix = None
        self.state = None
        self.gmail = None
        self.claude = None
        self.run_ts = ts_local()
        self.counters = dict(listed=0, new_messages=0, judged=0, filed=0, needs_you=0, errors=0)

    # ---- plumbing -------------------------------------------------------
    def open(self, need_state=True):
        self.matrix = parse_matrix(self.prog / "topic_matrix.md")
        load_prompt(self.cfg, "stage_a_system.txt")  # a missing prompt stops the run here
        load_prompt(self.cfg, "stage_b_system.txt")
        if need_state:
            self.secrets.mkdir(parents=True, exist_ok=True)
            self.state = State(self.secrets / "state.sqlite")

    def ensure_clients(self):
        if self.gmail is None:
            self.gmail = Gmail(self.secrets)
        if self.claude is None:
            self.claude = Claude(self.cfg)

    def status_rows(self):
        return read_csv(self.status_csv)

    def ledger_rows(self):
        return read_csv(self.ledger_path)

    def latest_by_thread(self):
        d = {}
        for r in self.ledger_rows():
            d[r["thread_id"]] = r
        return d

    def lookup_thread_info(self, item):
        """(sender, subject) for a correction item (NY id or thread id)."""
        tid = item
        if re.match(r"^NY-\d+$", item) and self.state:
            tid = self.state.thread_by_ny(item) or item
        r = self.latest_by_thread().get(tid)
        return (r["from_latest"], r["subject"]) if r else None

    # ---- run -----------------------------------------------------------
    def run(self):
        cfg = self.cfg
        lock = self.secrets / "run.lock"
        if not self.dry:
            if lock.exists() and time.time() - lock.stat().st_mtime < 50 * 60:
                log("WARN", "lock", "another run holds run.lock, exiting")
                return 0
            lock.write_text("%d %s" % (os.getpid(), self.run_ts), encoding="utf-8")
        try:
            return self._run()
        finally:
            if not self.dry:
                try:
                    lock.unlink()
                except OSError:
                    pass

    def _run(self):
        cfg = self.cfg
        err = None
        try:
            self.open()
            self.ensure_clients()
            status_rows = self.status_rows()
            self.apply_corrections(status_rows)
            threads = self.collect_threads()
            self.process_threads(threads, status_rows)
            if cfg["gmail_label_enabled"] and not self.dry:
                status_rows = self.park_label_removed(status_rows)
            self.rebuild_needs_you(status_rows)
            if cfg["gmail_label_enabled"] and not self.dry:
                self.label_sync(status_rows)
            self.flush_deferred_notes()
        except ImporterError as e:
            err = str(e)
        except Exception as e:  # unhandled
            err = "%s: %s" % (type(e).__name__, str(e).splitlines()[-1] if str(e) else "")
            log("ERROR", "run", err)
        self.finish(err)
        return 0

    def collect_threads(self):
        cfg = self.cfg
        last = self.state.meta_get("last_success")
        if last:
            since = datetime.fromisoformat(last) - timedelta(hours=cfg["overlap_hours"])
        else:
            since = datetime.strptime(cfg["start_date"], "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        q = "after:%d %s" % (int(since.timestamp()), cfg["gmail_query_exclusions"])
        ids = self.gmail.list_message_ids(q)
        self.counters["listed"] = len(ids)
        new = [(m, t) for m, t in ids if not self.state.is_processed(m)]
        self.counters["new_messages"] = len(new)
        tids = []
        for _, t in new:
            if t not in tids:
                tids.append(t)
        for r in read_csv(self.retry_path):
            if r.get("step") != "GIVEN UP" and int(r.get("attempts") or 0) < 5 and r["thread_id"] not in tids:
                tids.append(r["thread_id"])
        threads = []
        for t in tids:
            self.touch_lock()
            try:
                threads.append(parse_thread(self.gmail.get_thread(t)))
            except Exception as e:
                self.fail(t, "", "threads.get", e)
        return threads

    def touch_lock(self):
        """Keep run.lock fresh during a long run so a later hourly start does not treat it as stale."""
        if self.dry:
            return
        try:
            os.utime(self.secrets / "run.lock", None)
        except OSError:
            pass

    def fail(self, tid, mid, step, exc):
        msg = (str(exc).strip().splitlines() or [type(exc).__name__])[-1]
        log("ERROR", step, "thread %s: %s" % (tid, msg))
        self.counters["errors"] += 1
        if self.dry:
            return
        rows = read_csv(self.retry_path)
        now = ts_local()
        hit = False
        for r in rows:
            if r["thread_id"] == tid:
                r["last_failed_ts"], r["attempts"] = now, str(int(r.get("attempts") or 0) + 1)
                r["message_id"], r["error"] = mid or r.get("message_id", ""), msg
                r["step"] = "GIVEN UP" if int(r["attempts"]) >= 5 else step
                hit = True
        if not hit:
            rows.append({"first_failed_ts": now, "last_failed_ts": now, "attempts": "1", "thread_id": tid,
                         "message_id": mid, "step": step, "error": msg})
        write_csv(self.retry_path, RETRY_COLS, rows)

    def clear_retry(self, tid):
        if self.dry:
            return
        rows = read_csv(self.retry_path)
        keep = [r for r in rows if r["thread_id"] != tid]
        if len(keep) != len(rows):
            write_csv(self.retry_path, RETRY_COLS, keep)

    # ---- judging ----------------------------------------------------------
    def judge(self, th, a_result, force_stage_b_codes=True):
        """Return verdict dict. No writes. a_result is the Stage A object (or a synthetic one)."""
        cfg = self.cfg
        code = a_result["topic_code"]
        topic = self.matrix.by_code[code]
        v = {"stage_a": a_result["topic_code"], "confidence": a_result.get("confidence", ""),
             "topic_final": code, "pipeline": "", "demand": "NOISE", "reason": a_result.get("reason", ""),
             "line": "", "knowledge": {"present": False, "fact": "", "source": ""},
             "expected": {"present": False, "pipeline": "", "expected": "", "from": ""},
             "language": "", "atts": [], "file": False, "pipeline_item": False}
        if code == "NOISE":
            return v
        if topic.bucket:
            b = stage_b(self.claude, cfg, self.matrix, th, code, [], headers_only=True)
            self.apply_b(v, b, keep_code=True)
            return v
        if topic.pipeline and topic.pipeline not in cfg["conditional_pipelines"]:
            v.update(pipeline=topic.pipeline, demand="PIPELINE", reason="handled by " + topic.pipeline)
            return v
        atts = build_attachments(self.gmail, th, cfg)
        b = stage_b(self.claude, cfg, self.matrix, th, code, atts)
        self.apply_b(v, b, keep_code=False)
        final = self.matrix.by_code[v["topic_final"]]
        if final.pipeline and b["pipeline_item"]:
            v.update(pipeline=final.pipeline, demand="PIPELINE", reason="handled by " + final.pipeline,
                     line="", file=False)
            v["knowledge"] = {"present": False, "fact": "", "source": ""}
            # an expected event survives: the owner's request to the sender is itself a pipeline thread
            return v
        if final.bucket:
            return v  # Stage B moved it to a bucket: no file
        v["atts"] = atts
        v["file"] = True
        return v

    def apply_b(self, v, b, keep_code):
        if b["topic_changed"] and not keep_code and b["topic_code"] in self.matrix.by_code:
            v["topic_final"] = b["topic_code"]
        v["demand"] = b["demand"]
        v["reason"] = b["demand_reason"]
        v["line"] = b["needs_you_line"]
        v["knowledge"] = b["knowledge"]
        v["expected"] = b["expected_event"]
        v["language"] = b["language"]
        v["pipeline_item"] = b["pipeline_item"]

    # ---- processing --------------------------------------------------------
    def process_threads(self, threads, status_rows):
        cfg = self.cfg
        corr = corrections_text(status_rows, self.lookup_thread_info)
        need_a, known = [], {}
        for th in threads:
            t = self.state.thread_get(th["id"])
            if t and t["topic_final"] in self.matrix.by_code:
                known[th["id"]] = {"topic_code": t["topic_final"], "confidence": "", "reason": "kept from earlier run"}
            else:
                need_a.append(th)
        results = dict(known)
        if need_a:
            failures = {}
            try:
                results.update(stage_a(self.claude, cfg, self.matrix, need_a, corr, failures))
            except Exception as e:
                for th in need_a:
                    self.fail(th["id"], th["messages"][-1]["id"], "stage A", e)
                need_a = []
            for th in need_a:
                if th["id"] in failures:
                    self.fail(th["id"], th["messages"][-1]["id"], "stage A", ModelFormatError(failures[th["id"]]))
            threads = [th for th in threads if th["id"] in results]
        for th in threads:
            if th["id"] not in results:
                continue
            self.touch_lock()
            try:
                v = self.judge(th, results[th["id"]])
                if th["id"] in known:
                    v["stage_a"] = self.stage_a_of(th["id"]) or v["stage_a"]
                self.counters["judged"] += 1
                if self.dry:
                    self.dry_row(th, v)
                    continue
                self.commit(th, v)
                self.clear_retry(th["id"])
            except Exception as e:
                self.fail(th["id"], th["messages"][-1]["id"], getattr(e, "step", "judge"), e)
        if self.dry and self.out_csv:
            self.write_dry_csv()

    def stage_a_of(self, tid):
        r = self.latest_by_thread().get(tid)
        return r["topic_stage_a"] if r else ""

    # ---- commit one thread (spec section 4 step 7) -----------------------------
    def commit(self, th, v):
        cfg = self.cfg
        run_ts = self.run_ts
        tid = th["id"]
        topic = self.matrix.by_code[v["topic_final"]]
        old = self.state.thread_get(tid)
        ny = old["ny_id"] if old and old["ny_id"] else ""
        if v["demand"] in ("NEEDS-YOU", "FOLLOW-UP") and not ny:
            ny = self.state.next_id("NY")
        first, last = th["messages"][0], th["messages"][-1]
        thread_file, saved_names, not_read = "", [], []
        if v["file"]:
            emails_dir = topic.folder / "Input" / "Emails"
            tdir = emails_dir / "Emails"
            tdir.mkdir(parents=True, exist_ok=True)
            save_attachments(v["atts"], tdir)
            saved = []
            for r in v["atts"]:
                if r["save"] and r["data"] is not None:
                    nm = r["saved_name"]
                    saved_names.append(nm)
                    saved.append(nm + (" [not read]" if r["reason"] else ""))
                if r["reason"]:
                    not_read.append("%s=%s" % (r["orig"], r["reason"]))
            fname = "%s_%s_%s.md" % (first["dt"].strftime("%Y%m%d"), slugify(th["subject"]), tid)
            verdict = "topic=%s · demand=%s · knowledge=%s · run=%s" % (
                v["topic_final"], v["demand"], "yes" if v["knowledge"]["present"] else "no", run_ts)
            atomic_write(tdir / fname, render_thread(th, "; ".join(saved) if saved else "none", verdict))
            thread_file = str(tdir / fname)
            known = known_manifest_ids(emails_dir)
            rows = [r for r in manifest_rows(th) if r["message_id"] not in known]
            if rows:
                append_csv(emails_dir / "manifest_emails.csv", MANIFEST_COLS, rows)
            self.counters["filed"] += 1
        # expected event
        ex_id = ""
        try:
            ex_id = self.expected_events(th, v, topic)
        except Exception as e:
            log("WARN", "expected", "thread %s: %s" % (tid, e))
        n_rows = len(self.ledger_rows()) + 1
        append_csv(self.ledger_path, LEDGER_COLS, [{
            "run_ts": run_ts, "thread_id": tid, "last_message_id": last["id"],
            "first_date": first["dt"].strftime("%Y-%m-%d"), "last_date": last["dt"].strftime("%Y-%m-%d"),
            "from_latest": ", ".join(addr_list(last["from"])) or last["from"], "subject": th["subject"],
            "delivered_to": delivered_alias(th, cfg), "topic_stage_a": v["stage_a"],
            "topic_final": v["topic_final"], "confidence": v["confidence"], "pipeline": v["pipeline"],
            "demand": v["demand"], "demand_reason": v["reason"],
            "knowledge": "yes" if v["knowledge"]["present"] else "no", "ny_id": ny,
            "expected_event_id": ex_id, "thread_file": thread_file,
            "attachments_saved": ";".join(saved_names), "attachments_not_read": ";".join(not_read),
            "message_count": len(th["messages"]), "language": v["language"]}])
        try:
            self.state.meta_set("line:" + tid, v["line"])
            self.state.meta_set("to:" + tid, ", ".join(addr_list(last["to"])))
            if v["knowledge"]["present"] and v["file"]:
                self.knowledge_note(th, v, topic, thread_file, n_rows)
        except Exception as e:
            log("WARN", "note", "thread %s: %s" % (tid, e))
        self.state.thread_set(tid, th["fingerprint"], v["topic_final"], v["demand"], ny, run_ts)
        self.state.mark_processed(tid, [m["id"] for m in th["messages"]], run_ts)
        self.check_arrivals(th)

    # ---- expected events ---------------------------------------------------
    def expected_events(self, th, v, topic):
        e = v["expected"]
        if not e["present"]:
            return ""
        rows = read_csv(self.ex_path)
        for r in rows:
            if r["thread_id"] == th["id"] and r["pipeline"] == e["pipeline"] and r["expected"] == e["expected"] \
                    and r["status"] in ("waiting", "arrived"):
                return r["ex_id"]
        ex_id = self.state.next_id("EX")
        last = th["messages"][-1]
        append_csv(self.ex_path, EX_COLS, [{
            "ex_id": ex_id, "created_ts": ts_local(), "thread_id": th["id"], "topic_code": v["topic_final"],
            "pipeline": e["pipeline"], "expected": e["expected"], "from": e["from"],
            "asked_on": last["dt"].strftime("%Y-%m-%d"), "status": "waiting", "fulfilled_ts": "",
            "fulfilled_message_id": ""}])
        return ex_id

    def check_arrivals(self, th):
        rows = read_csv(self.ex_path)
        changed = False
        for r in rows:
            if r["thread_id"] != th["id"] or r["status"] != "waiting":
                continue
            dom = domain_of(r["from"])
            for m in th["messages"]:
                if any(domain_of(a) == dom for a in addr_list(m["from"])) and self.is_after_ask(th, m, r):
                    r["status"], r["fulfilled_ts"], r["fulfilled_message_id"] = "arrived", ts_local(), m["id"]
                    changed = True
                    break
        if changed:
            write_csv(self.ex_path, EX_COLS, rows)

    @staticmethod
    def is_after_ask(th, m, r):
        """A counterparty message that comes after the owner's asking message in the thread."""
        asked = r["asked_on"]
        ms = th["messages"]
        idx = ms.index(m)
        return any(x["sent"] and x["dt"].strftime("%Y-%m-%d") >= asked for x in ms[:idx])

    # ---- LOG.md -------------------------------------------------------------
    def knowledge_note(self, th, v, topic, thread_file, ledger_row):
        cfg = self.cfg
        key = "fact:" + th["id"]
        h = hashlib.sha1(v["knowledge"]["fact"].encode("utf-8")).hexdigest()
        if self.state.meta_get(key) == h:
            return
        log_path = cfg["project_logs"].get(topic.project)
        if not log_path:
            log("WARN", "note", "no LOG.md configured for %s" % topic.project)
            return
        try:
            rel = os.path.relpath(thread_file, str(Path(log_path).parent))
        except ValueError:
            rel = thread_file
        trig = v["line"] if v["demand"] in ("NEEDS-YOU", "FOLLOW-UP") and v["line"] else "none"
        note = ("\n## %s — [%s]\n- Source: %s, via email, thread \"%s\"\n- Fact: %s\n- Triggers: %s\n"
                "- Detail note: %s\n- Importer: run %s, ledger row %d\n") % (
            th["messages"][-1]["dt"].strftime("%Y-%m-%d"), topic.label,
            v["knowledge"]["source"] or "unknown", th["subject"], v["knowledge"]["fact"], trig, rel,
            self.run_ts, ledger_row)
        self.state.db.execute("INSERT INTO deferred_notes(log_path,note_text,created_ts) VALUES(?,?,?)",
                              (log_path, note, self.run_ts))
        self.state.meta_set(key, h)
        self.state.db.commit()

    def write_note(self, log_path, note):
        p = Path(log_path)
        quiet = self.cfg["log_md_quiet_minutes"] * 60
        if p.exists():
            own = self.state.meta_get("logmtime:" + str(log_path)) if self.state else None
            mt = p.stat().st_mtime
            if time.time() - mt < quiet and not (own and abs(float(own) - mt) < 1):
                return False  # someone else touched it recently: OneDrive guard
            cur = p.read_text(encoding="utf-8")
        else:
            title = self.cfg["project_log_titles"].get(
                next((k for k, val in self.cfg["project_logs"].items() if val == log_path), ""), p.parent.name)
            cur = "# Project log — %s\n\n%s" % (title, LOG_HEADER)
        if not cur.endswith("\n"):
            cur += "\n"
        atomic_write(p, cur + note)
        if self.state:
            self.state.meta_set("logmtime:" + str(log_path), p.stat().st_mtime)
        return True

    def flush_deferred_notes(self):
        if self.dry or not self.state:
            return
        rows = self.state.db.execute("SELECT id,log_path,note_text FROM deferred_notes ORDER BY id").fetchall()
        by_log = {}
        for i, lp, note in rows:
            by_log.setdefault(lp, []).append((i, note))
        for lp, items in by_log.items():
            if self.write_note(lp, "".join(n for _, n in items)):
                self.state.db.executemany("DELETE FROM deferred_notes WHERE id=?", [(i,) for i, _ in items])
                self.state.db.commit()

    # ---- corrections ----------------------------------------------------------
    def apply_corrections(self, status_rows):
        if self.dry:
            return
        last = {}
        for r in status_rows:
            last[(r.get("item") or "").strip()] = r
        for item, r in last.items():
            if (r.get("action") or "").strip() != "correct":
                continue
            code = (r.get("value") or "").strip()
            if code not in self.matrix.by_code:
                log("WARN", "correct", "%s: unknown code %r, ignored" % (item, code))
                continue
            if self.state.meta_get("corr:" + item) == r.get("ts"):
                continue
            tid = self.state.thread_by_ny(item) if item.startswith("NY-") else item
            row = self.latest_by_thread().get(tid or "")
            if not row:
                log("WARN", "correct", "%s: thread not in ledger, ignored" % item)
                continue
            try:
                self.refile(tid, row, code)
                self.state.meta_set("corr:" + item, r.get("ts"))
            except Exception as e:
                self.fail(tid, row["last_message_id"], "correct", e)

    def refile(self, tid, row, code):
        new = self.matrix.by_code[code]
        old_topic = self.matrix.by_code.get(row["topic_final"])
        files_moved = ""
        if new.folder is not None and new.pipeline == "" and row["thread_file"]:
            src = Path(row["thread_file"])
            new_dir = new.folder / "Input" / "Emails" / "Emails"
            new_dir.mkdir(parents=True, exist_ok=True)
            dst = new_dir / src.name
            if src.exists():
                txt = src.read_text(encoding="utf-8")
                txt = re.sub(r"(\*\*Importer verdict:\*\* topic=)\S+", r"\g<1>" + code, txt, count=1)
                atomic_write(dst, txt)
                src.unlink()
            for nm in [x for x in row["attachments_saved"].split(";") if x]:
                s = src.parent / nm
                if s.exists():
                    (new_dir / nm).write_bytes(s.read_bytes())
                    s.unlink()
            th = parse_thread(self.gmail.get_thread(tid))
            emails_dir = new.folder / "Input" / "Emails"
            known = known_manifest_ids(emails_dir)
            rows = [r for r in manifest_rows(th) if r["message_id"] not in known]
            if rows:
                append_csv(emails_dir / "manifest_emails.csv", MANIFEST_COLS, rows)
            files_moved = str(dst)
        else:
            log("WARN", "correct", "%s -> %s has no folder or is a pipeline code: ledger row only" % (tid, code))
        r2 = dict(row)
        r2.update(run_ts=self.run_ts, topic_final=code, demand_reason="refiled by correction",
                  thread_file=files_moved if files_moved else row["thread_file"])
        append_csv(self.ledger_path, LEDGER_COLS, [r2])
        t = self.state.thread_get(tid)
        if t:
            self.state.thread_set(tid, t["fingerprint"], code, t["demand"], t["ny_id"], self.run_ts)

    # ---- NEEDS_YOU.md -----------------------------------------------------------
    def status_map(self, status_rows):
        m = {}
        for r in status_rows:
            m[(r.get("item") or "").strip()] = r
        return m

    def hidden(self, item_ids, smap, today, row=None):
        """Returns (done, snoozed). A done item comes back when the thread got a newer verdict
        (a ledger row written after the done, other than a refile by correction)."""
        done = snoozed = False
        for it in item_ids:
            r = smap.get(it)
            if not r:
                continue
            a = (r.get("action") or "").strip()
            if a == "done":
                dts = (r.get("ts") or "").replace("T", " ")[:16]
                if row and row.get("run_ts", "") > dts and row.get("demand_reason") != "refiled by correction":
                    continue
                done = True
            elif a == "snooze" and (r.get("value") or "").strip() > today:
                snoozed = True
        return done, snoozed

    def needs_state(self, status_rows):
        smap = self.status_map(status_rows)
        today = now_local().strftime("%Y-%m-%d")
        latest = self.latest_by_thread()
        need, wait, stale = [], [], []
        for tid, r in latest.items():
            if r["demand"] not in ("NEEDS-YOU", "FOLLOW-UP") or not r["ny_id"]:
                continue
            done, snoozed = self.hidden([r["ny_id"], tid], smap, today, r)
            if done or snoozed:
                continue
            line = self.state.meta_get("line:" + tid, "") if self.state else ""
            row = {"no": r["ny_id"], "topic": r["topic_final"], "date": r["last_date"], "from": r["from_latest"],
                   "to": (self.state.meta_get("to:" + tid, "") if self.state else ""),
                   "subject": r["subject"], "what": line or r["demand_reason"], "file": r["thread_file"],
                   "demand": r["demand"], "tid": tid}
            if r["demand"] == "NEEDS-YOU":  # nothing goes stale
                need.append(row)
            else:
                wait.append(row)
        ex_rows = []
        for r in read_csv(self.ex_path):
            done, snoozed = self.hidden([r["ex_id"]], smap, today)
            if r["status"] == "closed":
                continue
            if done:
                r["status"] = "closed"
                continue
            if snoozed:
                continue
            ex_rows.append(r)
        ex_show = list(ex_rows)  # nothing goes stale
        stale_ex = []
        for k in (need, wait, stale):
            k.sort(key=lambda x: x["date"], reverse=True)
        return need, wait, stale, ex_show, stale_ex, smap

    def rebuild_needs_you(self, status_rows):
        need, wait, stale, ex_show, stale_ex, smap = self.needs_state(status_rows)
        # close expected events marked done
        ex_all = read_csv(self.ex_path)
        changed = False
        for r in ex_all:
            if r["status"] != "closed" and (smap.get(r["ex_id"], {}).get("action") or "").strip() == "done":
                r["status"] = "closed"
                changed = True
        if changed and not self.dry:
            write_csv(self.ex_path, EX_COLS, ex_all)
        self.counters["needs_you"] = len(need) + len([s for s in stale if s["demand"] == "NEEDS-YOU"])
        host = socket.gethostname()
        L = ["# Needs you — email",
             "Last run: %s local time · importer PC: %s · items: %d need you, %d waiting on others, %d expected reply" % (
                 self.run_ts, host, len(need), len(wait), len(ex_show)),
             "", "## Needs you",
             "| No. | Topic | Date | From | Subject | What to do | Thread file |", "|---|---|---|---|---|---|---|"]
        for r in need:
            L.append("| %s | %s | %s | %s | %s | %s | %s |" % tuple(cell(r[k]) for k in
                     ("no", "topic", "date", "from", "subject", "what", "file")))
        L += ["", "## Waiting on others (FOLLOW-UP)",
              "| No. | Topic | Date | To | Subject | Waiting for | Thread file |", "|---|---|---|---|---|---|---|"]
        for r in wait:
            L.append("| %s | %s | %s | %s | %s | %s | %s |" % tuple(cell(r[k]) for k in
                     ("no", "topic", "date", "to", "subject", "what", "file")))
        L += ["", "## Expected replies",
              "| No. | Topic | Asked on | From | Pipeline | Expected | Status |", "|---|---|---|---|---|---|---|"]
        for r in ex_show:
            st = ("arrived · offer to run %s" % r["pipeline"]) if r["status"] == "arrived" else \
                 ("waiting · when it arrives, offer to run %s" % r["pipeline"])
            L.append("| %s | %s | %s | %s | %s | %s | %s |" % tuple(cell(x) for x in (
                r["ex_id"], r["topic_code"], r["asked_on"], r["from"], r["pipeline"], r["expected"], st)))
        L += ["", "## How to answer",
              'In any session say "mail" to see this list, then "done NY-0007", "snooze NY-0007 2026-10-15" or '
              '"correct NY-0007 DEV/Accounting/Tax". Sessions write to NEEDS_YOU_status.csv; this file is rewritten '
              'by the importer and must not be edited. The Gmail label "__Needs you" mirrors the Needs-you table: '
              'done removes it on the next run.', ""]
        if not self.dry:
            atomic_write(self.needs_path, "\n".join(L))
        elif self.out_csv:
            prev = Path(self.out_csv).with_name(Path(self.out_csv).stem + "_NEEDS_YOU_preview.md")
            atomic_write(prev, "\n".join(L))
            log("INFO", "dry-run", "NEEDS_YOU preview written to %s" % prev)

    # ---- Gmail label sync -----------------------------------------------------------
    def park_label_removed(self, status_rows):
        """The owner removing the label by hand in Gmail counts as Park (his rule, 2026-10-05).
        A thread the importer left labelled at the end of the last run, that has lost the label
        and is still open, gets a done row with note parked. Skipped when the thread got a new
        verdict this run, and on the first run (no saved set yet)."""
        prev = self.state.meta_get("label_set", None)
        if prev is None:
            return status_rows
        prev = {x for x in prev.split(",") if x}
        if not prev:
            return status_rows
        lid = self.gmail.label_id(self.cfg["gmail_label_name"], create=True)
        have = self.gmail.threads_with_label(lid)
        smap = self.status_map(status_rows)
        today = now_local().strftime("%Y-%m-%d")
        latest = self.latest_by_thread()
        rows = []
        for tid in sorted(prev - have):
            r = latest.get(tid)
            if not r or r["demand"] != "NEEDS-YOU" or not r["ny_id"]:
                continue
            if r.get("run_ts", "") == self.run_ts:
                continue
            done, snoozed = self.hidden([r["ny_id"], tid], smap, today, r)
            if done or snoozed:
                continue
            rows.append({"ts": self.run_ts, "item": r["ny_id"], "action": "done", "value": "",
                         "chat": "Gmail label removed by hand", "note": "parked"})
            log("INFO", "label", "removed by hand, parked %s (%s)" % (r["ny_id"], tid))
        if rows:
            append_csv(self.status_csv, STATUS_COLS, rows)
            status_rows = list(status_rows) + rows
        return status_rows

    def label_sync(self, status_rows):
        cfg = self.cfg
        smap = self.status_map(status_rows)
        today = now_local().strftime("%Y-%m-%d")
        want = set()
        for tid, r in self.latest_by_thread().items():
            if r["demand"] != "NEEDS-YOU" or not r["ny_id"]:
                continue
            done, snoozed = self.hidden([r["ny_id"], tid], smap, today, r)
            if not done and not snoozed:  # snoozed mail loses the label until the snooze date (2026-10-05)
                want.add(tid)
        lid = self.gmail.label_id(cfg["gmail_label_name"], create=True)
        have = self.gmail.threads_with_label(lid)
        for tid in sorted(want - have):
            self.gmail.modify_thread(tid, add=[lid])
            log("INFO", "label", "added to %s" % tid)
        for tid in sorted(have - want):
            self.gmail.modify_thread(tid, remove=[lid])
            log("INFO", "label", "removed from %s" % tid)
        self.state.meta_set("label_set", ",".join(sorted(want)))

    # ---- finish -------------------------------------------------------------------
    def finish(self, err):
        if self.dry:
            return
        c = self.counters
        retry = read_csv(self.retry_path)
        given_up = [r for r in retry if r.get("step") == "GIVEN UP"]
        active = [r for r in retry if r.get("step") != "GIVEN UP"]
        failed = err is not None or c["errors"] > 0
        result = "OK"
        if err:
            result = "FAILED: " + err
        elif c["errors"] > 0:
            first = (active[0]["error"] if active else (given_up[0]["error"] if given_up else "see run.log"))
            result = "FAILED: %s" % first
        n = now_local()
        nxt = n.replace(minute=5, second=0, microsecond=0)
        if n.minute >= 5:
            nxt += timedelta(hours=1)
        success_ok = not err and not active
        if success_ok and self.state:
            self.state.meta_set("last_success", datetime.now(LOCAL_TZ).isoformat())
        last_success = self.state.meta_get("last_success") if self.state else None
        ls = datetime.fromisoformat(last_success).strftime("%Y-%m-%d %H:%M") if last_success else "never"
        md = ("# Email memory importer — run status\n"
              "last_run: %s local time\nlast_success: %s local time\nresult: %s\nimporter_pc: %s\n"
              "listed: %d · new messages: %d · threads judged: %d · filed: %d · needs-you now: %d · "
              "retry rows: %d (%d given up)\nnext scheduled run: %s local time\n%s") % (
            self.run_ts, ls, result, socket.gethostname(), c["listed"], c["new_messages"], c["judged"],
            c["filed"], c["needs_you"], len(retry), len(given_up), nxt.strftime("%H:%M"),
            self.size_line(c["needs_you"]))
        atomic_write(self.status_md, md)
        if self.state:
            self.state.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?)", (
                self.run_ts, 0 if failed else 1, c["listed"], c["new_messages"], c["judged"], c["filed"],
                c["needs_you"], c["errors"]))
            self.state.db.commit()
        log("INFO" if not failed else "ERROR", "finish", result)

    def size_line(self, needs_you):
        """2026-10-04 (asked by the owner): one line showing how big the email memory has grown.
        Never fails the run: any error becomes 'size check failed: <error>'."""
        try:
            parts = []
            if self.ledger_path.exists():
                rows = len(self.ledger_rows())
                parts.append("ledger %d rows (%.1f MB)" % (rows, self.ledger_path.stat().st_size / 1048576))
            logs = []
            for proj, p in sorted((self.cfg.get("project_logs") or {}).items()):
                pp = Path(p)
                if pp.exists():
                    logs.append("%s %d KB" % (proj, round(pp.stat().st_size / 1024)))
            if logs:
                parts.append("LOG.md " + ", ".join(logs))
            parts.append("needs-you list %d items" % needs_you)
            return "sizes: " + " · ".join(parts) + "\n"
        except Exception as e:  # noqa: BLE001
            return "sizes: size check failed: %s\n" % e

    # ---- dry run / replay ---------------------------------------------------------------
    def dry_row(self, th, v):
        last = th["messages"][-1]
        self.dry_rows = getattr(self, "dry_rows", [])
        self.dry_rows.append({
            "thread_id": th["id"], "date": th["messages"][0]["dt"].strftime("%Y-%m-%d"),
            "from": ", ".join(addr_list(th["messages"][0]["from"])), "subject": th["subject"],
            "topic_stage_a": v["stage_a"], "confidence": v["confidence"], "topic_final": v["topic_final"],
            "demand": v["demand"], "demand_reason": v["reason"], "needs_you_line": v["line"],
            "knowledge": "yes" if v["knowledge"]["present"] else "no", "knowledge_fact": v["knowledge"]["fact"],
            "knowledge_source": v["knowledge"]["source"],
            "expected_event_pipeline": v["expected"]["pipeline"] if v["expected"]["present"] else "",
            "expected_event": v["expected"]["expected"] if v["expected"]["present"] else "",
            "pipeline": v["pipeline"], "attachments_not_read": ";".join(
                "%s=%s" % (a["orig"], a["reason"]) for a in v["atts"] if a["reason"]),
            "messages": len(th["messages"])})

    DRY_COLS = ["thread_id", "date", "from", "subject", "topic_stage_a", "confidence", "topic_final", "demand",
                "demand_reason", "needs_you_line", "knowledge", "knowledge_fact", "knowledge_source",
                "expected_event_pipeline", "expected_event", "pipeline", "attachments_not_read", "messages"]

    def write_dry_csv(self):
        write_csv(self.out_csv, self.DRY_COLS, getattr(self, "dry_rows", []))
        log("INFO", "dry-run", "wrote %d rows to %s" % (len(getattr(self, "dry_rows", [])), self.out_csv))

    def replay(self, d1, d2):
        """Judge every thread with a message in [d1, d2) from scratch; write only the --out CSV."""
        cfg = self.cfg
        self.open(need_state=False)
        self.ensure_clients()
        s = datetime.strptime(d1, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        e = datetime.strptime(d2, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        q = "after:%d before:%d %s" % (int(s.timestamp()), int(e.timestamp()), cfg["gmail_query_exclusions"])
        ids = self.gmail.list_message_ids(q)
        tids = []
        for _, t in ids:
            if t not in tids:
                tids.append(t)
        log("INFO", "replay", "%d messages, %d threads" % (len(ids), len(tids)))
        threads = [parse_thread(self.gmail.get_thread(t)) for t in tids]
        rows = self.status_rows()
        self.state = None
        corr = corrections_text(rows, lambda item: None)
        failures = {}
        res = stage_a(self.claude, cfg, self.matrix, threads, corr, failures)
        self.state = None
        for th in threads:
            if th["id"] not in res:
                self.dry_rows = getattr(self, "dry_rows", [])
                self.dry_rows.append({"thread_id": th["id"], "subject": th["subject"],
                                      "topic_stage_a": "(stage A failed)",
                                      "demand_reason": "ERROR: " + failures.get(th["id"], "no answer")[:150]})
                continue
            try:
                v = self.judge(th, res[th["id"]])
                self.dry_row(th, v)
            except Exception as ex:
                self.dry_rows = getattr(self, "dry_rows", [])
                self.dry_rows.append({"thread_id": th["id"], "subject": th["subject"],
                                      "topic_stage_a": res[th["id"]]["topic_code"],
                                      "demand_reason": "ERROR: " + str(ex)[:150]})
                log("ERROR", "replay", "%s: %s" % (th["id"], ex))
        self.write_dry_csv()
        return 0


# ----------------------------------------------------------------------------
# command line
# ----------------------------------------------------------------------------
def cmd_write_hostname(cfg_path):
    cfg = load_config(cfg_path)
    cfg["importer_pc"] = socket.gethostname()
    atomic_write(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    print("importer_pc =", cfg["importer_pc"])
    return 0


def cmd_auth(cfg):
    secrets = Path(cfg["secrets_dir"])
    cred = secrets / "credentials.json"
    if not cred.exists():
        print("FAILED: Gmail sign-in cannot start: credentials.json is missing in %s. "
              "Download the OAuth client file from Google Cloud and save it there." % secrets)
        return 1
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(cred), SCOPES)
    try:
        creds = flow.run_local_server(port=0)
    except Exception as e:
        print("FAILED: Google consent: %s" % e)
        return 1
    (secrets / "token.json").write_text(creds.to_json(), encoding="utf-8")
    print("token.json written")
    return 0


def cmd_selftest(cfg):
    imp = Importer(cfg)
    try:
        imp.open(need_state=False)
    except ImporterError as e:
        msg = "FAILED: %s" % e
        print(msg)
        try:
            atomic_write(imp.status_md, "# Email memory importer — run status\nlast_run: %s local time\nresult: %s\n" % (ts_local(), msg))
        except Exception:
            pass
        return 1
    for t in imp.matrix.topics:
        if t.bucket:
            print("%-48s folder=(none, bucket)" % t.code)
        else:
            tag = (" pipeline=" + t.pipeline) if t.pipeline else ""
            if t.check_folder != t.folder and not Path(t.folder).is_dir():
                ex = ("yes (project folder %s; Knowledge stack\\Input\\Emails is created with the first email)" % t.check_folder
                      if Path(t.check_folder).is_dir() else "NO")
            else:
                ex = "yes" if Path(t.folder).is_dir() else "NO"
            print("%-48s folder=%s exists=%s%s" % (t.code, t.folder, ex, tag))
    print("CONFIG PARSE OK: %d codes" % len(imp.matrix.topics))
    secrets = Path(cfg["secrets_dir"])
    missing = [f for f in ("token.json", "anthropic_key.txt") if not (secrets / f).exists()]
    if missing:
        msg = "SELFTEST CONFIG OK (Gmail and API parts not run, missing: %s)" % ", ".join(missing)
        print(msg)
        atomic_write(imp.status_md, "# Email memory importer — run status\nlast_run: %s local time\nresult: %s\n" % (ts_local(), msg))
        return 0
    try:
        imp.ensure_clients()
        ids = imp.gmail.list_message_ids("newer_than:7d " + cfg["gmail_query_exclusions"])[:5]
        print("Gmail OK: profile %s, %d message ids listed (first 5 kept)" % (imp.gmail.profile().get("emailAddress"), len(ids)))
        out = imp.claude.raw("Answer with one word.", "Say OK.", 10)
        print("Anthropic OK: model %s answered %r" % (cfg["anthropic_model"], out.strip()[:20]))
    except Exception as e:
        msg = "FAILED: %s: %s" % (type(e).__name__, str(e).splitlines()[-1] if str(e) else "")
        print(msg)
        atomic_write(imp.status_md, "# Email memory importer — run status\nlast_run: %s local time\nresult: %s\n" % (ts_local(), msg))
        return 1
    atomic_write(imp.status_md, "# Email memory importer — run status\nlast_run: %s local time\nresult: SELFTEST OK\nimporter_pc: %s\n" % (ts_local(), socket.gethostname()))
    print("SELFTEST OK")
    return 0


def cmd_rebuild_state(cfg):
    imp = Importer(cfg)
    imp.open()
    rows = imp.ledger_rows()
    st = imp.state
    latest = {}
    for r in rows:
        latest[r["thread_id"]] = r
        st.mark_processed(r["thread_id"], [r["last_message_id"]], r["run_ts"])
    for tid, r in latest.items():
        st.thread_set(tid, "", r["topic_final"], r["demand"], r["ny_id"], r["run_ts"])
    for t in imp.matrix.topics:
        if t.folder is None:
            continue
        for mrow in read_csv(t.folder / "Input" / "Emails" / "manifest_emails.csv"):
            st.mark_processed(mrow["thread_id"], [mrow["message_id"]], "")
    ny_to_tid = {r["ny_id"]: tid for tid, r in latest.items() if r["ny_id"]}
    npath = Path(cfg["needs_you_path"])
    if npath.exists():
        section = ""
        for ln in npath.read_text(encoding="utf-8").splitlines():
            if ln.startswith("## "):
                section = ln
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) == 7 and cells[0] in ny_to_tid:
                tid = ny_to_tid[cells[0]]
                st.meta_set("line:" + tid, cells[5])
                if section.startswith("## Waiting"):
                    st.meta_set("to:" + tid, cells[3])
    nys = [int(r["ny_id"][3:]) for r in rows if r["ny_id"]]
    exs = [int(r["ex_id"][3:]) for r in read_csv(imp.ex_path)]
    st.meta_set("NY_counter", max(nys or [0]))
    st.meta_set("EX_counter", max(exs or [0]))
    if rows:
        st.meta_set("last_success", datetime.strptime(rows[-1]["run_ts"], "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ).isoformat())
    print("state rebuilt from ledger and manifests: %d threads" % len(latest))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--then-open", action="store_true")
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--write-hostname", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rebuild-state", action="store_true")
    ap.add_argument("--replay", nargs=2, metavar=("FROM", "TO"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--ledger", help="with --dry-run: read this ledger copy instead of ledger.csv")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    a = ap.parse_args(argv)
    try:
        if a.write_hostname:
            return cmd_write_hostname(a.config)
        cfg = load_config(a.config)
    except ImporterError as e:
        print("FAILED: %s" % e)
        return 1
    setup_log(cfg["secrets_dir"])
    if a.auth:
        return cmd_auth(cfg)
    if a.selftest:
        return cmd_selftest(cfg)
    if a.rebuild_state:
        return cmd_rebuild_state(cfg)
    if a.replay:
        if not (a.dry_run and a.out):
            print("FAILED: --replay needs --dry-run and --out <csv>")
            return 1
        try:
            return Importer(cfg, dry_run=True, out_csv=a.out).replay(*a.replay)
        except ImporterError as e:
            print("FAILED: %s" % e)
            return 1
    # normal run: one-PC guard
    host = socket.gethostname()
    if cfg["importer_pc"] != host:
        log("WARN", "guard", "wrong PC: %s, importer_pc is %s" % (host, cfg["importer_pc"]))
        return 0
    if a.ledger and not a.dry_run:
        print("FAILED: --ledger only works with --dry-run")
        return 1
    imp = Importer(cfg, dry_run=a.dry_run, out_csv=a.out, ledger=a.ledger)
    rc = imp.run()
    if a.then_open and not a.dry_run:
        try:
            os.startfile(cfg["needs_you_path"])  # Windows only
        except Exception as e:
            log("WARN", "open", str(e))
    return rc


if __name__ == "__main__":
    sys.exit(main())
