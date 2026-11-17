"""Helpers built on the synced books that only READ them: the credit warning when billing, bills by due date,
and the morning list of customers to remind. Nothing here is sent to Tally."""
import json
import os
import threading
import time
from datetime import date, timedelta

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CREDIT_FILE = os.path.join(DATA_DIR, "credit.json")
SENT_FILE = os.path.join(DATA_DIR, "reminders.json")
CREDIT_DEFAULT = {"on": True, "days": 30}      # warn when a bill is overdue by more than this many days
_lock = threading.Lock()


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, d):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)


# ------------------------------------------------------------------ credit warning
def credit_settings():
    return {**CREDIT_DEFAULT, **_load(CREDIT_FILE, {})}


def set_credit(on=None, days=None):
    d = credit_settings()
    if on is not None:
        d["on"] = bool(on)
    if days is not None:
        d["days"] = max(0, min(3650, int(days)))
    with _lock:
        _save(CREDIT_FILE, d)
    return d


def _source(c, cid):
    r = c.execute("SELECT bills_source FROM company WHERE id=?", (cid,)).fetchone()
    return (r["bills_source"] if r else None) or "vouchers"


def party_check(cid, party):
    """For the warning on a sales invoice or order: the party's balance against the credit limit set in Tally, and
    bills overdue longer than the days set in Settings. Only a warning: the entry can still be saved."""
    st = credit_settings()
    with store.conn() as c:
        l = c.execute("SELECT name, closing, chain, extra FROM ledger WHERE company_id=? AND name=?", (cid, party)).fetchone()
        if not l:
            return {"known": False}
        extra = json.loads(l["extra"] or "{}")
        bills = []
        if "|Sundry Debtors|" in (l["chain"] or ""):
            for p in store._party_bills(c, cid, "receivable", _source(c, cid)):
                if p["name"] == party:
                    bills = p["bills"]
                    break
    limit = extra.get("credit_limit")
    bal = l["closing"] or 0
    late = sorted((b for b in bills if (b.get("overdue") or 0) > st["days"] and b["amount"] > 0.5), key=lambda b: -(b["overdue"] or 0))
    warn = []
    if st["on"] and limit and bal > limit:
        warn.append(f"over the credit limit: owes {bal:,.2f} against a limit of {limit:,.2f}")
    if st["on"] and late:
        warn.append(f"{len(late)} bill{'s' if len(late) > 1 else ''} overdue more than {st['days']} days "
                    f"(oldest {late[0]['overdue']} days, {sum(b['amount'] for b in late):,.2f} in all)")
    return {"known": True, "on": st["on"], "balance": bal, "limit": limit, "credit_days": extra.get("credit_days"),
            "days": st["days"], "late": late[:5], "late_total": round(sum(b["amount"] for b in late), 2), "warn": warn}


# ------------------------------------------------------------------ bills by due date
def due_dates(cid, kind="receivable", ahead=31):
    """Every unpaid bill by its due date (or bill date when it has no credit period): overdue ones, then each day
    from today on. Totals per day for the calendar strip."""
    today = date.today()
    with store.conn() as c:
        parties = store._party_bills(c, cid, kind, _source(c, cid))
        phones = {r["name"]: r["mobile"] or r["phone"] or "" for r in c.execute(
            "SELECT name, mobile, phone FROM ledger WHERE company_id=?", (cid,))}
    rows = []
    for p in parties:
        for b in p["bills"]:
            if b["amount"] <= 0.5:
                continue
            due = b.get("due") or b.get("date")
            rows.append({"party": p["name"], "ref": b["ref"], "date": b.get("date"), "due": due, "amount": round(b["amount"], 2),
                         "overdue": b.get("overdue") or 0, "phone": phones.get(p["name"], ""), "nodue": not b.get("due")})
    end = (today + timedelta(days=ahead)).isoformat()
    t = today.isoformat()
    over = [r for r in rows if r["due"] and r["due"] < t]
    soon = [r for r in rows if r["due"] and t <= r["due"] <= end]
    days = {}
    for r in soon:
        d = days.setdefault(r["due"], {"day": r["due"], "total": 0.0, "count": 0})
        d["total"] += r["amount"]
        d["count"] += 1
    over.sort(key=lambda r: (r["due"], -r["amount"]))
    soon.sort(key=lambda r: (r["due"], -r["amount"]))
    return {"kind": kind, "today": t, "overdue": over, "overdue_total": round(sum(r["amount"] for r in over), 2),
            "upcoming": soon, "days": [{**v, "total": round(v["total"], 2)} for k, v in sorted(days.items())],
            "later_total": round(sum(r["amount"] for r in rows if r["due"] and r["due"] > end), 2),
            "nodate_total": round(sum(r["amount"] for r in rows if not r["due"]), 2)}


# ------------------------------------------------------------------ morning reminders
def _sent(cid):
    d = _load(SENT_FILE, {})
    return d.get(str(cid), {})


def reminders(cid):
    """Customers to remind today: anyone with a bill overdue, newest problems first. A bill that fell due
    yesterday or today is "new"; the rest are still waiting. Reminders sent in the last 7 days are shown as sent."""
    today = date.today()
    with store.conn() as c:
        parties = store._party_bills(c, cid, "receivable", _source(c, cid))
        info = {r["name"]: dict(r) for r in c.execute("SELECT name, mobile, phone, closing FROM ledger WHERE company_id=?", (cid,))}
    sent = _sent(cid)
    out = []
    for p in parties:
        od = [b for b in p["bills"] if (b.get("overdue") or 0) > 0 and b["amount"] > 0.5]
        if not od:
            continue
        newest = min(b["overdue"] for b in od)
        s = sent.get(p["name"])
        out.append({"party": p["name"], "phone": (info.get(p["name"]) or {}).get("mobile") or (info.get(p["name"]) or {}).get("phone") or "",
                    "balance": p["amount"], "overdue_amount": round(sum(b["amount"] for b in od), 2), "bills": od,
                    "oldest": max(b["overdue"] for b in od), "new": newest <= 1, "interest": p.get("interest", 0),
                    "sent": s if s and time.time() - s.get("t", 0) < 7 * 86400 else None})
    out.sort(key=lambda r: (r["sent"] is not None, not r["new"], -r["overdue_amount"]))
    return {"today": today.isoformat(), "parties": out,
            "todo": sum(1 for r in out if not r["sent"]), "new": sum(1 for r in out if r["new"] and not r["sent"])}


def mark_sent(cid, party, by=""):
    with _lock:
        d = _load(SENT_FILE, {})
        co = d.setdefault(str(cid), {})
        co[party] = {"t": time.time(), "by": by}
        # forget reminders older than 60 days
        for k in [k for k, v in co.items() if time.time() - v.get("t", 0) > 60 * 86400]:
            del co[k]
        _save(SENT_FILE, d)
    return {"ok": True}


def due_today_text(cid):
    """One line for the Telegram morning summary."""
    parts = []
    for kind, word in (("receivable", "to receive"), ("payable", "to pay")):
        d = due_dates(cid, kind, ahead=0)
        today = [r for r in d["upcoming"] if r["due"] == d["today"]]
        if today:
            parts.append(f"{len(today)} bill{'s' if len(today) > 1 else ''} {word} due today, {sum(r['amount'] for r in today):,.0f}")
    r = reminders(cid)
    if r["todo"]:
        parts.append(f"{r['todo']} customer{'s' if r['todo'] > 1 else ''} to remind ({r['new']} newly overdue)")
    return parts
