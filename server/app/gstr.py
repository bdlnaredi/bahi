"""GSTR-1 and GSTR-3B summaries for a month, put together from the vouchers synced from Tally, to check before
filing. Tax amounts are the ones on Tally's tax ledgers in each voucher; the rate of each line is the one Tally
gave it. Nothing is worked out afresh except splitting a voucher's tax across its lines by value, for the HSN table.
Bahi doesn't file anything."""
import json
import re
from collections import defaultdict
from datetime import date

import store

SLABS = [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28, 40]
B2CL_LIMIT = 100000      # inter-state sales to unregistered buyers above this go in B2C (Large)
OUT_BASES = ("Sales", "Credit Note", "Debit Note")


def _snap(r):
    return min(SLABS, key=lambda s: abs(s - r))


def _month_range(month):
    y, m = int(month[:4]), int(month[5:7])
    end = date(y + (m == 12), m % 12 + 1, 1).toordinal() - 1
    return f"{y:04d}-{m:02d}-01", date.fromordinal(end).isoformat()


def _tax_side(c, cid):
    """{ledger: (head, side)} for every GST ledger (the same rules as the GST summary)."""
    led = {r["name"]: r for r in c.execute("SELECT name, chain, taxtype, gst_head, closing, gstin FROM ledger WHERE company_id=?", (cid,))}
    tax = {n: l for n, l in led.items() if store._is_tax(l)}
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


