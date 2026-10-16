"""Bank reconciliation: a bank statement (Excel, CSV, or the .xls most Indian banks give, which is really a web
page) against the bank ledger in Tally.

Each statement line is matched to a Tally entry on the bank ledger with the same amount, in the same direction,
dated within a few days (cheques take time to clear). A cheque number seen in both sides wins over a closer date.
What's left over is the reconciliation: entries in Tally the bank hasn't shown yet, and bank entries (charges,
interest, direct credits) not yet entered in Tally.
"""
import csv
import hashlib
import html
import io
import json
import os
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DIR = os.path.join(DATA_DIR, "bankrec")
DAYS = 7          # how far apart the bank date and the Tally date may be
TOL = 0.01


# ---------------------------------------------------------------- reading the statement
def _date(s):
    s = str(s or "").strip()
    if not s:
        return ""
    try:                                   # Excel serial day number
        n = float(s)
        if 20000 < n < 80000:
            return (date(1899, 12, 30) + timedelta(days=int(n))).isoformat()
        return ""
    except ValueError:
        pass
    s = re.sub(r"\s+", " ", s.replace(",", " ")).strip()
    s = re.split(r"\s\d{1,2}:\d{2}", s)[0].strip()          # drop a time of day
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%Y-%m-%d", "%Y/%m/%d",
                "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y", "%d/%b/%Y", "%d/%b/%y", "%b %d %Y", "%d %B %Y",
                "%d-%B-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt).date()
            if 1990 < d.year < 2100:
                return d.isoformat()
        except ValueError:
            pass
    return ""


def _num(s):
    s = str(s or "").strip().replace(",", "").replace("₹", "").replace("INR", "").strip()
    if not s or s in ("-", "--"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*(cr|dr|c|d)?\.?$", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    if neg or (m.group(2) or "").lower() in ("dr", "d"):
        v = -abs(v)
    return v


def _xlsx_rows(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    best = []
    for sh in wb.find("m:sheets", ns):
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
        if len(rows) > len(best):
            best = rows
    return best


def _html_rows(text):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        rows.append([html.unescape(re.sub(r"<[^>]+>", " ", c)).replace("\xa0", " ").strip() for c in cells])
    return [r for r in rows if any(r)]


def _csv_rows(text):
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]


def _rows(raw, fname):
    low = (fname or "").lower()
    if raw[:2] == b"PK":
        return _xlsx_rows(raw)
    if raw[:4] == b"%PDF":
        raise ValueError("That's a PDF. Download the statement from net banking as Excel or CSV instead.")
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("That's an old-style Excel file (.xls). Open it in Excel and save it as .xlsx or CSV, then choose that file.")
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    if re.search(r"<t[dr][\s>]", text[:200000], re.I) or low.endswith((".xls", ".htm", ".html")):
        rows = _html_rows(text)
        if rows:
            return rows
    return _csv_rows(text)


HEAD = {
    "date": ("txn date", "tran date", "transaction date", "value date", "date", "value dt", "txn dt", "posting date"),
    "desc": ("narration", "description", "particulars", "remarks", "details", "transaction details", "transaction remarks"),
    "ref": ("chq", "cheque", "ref", "instrument"),
    "debit": ("withdrawal", "debit", "dr amount", "amount dr", "paid out", "dr."),
    "credit": ("deposit", "credit", "cr amount", "amount cr", "paid in", "cr."),
    "amount": ("amount", "transaction amount", "txn amount"),
    "drcr": ("dr/cr", "cr/dr", "dr / cr", "type", "debit/credit"),
    "balance": ("balance", "closing balance", "running balance"),
}


def _header(rows):
    """Position of the header row and which column holds what."""
    for i, r in enumerate(rows[:40]):
        names = [re.sub(r"\s+", " ", str(x).lower().replace("\n", " ")).strip() for x in r]
        if not any(n.startswith(("date", "txn date", "tran date", "transaction date", "value date", "post")) or n == "date"
                   for n in names):
            continue
        col = {}
        for key in ("balance", "drcr", "date", "debit", "credit", "desc", "ref", "amount"):
            for j, n in enumerate(names):
                if j in col.values() or not n:
                    continue
                if key == "date" and "value" in n and any("txn" in x or "tran" in x or "post" in x for x in names):
                    continue                     # prefer the transaction date over the value date
                if key in ("debit", "credit", "amount") and "balance" in n:
                    continue
                if key == "ref" and ("date" in n):
                    continue
                if any(n == k or n.startswith(k) or (len(k) > 4 and k in n) for k in HEAD[key]):
                    col[key] = j
                    break
        if "date" in col and (("debit" in col and "credit" in col) or "amount" in col):
            return i, col
    return None, {}


def parse(raw, fname=""):
    rows = _rows(raw, fname)
    hi, col = _header(rows)
    if hi is None:
        raise ValueError("Couldn't find the columns in that file. It needs a Date column and either Withdrawal and "
                         "Deposit columns, or an Amount column.")
    out = []
    get = lambda r, k: r[col[k]] if k in col and col[k] < len(r) else ""
    for r in rows[hi + 1:]:
        d = _date(get(r, "date"))
        if not d:
            continue
        if "debit" in col:
            dr, cr = _num(get(r, "debit")), _num(get(r, "credit"))
            amt = (abs(cr) if cr else 0) - (abs(dr) if dr else 0)
        else:
            a = _num(get(r, "amount"))
            if a is None:
                continue
            t = get(r, "drcr").strip().lower()
            amt = -abs(a) if t.startswith(("dr", "d", "w")) else abs(a) if t.startswith(("cr", "c", "dep")) else a
        if abs(amt) < 0.005:
            continue
        desc = get(r, "desc")
        ref = get(r, "ref").strip()
        if re.fullmatch(r"0+|-+", ref):
            ref = ""
        out.append({"date": d, "amount": round(amt, 2), "desc": re.sub(r"\s+", " ", desc).strip()[:200],
                    "ref": ref[:40], "balance": _num(get(r, "balance"))})
    if not out:
        raise ValueError("Found the columns but no entries under them.")
    # most statements list newest first; keep them oldest first, and keep the order within a day
    if out[0]["date"] > out[-1]["date"]:
        out.reverse()
    for k, t in enumerate(out):
        t["n"] = k
    return out


# ---------------------------------------------------------------- saving
def _path(company, ledger):
    h = hashlib.sha1(f"{company}\x00{ledger}".encode()).hexdigest()[:16]
    return os.path.join(DIR, h + ".json")


def save(company, ledger, txns, fname):
    os.makedirs(DIR, exist_ok=True)
    old = load(company, ledger) or {}
    seen = {(t["date"], t["amount"], t["desc"], t.get("ref", "")) for t in old.get("txns", [])}
    merged = list(old.get("txns", []))
    added = 0
    for t in txns:                    # a new statement adds to the earlier one, without doubling overlapping days
        k = (t["date"], t["amount"], t["desc"], t.get("ref", ""))
        if k not in seen:
            seen.add(k)
            merged.append(t)
            added += 1
    merged.sort(key=lambda t: (t["date"], t.get("n", 0)))
    for k, t in enumerate(merged):
        t["n"] = k
    d = {"company": company, "ledger": ledger, "txns": merged, "file": fname,
         "uploaded": datetime.now().isoformat(timespec="seconds"), "manual": old.get("manual", {})}
    tmp = _path(company, ledger) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, _path(company, ledger))
    return added


