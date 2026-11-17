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


# ------------------------------------------------------------------ compare periods
def _periods(mode, anchor):
    """The chosen period, the one before it, and the same one a year earlier: [(label, from, to), ...]"""
    a = date.fromisoformat(anchor) if anchor else date.today()
    def month(y, m):
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        return date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    if mode == "year":            # financial year, April to March
        y = a.year if a.month >= 4 else a.year - 1
        cur = (date(y, 4, 1), date(y + 1, 3, 31))
        prev = (date(y - 1, 4, 1), date(y, 3, 31))
        return [(f"FY {y}-{str(y + 1)[2:]}", *cur), (f"FY {y - 1}-{str(y)[2:]}", *prev)]
    if mode == "quarter":
        q0 = ((a.month - 4) % 12) // 3          # 0 = Apr-Jun
        y = a.year if a.month >= 4 else a.year - 1
        sm = 4 + q0 * 3
        cur = (month(y, sm)[0], month(y, sm + 2)[1])
        prev = (month(y, sm - 3)[0], month(y, sm - 1)[1])
        last = (month(y - 1, sm)[0], month(y - 1, sm + 2)[1])
        names = ["Apr-Jun", "Jul-Sep", "Oct-Dec", "Jan-Mar"]
        lab = lambda d: f"{names[((d.month - 4) % 12) // 3]} {d.year}"
        return [(lab(cur[0]), *cur), (lab(prev[0]), *prev), (lab(last[0]), *last)]
    cur = month(a.year, a.month)
    prev = month(a.year, a.month - 1)
    last = month(a.year - 1, a.month)
    lab = lambda d: d.strftime("%b %Y")
    return [(lab(cur[0]), *cur), (lab(prev[0]), *prev), (lab(last[0]), *last)]


def _figures(c, cid, f, t):
    sg = lambda g, sign: round(sign * store._sum_group(c, cid, g, f, t), 2)
    one = lambda sql: c.execute(sql, (cid, f, t)).fetchone()
    sales_n, sales_amt = one("""SELECT COUNT(*), COALESCE(SUM(amount),0) FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
        AND base='Sales' AND posting=1 AND status=''""")
    rec = one("""SELECT COALESCE(SUM(amount),0) FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
        AND base='Receipt' AND posting=1 AND status=''""")[0]
    pay = one("""SELECT COALESCE(SUM(amount),0) FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
        AND base='Payment' AND posting=1 AND status=''""")[0]
    custs = one("""SELECT COUNT(DISTINCT party) FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
        AND base='Sales' AND posting=1 AND status=''""")[0]
    return {"sales": sg("Sales Accounts", -1), "purchases": sg("Purchase Accounts", 1),
            "direct_exp": sg("Direct Expenses", 1), "indirect_exp": sg("Indirect Expenses", 1),
            "income": round(sg("Direct Incomes", -1) + sg("Indirect Incomes", -1), 2),
            "receipts": round(abs(rec), 2), "payments": round(abs(pay), 2), "bills": sales_n,
            "avg_bill": round(abs(sales_amt) / sales_n, 2) if sales_n else 0, "customers": custs}


def _top(c, cid, f, t, what):
    if what == "customers":
        sql = """SELECT party k, SUM(ABS(amount)) v FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
            AND base='Sales' AND posting=1 AND status='' GROUP BY party"""
    else:
        sql = """SELECT vi.item k, SUM(ABS(vi.amount)) v FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
            WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND v.base='Sales' AND v.posting=1 AND v.status='' GROUP BY vi.item"""
    return {r["k"]: r["v"] for r in c.execute(sql, (cid, f, t)) if r["k"]}