def gstr1(cid, month):
    f, t = _month_range(month)
    with store.conn() as c:
        tax, led = _tax_side(c, cid)
        co = c.execute("SELECT name FROM company WHERE id=?", (cid,)).fetchone()
        vs = store._rows(c, f"""SELECT id, date, vtype, base, number, party, party_gstin, amount FROM voucher
            WHERE company_id=? AND date BETWEEN ? AND ? AND posting=1 AND status='' AND base IN ({",".join("?" * len(OUT_BASES))})
            ORDER BY date, id""", [cid, f, t, *OUT_BASES])
        stock_hsn = {r["name"]: (r["hsn"], r["unit"]) for r in c.execute("SELECT name, hsn, unit FROM stock WHERE company_id=?", (cid,))}
        invoices, hsn = [], defaultdict(lambda: {"qty": 0.0, "taxable": 0.0, "IGST": 0.0, "CGST": 0.0, "SGST": 0.0, "Cess": 0.0})
        for v in vs:
            lines = c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],)).fetchall()
            items = c.execute("SELECT item, qty, unit, amount, hsn, gst FROM vitem WHERE voucher_id=?", (v["id"],)).fetchall()
            sign = -1 if v["base"] == "Credit Note" else 1          # a credit note reduces what was sold
            heads = {"IGST": 0.0, "CGST": 0.0, "SGST": 0.0, "Cess": 0.0}
            for x in lines:          # credited tax (a sale) counts up, debited tax (a credit note) counts down
                if x["ledger"] in tax:
                    heads[tax[x["ledger"]][0]] += -x["amount"]
            heads = {k: round(val, 2) if abs(val) > 0.005 else 0.0 for k, val in heads.items()}
            tax_total = sum(heads.values())
            party = v["party"] or ""
            gstin = (v["party_gstin"] or (led.get(party)["gstin"] if party in led else "") or "").strip().upper()
            # taxable value: the stock lines at the rate Tally gave each; otherwise the income lines of the voucher
            by_rate = defaultdict(float)
            if items:
                for it in items:
                    by_rate[it["gst"] if it["gst"] is not None else None] += abs(it["amount"])
            else:
                for x in lines:
                    l = led.get(x["ledger"])
                    if x["ledger"] in tax or x["ledger"] == party or not l or re.search(r"round", x["ledger"], re.I):
                        continue
                    if any(g in (l["chain"] or "") for g in ("|Sundry Debtors|", "|Sundry Creditors|", "|Bank Accounts|", "|Cash-in-Hand|")):
                        continue
                    by_rate[None] += abs(x["amount"])
            taxable = sum(by_rate.values())
            if None in by_rate:            # rate not known: the voucher's own tax over its value
                guess = _snap(abs(tax_total) / taxable * 100) if taxable > 0.5 else 0
                by_rate[guess] = by_rate.get(guess, 0) + by_rate.pop(None)
            inter = abs(heads["IGST"]) > 0.005
            value = abs(v["amount"] or 0)
            kind = ("CDNR" if gstin else "CDNUR") if v["base"] != "Sales" else \
                   "B2B" if gstin else ("B2CL" if inter and value > B2CL_LIMIT else "B2CS")
            rates = [{"rate": r, "taxable": round(sign * a, 2)} for r, a in sorted(by_rate.items())]
            invoices.append({"id": v["id"], "date": v["date"], "number": v["number"], "vtype": v["vtype"], "base": v["base"],
                             "party": party, "gstin": gstin, "kind": kind, "inter": inter, "value": round(sign * value, 2),
                             "taxable": round(sign * taxable, 2), "rates": rates, **heads})
            # HSN table: each stock line, the voucher's tax shared out over its lines by value
            if items:
                for it in items:
                    share = abs(it["amount"]) / taxable if taxable else 0
                    h, u = stock_hsn.get(it["item"], ("", it["unit"]))
                    key = ((it["hsn"] or h or "No HSN").strip(), it["gst"], it["unit"] or u or "")
                    row = hsn[key]
                    row["qty"] += sign * abs(it["qty"] or 0)
                    row["taxable"] += sign * abs(it["amount"])
                    for k in ("IGST", "CGST", "SGST", "Cess"):
                        row[k] += heads[k] * share
        # sections
        def tot(rows, keys=("taxable", "IGST", "CGST", "SGST", "Cess")):
            return {k: round(sum(r[k] for r in rows), 2) for k in keys}
        b2cs = defaultdict(lambda: {"taxable": 0.0, "IGST": 0.0, "CGST": 0.0, "SGST": 0.0, "Cess": 0.0, "count": 0})
        for inv in invoices:
            if inv["kind"] != "B2CS":
                continue
            for r in inv["rates"]:
                share = r["taxable"] / inv["taxable"] if inv["taxable"] else 0
                row = b2cs[(r["rate"], "Inter-state" if inv["inter"] else "Within the state")]
                row["taxable"] += r["taxable"]
                for k in ("IGST", "CGST", "SGST", "Cess"):
                    row[k] += inv[k] * share
                row["count"] += 1
        nil = round(sum(r["taxable"] for inv in invoices for r in inv["rates"] if r["rate"] == 0), 2)
        sections = {}
        for k in ("B2B", "B2CL", "CDNR", "CDNUR"):
            rows = [i for i in invoices if i["kind"] == k]
            sections[k] = {"count": len(rows), **tot(rows), "invoices": rows}
        sections["B2CS"] = {"count": sum(1 for i in invoices if i["kind"] == "B2CS"),
                            **tot([i for i in invoices if i["kind"] == "B2CS"]),
                            "rows": [{"rate": r, "supply": s, **{k: round(v, 2) for k, v in d.items()}} for (r, s), d in sorted(b2cs.items(), key=lambda x: (x[0][0] or 0, x[0][1]))]}
        return {"month": month, "from": f, "to": t, "company": co["name"] if co else "", "sections": sections,
                "total": {"count": len(invoices), **tot(invoices)}, "nil": nil,
                "hsn": [{"hsn": k[0], "rate": k[1], "unit": k[2], **{x: round(y, 2) for x, y in v.items()}}
                        for k, v in sorted(hsn.items(), key=lambda x: (x[0][0], x[0][1] or 0))],
                "no_tax_ledgers": not tax}


HEADS = ("IGST", "CGST", "SGST", "Cess")
CASHBANK = ("|Bank Accounts|", "|Cash-in-Hand|", "|Bank OD A/c|")
RCM_NAME = re.compile(r"\bRCM\b|reverse\s*charge", re.I)


def _z():
    return {h: 0.0 for h in HEADS}


def _r(d):
    return {h: round(d[h], 2) for h in HEADS}


