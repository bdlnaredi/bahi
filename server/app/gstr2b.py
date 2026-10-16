"""GSTR-2B check: the supplier invoices the GST portal shows for a month, against the purchases booked in Tally.

Reads the GSTR-2B file downloaded from the portal (JSON, a ZIP holding the JSON, or the Excel file) and
matches invoices by supplier GSTIN and invoice number. Debit/credit notes from suppliers are matched the same
way against Debit Note / Credit Note vouchers.
"""
import io
import json
import os
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DIR = os.path.join(DATA_DIR, "gstr2b")
HEADS = ("igst", "cgst", "sgst", "cess")
TOL = 1.0      # rupees of difference treated as a match (rounding)


# ---------------------------------------------------------------- reading the portal file
def _d(s):
    s = str(s or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    try:                       # Excel serial day number
        n = float(s)
        if 20000 < n < 80000:
            return (date(1899, 12, 30) + timedelta(days=int(n))).isoformat()
    except ValueError:
        pass
    return ""


def _f(x):
    try:
        return round(float(str(x).replace(",", "") or 0), 2)
    except ValueError:
        return 0.0


def _doc(kind, ctin, name, num, dt, val, taxable, igst, cgst, sgst, cess, itc="", note_type=""):
    return {"kind": kind, "ctin": (ctin or "").strip().upper(), "name": (name or "").strip(), "num": str(num or "").strip(),
            "date": _d(dt), "value": _f(val), "taxable": _f(taxable), "igst": _f(igst), "cgst": _f(cgst),
            "sgst": _f(sgst), "cess": _f(cess), "itc": itc, "note_type": note_type}


def _from_json(j):
    d = j.get("data", j)
    period = str(d.get("rtnprd") or "")
    dd = d.get("docdata") or {}
    docs = []
    for sup in dd.get("b2b", []) + dd.get("b2ba", []):
        for inv in sup.get("inv", []):
            items = inv.get("items") or []
            tx = inv.get("txval") if inv.get("txval") is not None else sum(_f(i.get("txval")) for i in items)
            docs.append(_doc("inv", sup.get("ctin"), sup.get("trdnm"), inv.get("inum"), inv.get("dt"), inv.get("val"), tx,
                             inv.get("igst", sum(_f(i.get("igst")) for i in items)),
                             inv.get("cgst", sum(_f(i.get("cgst")) for i in items)),
                             inv.get("sgst", sum(_f(i.get("sgst")) for i in items)),
                             inv.get("cess", sum(_f(i.get("cess")) for i in items)), inv.get("itcavl", "")))
    for sup in dd.get("cdnr", []) + dd.get("cdnra", []):
        for nt in sup.get("nt", []):
            items = nt.get("items") or []
            tx = nt.get("txval") if nt.get("txval") is not None else sum(_f(i.get("txval")) for i in items)
            docs.append(_doc("note", sup.get("ctin"), sup.get("trdnm"), nt.get("ntnum"), nt.get("dt"), nt.get("val"), tx,
                             nt.get("igst", sum(_f(i.get("igst")) for i in items)),
                             nt.get("cgst", sum(_f(i.get("cgst")) for i in items)),
                             nt.get("sgst", sum(_f(i.get("sgst")) for i in items)),
                             nt.get("cess", sum(_f(i.get("cess")) for i in items)), nt.get("itcavl", ""), nt.get("typ", "C")))
    return period, str(d.get("gstin") or ""), docs


def _xlsx_rows(raw, wanted):
    """Rows of the first sheet whose name contains one of `wanted`, as lists of strings (no extra libraries)."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in wb.find("m:sheets", ns):
        name = sh.get("name") or ""
        key = next((w for w in wanted if name.strip().upper() == w), None)
        if not key or key in out:
            continue
        target = rels[sh.get("{%s}id" % ns["r"])].lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(path)).iter("{%s}row" % ns["m"]):
            cells = {}
            for c in row.findall("m:c", ns):
                ref = re.match(r"([A-Z]+)", c.get("r") or "A").group(1)
                col = 0
                for ch in ref:
                    col = col * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None else ""
                cells[col] = val or ""
            if cells:
                rows.append([cells.get(i, "") for i in range(1, max(cells) + 1)])
        out[key] = rows
    return out


def _cols(rows, must):
    """Find the header row (the one containing `must`) and map column titles to positions."""
    for i, r in enumerate(rows[:15]):
        if any(must in str(x).lower() for x in r):
            names = [str(x).lower() for x in r]
            # the portal splits headings over two rows: join with the row below for the tax columns
            nxt = [str(x).lower() for x in rows[i + 1]] if i + 1 < len(rows) else []
            full = [(names[k] if k < len(names) else "") + " " + (nxt[k] if k < len(nxt) else "") for k in range(max(len(names), len(nxt)))]
            return i + 2 if any(nxt) and not any(re.match(r"^\d{2}[a-z0-9]{13}$", x.strip()) for x in nxt) else i + 1, full
    return None, []


def _pick(full, *keys, avoid=()):
    for k in keys:
        for j, n in enumerate(full):
            if k in n and not any(a in n for a in avoid):
                return j
    return None


def _from_xlsx(raw):
    sheets = _xlsx_rows(raw, ("B2B", "B2B-CDNR", "B2BA", "B2B-CDNRA", "READ ME"))
    period = ""
    for r in sheets.get("READ ME", [])[:20]:
        for x in r:
            m = re.search(r"\b(\d{2})(\d{4})\b", str(x))
            if "period" in " ".join(str(y).lower() for y in r) and m:
                period = m.group(0)
    docs = []
    for key, kind in (("B2B", "inv"), ("B2BA", "inv"), ("B2B-CDNR", "note"), ("B2B-CDNRA", "note")):
        rows = sheets.get(key)
        if not rows:
            continue
        start, full = _cols(rows, "gstin of supplier")
        if start is None:
            continue
        c = {"ctin": _pick(full, "gstin of supplier"), "name": _pick(full, "trade/legal name", "trade", "legal name"),
             "num": _pick(full, "note number", "invoice number", "number", avoid=("gstin",)),
             "date": _pick(full, "note date", "invoice date", "date", avoid=("filing",)),
             "val": _pick(full, "note value", "invoice value", "value", avoid=("taxable",)),
             "tx": _pick(full, "taxable value"), "igst": _pick(full, "integrated tax"), "cgst": _pick(full, "central tax"),
             "sgst": _pick(full, "state/ut tax", "state tax"), "cess": _pick(full, "cess"),
             "itc": _pick(full, "itc availability"), "nt": _pick(full, "note type")}
        g = lambda r, k: r[c[k]] if c[k] is not None and c[k] < len(r) else ""
        for r in rows[start:]:
            if not re.match(r"^\d{2}[A-Z0-9]{13}$", str(g(r, "ctin")).strip().upper()):
                continue
            docs.append(_doc(kind, g(r, "ctin"), g(r, "name"), g(r, "num"), g(r, "date"), g(r, "val"), g(r, "tx"),
                             g(r, "igst"), g(r, "cgst"), g(r, "sgst"), g(r, "cess"), g(r, "itc"),
                             "D" if "debit" in str(g(r, "nt")).lower() else "C" if kind == "note" else ""))
    return period, "", docs


def parse(raw, filename=""):
    name = (filename or "").lower()
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        if any(n.endswith(".json") for n in z.namelist()):
            j = json.loads(z.read(next(n for n in z.namelist() if n.endswith(".json"))).decode("utf-8-sig"))
            return _from_json(j)
        return _from_xlsx(raw)
    if name.endswith(".xls"):
        raise ValueError("That's the old Excel format. Download the JSON file from the portal, or save the Excel file as .xlsx.")
    try:
        return _from_json(json.loads(raw.decode("utf-8-sig")))
    except ValueError:
        raise ValueError("This doesn't look like a GSTR-2B file. Download it from the GST portal (Returns, GSTR-2B) as JSON or Excel.")


# ---------------------------------------------------------------- matching with Tally
def _key(num):
    s = re.sub(r"[^A-Z0-9]", "", str(num or "").upper())
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", s)          # 'INV/007' and 'INV7' match


def _books(cid):
    """Purchases and notes in Tally with their supplier GSTIN, supplier invoice no. and tax by head."""
    with store.conn() as c:
        led = {r["name"]: r for r in c.execute("SELECT name, chain, taxtype, gst_head, gstin, closing FROM ledger WHERE company_id=?", (cid,))}
        tax = {n for n, l in led.items() if store._is_tax(l)}
        vs = store._rows(c, """SELECT id, date, vtype, base, number, reference, party, party_gstin, amount FROM voucher
            WHERE company_id=? AND posting=1 AND base IN ('Purchase', 'Debit Note')""", (cid,))
        out = []
        for v in vs:
            gstin = (v["party_gstin"] or (led.get(v["party"]) or {"gstin": ""})["gstin"] or "").strip().upper()
            if not gstin:
                continue
            heads = {h: 0.0 for h in HEADS}
            for x in c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],)):
                if x["ledger"] in tax:
                    heads[store._gst_head(led[x["ledger"]]).lower()] += abs(x["amount"])
            t = round(sum(heads.values()), 2)
            out.append({**v, "gstin": gstin, **{h: round(a, 2) for h, a in heads.items()}, "tax": t,
                        "taxable": round(abs(v["amount"]) - t, 2), "kind": "inv" if v["base"] == "Purchase" else "note"})
    return out


def check(cid, period, docs):
    """period 'MMYYYY'. Returns the four lists and the input-credit totals."""
    books = _books(cid)
    by = {}
    for b in books:
        by.setdefault((b["kind"], b["gstin"], _key(b["reference"] or b["number"])), []).append(b)
        if b["reference"] and _key(b["number"]) != _key(b["reference"]):
            by.setdefault((b["kind"], b["gstin"], _key(b["number"])), []).append(b)
    used, matched, differ, missing = set(), [], [], []
    for d in docs:
        d = dict(d)
        d["tax"] = round(sum(d[h] for h in HEADS), 2)
        cands = [b for b in by.get((d["kind"], d["ctin"], _key(d["num"])), []) if b["id"] not in used]
        if not cands:
            missing.append(d)
            continue
        b = cands[0]
        used.add(b["id"])
        row = {**d, "vid": b["id"], "b_date": b["date"], "b_vtype": b["vtype"], "b_number": b["number"], "party": b["party"],
               "b_taxable": b["taxable"], "b_tax": b["tax"], **{"b_" + h: b[h] for h in HEADS}}
        diffs = [h for h in HEADS if abs(d[h] - b[h]) > TOL]
        if abs(d["taxable"] - b["taxable"]) > TOL and d["taxable"]:
            diffs.append("taxable")
        row["diffs"] = diffs
        (differ if diffs else matched).append(row)
    # booked in Tally for this month, from a registered supplier, but not in GSTR-2B
    mm, yy = period[:2], period[2:]
    start = f"{yy}-{mm}-01"
    end = (date(int(yy) + (mm == "12"), int(mm) % 12 + 1, 1) - timedelta(days=1)).isoformat()
    not_in_2b = [b for b in books if b["id"] not in used and start <= b["date"] <= end and b["tax"] > 0]
    s = lambda rows, k: round(sum(r[k] for r in rows), 2)
    return {"period": period, "from": start, "to": end,
            "matched": matched, "differ": differ, "missing": missing, "not_in_2b": not_in_2b,
            "totals": {"itc_2b": s([dict(x, tax=sum(x[h] for h in HEADS)) for x in docs], "tax"),
                       "matched": s(matched, "tax"), "differ_2b": s(differ, "tax"), "differ_books": s(differ, "b_tax"),
                       "missing": s(missing, "tax"), "at_risk": s(not_in_2b, "tax")}}


# ---------------------------------------------------------------- saved uploads
def _path(company, period):
    safe = re.sub(r"[^A-Za-z0-9]+", "_", company)[:60]
    return os.path.join(DIR, f"{safe}_{period}.json")


def save(company, period, gstin, docs, filename):
    os.makedirs(DIR, exist_ok=True)
    with open(_path(company, period), "w") as f:
        json.dump({"company": company, "period": period, "gstin": gstin, "docs": docs, "file": filename,
                   "uploaded": datetime.now().isoformat(timespec="seconds")}, f)


def load(company, period):
    try:
        with open(_path(company, period)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def listing(company):
    safe = re.sub(r"[^A-Za-z0-9]+", "_", company)[:60] + "_"
    out = []
    try:
        for n in sorted(os.listdir(DIR), reverse=True):
            if n.startswith(safe) and n.endswith(".json"):
                with open(os.path.join(DIR, n)) as f:
                    d = json.load(f)
                out.append({"period": d["period"], "uploaded": d.get("uploaded"), "docs": len(d.get("docs", []))})
    except OSError:
        pass
    out.sort(key=lambda x: x["period"][2:] + x["period"][:2], reverse=True)
    return out
