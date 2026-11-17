"""Quotations (estimates) made in the app: kept here only, shared as a PDF laid out like Tally's invoice, and turned
into a sales order (an ordinary phone entry) when the customer agrees. Nothing goes into Tally until then."""
import json
import os
import re
import threading
import time
from datetime import date, timedelta

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
FILE = os.path.join(DATA_DIR, "quotes.json")
_lock = threading.Lock()


def _load():
    try:
        with open(FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, FILE)


def _co(d, cid):
    return d.setdefault(str(cid), {"next": 1, "quotes": []})


def listing(cid):
    qs = _co(_load(), cid)["quotes"]
    out = [{k: q[k] for k in ("id", "number", "date", "valid", "party", "total", "status", "by")} for q in qs]
    out.sort(key=lambda q: (q["date"], q["id"]), reverse=True)
    return {"quotes": out}


def get(cid, qid):
    return next((q for q in _co(_load(), cid)["quotes"] if q["id"] == qid), None)


def _num(x, what):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"Enter the {what}.")
    if v < 0 or v > 1e11:
        raise ValueError(f"Check the {what}.")
    return round(v, 2)


def save(cid, data, by=""):
    """Check and store a quotation (new, or changes to one). Tax is worked out from each item's GST rate."""
    party = str(data.get("party", "")).strip()[:120]
    if not party:
        raise ValueError("Enter the customer's name.")
    day = str(data.get("date") or date.today().isoformat())
    valid = str(data.get("valid") or (date.fromisoformat(day) + timedelta(days=15)).isoformat())
    for d_ in (day, valid):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d_):
            raise ValueError("Check the dates.")
    inter = bool(data.get("igst"))
    with store.conn() as c:
        known = {r["name"]: dict(r) for r in c.execute("SELECT name, unit, hsn, gst FROM stock WHERE company_id=?", (cid,))}
    items = []
    for it in data.get("items") or []:
        name = str(it.get("item", "")).strip()
        if not name:
            continue
        q = _num(it.get("qty"), f"quantity of {name}")
        r = _num(it.get("rate"), f"rate of {name}")
        g = _num(it.get("gst") if it.get("gst") not in (None, "") else (known.get(name, {}) or {}).get("gst") or 0, f"GST rate of {name}")
        if q <= 0:
            continue
        k = known.get(name)
        items.append({"item": name, "qty": q, "unit": (k["unit"] if k else str(it.get("unit") or "Nos"))[:20],
                      "rate": r, "amount": round(q * r, 2), "gst": g, "hsn": (k["hsn"] if k else "") or ""})
    if not items:
        raise ValueError("Add at least one item.")
    taxable = round(sum(i["amount"] for i in items), 2)
    tax = round(sum(i["amount"] * i["gst"] / 100 for i in items), 2)
    total = round(taxable + tax, 2)
    with _lock:
        d = _load()
        co = _co(d, cid)
        qid = data.get("id")
        q = next((x for x in co["quotes"] if x["id"] == qid), None) if qid else None
        if not q:
            q = {"id": co["next"], "number": f"Q/{co['next']}", "status": "open", "made": time.time(), "by": by}
            co["next"] += 1
            co["quotes"].append(q)
        q.update({"party": party, "date": day, "valid": valid, "igst": inter, "items": items, "taxable": taxable,
                  "tax": tax, "total": total, "notes": str(data.get("notes", ""))[:600], "changed": time.time()})
        _save(d)
    return q


def set_status(cid, qid, status):
    if status not in ("open", "ordered", "lost"):
        raise ValueError("Unknown status.")
    with _lock:
        d = _load()
        q = next((x for x in _co(d, cid)["quotes"] if x["id"] == qid), None)
        if not q:
            raise ValueError("No such quotation.")
        q["status"] = status
        _save(d)
    return q


def delete(cid, qid):
    with _lock:
        d = _load()
        co = _co(d, cid)
        co["quotes"] = [x for x in co["quotes"] if x["id"] != qid]
        _save(d)
    return {"ok": True}


def pdf_data(cid, q):
    """The quotation in the shape the invoice PDF takes (the same layout as a Tally invoice, titled Quotation)."""
    with store.conn() as c:
        crow = c.execute("SELECT name, info FROM company WHERE id=?", (cid,)).fetchone()
        p = c.execute("SELECT name, gstin, mobile, phone, email, extra FROM ledger WHERE company_id=? AND name=?",
                      (cid, q["party"])).fetchone()
        bank = None
        for b in c.execute("""SELECT name, extra FROM ledger WHERE company_id=? AND chain LIKE '%|Bank Accounts|%'
                ORDER BY ABS(closing) DESC""", (cid,)):
            bx = json.loads(b["extra"] or "{}")
            if bx.get("bank_account"):
                bank = {"name": b["name"], **bx}
                break
    pinfo = {"name": q["party"]}
    if p:
        pinfo = {k: p[k] for k in ("name", "gstin", "mobile", "phone", "email")}
        pinfo.update(json.loads(p["extra"] or "{}"))
        pinfo["gstin"] = p["gstin"] or pinfo.get("gstin", "")
    lines = [{"ledger": q["party"], "amount": q["total"], "kind": "party", "cashbank": False},
             {"ledger": "Sales", "amount": -q["taxable"], "kind": "sales", "cashbank": False}]
    by_rate = {}
    for i in q["items"]:
        by_rate[i["gst"]] = by_rate.get(i["gst"], 0) + i["amount"] * i["gst"] / 100
    tax = sum(by_rate.values())
    if tax > 0.005:
        if q.get("igst"):
            lines.append({"ledger": "IGST", "amount": -round(tax, 2), "kind": "tax", "cashbank": False, "head": "IGST"})
        else:
            lines.append({"ledger": "CGST", "amount": -round(tax / 2, 2), "kind": "tax", "cashbank": False, "head": "CGST"})
            lines.append({"ledger": "SGST", "amount": -round(tax / 2, 2), "kind": "tax", "cashbank": False, "head": "SGST"})
    note = f"Valid till {date.fromisoformat(q['valid']).strftime('%d-%b-%Y')}." + (f" {q['notes']}" if q.get("notes") else "")
    return {"company": crow["name"] if crow else "", "company_info": json.loads((crow["info"] if crow else None) or "{}"), "bank": bank,
            "voucher": {"vtype": "Quotation", "base": "Sales", "title": "Quotation", "no_label": "Quotation No.", "number": q["number"], "date": q["date"],
                        "party": q["party"], "narration": note, "amount": q["total"], "extra": {},
                        "footer": "This is a quotation, not a tax invoice"},
            "lines": lines, "party": pinfo, "bills": [],
            "items": [{"item": i["item"], "qty": -i["qty"], "unit": i["unit"], "rate": i["rate"], "amount": i["amount"],
                       "hsn": i["hsn"], "disc": 0, "descr": "", "gst": i["gst"], "gst_master": i["gst"]} for i in q["items"]]}
