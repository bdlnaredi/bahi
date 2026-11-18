"""GSTR-3B, built from scratch, table by table (3.1 first; the ITC tables come next).

3.1 Tax on outward and reverse charge inward supplies:
  (a) outward taxable supplies (other than zero rated, nil rated and exempted): GSTR-1's B2B (taxable sales, not
      SEZ), B2C (Large), B2C (Small), credit and debit notes, and advances (11A less 11B)
  (b) outward taxable supplies (zero rated): exports and supplies to SEZ
  (c) other outward supplies (nil rated, exempted): GSTR-1's 8A-8D nil rated and exempted
  (d) inward supplies liable to reverse charge: the liability side of the Stat Adjustment journals in Tally
      ("Increase of Tax Liability", "Increase in Tax Liability & Input Tax Credit"; not the ones for advances)
  (e) non-GST outward supplies: GSTR-1's 8A-8D non-GST
3.2 Of the supplies in 3.1(a), the inter-state ones to unregistered persons (B2C Large, B2C Small to another
    state, notes to them), to composition dealers and to UIN holders (from the buyer's registration type in Tally),
    by place of supply: taxable value and IGST.
4(A) ITC available (in part or in full), from the debits to the GST ledgers in the month:
  (1) import of goods, (2) import of services, (3) inward supplies liable to reverse charge (the input side of the
  Stat Adjustment journals: Increase in Tax Liability & Input Tax Credit, Increase of Input Tax Credit), (4) inward
  supplies from ISD, (5) all other ITC (purchases, expenses with GST, less purchase returns).
4(B) ITC reversed: the Stat Adjustment journals that reverse credit (Decrease / Reversal of Input Tax Credit),
  (1) as per rules 38, 42 and 43 of the CGST Rules and section 17(5), (2) others. 4(C) net ITC = (A) - (B).
4(D) for information: (1) ITC reclaimed that was reversed under 4(B)(2) earlier (its journal, Increase of Input
  Tax Credit marked as a reclaim, is in 4(A)(5) too), (2) ineligible ITC under section 16(4) and ITC restricted due
  to place of supply rules.
5 Exempt, nil rated and non-GST inward supplies, from the purchase bills: (1) from composition dealers, and
  exempt and nil rated items (or ledgers named exempt / nil rated), (2) non-GST; each inter-state and intra-state
  (the supplier's state against the company's).
6.1 Interest, late fee, penalty and others: the amounts paid to (debited on) the GST ledgers for interest, late
  fee, penalty and other charges, by tax head.
Read-only: nothing here touches Tally."""
import json
import os
import re
import threading
import time

import gstr
import gstr1
import store

HEADS = ("IGST", "CGST", "SGST", "Cess")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
_DIR = os.path.join(DATA_DIR, "gstr3btally")
_lock = threading.Lock()

LABELS = {
    "a": "Outward taxable supplies (other than zero rated, nil rated and exempted)",
    "b": "Outward taxable supplies (zero rated)",
    "c": "Other outward supplies (nil rated, exempted)",
    "d": "Inward supplies (liable to reverse charge)",
    "e": "Non-GST outward supplies",
}


def _z():
    return {"taxable": 0.0, **{h: 0.0 for h in HEADS}}


def _add(t, x, sign=1):
    t["taxable"] += sign * (x.get("taxable") or 0)
    for h in HEADS:
        t[h] += sign * (x.get(h) or 0)


def _fin(t):
    out = {k: round(v, 2) for k, v in t.items()}
    out["tax"] = round(sum(out[h] for h in HEADS), 2)
    return out


def _is_sez(r):
    return "sez" in (r.get("reg_type") or "").lower()