def compare(cid, mode="month", anchor=None):
    ps = _periods(mode if mode in ("month", "quarter", "year") else "month", anchor)
    today = date.today()
    with store.conn() as c:
        cols = []
        for label, f, t in ps:
            fx = _figures(c, cid, f.isoformat(), t.isoformat())
            cols.append({"label": label, "from": f.isoformat(), "to": t.isoformat(),
                         "partial": f <= today <= t, "days_done": (min(today, t) - f).days + 1, "days": (t - f).days + 1, **fx})
        # who and what moved most against the period before
        a, b = ps[0], ps[1]
        moves = {}
        for what in ("customers", "items"):
            now, then = _top(c, cid, a[1].isoformat(), a[2].isoformat(), what), _top(c, cid, b[1].isoformat(), b[2].isoformat(), what)
            diff = [{"name": k, "now": round(now.get(k, 0), 2), "then": round(then.get(k, 0), 2),
                     "change": round(now.get(k, 0) - then.get(k, 0), 2)} for k in set(now) | set(then)]
            diff.sort(key=lambda r: -abs(r["change"]))
            moves[what] = {"up": [r for r in diff if r["change"] > 0][:5], "down": [r for r in diff if r["change"] < 0][:5]}
    return {"mode": mode, "periods": cols, "moves": moves}


# ------------------------------------------------------------------ reorder list
def reorder(cid, days=90, cover=30):
    """Items to buy: at or below the reorder level set in Tally (or the minimum set in Bahi), or that will run out
    within 15 days at the rate they sold over the last 90 days. Suggested quantity covers about a month."""
    import math
    co = next((x for x in store.companies() if x["id"] == cid), None)
    mins = store.stock_mins(co["name"]) if co else {}
    since = (date.today() - timedelta(days=days)).isoformat()
    with store.conn() as c:
        items = [dict(r) for r in c.execute("""SELECT name, parent, unit, closing_qty, closing_rate, reorder, minorder
            FROM stock WHERE company_id=? ORDER BY name""", (cid,))]
        sold = {r["item"]: r["q"] for r in c.execute("""SELECT vi.item, SUM(ABS(vi.qty)) q FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
            WHERE v.company_id=? AND v.base='Sales' AND v.status='' AND v.date>=? GROUP BY vi.item""", (cid, since))}
        last_buy = {}
        for r in c.execute("""SELECT vi.item, v.party, vi.rate, v.date FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
                WHERE v.company_id=? AND v.base='Purchase' AND v.status='' ORDER BY v.date, v.id""", (cid,)):
            last_buy[r["item"]] = {"party": r["party"], "rate": r["rate"], "date": r["date"]}
        phones = {r["name"]: r["mobile"] or r["phone"] or "" for r in c.execute("SELECT name, mobile, phone FROM ledger WHERE company_id=?", (cid,))}
    out = []
    for it in items:
        qty = it["closing_qty"] or 0
        avg = (sold.get(it["name"]) or 0) / days
        level = it["reorder"] if it["reorder"] else mins.get(it["name"])
        left = max(qty, 0) / avg if avg > 0 else None
        why = ""
        if level is not None and qty <= level:
            why = "at or below the reorder level"
        elif avg > 0 and qty <= 0:
            why = "out of stock"
        elif left is not None and left < 15:
            why = f"runs out in about {max(0, int(left))} days"
        if not why:
            continue
        have = max(qty, 0)       # stock below zero in Tally is a timing gap, not something to buy back
        want = max(it["minorder"] or 0, (level * 2 - have) if level else 0, cover * avg - have, 1 if have <= 0 else 0)
        want = math.ceil(want) if want > 0 else 0
        lb = last_buy.get(it["name"]) or {}
        out.append({"item": it["name"], "group": it["parent"], "unit": it["unit"], "qty": round(qty, 3), "level": level,
                    "level_from": "Tally" if it["reorder"] else ("Bahi" if level is not None else ""), "minorder": it["minorder"],
                    "per_day": round(avg, 2), "days_left": None if left is None else round(left, 1), "why": why, "order": want,
                    "supplier": lb.get("party", ""), "supplier_phone": phones.get(lb.get("party", ""), ""),
                    "last_rate": lb.get("rate"), "last_date": lb.get("date"),
                    "value": round(want * (lb.get("rate") or it["closing_rate"] or 0), 2)})
    out.sort(key=lambda r: (r["supplier"] or "~", r["days_left"] if r["days_left"] is not None else -1))
    return {"items": out, "days": days, "cover": cover, "total": round(sum(r["value"] for r in out), 2)}