def _tax_3b(c, cid, f, t, led, tax):
    """Every tax line of the month, sorted by what the voucher is, not by the ledger's name, so one GST ledger used
    for both sales and purchases works too. Amounts are Tally's own (debit +, credit -)."""
    out, out_rcm, itc, itc_rcm = _z(), _z(), _z(), _z()
    rcm_untaxed = {"count": 0, "value": 0.0}
    vs = store._rows(c, """SELECT id, base, party, extra, amount FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
        AND posting=1 AND status=''""", (cid, f, t))
    is_cb = lambda n: any(g in ((led.get(n) or {"chain": ""})["chain"] or "") for g in CASHBANK)
    # the ledgers your reverse-charge journals post against ("Tax paid on RCM", "RCM Payable" ...): a journal that
    # uses one of them with GST ledgers is reverse charge too (the Increase of Input Tax Credit journal often
    # carries no reverse-charge mark of its own)
    rcm_led = set()
    for r in c.execute("""SELECT vl.ledger FROM vline vl JOIN voucher v ON v.id=vl.voucher_id WHERE v.company_id=?
            AND v.extra LIKE '%"rcm": true%' AND v.base NOT IN ('Sales','Purchase','Credit Note','Debit Note')""", (cid,)):
        if r["ledger"] not in tax and not is_cb(r["ledger"]):
            rcm_led.add(r["ledger"])
    for n in led:
        if n not in tax and RCM_NAME.search(n):
            rcm_led.add(n)
    for v in vs:
        lines = [dict(x) for x in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],))]
        try:
            vx = json.loads(v["extra"] or "{}")
        except ValueError:
            vx = {}
        rcm = bool(vx.get("rcm"))
        if vx.get("gross"):          # a ledger both debited and credited: its separate lines, not the net
            g = {ln for ln, _ in vx["gross"]}
            lines = [x for x in lines if x["ledger"] not in g] + [{"ledger": ln, "amount": a} for ln, a in vx["gross"]]
        tl = [(tax[x["ledger"]][0], x["amount"]) for x in lines if x["ledger"] in tax]
        base = v["base"]
        if tl and not rcm and base not in ("Sales", "Purchase", "Credit Note", "Debit Note") and \
                any(x["ledger"] in rcm_led for x in lines):
            rcm = True
        if not tl:
            if rcm and base == "Purchase":       # Tally adds this tax with its reverse-charge journal
                rcm_untaxed["count"] += 1
                rcm_untaxed["value"] += abs(v["amount"] or 0)
            continue
        pchain = (led.get(v["party"]) or {"chain": ""})["chain"] or ""
        if base in ("Credit Note", "Debit Note"):
            outward = "|Sundry Debtors|" in pchain or ("|Sundry Creditors|" not in pchain and base == "Credit Note")
        else:
            outward = base == "Sales"
        others = [x["ledger"] for x in lines if x["ledger"] not in tax]
        only_tax = all(any(g in ((led.get(o) or {"chain": ""})["chain"] or "") for g in CASHBANK) for o in others)
        for h, a in tl:
            if outward:                                   # sales (and notes to customers): tax on what you sold
                out[h] += -a
            elif base in ("Purchase", "Credit Note", "Debit Note"):
                if a > 0 or base != "Purchase":           # tax paid on purchases (a purchase return takes it back)
                    (itc_rcm if rcm else itc)[h] += a
                else:                                     # tax credited on a purchase: payable under reverse charge
                    out_rcm[h] += -a
            elif only_tax and not rcm:
                continue                                  # set-off or tax paid to the government: not a supply
            elif a > 0:                                   # journals, payments: tax debited is credit taken
                (itc_rcm if rcm else itc)[h] += a
            else:                                         # tax credited is tax payable
                (out_rcm if rcm else out)[h] += -a
    rcm_untaxed["value"] = round(rcm_untaxed["value"], 2)
    return _r(out), _r(out_rcm), _r(itc), _r(itc_rcm), rcm_untaxed


