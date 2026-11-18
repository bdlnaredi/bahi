"""GSTR-1 for a month, built from the sales vouchers synced from Tally, table by table as the GST portal and Tally's
GSTR-1 have them. Tax is the amount on Tally's GST ledgers in each voucher; the taxable value of each rate is the
assessable value Tally put on the GST lines when it is there, otherwise the stock lines at their GST rate.
Amendments are not made here: they come from fresh vouchers and notes, as they are entered in Tally.
Nothing is filed or sent anywhere."""
import json
import re
from collections import defaultdict
from datetime import date

import gstr
import store

HEADS = ("IGST", "CGST", "SGST", "Cess")
SLABS = [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28, 40]
B2CL_LIMIT = 100000          # inter-state invoices to unregistered buyers above this are B2C (Large)
UNREG = ("unregistered", "consumer", "unknown")
CASHBANK = ("|Bank Accounts|", "|Cash-in-Hand|", "|Bank OD A/c|")
UQC = [(r"^(nos?|numbers?)\.?$", "NOS"), (r"^(pcs?|pieces?)\.?$", "PCS"), (r"^(kgs?|kilo(gram)?s?)\.?$", "KGS"),
       (r"^(gms?|grams?|gm)\.?$", "GMS"), (r"^(ltrs?|lit(re|er)s?|l)\.?$", "LTR"), (r"^(ml|millilit(re|er)s?)\.?$", "MLT"),
       (r"^(mtrs?|met(re|er)s?|m)\.?$", "MTR"), (r"^(bags?)\.?$", "BAG"), (r"^(box(es)?)\.?$", "BOX"),
       (r"^(btls?|bottles?)\.?$", "BTL"), (r"^(cans?)\.?$", "CAN"), (r"^(ctns?|cartons?)\.?$", "CTN"), (r"^(doz(en)?)\.?$", "DOZ"),
       (r"^(pkts?|packets?)\.?$", "PAC"), (r"^(prs?|pairs?)\.?$", "PRS"), (r"^(qtls?|quintals?)\.?$", "QTL"),
       (r"^(sets?)\.?$", "SET"), (r"^(tons?|tonnes?|mts?)\.?$", "TON"), (r"^(rolls?)\.?$", "ROL"), (r"^(sq\.?\s?ft|sqf)\.?$", "SQF"),
       (r"^(sq\.?\s?m(tr)?|sqm)\.?$", "SQM"), (r"^(units?|u)\.?$", "UNT")]


def uqc(unit):
    u = (unit or "").strip().lower()
    for pat, code in UQC:
        if re.match(pat, u):
            return code
    return "OTH" if u else ""


def _snap(r):
    return min(SLABS, key=lambda s: abs(s - r))


def _z():
    return {h: 0.0 for h in HEADS}


def _round(d):
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}


def _nil_kind(t):
    t = (t or "").lower()
    if "exempt" in t:
        return "exempt"
    if "non" in t:
        return "nongst"
    return "nil"


