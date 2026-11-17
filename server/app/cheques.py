"""Cheque register: cheques on bank entries in Tally (from the bank details Tally keeps on each voucher), plus
post-dated cheques written down in Bahi before they go into Tally (a customer hands over three PDCs, say).
Reminds a few days before each one's date. The cheques written down here never go into Tally by themselves."""
import json
import os
import threading
import time
from datetime import date, timedelta

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
FILE = os.path.join(DATA_DIR, "cheques.json")
_lock = threading.Lock()
STATUSES = ("pending", "deposited", "cleared", "bounced", "cancelled")


def _load():
    try:
        with open(FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    with open(FILE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(FILE + ".tmp", FILE)


def _co(d, cid):
    return d.setdefault(str(cid), {"next": 1, "cheques": []})


def save(cid, data, by=""):
    kind = "in" if data.get("kind") != "out" else "out"
    party = str(data.get("party", "")).strip()[:120]
    no = str(data.get("number", "")).strip()[:40]
    day = str(data.get("date", ""))
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ValueError("Enter the cheque date.")
    try:
        amt = round(float(data.get("amount")), 2)
    except (TypeError, ValueError):
        raise ValueError("Enter the amount.")
    if not party or not no or amt <= 0:
        raise ValueError("Enter the party, cheque number and amount.")
    with _lock:
        d = _load()
        co = _co(d, cid)
        cid_ = data.get("id")
        ch = next((x for x in co["cheques"] if x["id"] == cid_), None) if cid_ else None
        if not ch:
            ch = {"id": co["next"], "status": "pending", "made": time.time(), "by": by}
            co["next"] += 1
            co["cheques"].append(ch)
        ch.update({"kind": kind, "party": party, "number": no, "date": day, "amount": amt,
                   "bank": str(data.get("bank", "")).strip()[:60], "note": str(data.get("note", "")).strip()[:200]})
        _save(d)
    return ch


def set_status(cid, chid, status, by=""):
    if status not in STATUSES and status != "delete":
        raise ValueError("Unknown status.")
    with _lock:
        d = _load()
        co = _co(d, cid)
        if status == "delete":
            co["cheques"] = [x for x in co["cheques"] if x["id"] != chid]
        else:
            ch = next((x for x in co["cheques"] if x["id"] == chid), None)
            if not ch:
                raise ValueError("No such cheque.")
            ch["status"] = status
            ch["changed"] = time.time()
            ch["changed_by"] = by
        _save(d)
    return {"ok": True}


def listing(cid):
    today = date.today()
    t = today.isoformat()
    soon = (today + timedelta(days=7)).isoformat()
    since = (today - timedelta(days=120)).isoformat()
    rows = []
    for x in _co(_load(), cid)["cheques"]:
        if x["status"] in ("cleared", "cancelled") and x["date"] < since:
            continue
        rows.append({**x, "src": "bahi"})
    with store.conn() as c:
        for v in c.execute("""SELECT id, date, vtype, number, party, extra, status FROM voucher WHERE company_id=?
                AND extra LIKE '%"cheques"%' AND date>=? ORDER BY date""", (cid, since)):
            try:
                x = json.loads(v["extra"] or "{}")
            except ValueError:
                continue
            for q in x.get("cheques") or []:
                if q.get("type") and not any(w in q["type"].lower() for w in ("cheque", "dd", "check")):
                    continue                    # NEFT, UPI and the like aren't cheques
                st = "cleared" if q.get("cleared") else "cancelled" if v["status"] == "cancelled" else "pending"
                qd = q.get("date") or v["date"]
                if st == "pending" and qd < (today - timedelta(days=30)).isoformat():
                    continue                    # old and never marked cleared in Tally: most likely cleared long ago
                rows.append({"src": "tally", "vid": v["id"], "vtype": v["vtype"], "vno": v["number"], "kind": "in" if q.get("in") else "out",
                             "party": v["party"] or "", "number": q["no"], "date": q.get("date") or v["date"], "amount": q["amount"],
                             "bank": q.get("bank") or q.get("ledger") or "", "status": st, "cleared": q.get("cleared") or "",
                             "postdated": bool(x.get("postdated")), "account": q.get("ledger", "")})
    for r in rows:
        open_ = r["status"] in ("pending", "deposited")
        r["due"] = open_ and r["date"] <= soon
        r["late"] = open_ and r["date"] < t
        r["days"] = date.fromisoformat(r["date"]).toordinal() - today.toordinal()
    rows.sort(key=lambda r: (r["status"] not in ("pending", "deposited", "bounced"), r["date"]))
    due = [r for r in rows if r["due"]]
    return {"today": t, "cheques": rows, "due_in": sum(1 for r in due if r["kind"] == "in"),
            "due_out": sum(1 for r in due if r["kind"] == "out"),
            "due_in_amount": round(sum(r["amount"] for r in due if r["kind"] == "in"), 2),
            "due_out_amount": round(sum(r["amount"] for r in due if r["kind"] == "out"), 2)}