def _setoff(liab, credit):
    """Use the input credit the way the GST portal does (rule 88A): IGST credit first, on IGST, then on CGST and
    SGST; then CGST credit on CGST, then IGST; SGST credit on SGST, then IGST. CGST and SGST never cross.
    Returns what each credit paid and what's left: cash to pay and credit carried forward."""
    L = {h: max(0.0, liab[h]) for h in HEADS}
    A = {h: max(0.0, credit[h]) for h in HEADS}
    used = {k: _z() for k in ("IGST", "CGST", "SGST", "Cess")}       # used[credit head][liability head]

    def take(ch, lh, amt):
        amt = max(0.0, min(amt, A[ch], L[lh]))
        A[ch] -= amt
        L[lh] -= amt
        used[ch][lh] += amt
    take("IGST", "IGST", L["IGST"])
    # what's left of IGST credit goes to CGST and SGST: first where their own credit falls short, then the rest
    need = {h: max(0.0, L[h] - A[h]) for h in ("CGST", "SGST")}
    tot = need["CGST"] + need["SGST"]
    if tot > 0 and A["IGST"] > 0:
        part = min(A["IGST"], tot)
        for h in ("CGST", "SGST"):
            take("IGST", h, part * need[h] / tot)
    for h in ("CGST", "SGST"):
        take("IGST", h, A["IGST"] / 2 if h == "CGST" else A["IGST"])
    take("IGST", "CGST", A["IGST"])
    take("CGST", "CGST", L["CGST"])
    take("SGST", "SGST", L["SGST"])
    take("CGST", "IGST", L["IGST"])
    take("SGST", "IGST", L["IGST"])
    take("Cess", "Cess", L["Cess"])
    return {"used": {k: _r(v) for k, v in used.items()}, "cash": _r(L), "left": _r(A)}


def gstr3b(cid, month):
    f, t = _month_range(month)
    g1 = gstr1(cid, month)
    with store.conn() as c:
        tax, led = _tax_side(c, cid)
        out, out_rcm, itc, itc_rcm, rcm_untaxed = _tax_3b(c, cid, f, t, led, tax)
        pur = c.execute("""SELECT COALESCE(SUM(amount),0) FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
            AND posting=1 AND status='' AND base='Purchase'""", (cid, f, t)).fetchone()[0]
        comp = c.execute("SELECT from_date FROM company WHERE id=?", (cid,)).fetchone()
        sync_from = (comp and comp["from_date"]) or "2000-01-01"
        # your GST ledgers in Tally, as they are: net per head at the start and end of the month (debit +)
        start, end = _z(), _z()
        nxt = date.fromordinal(date.fromisoformat(t).toordinal() + 1).isoformat()
        known = f >= sync_from
        for n, l in ((n, led[n]) for n in tax):
            h = tax[n][0]
            if known:
                start[h] += store._opening_at(c, cid, n, l["closing"], sync_from, f)
            end[h] += store._opening_at(c, cid, n, l["closing"], sync_from, nxt)
    start, end = _r(start), _r(end)
    bf = {h: max(0.0, start[h]) for h in HEADS}          # a debit balance at the start is credit not used yet
    credit = {h: itc[h] + itc_rcm[h] + bf[h] for h in HEADS}
    so = _setoff(out, credit)
    cash = {h: round(so["cash"][h] + max(0.0, out_rcm[h]), 2) for h in HEADS}   # reverse charge is paid in cash only
    return {"month": month, "from": f, "to": t, "company": g1["company"],
            "out": {"taxable": round(g1["total"]["taxable"] - g1["nil"], 2), **out}, "out_total": round(sum(out.values()), 2),
            "rcm": out_rcm, "rcm_total": round(sum(out_rcm.values()), 2), "rcm_untaxed": rcm_untaxed,
            "nil": g1["nil"],
            "itc": itc, "itc_rcm": itc_rcm, "itc_total": round(sum(itc.values()) + sum(itc_rcm.values()), 2),
            "bf": _r(bf), "bf_total": round(sum(bf.values()), 2), "start": start if known else None, "end": end,
            "used": so["used"], "cash": cash, "cash_total": round(sum(cash.values()), 2),
            "left": so["left"], "left_total": round(sum(so["left"].values()), 2),
            "purchases": round(abs(pur), 2), "no_tax_ledgers": g1["no_tax_ledgers"]}


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