def _state_key(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _analyse(c, v, tax, led, company_state, stock):
    """One voucher: tax by head, taxable value by rate, nil/exempt/non-GST value, its stock lines, where it goes."""
    x = json.loads(v["extra"] or "{}")
    lines = [dict(r) for r in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],))]
    if x.get("gross"):
        g = {ln for ln, _ in x["gross"]}
        lines = [r for r in lines if r["ledger"] not in g] + [{"ledger": ln, "amount": a} for ln, a in x["gross"]]
    items = [dict(r) for r in c.execute("SELECT item, qty, unit, amount, hsn, gst FROM vitem WHERE voucher_id=?", (v["id"],))]
    note = v["base"] == "Credit Note"
    sign = 1 if note else -1          # sales credit their GST ledgers; a credit note debits them
    heads = _z()
    for r in lines:
        if r["ledger"] in tax:
            heads[tax[r["ledger"]][0]] += sign * r["amount"]
    tax_total = sum(heads.values())
    taxab = x.get("taxability") or {}
    by_rate, nil = defaultdict(float), {"nil": 0.0, "exempt": 0.0, "nongst": 0.0}
    rows = []
    for it in items:
        amt = abs(it["amount"] or 0)
        rate = it["gst"]
        kind = taxab.get(it["item"])
        if kind and "taxable" not in kind.lower():
            nil[_nil_kind(kind)] += amt
            rate = 0
        elif rate is not None and rate == 0:
            nil["nil"] += amt
        elif rate is not None:
            by_rate[rate] += amt
        else:
            by_rate[None] += amt
        s = stock.get(it["item"], {})
        rows.append({"item": it["item"], "qty": abs(it["qty"] or 0), "unit": it["unit"] or s.get("unit", ""),
                     "hsn": (it["hsn"] or s.get("hsn") or "").strip(), "rate": rate, "amount": amt})
    # Tally's own assessable value on the GST lines, when the voucher has it: exact taxable value per rate
    gl = [(ln, abs(base), rate) for ln, base, rate in (x.get("gst_lines") or []) if ln in tax]
    if gl and tax_total:
        exact = defaultdict(float)
        for ln, base, rate in gl:
            h = tax[ln][0]
            if h == "IGST":
                exact[rate] += base
            elif h == "CGST":
                exact[round(rate * 2, 2)] += base
        if exact:
            by_rate = exact
    if not items and not gl:
        # no stock lines: the income lines of the voucher are its value
        for r in lines:
            l = led.get(r["ledger"])
            if r["ledger"] in tax or r["ledger"] == v["party"] or not l or re.search(r"round", r["ledger"], re.I):
                continue
            if any(g in (l["chain"] or "") for g in CASHBANK + ("|Sundry Debtors|", "|Sundry Creditors|")):
                continue
            by_rate[None] += sign * r["amount"]
    if None in by_rate:
        known = sum(a * (r or 0) / 100 for r, a in by_rate.items() if r)
        rest = by_rate.pop(None)
        if rest > 0.5:
            guess = _snap((tax_total - known) / rest * 100) if tax_total - known > 0.5 else 0
            if guess:
                by_rate[guess] += rest
            else:
                nil["nil"] += rest
    # charges (freight, packing) with GST on them: the tax says so; put them with the main rate
    if items and not gl:
        expected = sum(a * r / 100 for r, a in by_rate.items())
        if tax_total - expected > 0.5 and by_rate:
            main = max(by_rate, key=lambda r: by_rate[r])
            by_rate[main] += (tax_total - expected) / main * 100 if main else 0
    by_rate = {r: a for r, a in by_rate.items() if abs(a) > 0.004}
    # where it goes
    pl = led.get(v["party"]) or {}
    gstin = (v["party_gstin"] or pl.get("gstin") or "").strip().upper()
    reg = (x.get("gst_reg_type") or "").lower()
    registered = bool(gstin) and not any(u in reg for u in UNREG)
    pos = x.get("place_of_supply") or x.get("buyer_state") or ""
    if heads["IGST"] > 0.005 and heads["CGST"] < 0.005:
        inter = True
    elif heads["CGST"] > 0.005:
        inter = False
    else:
        inter = bool(pos and company_state and _state_key(pos) != _state_key(company_state))
    export = "overseas" in reg or "export" in (x.get("gst_nature") or "").lower()
    return {"id": v["id"], "date": v["date"], "vtype": v["vtype"], "number": v["number"], "base": v["base"],
            "party": v["party"] or x.get("buyer_name") or "", "gstin": gstin, "registered": registered, "reg_type": x.get("gst_reg_type", ""),
            "pos": pos or company_state, "inter": inter, "export": export, "rcm": bool(x.get("rcm")),
            "value": round(abs(v["amount"] or 0), 2), "heads": heads, "tax": tax_total, "by_rate": by_rate, "nil": nil,
            "items": rows}


def _split(a, rate_amt, heads):
    """A voucher's tax shared over its rates (by taxable x rate)."""
    w = sum(t * r for r, t in rate_amt.items()) or 1
    return {r: {h: heads[h] * (t * r) / w for h in HEADS} for r, t in rate_amt.items()}