# ------------------------------------------------------------------ item profit
def profit(cid, d_from=None, d_to=None):
    """Profit on each item sold and on each customer: selling value less the cost of what was sold, cost being the
    item's average purchase rate in Tally (or Tally's stock rate when it was never bought)."""
    a = store.analysis_items(cid, d_from, d_to)
    cost = {r["item"]: r["buy_rate"] for r in a["items"]}
    items = []
    for r in a["items"]:
        c_ = (r["buy_rate"] or 0) * (r["qty"] or 0)
        items.append({"item": r["item"], "unit": r["unit"], "qty": r["qty"], "sales": round(r["value"], 2),
                      "cost": round(c_, 2) if r["buy_rate"] else None, "rate": r["rate"], "buy_rate": r["buy_rate"],
                      "profit": round(r["value"] - c_, 2) if r["buy_rate"] else None, "margin": r["margin"]})
    with store.conn() as c:
        rows = c.execute("""SELECT v.party, vi.item, SUM(ABS(vi.qty)) q, SUM(vi.amount) amt FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
            WHERE v.company_id=? AND v.base='Sales' AND v.status='' AND v.date BETWEEN ? AND ? GROUP BY v.party, vi.item""",
                         (cid, a["from"], a["to"])).fetchall()
    cust = {}
    for r in rows:
        x = cust.setdefault(r["party"], {"party": r["party"], "sales": 0.0, "cost": 0.0, "unknown": 0.0})
        x["sales"] += r["amt"] or 0
        if cost.get(r["item"]):
            x["cost"] += cost[r["item"]] * (r["q"] or 0)
        else:
            x["unknown"] += r["amt"] or 0
    customers = []
    for x in cust.values():
        known = x["sales"] - x["unknown"]
        p = known - x["cost"]
        customers.append({"party": x["party"], "sales": round(x["sales"], 2), "cost": round(x["cost"], 2), "profit": round(p, 2),
                          "margin": round(p / known * 100, 1) if known > 0.5 else None, "no_cost": round(x["unknown"], 2)})
    items.sort(key=lambda r: -(r["profit"] or 0))
    customers.sort(key=lambda r: -r["profit"])
    tp = sum(r["profit"] for r in items if r["profit"] is not None)
    ts = sum(r["sales"] for r in items if r["profit"] is not None)
    return {"from": a["from"], "to": a["to"], "items": items, "customers": customers, "profit": round(tp, 2),
            "sales": round(a["total"], 2), "margin": round(tp / ts * 100, 1) if ts > 0.5 else None,
            "no_cost": [r["item"] for r in items if r["profit"] is None]}


# ------------------------------------------------------------------ cash flow forecast
CASHBANK_GROUPS = ("|Cash-in-Hand|", "|Bank Accounts|", "|Bank OD A/c|")