def _rcm(cid, month):
    """3.1(d): the month's journals that raise the tax liability on reverse charge purchases (from a registered
    supplier under reverse charge, or from an unregistered one, or import of services): the tax on their
    liability side (the credit lines on GST ledgers) and the assessable value Tally put on those lines."""
    f, t = gstr._month_range(month)
    rows = []
    with store.conn() as c:
        tax, _ = gstr._tax_side(c, cid)
        vs = store._rows(c, """SELECT id, date, vtype, number, party, extra FROM voucher WHERE company_id=? AND """ + gstr.RET_SQL + """
            AND posting=1 AND status='' AND base='Journal' AND extra LIKE '%tax_adj%' ORDER BY date, id""", (cid, f, t))
        for v in vs:
            x = json.loads(v["extra"] or "{}")
            if not gstr.in_return(x, v["date"], f, t):
                continue
            adj, addl = (x.get("tax_adj") or "").lower(), (x.get("gst_addl") or "").lower()
            if not ("increase" in adj and "liability" in adj) or "advance" in addl or "advance" in adj:
                continue
            lines = [(r["ledger"], r["amount"]) for r in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],))]
            if x.get("gross"):                  # the same ledger debited and credited: its separate lines
                g = {ln for ln, _ in x["gross"]}
                lines = [l for l in lines if l[0] not in g] + [(ln, a) for ln, a in x["gross"]]
            r = {"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"], "party": v["party"] or "",
                 "nature": x.get("gst_addl") or x.get("tax_adj") or "", **_z()}
            for ln, a in lines:
                if ln in tax and a < 0:          # credited: the tax payable
                    r[tax[ln][0]] += -a
            for ln, base, rate in x.get("gst_lines") or []:
                if ln in tax and base < 0 and tax[ln][0] in ("IGST", "CGST"):
                    r["taxable"] += -base       # once per supply: on the IGST line, or on the CGST line
            if r["taxable"] < 0.005:            # no assessable value in Tally: from the rate in the ledger's name
                for ln, a in lines:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*%", ln)
                    if ln in tax and a < 0 and tax[ln][0] in ("IGST", "CGST") and m and float(m.group(1)) > 0:
                        r["taxable"] += -a * 100 / float(m.group(1))
            if r["taxable"] < 0.005 and not any(r[h] for h in HEADS):
                continue
            r["tax"] = sum(r[h] for h in HEADS)
            rows.append({k: (round(v_, 2) if isinstance(v_, float) else v_) for k, v_ in r.items()})
    return rows


def build(cid, month):
    g = gstr1.build(cid, month)
    S = g["sections"]
    rows = {k: _z() for k in LABELS}
    parts = {k: [] for k in LABELS}

    def part(k, label, x, sign=1):
        _add(rows[k], x, sign)
        if abs(x.get("taxable") or 0) > 0.004 or any(abs(x.get(h) or 0) > 0.004 for h in HEADS):
            parts[k].append({"label": label, **_fin({f: sign * (x.get(f) or 0) for f in ("taxable",) + HEADS})})

    # (a) and (b)
    sez = _z()
    for r in S["b2b"].get("list") or []:
        if _is_sez(r) and not r.get("rcm"):
            _add(sez, r)
    a_b2b = _z()
    _add(a_b2b, S["b2b_taxable"])
    _add(a_b2b, sez, -1)
    part("a", "B2B invoices: 4A, 4B, 4C, 6B, 6C (taxable sales)", a_b2b)
    part("a", "B2C (Large) invoices: 5A, 5B", S["b2cl"])
    part("a", "B2C (Small) invoices: 7", S["b2cs"])
    part("a", "Credit / debit notes (registered): 9B", S["cdnr"])
    part("a", "Credit / debit notes (unregistered): 9B", S["cdnur"])
    part("a", "Tax on advances received: 11A", S["at"])
    part("a", "Advances adjusted: 11B", S["atadj"], -1)
    part("b", "Exports: 6A", S["exp"])
    part("b", "Supplies to SEZ: 6B", sez)
    # (c) and (e): GSTR-1 table 8
    nil = {"nil": 0.0, "exempt": 0.0, "nongst": 0.0}
    for r in S["nil"].get("rows") or []:
        for k in nil:
            nil[k] += r.get(k) or 0
    part("c", "Nil rated: 8A-8D", {"taxable": nil["nil"]})
    part("c", "Exempted: 8A-8D", {"taxable": nil["exempt"]})
    part("e", "Non-GST: 8A-8D", {"taxable": nil["nongst"]})
    # (d)
    rcm = _rcm(cid, month)
    for r in rcm:
        _add(rows["d"], r)
    out = {k: {"label": LABELS[k], **_fin(rows[k]), "parts": parts[k]} for k in LABELS}
    out["d"]["list"] = rcm
    out["d"]["count"] = len(rcm)
    # the check: 3.1(a) + (b), less the advances, is the tax of GSTR-1's sales tables
    mine = {h: rows["a"][h] + rows["b"][h] - (S["at"].get(h) or 0) + (S["atadj"].get(h) or 0) + (S["b2b_rcm"].get(h) or 0) for h in HEADS}
    g1 = {h: g["tax_total"].get(h) or 0 for h in HEADS}
    vs_g1 = {"ok": all(abs(mine[h] - g1[h]) <= 1 for h in HEADS), **{h: round(g1[h], 2) for h in HEADS}}
    t32 = _t32(S, g.get("state") or "")
    total = _z()
    for k in LABELS:
        _add(total, rows[k])
    t4a, total4a = _itc(cid, month)
    more = _itc_more(cid, month)
    tb = {h: round(more["b1"][h] + more["b2"][h], 2) for h in HEADS}
    tc = {h: round(total4a[h] - tb[h], 2) for h in HEADS}
    t4 = {"b1": more["b1"], "b2": more["b2"], "b": {**tb, "tax": round(sum(tb.values()), 2)},
          "c": {**tc, "tax": round(sum(tc.values()), 2)}, "d1": more["d1"], "d2": more["d2"]}
    # the check: the credit taken on reverse charge is the tax paid on it in 3.1(d)
    vs_rcm = {"ok": all(abs(t4a["3"][h] - out["d"][h]) <= 1 for h in HEADS)}
    t5 = _inward_exempt(cid, month, g.get("state") or "")
    t61 = _other_dues(cid, month)
    return {"month": month, "from": g["from"], "to": g["to"], "company": g["company"], "moved": gstr.moved(cid, g["from"], g["to"]), "t5": t5, "t61": t61, "t31": out, "total31": _fin(total), "t32": t32, "vs_gstr1": vs_g1,
            "t4a": t4a, "total4a": total4a, "vs_rcm": vs_rcm, "t4": t4,
            "no_tax_ledgers": g.get("no_tax_ledgers")}


