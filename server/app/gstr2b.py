"""GSTR-2B matching: the GSTR-2B JSON downloaded from the GST portal, against the purchase bills in Tally.
Shows which bills match, which differ in tax, which suppliers' bills are in 2B but not entered in Tally, and which
Tally bills aren't in 2B (the supplier hasn't filed them: that credit is at risk). Kept apart from Tally."""
import io
import json
import os
import re
import threading
import time
import zipfile
from datetime import date

import gstr
import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DIR = os.path.join(DATA_DIR, "gstr2b")
_lock = threading.Lock()
HEADS = ("IGST", "CGST", "SGST", "Cess")


def _path(cid):
    return os.path.join(DIR, f"{int(cid)}.json")


def _load(cid):
    try:
        with open(_path(cid)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(cid, d):
    os.makedirs(DIR, exist_ok=True)
    with open(_path(cid) + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(_path(cid) + ".tmp", _path(cid))


def norm(no):
    """Invoice numbers as suppliers write them differ in case, slashes and leading zeros: compare the letters and
    digits only, without leading zeros."""
    s = re.sub(r"[^A-Z0-9]", "", str(no or "").upper())
    return s.lstrip("0") or s


def _d(s):
    s = str(s or "")
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", s)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else s[:10]


def _f(x):
    try:
        return round(float(x or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _find(o, key):
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = _find(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find(v, key)
            if r is not None:
                return r
    return None


def _amounts(x):
    """Taxable value and tax heads of an invoice: at its own level, or added up from its items."""
    items = x.get("items") or x.get("itms") or []
    src = items if items and not any(k in x for k in ("txval", "igst", "cgst")) else [x]
    out = {"taxable": 0.0, "IGST": 0.0, "CGST": 0.0, "SGST": 0.0, "Cess": 0.0}
    for it in src:
        it = it.get("itm_det", it) if isinstance(it, dict) else {}
        out["taxable"] += _f(it.get("txval"))
        out["IGST"] += _f(it.get("igst") or it.get("iamt"))
        out["CGST"] += _f(it.get("cgst") or it.get("camt"))
        out["SGST"] += _f(it.get("sgst") or it.get("samt"))
        out["Cess"] += _f(it.get("cess") or it.get("csamt"))
    return {k: round(v, 2) for k, v in out.items()}


def parse(raw, fname=""):
    """The portal's GSTR-2B file (JSON, or the zip it comes in) → (period 'YYYY-MM', own GSTIN, documents)."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            js = [n for n in z.namelist() if n.lower().endswith(".json")]
            if not js:
                raise ValueError("The zip has no GSTR-2B JSON file in it.")
            raw = z.read(js[0])
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("That isn't the GSTR-2B JSON file. On the GST portal, open GSTR-2B and choose Download JSON.")
    docdata = _find(d, "docdata")
    rtnprd = str(_find(d, "rtnprd") or "")
    if not isinstance(docdata, dict) or not re.match(r"^\d{6}$", rtnprd):
        raise ValueError("This JSON isn't a GSTR-2B (no return period or documents in it).")
    period = f"{rtnprd[2:]}-{rtnprd[:2]}"
    docs = []
    for sec, listkey, nokey, kind in (("b2b", "inv", "inum", "Invoice"), ("b2ba", "inv", "inum", "Amended invoice"),
                                      ("cdnr", "nt", "ntnum", "Note"), ("cdnra", "nt", "ntnum", "Amended note")):
        for sup in docdata.get(sec) or []:
            for x in sup.get(listkey) or []:
                a = _amounts(x)
                credit_note = str(x.get("typ", "")).upper() == "C"
                sign = -1 if credit_note else 1
                docs.append({"gstin": str(sup.get("ctin", "")).upper(), "supplier": sup.get("trdnm") or "",
                             "number": str(x.get(nokey, "")), "date": _d(x.get("dt")), "kind": "Credit note" if credit_note else kind,
                             "value": round(sign * _f(x.get("val")), 2), "itc": str(x.get("itcavl", "Y")).upper() != "N",
                             "rcm": str(x.get("rev", "N")).upper() == "Y", **{k: round(sign * v, 2) for k, v in a.items()}})
    if not docs:
        raise ValueError(f"The GSTR-2B for {period} has no invoices or notes from suppliers.")
    return period, str(_find(d, "gstin") or ""), docs


def upload(cid, raw, fname=""):
    period, gstin, docs = parse(raw, fname)
    with _lock:
        d = _load(cid)
        d[period] = {"uploaded": time.time(), "file": fname[:120], "gstin": gstin, "docs": docs}
        _save(cid, d)
    return period


def remove(cid, period):
    with _lock:
        d = _load(cid)
        d.pop(period, None)
        _save(cid, d)
    return {"ok": True}


def _tally(cid, f, t):
    """Purchase bills (and notes from suppliers) in Tally between f and t, with the supplier's GSTIN, the
    supplier's bill number and the tax on Tally's GST ledgers."""
    with store.conn() as c:
        tax, led = gstr._tax_side(c, cid)
        vs = store._rows(c, """SELECT id, date, vtype, base, number, reference, party, party_gstin, amount FROM voucher
            WHERE company_id=? AND date BETWEEN ? AND ? AND posting=1 AND status=''
            AND base IN ('Purchase','Debit Note','Credit Note')""", (cid, f, t))
        out = []
        for v in vs:
            pl = led.get(v["party"])
            ch = (pl["chain"] if pl else "") or ""
            if v["base"] != "Purchase" and "|Sundry Creditors|" not in ch:
                continue                       # a note to a customer belongs to sales
            gstin = (v["party_gstin"] or (pl["gstin"] if pl else "") or "").strip().upper()
            heads = {h: 0.0 for h in HEADS}
            for x in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],)):
                if x["ledger"] in tax:
                    heads[tax[x["ledger"]][0]] += x["amount"]
            heads = {h: round(a, 2) for h, a in heads.items()}
            out.append({"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"], "ref": v["reference"] or "",
                        "party": v["party"] or "", "gstin": gstin, "value": round(abs(v["amount"] or 0), 2), **heads,
                        "tax": round(sum(heads.values()), 2)})
    return out


def _shift(iso, months):
    y, m = int(iso[:4]), int(iso[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"


def periods(cid):
    d = _load(cid)
    return [{"period": p, "uploaded": v["uploaded"], "file": v.get("file", ""), "count": len(v["docs"])}
            for p, v in sorted(d.items(), reverse=True)]


def match(cid, period):
    d = _load(cid)
    if period not in d:
        return {"period": period, "have": False, "periods": periods(cid)}
    docs = d[period]["docs"]
    p0 = f"{period}-01"
    # Tally bills from six months before to one month after: a bill is often entered in another month
    tl = _tally(cid, _shift(p0, -6), date.fromordinal(date.fromisoformat(_shift(p0, 2)).toordinal() - 1).isoformat())
    by_key = {}
    for v in tl:
        for no in {norm(v["ref"]), norm(v["number"]) if not v["ref"] else ""} - {""}:
            by_key.setdefault((v["gstin"], no), []).append(v)
    used = set()
    matched, differ, missing = [], [], []
    for x in docs:
        cands = [v for v in by_key.get((x["gstin"], norm(x["number"])), []) if v["id"] not in used]
        if not cands:
            missing.append(x)
            continue
        v = cands[0]
        used.add(v["id"])
        x_tax = round(sum(x[h] for h in HEADS), 2)
        tol = max(1.0, abs(x_tax) * 0.001)
        diffs = [h for h in HEADS if abs(abs(x[h]) - abs(v[h])) > tol]
        row = {"doc": x, "tally": v, "tax_2b": x_tax, "tax_tally": v["tax"], "diff": round(abs(x_tax) - abs(v["tax"]), 2), "heads": diffs}
        (differ if diffs else matched).append(row)
    # Tally bills of this month that no GSTR-2B (of any month uploaded) has
    in_any = set()
    for p, v in d.items():
        for x in v["docs"]:
            in_any.add((x["gstin"], norm(x["number"])))
    month_end = date.fromordinal(date.fromisoformat(_shift(p0, 1)).toordinal() - 1).isoformat()
    not_in = [v for v in tl if p0 <= v["date"] <= month_end and v["gstin"] and v["id"] not in used
              and (v["gstin"], norm(v["ref"] or v["number"])) not in in_any and abs(v["tax"]) > 0.005]
    no_gstin = [v for v in tl if p0 <= v["date"] <= month_end and not v["gstin"] and abs(v["tax"]) > 0.005]
    sm = lambda rows, key=None: round(sum(abs(key(r)) for r in rows), 2)
    return {"period": period, "have": True, "uploaded": d[period]["uploaded"], "file": d[period].get("file", ""),
            "periods": periods(cid), "count": len(docs),
            "matched": matched, "differ": differ, "missing": missing, "not_in": not_in, "no_gstin": no_gstin,
            "totals": {"itc_2b": round(sum(sum(x[h] for h in HEADS) for x in docs if x["itc"]), 2),
                       "matched": sm(matched, lambda r: r["tax_2b"]), "differ": sm(differ, lambda r: r["diff"]),
                       "missing": sm(missing, lambda x: sum(x[h] for h in HEADS)),
                       "at_risk": sm(not_in, lambda v: v["tax"])}}