def cashflow(cid, days=30):
    """Cash and bank today, then day by day: customers' bills falling due come in, suppliers' bills falling due go
    out, and regular expenses go out at their usual daily rate (the last 90 days' payments other than to suppliers).
    Overdue bills are shown apart, as they may or may not come in. Nothing here is Tally's own figure except the
    balances and bills it starts from."""
    today = date.today()
    t = today.isoformat()
    end = (today + timedelta(days=days)).isoformat()
    with store.conn() as c:
        cb = [dict(r) for r in c.execute("SELECT name, chain, closing FROM ledger WHERE company_id=?", (cid,))
              if any(g in (r["chain"] or "") for g in CASHBANK_GROUPS)]
        now = round(sum(r["closing"] for r in cb), 2)
        src = _source(c, cid)
        rec = store._party_bills(c, cid, "receivable", src)
        pay = store._party_bills(c, cid, "payable", src)
        f90 = (today - timedelta(days=90)).isoformat()
        names = {r["name"] for r in cb}
        led = {r["name"]: r["chain"] or "" for r in c.execute("SELECT name, chain FROM ledger WHERE company_id=?", (cid,))}
        exp = 0.0
        for r in c.execute("""SELECT vl.ledger, vl.amount FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
                WHERE v.company_id=? AND v.base='Payment' AND v.posting=1 AND v.status='' AND v.date BETWEEN ? AND ?
                AND vl.amount > 0""", (cid, f90, t)):
            ch = led.get(r["ledger"], "")
            if r["ledger"] in names or "|Sundry Creditors|" in ch or "|Sundry Debtors|" in ch:
                continue
            exp += r["amount"]
    per_day = round(exp / 90, 2)

    def flow(parties):
        by, over, n_over = {}, 0.0, 0
        for p in parties:
            for b in p["bills"]:
                if b["amount"] <= 0.5:
                    continue
                due = b.get("due") or b.get("date") or ""
                if due and due < t:
                    over += b["amount"]
                    n_over += 1
                elif due and due <= end:
                    by[due] = by.get(due, 0) + b["amount"]
        return by, round(over, 2), n_over
    cin, over_in, n_in = flow(rec)
    cout, over_out, n_out = flow(pay)
    series, bal, low = [], now, (now, t)
    for i in range(days + 1):
        d = (today + timedelta(days=i)).isoformat()
        i_ = round(cin.get(d, 0), 2)
        o_ = round(cout.get(d, 0), 2)
        e_ = per_day if i else 0
        bal = round(bal + i_ - o_ - e_, 2)
        series.append({"day": d, "in": i_, "out": o_, "exp": e_, "balance": bal})
        if bal < low[0]:
            low = (bal, d)
    return {"today": t, "days": days, "now": now, "accounts": sorted(({"name": r["name"], "balance": round(r["closing"], 2)} for r in cb),
                                                                   key=lambda r: -abs(r["balance"])),
            "series": series, "end": bal, "low": {"balance": low[0], "day": low[1]},
            "in_total": round(sum(cin.values()), 2), "out_total": round(sum(cout.values()), 2), "exp_total": round(per_day * days, 2),
            "exp_per_day": per_day, "overdue_in": over_in, "overdue_in_n": n_in, "overdue_out": over_out, "overdue_out_n": n_out}