ITC_LABELS = {"1": "Import of goods", "2": "Import of services", "3": "Inward supplies liable to reverse charge (other than 1 and 2)",
              "4": "Inward supplies from ISD", "5": "All other ITC"}


def _itc_kind(text, default):
    t = (text or "").lower()
    if "import" in t and "service" in t:
        return "2"
    if "import" in t or "overseas" in t or "sez" in t and "import" in t:
        return "1"
    if "isd" in t or "input service distributor" in t:
        return "4"
    if "reclaim" in t:
        return default
    if "reverse charge" in t or "unregistered" in t or "rcm" in t:
        return "3"
    return default


def _ineligible(t):
    t = (t or "").lower()
    return "16(4)" in t or "16 (4)" in t or "place of supply" in t or re.search(r"\bpos\b", t) is not None or "ineligible" in t


def _itc_more(cid, month):
    """4(B) reversed and 4(D) for information, from the Stat Adjustment journals of the month."""
    f, t = gstr._month_range(month)
    rows = {"b1": [], "b2": [], "d1": [], "d2": []}
    with store.conn() as c:
        tax, _ = gstr._tax_side(c, cid)
        vs = store._rows(c, """SELECT id, date, vtype, number, party, extra FROM voucher WHERE company_id=? AND """ + gstr.RET_SQL + """
            AND posting=1 AND status='' AND extra LIKE '%tax_adj%' ORDER BY date, id""", (cid, f, t))
        for v in vs:
            x = json.loads(v["extra"] or "{}")
            if not gstr.in_return(x, v["date"], f, t):
                continue
            adj, addl = (x.get("tax_adj") or "").lower(), (x.get("gst_addl") or "").lower()
            text = adj + " " + addl
            lines = [(r["ledger"], r["amount"]) for r in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],))]
            if x.get("gross"):
                g = {ln for ln, _ in x["gross"]}
                lines = [l for l in lines if l[0] not in g] + [(ln, a) for ln, a in x["gross"]]
            tl = [(ln, a) for ln, a in lines if ln in tax]
            if not tl:
                continue
            if "input tax credit" not in adj and not _ineligible(text) and "reclaim" not in text:
                continue
            reverse = any(w in adj for w in ("decrease", "reversal", "reverse"))
            if _ineligible(text):
                key = "d2"
            elif "reclaim" in text and not reverse:
                key = "d1"
            elif reverse:
                key = "b1" if re.search(r"\b(38|42|43)\b|17\s*\(5\)", text) else "b2"
            else:
                continue
            heads = {h: 0.0 for h in HEADS}
            side = [a for _, a in tl if (a < 0 if key in ("b1", "b2") else a > 0)]
            for ln, a in tl:
                if key in ("b1", "b2") and a < 0:
                    heads[tax[ln][0]] += -a       # the input GST ledgers credited: credit reversed
                elif key == "d1" and a > 0:
                    heads[tax[ln][0]] += a        # credit taken back
                elif key == "d2":
                    if (a < 0) == any(b < 0 for _, b in tl):
                        heads[tax[ln][0]] += abs(a)
            if not side and key != "d2" or not any(abs(a) > 0.004 for a in heads.values()):
                continue
            r = {"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"], "party": v["party"] or "",
                 "nature": x.get("gst_addl") or x.get("tax_adj") or "", **{h: round(a, 2) for h, a in heads.items()}}
            r["tax"] = round(sum(heads.values()), 2)
            rows[key].append(r)
    labels = {"b1": "As per rules 38, 42 and 43 of CGST Rules and section 17(5)", "b2": "Others",
              "d1": "ITC reclaimed which was reversed under table 4(B)(2) in an earlier tax period",
              "d2": "Ineligible ITC under section 16(4) and ITC restricted due to PoS rules"}
    out = {}
    for k, lab in labels.items():
        tot = {h: round(sum(r[h] for r in rows[k]), 2) for h in HEADS}
        out[k] = {"label": lab, **tot, "tax": round(sum(tot.values()), 2), "count": len(rows[k]), "list": rows[k]}
    return out


