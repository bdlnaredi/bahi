"""GST helpers for GSTR-1 and the e-invoice / e-way bill check: which ledgers are GST ledgers and
their side (input or output), and a month's dates. (GSTR-3B and the GST summary were removed, to be built again from
scratch; GSTR-2B matching was removed.)"""
import json
import re
from datetime import date

import store

def _month_range(month):
    y, m = int(month[:4]), int(month[5:7])
    end = date(y + (m == 12), m % 12 + 1, 1).toordinal() - 1
    return f"{y:04d}-{m:02d}-01", date.fromordinal(end).isoformat()


OTHER_DUES = re.compile(r"interest|late\s*fee|penalty|other charges", re.I)   # GST ledgers that aren't tax (table 6.1)


RET_SQL = "(date BETWEEN ? AND ? OR extra LIKE '%\"ret_moved\"%' OR extra LIKE '%\"gst_excluded\"%')"


def in_return(x, vdate, f, t):
    """Is this voucher in the GST return for f..t? Its own date, unless Tally has it moved to another month's return
    (then that month's), or excluded from the returns. Moved with the new month unknown: in no month's return."""
    if x.get("gst_excluded"):
        return False
    if x.get("ret_moved"):
        d = x.get("ret_date")
        return bool(d) and f <= d <= t
    return f <= vdate <= t


def moved(cid, f, t, bases=None):
    """The vouchers moved into or out of this period's return in Tally (of these voucher kinds, or all)."""
    out, inn = [], []
    with store.conn() as c:
        for v in c.execute("""SELECT id, date, vtype, base, number, party, amount, extra FROM voucher WHERE company_id=? AND posting=1 AND status=''
                AND (extra LIKE '%"ret_moved"%' OR extra LIKE '%"gst_excluded"%') ORDER BY date, id""", (cid,)):
            if bases and v["base"] not in bases:
                continue
            x = json.loads(v["extra"] or "{}")
            r = {"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"], "party": v["party"] or "",
                 "value": round(abs(v["amount"] or 0), 2), "ret_date": x.get("ret_date") or "", "excluded": bool(x.get("gst_excluded"))}
            here = in_return(x, v["date"], f, t)
            if f <= v["date"] <= t and not here:
                out.append(r)
            elif here and not f <= v["date"] <= t:
                inn.append(r)
    return {"out": out, "in": inn}


def _tax_side(c, cid):
    """{ledger: (head, side)} for every GST ledger (the same rules as the GST summary)."""
    led = {r["name"]: r for r in c.execute("SELECT name, chain, taxtype, gst_head, closing, gstin FROM ledger WHERE company_id=?", (cid,))}
    tax = {n: l for n, l in led.items() if store._is_tax(l) and not OTHER_DUES.search(n + " " + (l["gst_head"] or ""))}
    use = {r["ledger"]: (r["s"], r["p"]) for r in c.execute("""SELECT vl.ledger,
        SUM(CASE WHEN v.base IN ('Sales','Debit Note') THEN 1 ELSE 0 END) s,
        SUM(CASE WHEN v.base IN ('Purchase','Credit Note') THEN 1 ELSE 0 END) p
        FROM vline vl JOIN voucher v ON v.id=vl.voucher_id WHERE v.company_id=? GROUP BY vl.ledger""", (cid,))}
    out = {}
    for n, l in tax.items():
        low = n.lower()
        if "input" in low or "itc" in low:
            sd = "input"
        elif "output" in low:
            sd = "output"
        else:
            s_, p_ = use.get(n, (0, 0))
            sd = "output" if s_ > p_ else "input" if p_ > s_ else ("output" if l["closing"] < 0 else "input")
        out[n] = (store._gst_head(l), sd)
    return out, led


def einvoice_status(cid, month, ewb_limit=50000):
    """Sales of the month that look like they need an e-invoice (IRN) or an e-way bill but have none in Tally.
    E-invoice: only once the company issues e-invoices at all (an IRN on any voucher), for sales to registered
    buyers. E-way bill: goods worth more than the limit (₹50,000 in most states). A guide to check, not a ruling."""
    f, t = _month_range(month)
    today = date.today()
    with store.conn() as c:
        led = {r["name"]: dict(r) for r in c.execute("SELECT name, chain, gstin FROM ledger WHERE company_id=?", (cid,))}
        uses = c.execute("""SELECT COUNT(*) FROM voucher WHERE company_id=? AND extra LIKE '%"irn"%'""", (cid,)).fetchone()[0] > 0
        vs = store._rows(c, """SELECT v.id, v.date, v.vtype, v.base, v.number, v.party, v.party_gstin, v.amount, v.extra,
            (SELECT COUNT(*) FROM vitem WHERE voucher_id=v.id) items FROM voucher v
            WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND v.posting=1 AND v.status=''
            AND v.base IN ('Sales','Credit Note','Debit Note') ORDER BY v.date, v.id""", (cid, f, t))
    rows = []
    for v in vs:
        pl = led.get(v["party"]) or {}
        if v["base"] != "Sales" and "|Sundry Debtors|" not in (pl.get("chain") or ""):
            continue
        try:
            x = json.loads(v["extra"] or "{}")
        except ValueError:
            x = {}
        gstin = (v["party_gstin"] or pl.get("gstin") or "").strip()
        has_irn = bool(x.get("irn")) and str(x.get("irn_cancelled", "")).lower() not in ("yes", "true", "1")
        value = abs(v["amount"] or 0)
        need_irn = uses and bool(gstin) and not has_irn
        need_ewb = v["base"] == "Sales" and v["items"] > 0 and value > ewb_limit and not x.get("ewb_no")
        rows.append({"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"], "party": v["party"] or "",
                     "gstin": gstin, "value": round(value, 2), "irn": has_irn, "ewb": bool(x.get("ewb_no")), "ewb_no": x.get("ewb_no", ""),
                     "need_irn": need_irn, "need_ewb": need_ewb,
                     "age": today.toordinal() - date.fromisoformat(v["date"]).toordinal()})
    b2b = [r for r in rows if r["gstin"]]
    return {"month": month, "from": f, "to": t, "uses_einvoice": uses, "ewb_limit": ewb_limit,
            "count": len(rows), "b2b": len(b2b), "with_irn": sum(1 for r in rows if r["irn"]),
            "with_ewb": sum(1 for r in rows if r["ewb"]),
            "need_irn": [r for r in rows if r["need_irn"]], "need_ewb": [r for r in rows if r["need_ewb"]]}