def build(cid, month):
    f, t = gstr._month_range(month)
    with store.conn() as c:
        tax, led_rows = gstr._tax_side(c, cid)
        led = {n: dict(l) for n, l in led_rows.items()}
        co = c.execute("SELECT name, info FROM company WHERE id=?", (cid,)).fetchone()
        info = json.loads((co["info"] if co else None) or "{}")
        company_state = info.get("state") or ""
        stock = {r["name"]: dict(r) for r in c.execute("SELECT name, unit, hsn FROM stock WHERE company_id=?", (cid,))}
        vs = store._rows(c, """SELECT id, date, vtype, base, number, party, party_gstin, amount, extra, status, posting FROM voucher
            WHERE company_id=? AND date BETWEEN ? AND ? AND base IN ('Sales','Credit Note','Debit Note','Receipt','Journal')
            AND status IN ('', 'cancelled') ORDER BY date, id""", (cid, f, t))
        docs = defaultdict(lambda: {"nums": [], "cancelled": 0})
        sec = {k: {"vouchers": set(), "taxable": 0.0, "value": 0.0, **_z(), "list": []} for k in
               ("b2b", "b2b_taxable", "b2b_rcm", "b2cl", "exp", "cdnr", "cdnur", "b2cs", "nil", "at", "atadj")}
        b2cs = defaultdict(lambda: {"taxable": 0.0, **_z()})
        nil8 = {k: {"nil": 0.0, "exempt": 0.0, "nongst": 0.0} for k in ("8A", "8B", "8C", "8D")}
        hsn = {"b2b": defaultdict(lambda: {"qty": 0.0, "taxable": 0.0, **_z()}), "b2c": defaultdict(lambda: {"qty": 0.0, "taxable": 0.0, **_z()})}
        at = defaultdict(lambda: {"taxable": 0.0, **_z()})
        atadj = defaultdict(lambda: {"taxable": 0.0, **_z()})
        notes = []

        def add(k, a, rate_amt, sign=1, row=None):
            s_ = sec[k]
            s_["vouchers"].add(a["id"])
            s_["taxable"] += sign * sum(rate_amt.values())
            s_["value"] += sign * a["value"]
            for h in HEADS:
                s_[h] += sign * a["heads"][h]
            if row is not None:
                s_["list"].append(row)

        for v in vs:
            base = v["base"]
            # 13 - documents issued: every sales invoice and note, cancelled ones too
            if base in ("Sales", "Credit Note", "Debit Note"):
                pchain = (led.get(v["party"]) or {}).get("chain") or ""
                if base == "Sales" or "|Sundry Creditors|" not in pchain:
                    kind = {"Sales": "Invoices for outward supply", "Credit Note": "Credit Note", "Debit Note": "Debit Note"}[base]
                    m = re.match(r"^(.*?)(\d+)(\D*)$", v["number"] or "")
                    key = (kind, v["vtype"], (m.group(1) + "#" + m.group(3)) if m else (v["number"] or ""))
                    docs[key]["nums"].append((int(m.group(2)) if m else 0, v["number"] or ""))
                    if v["status"] == "cancelled":
                        docs[key]["cancelled"] += 1
            if v["status"] == "cancelled" or not v["posting"]:
                continue
            if base in ("Receipt", "Journal"):
                x = json.loads(v["extra"] or "{}")
                adj, addl = (x.get("tax_adj") or "").lower(), (x.get("gst_addl") or "").lower()
                tl = [(r["ledger"], r["amount"]) for r in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],)) if r["ledger"] in tax]
                if not tl or "reverse charge" in addl or "unregistered" in addl or "input tax" in adj and "liability" not in adj:
                    continue
                advance = "advance" in addl or "advance" in adj
                if not advance and not (base == "Receipt" and any(a < 0 for _, a in tl)):
                    continue
                increase = ("increase" in adj or base == "Receipt") and "decrease" not in adj
                gl = {ln: (abs(b_), r_) for ln, b_, r_ in (x.get("gst_lines") or [])}
                tgt, key = (at, "at") if increase else (atadj, "atadj")
                heads, rate_amt = _z(), defaultdict(float)
                for ln, a in tl:
                    h = tax[ln][0]
                    val = -a if increase else a
                    heads[h] += val
                    base_, r_ = gl.get(ln, (None, None))
                    if r_ is None:
                        m = re.search(r"(\d+(?:\.\d+)?)\s*%", ln)
                        r_ = float(m.group(1)) if m else None
                    if base_ is not None and r_ is not None and h in ("IGST", "CGST"):
                        rate_amt[r_ * (2 if h == "CGST" else 1)] += base_
                pos = x.get("place_of_supply") or company_state
                rate = max(rate_amt, key=lambda r: rate_amt[r]) if rate_amt else 0
                row = tgt[(pos, rate)]
                row["taxable"] += sum(rate_amt.values())
                for h in HEADS:
                    row[h] += heads[h]
                a_ = {"id": v["id"], "value": 0.0, "heads": heads}
                add(key, a_, dict(rate_amt))
                continue
            a = _analyse(c, v, tax, led, company_state, stock)
            if base in ("Credit Note", "Debit Note") and "|Sundry Creditors|" in ((led.get(v["party"]) or {}).get("chain") or ""):
                continue                          # a note to a supplier: purchases, not GSTR-1
            if base == "Sales" and not a["by_rate"] and not any(a["nil"].values()) and abs(a["tax"]) < 0.005:
                continue
            taxable = sum(a["by_rate"].values())
            split = _split(a, a["by_rate"], a["heads"])
            row = {"id": a["id"], "date": a["date"], "vtype": a["vtype"], "number": a["number"], "party": a["party"], "gstin": a["gstin"],
                   "pos": a["pos"], "value": a["value"], "taxable": round(taxable, 2), **{h: round(a["heads"][h], 2) for h in HEADS},
                   "rates": [{"rate": r, "taxable": round(x_, 2)} for r, x_ in sorted(a["by_rate"].items())], "rcm": a["rcm"],
                   "reg_type": a["reg_type"]}
            nsum = sum(a["nil"].values())
            note = base != "Sales"
            nsign = -1 if base == "Credit Note" else 1
            if taxable > 0.004 or abs(a["tax"]) > 0.004:
                if note:
                    if a["registered"]:
                        add("cdnr", a, a["by_rate"], nsign, {**row, "type": "C" if base == "Credit Note" else "D"})
                    elif a["inter"] and a["value"] > B2CL_LIMIT:
                        add("cdnur", a, a["by_rate"], nsign, {**row, "type": "C" if base == "Credit Note" else "D"})
                    else:                       # a note to an unregistered buyer, small or within the state: nets in B2C (Small)
                        sec["b2cs"]["vouchers"].add(a["id"])
                        for r, amt in a["by_rate"].items():
                            k = (a["pos"], r)
                            b2cs[k]["taxable"] += nsign * amt
                            for h in HEADS:
                                b2cs[k][h] += nsign * split[r][h]
                        sec["b2cs"]["taxable"] += nsign * taxable
                        for h in HEADS:
                            sec["b2cs"][h] += nsign * a["heads"][h]
                elif a["export"]:
                    add("exp", a, a["by_rate"], 1, row)
                elif a["registered"]:
                    add("b2b", a, a["by_rate"], 1, row)
                    add("b2b_rcm" if a["rcm"] else "b2b_taxable", a, a["by_rate"], 1)
                elif a["inter"] and a["value"] > B2CL_LIMIT:
                    add("b2cl", a, a["by_rate"], 1, row)
                else:
                    sec["b2cs"]["vouchers"].add(a["id"])
                    for r, amt in a["by_rate"].items():
                        k = (a["pos"], r)
                        b2cs[k]["taxable"] += amt
                        for h in HEADS:
                            b2cs[k][h] += split[r][h]
                    sec["b2cs"]["taxable"] += taxable
                    for h in HEADS:
                        sec["b2cs"][h] += a["heads"][h]
            if nsum > 0.004:
                box = ("8A" if a["inter"] else "8B") if a["registered"] else ("8C" if a["inter"] else "8D")
                for k_, val in a["nil"].items():
                    nil8[box][k_] += nsign * val
                sec["nil"]["vouchers"].add(a["id"])
                sec["nil"]["taxable"] += nsign * nsum
            # 12 - HSN summary: every stock line, its tax shared by value x rate
            tgt = hsn["b2b" if a["registered"] else "b2c"]
            w = sum(it["amount"] * (it["rate"] or 0) for it in a["items"]) or 0
            for it in a["items"]:
                r_ = it["rate"] if it["rate"] is not None else (max(a["by_rate"], key=lambda r: a["by_rate"][r]) if a["by_rate"] else 0)
                k = (it["hsn"] or "No HSN", uqc(it["unit"]), r_)
                row_ = tgt[k]
                row_["qty"] += nsign * it["qty"]
                row_["taxable"] += nsign * it["amount"]
                for h in HEADS:
                    row_[h] += nsign * (a["heads"][h] * it["amount"] * (it["rate"] or 0) / w if w else 0)
            if not a["items"] and (taxable > 0.004 or nsum > 0.004):
                for r, amt in list(a["by_rate"].items()) + [(0, nsum)]:
                    if amt > 0.004:
                        row_ = tgt[("No HSN", "", r)]
                        row_["taxable"] += nsign * amt
                        for h in HEADS:
                            row_[h] += nsign * (split[r][h] if r in split else 0)
            if note:
                notes.append(a["id"])

    def fin(s_):
        out = {"count": len(s_["vouchers"]), "taxable": round(s_["taxable"], 2), "value": round(s_["value"], 2),
               **{h: round(s_[h], 2) for h in HEADS}}
        out["tax"] = round(sum(out[h] for h in HEADS), 2)
        if s_["list"]:
            out["list"] = s_["list"]
        return out
    out = {k: fin(s_) for k, s_ in sec.items()}
    out["b2cs"]["rows"] = sorted(({"pos": p, "rate": r, **{k: round(v_, 2) for k, v_ in d.items()}} for (p, r), d in b2cs.items()
                                  if abs(d["taxable"]) > 0.004 or any(abs(d[h]) > 0.004 for h in HEADS)), key=lambda x: (x["pos"], x["rate"]))
    out["nil"]["rows"] = [{"box": k, "label": {"8A": "Inter-state to registered persons", "8B": "Intra-state to registered persons",
                                               "8C": "Inter-state to unregistered persons", "8D": "Intra-state to unregistered persons"}[k],
                           **{x: round(y, 2) for x, y in d.items()}} for k, d in nil8.items()]
    out["at"]["rows"] = [{"pos": p, "rate": r, **{k: round(v_, 2) for k, v_ in d.items()}} for (p, r), d in sorted(at.items())]
    out["atadj"]["rows"] = [{"pos": p, "rate": r, **{k: round(v_, 2) for k, v_ in d.items()}} for (p, r), d in sorted(atadj.items())]
    out["hsn"] = {k: sorted(({"hsn": h_, "uqc": u, "rate": r, **{x: round(y, 3 if x == "qty" else 2) for x, y in d.items()}}
                             for (h_, u, r), d in tbl.items()), key=lambda x: (x["hsn"], x["rate"])) for k, tbl in hsn.items()}
    docrows = []
    for (kind, vtype, series), d in sorted(docs.items()):
        nums = sorted(d["nums"])
        docrows.append({"kind": kind, "vtype": vtype, "from": nums[0][1], "to": nums[-1][1], "total": len(nums),
                        "cancelled": d["cancelled"], "net": len(nums) - d["cancelled"]})
    out["doc"] = docrows
    for k in ("b2ba", "b2cla", "expa", "cdnra", "cdnura", "b2csa", "ata", "atadja"):
        out[k] = {"count": 0, "taxable": 0.0, "value": 0.0, **_z(), "tax": 0.0}
    # tax on outward supplies, all tables together (credit notes count less)
    tot = {h: round(sum(out[k][h] for k in ("b2b", "b2cl", "exp", "b2cs", "cdnr", "cdnur")), 2) for h in HEADS}
    tot["taxable"] = round(sum(out[k]["taxable"] for k in ("b2b", "b2cl", "exp", "b2cs", "cdnr", "cdnur")), 2)
    return {"month": month, "from": f, "to": t, "company": co["name"] if co else "", "state": company_state,
            "sections": out, "tax_total": tot, "no_tax_ledgers": not tax}