def _itc(cid, month):
    """4(A): the input tax credit taken in the month, row by row, with the vouchers behind it.
    - Purchase vouchers: the GST on them (import of goods / services and ISD by the supplier's registration type
      or the nature of the purchase; everything else is 'all other ITC'). A purchase under reverse charge carries
      no GST: its credit comes from the journal below.
    - Debit notes to suppliers (purchase returns): their GST, less.
    - Stat Adjustment journals that raise the input credit (Increase in Tax Liability & Input Tax Credit, Increase
      of Input Tax Credit): the GST ledgers debited, under the row their 'additional details' name.
    - Other journals and payments with GST on an input GST ledger (expenses with GST): all other ITC.
    Journals that reverse credit, set it off or pay tax are not credit taken, and are left out."""
    f, t = gstr._month_range(month)
    rows = {k: [] for k in ITC_LABELS}
    with store.conn() as c:
        tax, led = gstr._tax_side(c, cid)
        vs = store._rows(c, """SELECT id, date, vtype, base, number, party, party_gstin, amount, extra FROM voucher
            WHERE company_id=? AND """ + gstr.RET_SQL + """ AND posting=1 AND status=''
            AND base IN ('Purchase','Debit Note','Credit Note','Journal','Payment') ORDER BY date, id""", (cid, f, t))
        for v in vs:
            x = json.loads(v["extra"] or "{}")
            if not gstr.in_return(x, v["date"], f, t):
                continue
            lines = [(r["ledger"], r["amount"]) for r in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],))]
            if x.get("gross"):
                g = {ln for ln, _ in x["gross"]}
                lines = [l for l in lines if l[0] not in g] + [(ln, a) for ln, a in x["gross"]]
            tl = [(ln, a) for ln, a in lines if ln in tax]
            if not tl:
                continue
            adj, addl = (x.get("tax_adj") or "").lower(), (x.get("gst_addl") or "").lower()
            base = v["base"]
            pchain = ((led.get(v["party"]) or {})["chain"] if led.get(v["party"]) else "") or ""
            what = " ".join([x.get("gst_reg_type") or "", x.get("gst_nature") or "", addl])
            heads, kind = {h: 0.0 for h in HEADS}, None
            if base == "Purchase":
                kind = _itc_kind(what, "5")
                if kind == "3":                  # reverse charge: the credit is in the journal, not on the bill
                    continue
                for ln, a in tl:
                    heads[tax[ln][0]] += a
            elif base in ("Debit Note", "Credit Note"):
                if "|Sundry Creditors|" not in pchain:
                    continue                     # a note to a customer: sales
                kind = _itc_kind(what, "5")
                for ln, a in tl:
                    heads[tax[ln][0]] += a       # a return credits the GST ledgers: less credit
            elif adj:
                if "increase" not in adj or "input tax credit" not in adj or "advance" in addl:
                    continue                     # reversal, set-off, payment or liability only
                kind = _itc_kind(addl, "5")
                for ln, a in tl:
                    if a > 0:                    # the debit side is the credit taken
                        heads[tax[ln][0]] += a
            else:
                if any(a < 0 for _, a in tl):
                    continue                     # GST ledgers credited too: a transfer or set-off
                if not all(tax[ln][1] == "input" for ln, _ in tl):
                    continue                     # paying output tax
                kind = "5"
                for ln, a in tl:
                    heads[tax[ln][0]] += a
            if not any(abs(a) > 0.004 for a in heads.values()):
                continue
            r = {"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"],
                 "party": v["party"] or "", "gstin": v["party_gstin"] or "", "nature": x.get("gst_addl") or x.get("tax_adj") or "",
                 **{h: round(a, 2) for h, a in heads.items()}}
            r["tax"] = round(sum(heads.values()), 2)
            rows[kind].append(r)
    out = {}
    for k, label in ITC_LABELS.items():
        tot = {h: round(sum(r[h] for r in rows[k]), 2) for h in HEADS}
        out[k] = {"label": label, **tot, "tax": round(sum(tot.values()), 2), "count": len(rows[k]), "list": rows[k]}
    tot = {h: round(sum(out[k][h] for k in ITC_LABELS), 2) for h in HEADS}
    return out, {**tot, "tax": round(sum(tot.values()), 2)}


