"""Parse XML exported by TallyPrime's HTTP/XML server into plain Python dicts.

Sign convention used everywhere downstream: amounts are DEBIT-POSITIVE
(Tally itself writes debits as negative numbers, so we flip them here).
"""
import re
import xml.etree.ElementTree as ET

_BAD_REF = re.compile(r"&#(x[0-9a-fA-F]+|\d+);")
_BAD_RAW = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_NUM = re.compile(r"-?\d[\d,]*\.?\d*|-?\.\d+")


def _fix_ref(m):
    s = m.group(1)
    n = int(s[1:], 16) if s[0] in "xX" else int(s)
    if n < 32 and n not in (9, 10, 13):
        return ""
    return m.group(0)


def decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif len(raw) > 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        text = raw.decode("utf-16-le")
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    text = _BAD_REF.sub(_fix_ref, text)
    return _BAD_RAW.sub("", text)


def parse_xml(raw: bytes) -> ET.Element:
    text = decode(raw)
    # ElementTree refuses an encoding declaration on an already-decoded str
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    return ET.fromstring(text)


def num(text) -> float:
    if not text:
        return 0.0
    m = _NUM.search(text.replace(" ", ""))
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return 0.0


def unit_of(text) -> str:
    if not text:
        return ""
    t = text.strip()
    m = _NUM.search(t)
    if not m:
        return ""
    rest = t[m.end():].strip()
    return rest.split("/")[0].strip()


def txt(el, tag) -> str:
    c = el.find(tag)
    return (c.text or "").strip() if c is not None and c.text else ""


def name_of(el) -> str:
    n = (el.get("NAME") or "").strip()
    if not n:
        n = txt(el, "NAME")
    if not n:
        nl = el.find(".//NAME.LIST/NAME")
        if nl is not None and nl.text:
            n = nl.text.strip()
    return n


def clean_parent(p: str) -> str:
    p = (p or "").strip()
    return "" if p.lower() == "primary" else p


def yes(el, tag) -> bool:
    return txt(el, tag).lower() == "yes"


# ---------------------------------------------------------------- masters

def parse_companies(root):
    out = []
    for el in root.iter("COMPANY"):
        n = name_of(el)
        if n:
            out.append({"name": n, "alt_vch": txt(el, "ALTVCHID"), "alt_mst": txt(el, "ALTMSTID")})
    return out


def parse_groups(root):
    return [{"name": name_of(el), "parent": clean_parent(txt(el, "PARENT"))}
            for el in root.iter("GROUP") if name_of(el)]


def parse_vtypes(root):
    return [{"name": name_of(el), "parent": clean_parent(txt(el, "PARENT"))}
            for el in root.iter("VOUCHERTYPE") if name_of(el)]


def parse_ledgers(root):
    out = []
    for el in root.iter("LEDGER"):
        n = name_of(el)
        if not n:
            continue
        gstin = txt(el, "PARTYGSTIN")
        if not gstin:
            g = el.find(".//LEDGSTREGDETAILS.LIST/GSTIN")
            gstin = (g.text or "").strip() if g is not None and g.text else ""
        out.append({
            "name": n,
            "parent": clean_parent(txt(el, "PARENT")),
            "opening": -num(txt(el, "OPENINGBALANCE")),
            "closing": -num(txt(el, "CLOSINGBALANCE")),
            "phone": txt(el, "LEDGERPHONE"),
            "mobile": txt(el, "LEDGERMOBILE"),
            "email": txt(el, "EMAIL"),
            "gstin": gstin,
            "taxtype": txt(el, "TAXTYPE"),
            "gst_head": txt(el, "GSTDUTYHEAD"),
        })
    return out


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def tdate(s):
    """Tally dates come as 20260401, 1-Apr-2026 or 1-Apr-26. Returns ISO or ''."""
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.fullmatch(r"(\d{1,2})[-/ ]([A-Za-z]{3})[A-Za-z]*[-/ ](\d{2,4})", s)
    if m and m.group(2).lower() in MONTHS:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return f"{y:04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def parse_bill_report(root):
    """Bills Receivable / Bills Payable report: BILLFIXED (date, ref, party) followed
    by sibling BILLCL / BILLDUE / BILLOVERDUE elements. Returns positive amounts.
    Returns None when the response holds no bill structure at all (report unsupported)."""
    out, cur, seen = [], None, False
    for el in root.iter():
        tag = el.tag
        if tag == "BILLFIXED":
            seen = True
            cur = {"date": tdate(txt(el, "BILLDATE")), "ref": txt(el, "BILLREF"),
                   "party": txt(el, "BILLPARTY"), "amount": 0.0, "due": ""}
            out.append(cur)
        elif cur is not None and tag == "BILLCL":
            cur["amount"] = abs(num(el.text))
        elif cur is not None and tag == "BILLDUE":
            cur["due"] = tdate(el.text)
    if not seen:
        return None
    return [b for b in out if b["party"] and b["amount"] > 0.005]


