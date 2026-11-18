"""Tally's own GSTR-3B report, month by month: fetched by the Tally PC (or a file exported from Tally's GSTR-3B
with Alt+E, uploaded in the app). Its figures are shown as they are; Bahi's own working from the vouchers is only
the fallback, and the split of a total where Tally's export has no detail lines."""
import json
import os
import re
import threading
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DIR = os.path.join(DATA_DIR, "tally3b")
HEADS = ("IGST", "CGST", "SGST", "Cess")
_lock = threading.Lock()
TAGS = {"GSTRTAXABLEAMOUNT": "taxable", "GSTRIGSTAMOUNT": "IGST", "GSTRCGSTAMOUNT": "CGST", "GSTRSGSTAMOUNT": "SGST",
        "GSTRCESSAMOUNT": "Cess", "GSTRTAXAMOUNT": "total"}


def parse(raw):
    """Tally's GSTR-3B export: one particulars line, then its amounts, row after row."""
    if isinstance(raw, bytes):
        for enc in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                text = raw.decode(enc)
                if "GSTRRETVIEWPARTICULARS" in text:
                    break
            except UnicodeDecodeError:
                continue
        else:
            text = ""
    else:
        text = raw
    if "GSTRRETVIEWPARTICULARS" not in text:
        raise ValueError("This isn't Tally's GSTR-3B export. In Tally open GSTR-3B, press Alt+E and choose XML (Data Interchange).")
    rows = []
    for m in re.finditer(r"<(GSTRRETVIEWPARTICULARS|GSTR[A-Z]*AMOUNT)>([^<]*)</\1>", text):
        tag, val = m.group(1), m.group(2).strip()
        if tag == "GSTRRETVIEWPARTICULARS":
            rows.append({"label": re.sub(r"\s+", " ", val.replace("&amp;", "&"))})
        elif rows and tag in TAGS:
            try:
                rows[-1][TAGS[tag]] = float(val.replace(",", "")) if val else 0.0
            except ValueError:
                rows[-1][TAGS[tag]] = 0.0
    if not rows:
        raise ValueError("No figures found in the GSTR-3B file.")
    return rows


def _amt(r, sign=1):
    return {k: round(sign * (r.get(k) or 0.0), 2) + 0.0 for k in ("taxable",) + HEADS}


def interpret(rows):
    """Tally's rows → the GSTR-3B boxes. Section lines are 3.1, 3.2, 4, A., B., C., 5, 6.1; detail lines (when the
    report was exported in detail) start with (a), (b) ... under 3.1 and (1), (2) ... under 4 A."""
    out, sec = {"sub31": {}, "sub4a": {}, "sub4b": {}}, None
    for r in rows:
        lab = r["label"]
        m = re.match(r"^(3\.1|3\.2|4|5|6\.1|[ABCD]\.)\s", lab + " ")
        sub = re.match(r"^\(?([a-e1-5])\)?[\s.]", lab + " ")
        m31 = re.match(r"^3\.1\s*\(?([a-e])\)?[\s.]", lab + " ")      # Tally: "3.1a. Outward Taxable Supplies ..."
        if m31:
            out["sub31"][m31.group(1)] = {**_amt(r, 1), "label": lab}
            sec = "s31"
            continue
        if m:
            k = m.group(1)
            sec = {"3.1": "s31", "3.2": "s32", "4": "s4", "5": "s5", "6.1": "s61", "A.": "s4a", "B.": "s4b", "C.": "s4c", "D.": "s4d"}[k]
            out[sec] = _amt(r, -1 if sec in ("s4", "s4a", "s4b", "s4c", "s4d", "s5") else 1)
            out[sec]["label"] = lab
        elif sub and sec in ("s31", "s4a", "s4b"):
            box = {"s31": "sub31", "s4a": "sub4a", "s4b": "sub4b"}[sec]
            out[box][sub.group(1)] = {**_amt(r, 1 if sec == "s31" else -1), "label": lab}
        elif sub and sec == "s4c" and lab.startswith(("1.", "2.")):
            out.setdefault("sub4d", {})[lab[0]] = {**_amt(r, -1), "label": lab}
    return out


def _path(cid):
    return os.path.join(DIR, f"{int(cid)}.json")


def _load(cid):
    try:
        with open(_path(cid)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(cid, month, raw, source):
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        raise ValueError("Which month is this GSTR-3B for?")
    rows = parse(raw)
    with _lock:
        d = _load(cid)
        d[month] = {"rows": rows, "at": time.time(), "source": source}
        os.makedirs(DIR, exist_ok=True)
        with open(_path(cid) + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(_path(cid) + ".tmp", _path(cid))
    return {"ok": True, "month": month, "rows": len(rows)}


def remove(cid, month):
    with _lock:
        d = _load(cid)
        d.pop(month, None)
        os.makedirs(DIR, exist_ok=True)
        with open(_path(cid) + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(_path(cid) + ".tmp", _path(cid))
    return {"ok": True}


def get(cid, month):
    rec = _load(cid).get(month)
    if not rec:
        return None
    return {**interpret(rec["rows"]), "rows": rec["rows"], "at": rec["at"], "source": rec["source"]}