def _inward_exempt(cid, month, company_state):
    """Table 5: purchases with no GST on them, by kind and inter / intra state."""
    f, t = gstr._month_range(month)
    st = (company_state or "").strip().lower()
    out = {k: {"inter": 0.0, "intra": 0.0, "list": []} for k in ("1", "2")}
    with store.conn() as c:
        tax, led = gstr._tax_side(c, cid)
        vs = store._rows(c, """SELECT id, date, vtype, base, number, party, party_gstin, amount, extra FROM voucher
            WHERE company_id=? AND """ + gstr.RET_SQL + """ AND posting=1 AND status='' AND base IN ('Purchase','Debit Note')
            ORDER BY date, id""", (cid, f, t))
        for v in vs:
            if not gstr.in_return(json.loads(v["extra"] or "{}"), v["date"], f, t):
                continue
            pl = led.get(v["party"])
            if v["base"] == "Debit Note" and "|Sundry Creditors|" not in ((pl["chain"] if pl else "") or ""):
                continue
            x = json.loads(v["extra"] or "{}")
            sign = -1 if v["base"] == "Debit Note" else 1
            comp = "composition" in (x.get("gst_reg_type") or "").lower()
            taxab = x.get("taxability") or {}
            amt = {"1": 0.0, "2": 0.0}
            items = list(c.execute("SELECT item, amount, gst FROM vitem WHERE voucher_id=?", (v["id"],)))
            lines = list(c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],)))
            for it in items:
                kind = (taxab.get(it["item"]) or "").lower()
                a = abs(it["amount"] or 0)
                if "non" in kind and "gst" in kind:
                    amt["2"] += a
                elif comp or kind and "taxable" not in kind or not kind and it["gst"] is not None and it["gst"] == 0:
                    amt["1"] += a
            if not items:
                for r in lines:
                    l = led.get(r["ledger"])
                    if r["ledger"] in tax or r["ledger"] == v["party"] or not l or r["amount"] <= 0:
                        continue
                    if any(g in (l["chain"] or "") for g in ("|Bank Accounts|", "|Cash-in-Hand|", "|Sundry Creditors|", "|Duties & Taxes|")):
                        continue
                    n = r["ledger"].lower()
                    if re.search(r"non[\s-]*gst", n):
                        amt["2"] += r["amount"]
                    elif comp or re.search(r"exempt|nil", n):
                        amt["1"] += r["amount"]
            if amt["1"] < 0.005 and amt["2"] < 0.005:
                continue
            sup = (x.get("buyer_state") or x.get("place_of_supply") or "").strip().lower()
            side = "inter" if sup and st and sup != st else "intra"
            for k in ("1", "2"):
                if amt[k] > 0.004:
                    out[k][side] += sign * amt[k]
                    out[k]["list"].append({"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"],
                                           "party": v["party"] or "", "taxable": round(sign * amt[k], 2), "tax": 0.0,
                                           "nature": ("Composition dealer" if comp else "") + (" · inter-state" if side == "inter" else "")})
    labels = {"1": "From a supplier under composition scheme, exempt and nil rated supplies", "2": "Non-GST supply"}
    res = {}
    for k, lab in labels.items():
        o = out[k]
        res[k] = {"label": lab, "inter": round(o["inter"], 2), "intra": round(o["intra"], 2),
                  "taxable": round(o["inter"] + o["intra"], 2), "count": len(o["list"]), "list": o["list"]}
    return res