# ------------------------------------------------------------------ comparing with Tally's own GSTR-1
import os as _os
import threading as _th
import time as _time

_DIR = _os.path.join(_os.environ.get("DATA_DIR", "/data"), "gstr1tally")
_lock = _th.Lock()
TALLY_ROWS = [  # Tally's row (start of its label) -> the table here
    ("B2B Invoices", "b2b"), ("Taxable Sales", "b2b_taxable"), ("Reverse Charge Supplies", "b2b_rcm"),
    ("B2C (Large) Invoices", "b2cl"), ("Exports Invoices", "exp"), ("Credit or Debit Notes (Registered)", "cdnr"),
    ("Credit or Debit Notes (Unregistered)", "cdnur"), ("Amended B2B", "b2ba"), ("Amended B2C (Large)", "b2cla"),
    ("Amended Exports", "expa"), ("Amended Credit or Debit Notes (Registered)", "cdnra"),
    ("Amended Credit or Debit Notes (Unregistered)", "cdnura"), ("B2C (Small) Invoices", "b2cs"), ("Nil Rated", "nil"),
    ("Amendment B2C (Small)", "b2csa"), ("Tax Liability (Advances Received)", "at"), ("Adjustment of Advances", "atadj"),
    ("Amended Tax Liability", "ata"), ("Amendment of Adjusted Advances", "atadja"), ("HSN Summary", "hsn"), ("Document Summary", "doc")]


