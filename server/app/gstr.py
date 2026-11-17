"""GSTR-1 and GSTR-3B summaries for a month, put together from the vouchers synced from Tally, to check before
filing. Tax amounts are the ones on Tally's tax ledgers in each voucher; the rate of each line is the one Tally
gave it. Nothing is worked out afresh except splitting a voucher's tax across its lines by value, for the HSN table.
Bahi doesn't file anything."""
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


def gstr3b(cid, month):
    f, t = _month_range(month)
    g1 = gstr1(cid, month)
    s = store.gst(cid, f, t)        # tax on the tax ledgers, output and input, for the month (as the GST summary)
    m = s["months"][0] if s["months"] else {"output": {h: 0 for h in store.GST_HEADS}, "input": {h: 0 for h in store.GST_HEADS}}
    out_tax = {h: round(m["output"][h], 2) for h in store.GST_HEADS}
    itc = {h: round(m["input"][h], 2) for h in store.GST_HEADS}
    taxable_out = round(g1["total"]["taxable"] - g1["nil"], 2)
    with store.conn() as c:
        pur = c.execute("""SELECT COALESCE(SUM(amount),0) FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
            AND posting=1 AND status='' AND base='Purchase'""", (cid, f, t)).fetchone()[0]
    # what's left to pay after using the input credit (simply head by head; the portal's set-off order can move
    # IGST credit across heads, so the final figures there may differ)
    net = {h: round(out_tax[h] - itc[h], 2) for h in store.GST_HEADS}
    return {"month": month, "from": f, "to": t, "company": g1["company"],
            "out": {"taxable": taxable_out, **out_tax}, "nil": g1["nil"],
            "itc": itc, "itc_total": round(sum(itc.values()), 2), "out_total": round(sum(out_tax.values()), 2),
            "net": net, "net_total": round(sum(net.values()), 2), "purchases": round(abs(pur), 2),
            "no_tax_ledgers": g1["no_tax_ledgers"]}