def _other_dues(cid, month):
    """Table 6.1: interest, late fee, penalty and other charges paid on GST in the month (debits to those GST
    ledgers), by tax head (from the ledger's GST head or its name)."""
    f, t = gstr._month_range(month)
    kinds = {"i": ("Interest", r"interest"), "l": ("Late fee", r"late\s*fee"), "p": ("Penalty", r"penalty"),
             "o": ("Other charges", r"other charges")}
    out = {k: {"label": lab, **{h: 0.0 for h in HEADS}, "other": 0.0, "list": []} for k, (lab, _) in kinds.items()}
    with store.conn() as c:
        led = {r["name"]: r for r in c.execute("SELECT name, chain, taxtype, gst_head FROM ledger WHERE company_id=?", (cid,))}
        dues = {}
        for n, l in led.items():
            txt_ = n + " " + (l["gst_head"] or "")
            if not ("|Duties & Taxes|" in (l["chain"] or "") or re.search(r"GST|CESS", n, re.I)):
                continue
            k = next((k for k, (_, rx) in kinds.items() if re.search(rx, txt_, re.I)), None)
            if not k:
                continue
            hn = (l["gst_head"] or "").lower() + " " + n.upper()
            head = ("IGST" if "integrated" in hn or "IGST" in hn else "CGST" if "central" in hn or "CGST" in hn else
                    "SGST" if "state" in hn or "SGST" in hn or "UTGST" in hn else "Cess" if "CESS" in hn else None)
            dues[n] = (k, head)
        if not dues:
            res = {k: {**{x: round(y, 2) if isinstance(y, float) else y for x, y in o.items()}, "tax": 0.0, "count": 0} for k, o in out.items()}
            return res
        marks = ",".join("?" * len(dues))
        for r in c.execute(f"""SELECT v.id, v.date, v.vtype, v.number, v.party, vl.ledger, vl.amount FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
                WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND v.posting=1 AND v.status='' AND vl.ledger IN ({marks})
                AND vl.amount > 0 ORDER BY v.date, v.id""", (cid, f, t, *dues)):
            k, head = dues[r["ledger"]]
            o = out[k]
            o[head or "other"] += r["amount"]
            o["list"].append({"id": r["id"], "date": r["date"], "vtype": r["vtype"], "number": r["number"], "party": r["party"] or "",
                              "nature": r["ledger"], "tax": round(r["amount"], 2), **{h: round(r["amount"], 2) if h == head else 0.0 for h in HEADS}})
    res = {}
    for k, o in out.items():
        r_ = {x: round(y, 2) if isinstance(y, float) else y for x, y in o.items()}
        r_["tax"] = round(sum(o[h] for h in HEADS) + o["other"], 2)
        r_["count"] = len({x["id"] for x in o["list"]})
        res[k] = r_
    return res


KINDS32 = {"unreg": "Supplies made to unregistered persons", "comp": "Supplies made to composition taxable persons",
           "uin": "Supplies made to UIN holders"}