def _text(raw):
    """Tally's export as text, whichever way it was saved: UTF-8, or UTF-16 (Tally's 'Unicode'), with or without the
    byte-order mark, or the old Windows code page."""
    if isinstance(raw, str):
        return raw
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    head = raw[:400]
    if head.count(b"\x00") > len(head) // 4:      # UTF-16 without the mark
        return raw.decode("utf-16-le" if head[1:2] == b"\x00" else "utf-16-be", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def _row_key(label):
    lab = re.sub(r"\s+", " ", label or "").strip().lower()
    return next((k for l, k in TALLY_ROWS if lab.startswith(l.lower())), None)


def _num(val):
    try:
        return abs(float(re.sub(r"[^0-9.\-]", "", str(val)) or 0))
    except ValueError:
        return 0.0


def _xlsx_rows(raw):
    """The cells of each row of the first sheet of an Excel export, as text (standard library only)."""
    import io
    import zipfile
    from xml.etree import ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(ns + "si"):
                shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
        sheet = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        if not sheet:
            raise ValueError("This Excel file has no sheet in it.")
        out = []
        for r in ET.fromstring(z.read(sheet[0])).iter(ns + "row"):
            cells = {}
            for c in r.iter(ns + "c"):
                ref = re.match(r"([A-Z]+)", c.get("r") or "")
                col = 0
                for ch in (ref.group(1) if ref else ""):
                    col = col * 26 + ord(ch) - 64
                v = c.find(ns + "v")
                if c.get("t") == "s" and v is not None:
                    txt = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
                elif c.get("t") == "inlineStr":
                    txt = "".join(t.text or "" for t in c.iter(ns + "t"))
                else:
                    txt = v.text if v is not None and v.text else ""
                cells[(col or len(cells) + 1) - 1] = txt
            out.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        return out


def _from_table(rows):
    """Tally's GSTR-1 saved as Excel: find the heading row (Taxable ...) and read each table's row under it."""
    cols = None
    found = {}
    for r in rows:
        low = [str(x).strip().lower() for x in r]
        if cols is None and any("taxable" in x for x in low):
            cols = {}
            for i, x in enumerate(low):
                f = ("count" if "count" in x or "no. of" in x or "number" in x else
                     "taxable" if "taxable" in x else
                     "IGST" if "igst" in x or "integrated" in x else
                     "CGST" if "cgst" in x or "central" in x else
                     "SGST" if "sgst" in x or "state" in x or "utgst" in x else
                     "Cess" if "cess" in x else
                     "value" if "invoice" in x or "value" in x else
                     "tax" if "tax" in x else None)
                if f and f not in cols.values():
                    cols[i] = f
            continue
        if cols is None:
            continue
        label = next((str(x) for x in r if str(x).strip()), "")
        key = _row_key(label)
        if key and key not in found:
            found[key] = {"label": label.strip(), **{f: _num(r[i]) if i < len(r) else 0.0 for i, f in cols.items()}}
    return found


def parse_tally(raw):
    """Tally's GSTR-1 export for the month (XML, or Excel), to compare with: each table's row -> its figures."""
    if isinstance(raw, bytes) and raw[:2] == b"PK":
        try:
            rows = _from_table(_xlsx_rows(raw))
        except ValueError:
            raise
        except Exception:
            raise ValueError("Couldn't open this Excel file. In Tally open GSTR-1, press Alt+E and choose XML (Data Interchange).")
        if not rows:
            raise ValueError("This Excel file isn't Tally's GSTR-1 for a month (no GSTR-1 tables found in it).")
        return rows
    if not raw:
        raise ValueError("The file is empty.")
    text = _text(raw)
    if "GSTRRETVIEWPARTICULARS" not in text.upper():
        if re.search(r"B2B Invoices|B2C \(Small\)", text, re.I):
            raise ValueError("This is GSTR-1 saved in another format. In Tally press Alt+E, set Format to XML (Data Interchange), and export again.")
        raise ValueError("This isn't Tally's GSTR-1 export. In Tally open GSTR-1 for the month, press Alt+E and choose XML (Data Interchange).")
    rows, cur = {}, None
    tags = {"GSTRVCHCOUNT": "count", "GSTRTAXABLEAMOUNT": "taxable", "GSTRIGSTAMOUNT": "IGST", "GSTRCGSTAMOUNT": "CGST",
            "GSTRSGSTAMOUNT": "SGST", "GSTRCESSAMOUNT": "Cess", "GSTRTAXAMOUNT": "tax", "GSTRINVOICEAMOUNT": "value"}
    ent = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}
    for m in re.finditer(r"<(GSTR[A-Z]*)(?:\s[^>]*)?>([^<]*)</\1\s*>", text, re.I):
        tag, val = m.group(1).upper(), re.sub(r"&\w+;", lambda e: ent.get(e.group(0), " "), m.group(2)).strip()
        if tag == "GSTRRETVIEWPARTICULARS":
            key = _row_key(val)
            cur = None
            if key and key not in rows:
                cur = rows[key] = {"label": val}
        elif cur is not None and tag in tags:
            cur[tags[tag]] = _num(val) if val else 0.0
    if not rows:
        raise ValueError("No GSTR-1 tables found in the file.")
    return rows