def parse_stock(root):
    out = []
    for el in root.iter("STOCKITEM"):
        n = name_of(el)
        if not n:
            continue
        cb = txt(el, "CLOSINGBALANCE")
        ob = txt(el, "OPENINGBALANCE")
        out.append({
            "name": n,
            "parent": clean_parent(txt(el, "PARENT")),
            "unit": txt(el, "BASEUNITS") or unit_of(cb) or unit_of(ob),
            "opening_qty": num(ob),
            "opening_value": abs(num(txt(el, "OPENINGVALUE"))),
            "closing_qty": num(cb),
            "closing_value": abs(num(txt(el, "CLOSINGVALUE"))),
            "closing_rate": num(txt(el, "CLOSINGRATE")),
        })
    return out


# ---------------------------------------------------------------- vouchers

def _ledger_rows(entries):
    rows = []
    for e in entries:
        ln = txt(e, "LEDGERNAME")
        if ln:
            rows.append((ln, -num(txt(e, "AMOUNT"))))
    return rows


def _inv_row(e, force_dir=None):
    item = txt(e, "STOCKITEMNAME")
    if not item:
        return None
    qtxt = txt(e, "ACTUALQTY") or txt(e, "BILLEDQTY")
    qty = abs(num(qtxt))
    amount = num(txt(e, "AMOUNT"))
    if force_dir is not None:
        inward = force_dir
    elif txt(e, "ISDEEMEDPOSITIVE"):
        inward = yes(e, "ISDEEMEDPOSITIVE")
    else:
        inward = amount < 0
    return {
        "item": item,
        "qty": qty if inward else -qty,
        "unit": unit_of(qtxt),
        "rate": num(txt(e, "RATE")),
        "amount": abs(amount),
    }


def parse_vouchers(root):
    out = []
    for v in root.iter("VOUCHER"):
        if yes(v, "ISCANCELLED") or yes(v, "ISOPTIONAL") or yes(v, "ISDELETED"):
            continue
        date = txt(v, "DATE")
        if len(date) != 8:
            continue
        all_le = v.findall("ALLLEDGERENTRIES.LIST")
        le = v.findall("LEDGERENTRIES.LIST")
        inv_lists = v.findall("ALLINVENTORYENTRIES.LIST") + v.findall("INVENTORYENTRIES.LIST")
        alloc = []
        for ie in inv_lists:
            alloc += ie.findall("ACCOUNTINGALLOCATIONS.LIST")

        r_all, r_le, r_alloc = _ledger_rows(all_le), _ledger_rows(le), _ledger_rows(alloc)
        candidates = [r_all + r_alloc, r_le + r_alloc, r_all, r_le, r_all + r_le + r_alloc]
        lines, balanced = None, False
        for c in candidates:
            if c and abs(sum(a for _, a in c)) < 0.5:
                lines, balanced = c, True
                break
        if lines is None:
            lines = r_all + r_le + r_alloc

        items = []
        for ie in inv_lists:
            r = _inv_row(ie)
            if r:
                items.append(r)
        for e in all_le + le:
            for ia in e.findall("INVENTORYALLOCATIONS.LIST"):
                r = _inv_row(ia)
                if r:
                    items.append(r)
        for ie in v.findall("INVENTORYENTRIESIN.LIST"):
            r = _inv_row(ie, True)
            if r:
                items.append(r)
        for ie in v.findall("INVENTORYENTRIESOUT.LIST"):
            r = _inv_row(ie, False)
            if r:
                items.append(r)

        bills = []
        for e in all_le + le:
            ln = txt(e, "LEDGERNAME")
            for b in e.findall("BILLALLOCATIONS.LIST"):
                bname = txt(b, "NAME")
                btype = txt(b, "BILLTYPE")
                if not (bname or btype):
                    continue
                bills.append({"ledger": ln, "name": bname, "type": btype or "New Ref",
                              "amount": -num(txt(b, "AMOUNT")),
                              "days": int(num(txt(b, "BILLCREDITPERIOD")))})

        out.append({
            "guid": txt(v, "GUID") or v.get("REMOTEID") or "",
            "reference": txt(v, "REFERENCE"),
            "party_gstin": txt(v, "PARTYGSTIN"),
            "bills": bills,
            "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
            "vtype": txt(v, "VOUCHERTYPENAME") or v.get("VCHTYPE") or "",
            "number": txt(v, "VOUCHERNUMBER"),
            "party": txt(v, "PARTYLEDGERNAME"),
            "narration": txt(v, "NARRATION"),
            "amount": round(sum(a for _, a in lines if a > 0), 2),
            "balanced": balanced,
            "lines": lines,
            "items": items,
        })
    return out