def _kind32(reg):
    reg = (reg or "").lower()
    if "composition" in reg:
        return "comp"
    if "uin" in reg or "un agency" in reg or "embassy" in reg or "consulate" in reg:
        return "uin"
    return None


def _t32(S, state):
    """3.2: inter-state supplies of 3.1(a) to unregistered persons, composition dealers and UIN holders, by place
    of supply."""
    st = (state or "").strip().lower()
    inter = lambda r: abs(r.get("IGST") or 0) > 0.004 or bool(r.get("pos") and st and r["pos"].strip().lower() != st)
    out = {k: {} for k in KINDS32}

    def put(k, r, sign=1):
        pos = r.get("pos") or "Unknown"
        t = out[k].setdefault(pos, {"taxable": 0.0, "IGST": 0.0, "count": 0})
        t["taxable"] += sign * (r.get("taxable") or 0)
        t["IGST"] += sign * (r.get("IGST") or 0)
        t["count"] += 1 if "id" in r else 0

    for r in S["b2cl"].get("list") or []:
        put("unreg", r)
    for r in S["cdnur"].get("list") or []:
        put("unreg", r, -1 if r.get("type") == "C" else 1)
    for r in S["b2cs"].get("rows") or []:
        if inter(r):
            put("unreg", r)
    for r in S["b2b"].get("list") or []:
        k = _kind32(r.get("reg_type"))
        if k and not r.get("rcm") and inter(r):
            put(k, r)
    for r in S["cdnr"].get("list") or []:
        k = _kind32(r.get("reg_type"))
        if k and inter(r):
            put(k, r, -1 if r.get("type") == "C" else 1)
    res = {}
    for k, label in KINDS32.items():
        rows = [{"pos": p, "taxable": round(t["taxable"], 2), "IGST": round(t["IGST"], 2), "count": t["count"]}
                for p, t in sorted(out[k].items()) if abs(t["taxable"]) > 0.004 or abs(t["IGST"]) > 0.004]
        res[k] = {"label": label, "rows": rows, "taxable": round(sum(r["taxable"] for r in rows), 2),
                  "IGST": round(sum(r["IGST"] for r in rows), 2)}
    return res


# ------------------------------------------------------------------ comparing with Tally's own GSTR-3B
def parse_tally(raw):
    """Tally's GSTR-3B export for the month (Alt+E, XML): the 3.1 heading and its rows (a) to (e)."""
    if not raw:
        raise ValueError("The file is empty.")
    if isinstance(raw, bytes) and raw[:2] == b"PK":
        raise ValueError("This is an Excel file. In Tally open GSTR-3B for the month, press Alt+E and choose XML (Data Interchange).")
    text = gstr1._text(raw)
    if "GSTRRETVIEWPARTICULARS" not in text.upper():
        raise ValueError("This isn't Tally's GSTR-3B export. In Tally open GSTR-3B for the month, press Alt+E and choose XML (Data Interchange).")
    if not re.search(r"3\.1\s*Tax on Outward", text, re.I):
        raise ValueError("This looks like another report (no table 3.1 in it). Export GSTR-3B from Tally.")
    tags = {"GSTRTAXABLEAMOUNT": "taxable", "GSTRIGSTAMOUNT": "IGST", "GSTRCGSTAMOUNT": "CGST", "GSTRSGSTAMOUNT": "SGST",
            "GSTRCESSAMOUNT": "Cess", "GSTRTAXAMOUNT": "tax"}
    ent = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}
    rows, cur, part = {}, None, ""
    for m in re.finditer(r"<(GSTR[A-Z]*)(?:\s[^>]*)?>([^<]*)</\1\s*>", text, re.I):
        tag, val = m.group(1).upper(), re.sub(r"&\w+;", lambda e: ent.get(e.group(0), " "), m.group(2)).strip()
        if tag == "GSTRRETVIEWPARTICULARS":
            lab = re.sub(r"\s+", " ", val)
            mm = re.match(r"^3\.1\s*\(?([a-e])\b", lab, re.I)
            key = mm.group(1).lower() if mm else ("total" if re.match(r"^3\.1\s+Tax on", lab, re.I) else None)
            m32 = re.match(r"^Supplies (?:made )?to (Unregistered|Composition|UIN)", lab, re.I)
            if m32:
                key = {"unregistered": "unreg", "composition": "comp", "uin": "uin"}[m32.group(1).lower()]
            mp = re.match(r"^([A-E])\.\s", lab)
            if re.match(r"^\d+(\.\d+)?\s+[A-Z]", lab):
                part = ""                       # a new table (4, 5, 6.1 ...)
            if re.match(r"^4\s", lab):
                part = "4"
            elif re.match(r"^5\s", lab):
                part, key = "5", "5"
            elif re.match(r"^6\.1\s", lab):
                part, key = "61", "61"
            elif part == "5" and re.match(r"^From a Supplier", lab, re.I):
                key = "51"
            elif part == "5" and re.match(r"^Non-?GST", lab, re.I):
                key = "52"
            elif part == "61":
                k6 = next((k for k, rx in (("61i", r"^Interest"), ("61l", r"^Late"), ("61p", r"^Penalty"), ("61o", r"^Other")) if re.match(rx, lab, re.I)), None)
                key = k6 or key
            elif mp and part[:1] == "4":
                part = "4" + mp.group(1).lower()
                if part == "4a":
                    key = "4a"
                elif part in ("4b", "4c"):
                    key = part
            mn = re.match(r"^(\d)\.\s", lab)
            if mn and part in ("4a", "4b"):
                key = part + mn.group(1)
            if mn and re.search(r"reclaimed", lab, re.I):
                key = "4d1"
            elif mn and re.search(r"ineligible", lab, re.I):
                key = "4d2"
            cur = None
            if key and key not in rows:
                cur = rows[key] = {"label": lab}
        elif cur is not None and tag in tags:
            cur[tags[tag]] = gstr1._num(val) if val else 0.0
    if not rows:
        raise ValueError("No table 3.1 found in the file.")
    return rows