def load(company, ledger):
    try:
        with open(_path(company, ledger)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clear(company, ledger):
    try:
        os.remove(_path(company, ledger))
    except OSError:
        pass


# ---------------------------------------------------------------- matching
def bank_ledgers(cid):
    with store.conn() as c:
        return [r["name"] for r in c.execute(
            "SELECT name FROM ledger WHERE company_id=? AND (chain LIKE '%|Bank Accounts|%' OR chain LIKE '%|Bank OD A/c|%') "
            "ORDER BY name COLLATE NOCASE", (cid,))]


def _digits(s):
    return {x.lstrip("0") for x in re.findall(r"\d{4,}", s or "") if x.lstrip("0")}


def _balance_at(c, cid, ledger, day):
    """Tally balance of the bank ledger at the end of `day` (positive = money in the bank)."""
    comp = c.execute("SELECT from_date FROM company WHERE id=?", (cid,)).fetchone()
    sync_from = (comp and comp["from_date"]) or "2000-01-01"
    led = c.execute("SELECT closing FROM ledger WHERE company_id=? AND name=?", (cid, ledger)).fetchone()
    if not led:
        return None
    return store._opening_at(c, cid, ledger, led["closing"], sync_from, (date.fromisoformat(day) + timedelta(days=1)).isoformat())


def check(cid, ledger, saved, d_from=None, d_to=None):
    txns = saved["txns"]
    f = d_from or txns[0]["date"]
    t = d_to or txns[-1]["date"]
    bank = [x for x in txns if f <= x["date"] <= t]
    lo = (date.fromisoformat(txns[0]["date"]) - timedelta(days=DAYS + 30)).isoformat()
    hi = (date.fromisoformat(txns[-1]["date"]) + timedelta(days=DAYS)).isoformat()
    with store.conn() as c:
        tally = store._rows(c, """SELECT v.id, v.date, v.vtype, v.number, v.party, v.narration, SUM(vl.amount) amount
            FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
            WHERE v.company_id=? AND vl.ledger=? AND v.date BETWEEN ? AND ?
            GROUP BY v.id HAVING ABS(SUM(vl.amount)) > 0.005 ORDER BY v.date, v.id""", (cid, ledger, lo, hi))
        tally_bal = _balance_at(c, cid, ledger, t)
    all_bank = txns       # bank lines outside the period still claim their Tally entries
    manual = saved.get("manual", {})          # bank line n -> voucher id the owner paired by hand
    for v in tally:
        v["amount"] = round(v["amount"], 2)
        v["refs"] = _digits(f"{v['number']} {v['narration']}")
    used_v, pair = set(), {}
    byid = {v["id"]: v for v in tally}
    for n, vid in manual.items():
        if int(vid) in byid:
            pair[int(n)] = int(vid)
            used_v.add(int(vid))
    cands = []
    for b in all_bank:
        if b["n"] in pair:
            continue
        bd = date.fromisoformat(b["date"])
        brefs = _digits(f"{b.get('ref', '')} {b['desc']}")
        for v in tally:
            if abs(v["amount"] - b["amount"]) > TOL:
                continue
            gap = (bd - date.fromisoformat(v["date"])).days
            if not -2 <= gap <= DAYS + (30 if v["vtype"].lower().startswith(("pay", "contra")) else 0):
                continue          # the bank can't show it much before Tally; an issued cheque may take weeks
            same_ref = bool(brefs & v["refs"])
            if gap > DAYS and not same_ref:
                continue
            cands.append((0 if same_ref else 1, abs(gap), b["n"], v["id"]))
    cands.sort()
    for _, _, n, vid in cands:
        if n in pair or vid in used_v:
            continue
        pair[n] = vid
        used_v.add(vid)
    matched, bank_only = [], []
    for b in bank:
        if b["n"] in pair:
            v = byid[pair[b["n"]]]
            matched.append({"bank": b, "tally": _vpub(v), "days": (date.fromisoformat(b["date"]) - date.fromisoformat(v["date"])).days,
                            "manual": str(b["n"]) in manual})
        else:
            bank_only.append(b)
    tally_only = [_vpub(v) for v in tally if v["id"] not in used_v and v["date"] <= t and v["date"] >= f]
    # entries made in Tally up to the end date and not yet in the bank, from before the statement too
    pending = [_vpub(v) for v in tally if v["id"] not in used_v and txns[0]["date"] <= v["date"] < f]
    unpresented = round(-sum(v["amount"] for v in tally_only + pending if v["amount"] < 0), 2)   # cheques issued
    uncleared = round(sum(v["amount"] for v in tally_only + pending if v["amount"] > 0), 2)      # deposited, not credited
    bank_dr = round(-sum(b["amount"] for b in bank_only if b["amount"] < 0), 2)
    bank_cr = round(sum(b["amount"] for b in bank_only if b["amount"] > 0), 2)
    stmt_bal = next((b["balance"] for b in reversed(bank) if b.get("balance") is not None), None)
    expected = None if tally_bal is None else round(tally_bal + unpresented - uncleared + bank_cr - bank_dr, 2)
    return {"ledger": ledger, "from": f, "to": t, "first": txns[0]["date"], "last": txns[-1]["date"],
            "file": saved.get("file"), "uploaded": saved.get("uploaded"),
            "matched": matched, "bank_only": bank_only, "tally_only": tally_only, "pending": pending,
            "summary": {"tally": None if tally_bal is None else round(tally_bal, 2), "unpresented": unpresented,
                        "uncleared": uncleared, "bank_cr": bank_cr, "bank_dr": bank_dr, "expected": expected,
                        "statement": stmt_bal,
                        "diff": None if expected is None or stmt_bal is None else round(stmt_bal - expected, 2)},
            "candidates": {b["n"]: [v["id"] for v in tally if v["id"] not in used_v and abs(v["amount"] - b["amount"]) <= TOL]
                           for b in bank_only}}


def _vpub(v):
    return {k: v[k] for k in ("id", "date", "vtype", "number", "party", "narration", "amount")}


def pair(company, ledger, n, vid):
    d = load(company, ledger)
    if not d:
        return
    m = d.setdefault("manual", {})
    if vid:
        m[str(n)] = int(vid)
    else:
        m.pop(str(n), None)
    tmp = _path(company, ledger) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, _path(company, ledger))