def _tpath(cid):
    return _os.path.join(_DIR, f"{int(cid)}.json")


def tally_load(cid):
    try:
        with open(_tpath(cid)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def tally_save(cid, month, raw):
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        raise ValueError("Which month?")
    rows = parse_tally(raw)
    with _lock:
        d = tally_load(cid)
        d[month] = {"rows": rows, "at": _time.time()}
        _os.makedirs(_DIR, exist_ok=True)
        with open(_tpath(cid) + ".tmp", "w") as f:
            json.dump(d, f)
        _os.replace(_tpath(cid) + ".tmp", _tpath(cid))
    return {"ok": True, "rows": len(rows)}


def tally_remove(cid, month):
    with _lock:
        d = tally_load(cid)
        d.pop(month, None)
        _os.makedirs(_DIR, exist_ok=True)
        with open(_tpath(cid) + ".tmp", "w") as f:
            json.dump(d, f)
        _os.replace(_tpath(cid) + ".tmp", _tpath(cid))
    return {"ok": True}


def with_tally(cid, month):
    """The GSTR-1 here, and beside each table Tally's figures (when its export for the month was uploaded), and
    whether they agree: vouchers, taxable value and each tax within a rupee."""
    r = build(cid, month)
    t = tally_load(cid).get(month)
    if t:
        r["tally"] = {"at": t["at"], "rows": t["rows"]}
        for k, tr in t["rows"].items():
            mine = r["sections"].get(k)
            if not isinstance(mine, dict) or k in ("hsn", "doc"):
                continue
            diffs = []
            if tr.get("count") is not None and int(tr.get("count") or 0) != mine.get("count", 0):
                diffs.append("vouchers")
            for f_ in ("taxable",) + HEADS:
                if abs(abs(mine.get(f_, 0)) - (tr.get(f_) or 0)) > 1:
                    diffs.append(f_)
            mine["vs_tally"] = {"ok": not diffs, "diffs": diffs, **{k2: tr.get(k2) for k2 in ("count", "taxable") + HEADS}}
    return r