def _tpath(cid):
    return os.path.join(_DIR, f"{int(cid)}.json")


def tally_load(cid):
    try:
        with open(_tpath(cid)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _tsave(cid, d):
    os.makedirs(_DIR, exist_ok=True)
    with open(_tpath(cid) + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(_tpath(cid) + ".tmp", _tpath(cid))


def tally_save(cid, month, raw):
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        raise ValueError("Which month?")
    rows = parse_tally(raw)
    with _lock:
        d = tally_load(cid)
        d[month] = {"rows": rows, "at": time.time()}
        _tsave(cid, d)
    return {"ok": True, "rows": len(rows)}


def tally_remove(cid, month):
    with _lock:
        d = tally_load(cid)
        d.pop(month, None)
        _tsave(cid, d)
    return {"ok": True}


def with_tally(cid, month):
    """GSTR-3B here, and beside each row of 3.1 Tally's figures (when its export for the month was uploaded) and
    whether they agree: taxable value and each tax within a rupee."""
    r = build(cid, month)
    t = tally_load(cid).get(month)
    if not t:
        return r
    r["tally"] = {"at": t["at"], "detailed": any(k in t["rows"] for k in LABELS)}
    targets = [(k, r["t31"][k]) for k in LABELS] + [("total", r["total31"])]
    targets += [(k, r["t32"][k]) for k in KINDS32]
    targets += [("4a" + k, r["t4a"][k]) for k in ITC_LABELS] + [("4a", r["total4a"])]
    targets += [("51", r["t5"]["1"]), ("52", r["t5"]["2"])]
    targets += [("61" + k, r["t61"][k]) for k in ("i", "l", "p", "o")]
    targets += [("4b1", r["t4"]["b1"]), ("4b2", r["t4"]["b2"]), ("4b", r["t4"]["b"]), ("4c", r["t4"]["c"]),
                ("4d1", r["t4"]["d1"]), ("4d2", r["t4"]["d2"])]
    for k, mine in targets:
        tr = t["rows"].get(k)
        if not tr:
            continue
        diffs = [f for f in ("taxable",) + HEADS if (f in mine or tr.get(f)) and abs(abs(mine.get(f, 0)) - (tr.get(f) or 0)) > 1]
        mine["vs_tally"] = {"ok": not diffs, "diffs": diffs, **{f: tr.get(f, 0) for f in ("taxable",) + HEADS}}
    return r