# ------------------------------------------------------------------ customers who stopped buying
def lost_customers(cid):
    """Customers who used to buy regularly (3 or more bills in the last year) but haven't bought for more than
    twice their usual gap, and at least 30 days. Biggest buyers first."""
    today = date.today()
    f = (today - timedelta(days=365)).isoformat()
    with store.conn() as c:
        rows = c.execute("""SELECT v.party, v.date, ABS(v.amount) amt FROM voucher v JOIN ledger l
            ON l.company_id=v.company_id AND l.name=v.party
            WHERE v.company_id=? AND v.base='Sales' AND v.posting=1 AND v.status='' AND v.date>=? AND l.chain LIKE '%|Sundry Debtors|%'
            ORDER BY v.party, v.date""", (cid, f)).fetchall()
        info = {r["name"]: dict(r) for r in c.execute("SELECT name, mobile, phone, closing FROM ledger WHERE company_id=?", (cid,))}
    by = {}
    for r in rows:
        p = by.setdefault(r["party"], {"dates": [], "value": 0.0})
        p["dates"].append(r["date"])
        p["value"] += r["amt"] or 0
    out = []
    for party, p in by.items():
        ds = sorted(set(p["dates"]))
        if len(ds) < 3:
            continue
        gaps = sorted(date.fromisoformat(b).toordinal() - date.fromisoformat(a).toordinal() for a, b in zip(ds, ds[1:]))
        usual = gaps[len(gaps) // 2]
        since = today.toordinal() - date.fromisoformat(ds[-1]).toordinal()
        if since > max(2 * usual, 30):
            i = info.get(party, {})
            out.append({"party": party, "last": ds[-1], "days": since, "usual": usual, "bills": len(p["dates"]),
                        "value": round(p["value"], 2), "phone": i.get("mobile") or i.get("phone") or "",
                        "balance": round(i.get("closing") or 0, 2)})
    out.sort(key=lambda r: -r["value"])
    return {"customers": out, "total": round(sum(r["value"] for r in out), 2)}


# ------------------------------------------------------------------ month-end statements
STMT_FILE = os.path.join(DATA_DIR, "statements.json")


def statements(cid, company, link_of):
    """Every customer who owes money, with a link to their statement, to send on WhatsApp one by one. Each send is
    marked for the month, so a second phone or a second sitting carries on where the first stopped."""
    month = date.today().strftime("%Y-%m")
    sent = _load(STMT_FILE, {}).get(str(cid), {}).get(month, {})
    with store.conn() as c:
        rows = [dict(r) for r in c.execute("""SELECT name, closing, mobile, phone FROM ledger WHERE company_id=?
            AND chain LIKE '%|Sundry Debtors|%' AND closing > 0.5 ORDER BY closing DESC""", (cid,))]
    out = [{"party": r["name"], "balance": round(r["closing"], 2), "phone": r["mobile"] or r["phone"] or "",
            "url": link_of(r["name"]), "sent": sent.get(r["name"])} for r in rows]
    return {"month": month, "company": company, "parties": out, "sent": sum(1 for r in out if r["sent"]),
            "total": round(sum(r["balance"] for r in out), 2)}


def statement_sent(cid, party, by=""):
    month = date.today().strftime("%Y-%m")
    with _lock:
        d = _load(STMT_FILE, {})
        co = d.setdefault(str(cid), {})
        for m in [m for m in co if m < month]:          # keep only this month's marks
            co.pop(m)
        co.setdefault(month, {})[party] = {"time": time.time(), "by": by}
        _save(STMT_FILE, d)
    return {"ok": True}


# ------------------------------------------------------------------ sales target
TARGET_FILE = os.path.join(DATA_DIR, "targets.json")


def target(cid):
    """This month's sales against the target the owner set (one figure for every month, or one for this month)."""
    today = date.today()
    month = today.strftime("%Y-%m")
    t = _load(TARGET_FILE, {}).get(str(cid), {})
    goal = t.get("months", {}).get(month, t.get("monthly"))
    f = today.replace(day=1)
    nxt = (f + timedelta(days=32)).replace(day=1)
    with store.conn() as c:
        sales = _figures(c, cid, f.isoformat(), today.isoformat())["sales"]
    left_days = (nxt - today).days
    out = {"month": month, "target": goal, "monthly": t.get("monthly"), "sales": sales, "days_left": left_days,
           "days_in_month": (nxt - f).days, "day": today.day}
    if goal:
        out["pct"] = round(sales / goal * 100, 1) if goal else 0
        out["need_per_day"] = round(max(0, goal - sales) / left_days, 2) if left_days else 0
        out["on_track"] = sales >= goal * today.day / out["days_in_month"]
    return out


def set_target(cid, monthly=None, this_month=None):
    with _lock:
        d = _load(TARGET_FILE, {})
        t = d.setdefault(str(cid), {})
        if monthly is not None:
            t["monthly"] = round(float(monthly), 2) if float(monthly) > 0 else None
        if this_month is not None:
            m = date.today().strftime("%Y-%m")
            if float(this_month) > 0:
                t.setdefault("months", {})[m] = round(float(this_month), 2)
            else:
                t.setdefault("months", {}).pop(m, None)
        _save(TARGET_FILE, d)
    return target(cid)


# ------------------------------------------------------------------ price list
def price_list(cid, group="", with_gst=False, in_stock=False):
    """Selling rates of stock items: the last rate each was sold at in Tally (Tally's stock rate when never sold),
    grouped by stock group. With GST adds the item's GST rate."""
    import invoice
    fm = invoice.form(cid, "sales")
    with store.conn() as c:
        parent = {r["name"]: r["parent"] or "" for r in c.execute("SELECT name, parent FROM stock WHERE company_id=?", (cid,))}
    groups = {}
    for it in fm["items"]:
        g = parent.get(it["name"], "")
        if group and g != group:
            continue
        if in_stock and (it.get("in_hand") or 0) <= 0:
            continue
        r = it.get("rate") or 0
        if r <= 0:
            continue
        rate = round(r * (1 + (it.get("gst") or 0) / 100), 2) if with_gst else round(r, 2)
        groups.setdefault(g, []).append({"name": it["name"], "unit": it.get("unit") or "", "hsn": it.get("hsn") or "",
                                         "gst": it.get("gst"), "rate": rate})
    all_groups = sorted({g for g in parent.values() if g})
    return {"groups": [{"name": g, "items": sorted(v, key=lambda x: x["name"].lower())} for g, v in sorted(groups.items())],
            "all_groups": all_groups, "count": sum(len(v) for v in groups.values()), "gst": bool(with_gst)}
