# Project log: <project>

Dated facts tied to this project that are not documents: a remark in a call, a voice message, a rule stated in an email, a figure someone confirmed. Append-only, newest last. Two writers share the format: a session (on "log this" or "file this") and the email importer (knowledge notes). Not read at session start; searched when a question needs it.

Format:

```
## YYYY-MM-DD — [Topic/Subtopic]
- Source: who, via what channel (for mail: the sender, via email, thread "<subject>")
- Fact: the information, compressed but complete, with the figure or rule itself
- Triggers: pending action and who owns it, or "none"
- Detail note: path of the thread file or note, relative to this file (optional)
- Importer: run YYYY-MM-DD HH:MM, ledger row N (machine entries only)
```

Rules: a session never rewrites or condenses this file; a wrong entry is corrected by a new entry naming the date of the wrong one. The importer writes only when the file has been quiet for five minutes and writes all of a run's notes in one write, so it never collides with a session or the sync client.

---

## 2026-10-01 — [Accounting/Tax]
- Source: the accountant, via email, thread "Monthly close September"
- Fact: The September close is approved as sent; the two reclassified invoices stay in September, not October.
- Triggers: none
- Detail note: Input\Emails\Emails\20261001_monthly-close-september_<thread id>.md
- Importer: run 2026-10-01 14:05, ledger row 212
