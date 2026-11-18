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
        vs = store._rows(c, """SELECT id, date, vtype, number, party, extra FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?
            AND posting=1 AND status='' AND base='Journal' AND extra LIKE '%tax_adj%' ORDER BY date, id""", (cid, f, t))
        for v in vs:
            x = json.loads(v["extra"] or "{}")
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
    return {"month": month, "from": g["from"], "to": g["to"], "company": g["company"], "t31": out, "total31": _fin(total), "t32": t32, "vs_gstr1": vs_g1,
            "no_tax_ledgers": g.get("no_tax_ledgers")}


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
    rows, cur = {}, None
    for m in re.finditer(r"<(GSTR[A-Z]*)(?:\s[^>]*)?>([^<]*)</\1\s*>", text, re.I):
        tag, val = m.group(1).upper(), re.sub(r"&\w+;", lambda e: ent.get(e.group(0), " "), m.group(2)).strip()
        if tag == "GSTRRETVIEWPARTICULARS":
            lab = re.sub(r"\s+", " ", val)
            mm = re.match(r"^3\.1\s*\(?([a-e])\b", lab, re.I)
            key = mm.group(1).lower() if mm else ("total" if re.match(r"^3\.1\s+Tax on", lab, re.I) else None)
            m32 = re.match(r"^Supplies (?:made )?to (Unregistered|Composition|UIN)", lab, re.I)
            if m32:
                key = {"unregistered": "unreg", "composition": "comp", "uin": "uin"}[m32.group(1).lower()]
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
    for k, mine in targets:
        tr = t["rows"].get(k)
        if not tr:
            continue
        diffs = [f for f in ("taxable",) + HEADS if (f in mine or tr.get(f)) and abs(abs(mine.get(f, 0)) - (tr.get(f) or 0)) > 1]
        mine["vs_tally"] = {"ok": not diffs, "diffs": diffs, **{f: tr.get(f, 0) for f in ("taxable",) + HEADS}}
    return r
