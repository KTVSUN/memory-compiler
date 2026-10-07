"""start_topics.py - the /start topic menu in a few seconds.

Finds topic folders (contain both Input and Output, depth 2 under each root)
and dates each by its newest HANDOFF file name (the last session closed on it),
falling back to folder modification times. No file walk, so it stays fast over
the Cowork mount (a file walk runs at about 270 files a second there).
Usage: python3 start_topics.py [all]
Roots are the mounted folders under $HOME/mnt named in ROOTS below.
"""
import os, re, sys, time
MNT = os.path.expanduser("~/mnt")
# One line per root: (folder name under ~/mnt, label printed in the menu).
ROOTS = [("Projects", "Projects"), ("Development", "Development")]
SKIP = {"_to_delete", "old", "Input", "Output", "Work folder", ".git"}
DORMANT_DAYS = 30
SUBS = ["Input", "Output", "Work folder", os.path.join("Output", "md")]

def is_topic(p):
    return os.path.isdir(os.path.join(p, "Input")) and os.path.isdir(os.path.join(p, "Output"))

HANDOFF = re.compile(r"^HANDOFF - .* (20\d{6})[a-z]?\.md$")

def touched(p):
    """Date of the newest handoff (the last session that closed on this topic).
    Folder times are only the fallback: the 15-Sep-2026 Work folder rollout
    stamped every topic folder that day."""
    best = None
    for d in (os.path.join(p, SUBS[3]), os.path.join(p, "Output")):
        try:
            for e in os.scandir(d):
                m = HANDOFF.match(e.name)
                if m:
                    t = time.mktime(time.strptime(m.group(1), "%Y%m%d"))
                    best = t if best is None else max(best, t)
        except OSError:
            pass
    if best is not None:
        return best
    t = os.stat(p).st_mtime
    for s in SUBS:
        try: t = max(t, os.stat(os.path.join(p, s)).st_mtime)
        except OSError: pass
    return t

def subdirs(p):
    try:
        return [e for e in os.scandir(p) if e.is_dir() and e.name not in SKIP and not e.name.startswith((".", "_"))]
    except OSError:
        return []

topics = []
for folder, label in ROOTS:
    root = os.path.join(MNT, folder)
    if not os.path.isdir(root):
        print(f"(not connected: {label})"); continue
    for d1 in subdirs(root):
        if is_topic(d1.path):
            topics.append((touched(d1.path), f"{label} › {d1.name}" if label != "Projects" else f"{d1.name} (Projects)"))
        for d2 in subdirs(d1.path):
            if is_topic(d2.path):
                name = f"{d1.name} › {d2.name}"
                topics.append((touched(d2.path), f"{label} › {name}" if label != "Projects" else f"{name} (Projects)"))

topics.sort(reverse=True)
cut = time.time() - DORMANT_DAYS * 86400
active = [t for t in topics if t[0] >= cut]
dormant = [t for t in topics if t[0] < cut]
RECENT = 5  # the owner's choice, 1-Oct-2026: the 5 latest first, newest first, then the rest alphabetically
recent, rest = active[:RECENT], sorted(active[RECENT:], key=lambda x: x[1].lower())
show = recent + rest
if "all" in sys.argv[1:]:
    show += sorted(dormant, key=lambda x: x[1].lower())
for i, (t, name) in enumerate(show, 1):
    if i == len(recent) + 1 and rest:
        print("--")
    print(f"{i}. {name} · {time.strftime('%d-%b', time.localtime(t))}")
if dormant and "all" not in sys.argv[1:]:
    print(f"+ {len(dormant)} dormant, say all")
print("Which topic? Reply with the number.")
