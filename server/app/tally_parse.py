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
    hsn = ""
    for tag in ("GSTHSNNAME", "HSNCODE", "GSTHSNCODE"):
        el = e.find(".//" + tag)
        if el is not None and (el.text or "").strip():
            hsn = el.text.strip()
            break
    descr = [d.text.strip() for d in e.findall(".//BASICUSERDESCRIPTION.LIST/BASICUSERDESCRIPTION") if d.text and d.text.strip()]
    rtxt = txt(e, "RATE")
    return {
        "item": item,
        "qty": qty if inward else -qty,
        "unit": unit_of(qtxt) or rtxt.split("/")[-1].strip() if "/" in rtxt else unit_of(qtxt),
        "rate": num(rtxt),
        "amount": abs(amount),
        "hsn": hsn,
        "disc": num(txt(e, "DISCOUNT")),
        "descr": " ".join(descr),
    }


def parse_vouchers(root):
    out = []
    for v in root.iter("VOUCHER"):
        if yes(v, "ISCANCELLED") or yes(v, "ISOPTIONAL") or yes(v, "ISDELETED"):
            continue
        date = tdate(txt(v, "DATE"))
        if not date:
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
            if not lines:
                balanced = True   # stock journals, delivery notes, orders: no account entries at all

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
            "extra": voucher_extra(v),
            "guid": txt(v, "GUID") or v.get("REMOTEID") or "",
            "reference": txt(v, "REFERENCE"),
            "party_gstin": txt(v, "PARTYGSTIN"),
            "bills": bills,
            "date": date,
            "vtype": txt(v, "VOUCHERTYPENAME") or v.get("VCHTYPE") or "",
            "number": txt(v, "VOUCHERNUMBER"),
            "party": txt(v, "PARTYLEDGERNAME"),
            "narration": txt(v, "NARRATION"),
            "amount": round(sum(a for _, a in lines if a > 0), 2),
            "balanced": balanced,
            "imbalance": round(sum(a for _, a in lines), 2),
            "lines": lines,
            "items": items,
        })
    return out


# ---------------------------------------------------------------- details used for printing

def _lines(el, path):
    return [x.text.strip() for x in el.findall(path) if x.text and x.text.strip()]


def _first(el, *tags):
    for t in tags:
        x = el.find(".//" + t) if "/" not in t else el.find(t)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
    return ""


def voucher_extra(v):
    """Invoice header fields Tally keeps on the voucher (buyer, consignee, dispatch, orders)."""
    x = {
        "buyer_name": _first(v, "BASICBUYERNAME"),
        "buyer_address": _lines(v, "BASICBUYERADDRESS.LIST/BASICBUYERADDRESS") or _lines(v, "ADDRESS.LIST/ADDRESS"),
        "buyer_state": txt(v, "STATENAME"),
        "buyer_gstin": txt(v, "PARTYGSTIN"),
        "buyer_pincode": txt(v, "PARTYPINCODE"),
        "consignee_name": txt(v, "CONSIGNEEMAILINGNAME"),
        "consignee_address": _lines(v, "CONSIGNEEADDRESS.LIST/CONSIGNEEADDRESS"),
        "consignee_state": txt(v, "CONSIGNEESTATENAME"),
        "consignee_gstin": txt(v, "CONSIGNEEGSTIN"),
        "place_of_supply": txt(v, "PLACEOFSUPPLY"),
        "delivery_note": txt(v, "BASICSHIPDELIVERYNOTE") or _first(v, "INVOICEDELNOTES.LIST/BASICSHIPDELIVERYNOTE"),
        "delivery_note_date": tdate(_first(v, "INVOICEDELNOTES.LIST/BASICSHIPPINGDATE")),
        "terms_payment": txt(v, "BASICDUEDATEOFPYMT"),
        "reference_date": tdate(txt(v, "REFERENCEDATE")),
        "other_refs": txt(v, "BASICORDERREF"),
        "order_no": _first(v, "INVOICEORDERLIST.LIST/BASICPURCHASEORDERNO") or txt(v, "BASICPURCHASEORDERNO"),
        "order_date": tdate(_first(v, "INVOICEORDERLIST.LIST/BASICORDERDATE")),
        "dispatch_doc": txt(v, "BASICSHIPDOCUMENTNO"),
        "dispatched_through": txt(v, "BASICSHIPPEDBY"),
        "destination": txt(v, "BASICFINALDESTINATION"),
        "terms_delivery": " ".join(_lines(v, "BASICORDERTERMS.LIST/BASICORDERTERMS")),
        "vehicle_no": txt(v, "BASICSHIPVESSELNO"),
        "irn": txt(v, "IRN") or txt(v, "IRNACKNO"),
    }
    return {k: val for k, val in x.items() if val}


def _mailing(el):
    """Address/state/pincode from a ledger or company: TallyPrime 3+ keeps them in a
    dated *MAILINGDETAILS.LIST; older releases on the object itself. Latest dated entry wins."""
    blocks = el.findall("LEDMAILINGDETAILS.LIST") + el.findall("COMPANYMAILINGDETAILS.LIST")
    if blocks:
        b = sorted(blocks, key=lambda x: txt(x, "APPLICABLEFROM"))[-1]
        return {"address": _lines(b, "ADDRESS.LIST/ADDRESS"), "state": txt(b, "STATE"),
                "pincode": txt(b, "PINCODE"), "country": txt(b, "COUNTRY"), "mailing_name": txt(b, "MAILINGNAME")}
    return {"address": _lines(el, "ADDRESS.LIST/ADDRESS"),
            "state": txt(el, "LEDSTATENAME") or txt(el, "STATENAME"),
            "pincode": txt(el, "PINCODE"), "country": txt(el, "COUNTRYNAME"),
            "mailing_name": _first(el, "MAILINGNAME.LIST/MAILINGNAME")}


def parse_company_info(root):
    """{company name: details} for every company in the response."""
    out = {}
    for el in root.iter("COMPANY"):
        info = _mailing(el)
        gst = txt(el, "GSTREGISTRATIONNUMBER") or _first(el, "GSTIN", "GSTREGNUMBER")
        info.update({
            "name": name_of(el), "gstin": gst, "pan": txt(el, "INCOMETAXNUMBER"),
            "email": txt(el, "EMAIL"), "phone": txt(el, "PHONENUMBER") or txt(el, "MOBILENUMBERS"),
            "website": txt(el, "WEBSITE"),
        })
        if not info["state"]:
            info["state"] = _first(el, "GSTREGISTRATIONDETAILS.LIST/STATE", "STATENAME")
        if info["name"]:
            out[info["name"]] = {k: v for k, v in info.items() if v}
    return out


def parse_ledger_extra(root):
    out = {}
    for el in root.iter("LEDGER"):
        n = name_of(el)
        if not n:
            continue
        info = _mailing(el)
        info.update({
            "pan": txt(el, "INCOMETAXNUMBER"),
            "gstin": txt(el, "PARTYGSTIN") or _first(el, "LEDGSTREGDETAILS.LIST/GSTIN"),
            "bank_account": txt(el, "BANKDETAILS") or txt(el, "BANKACCOUNTNUMBER"),
            "ifsc": txt(el, "IFSCODE"), "branch": txt(el, "BANKBRANCHNAME"),
            "holder": txt(el, "BANKACCHOLDERNAME"),
        })
        out[n] = {k: v for k, v in info.items() if v}
    return out


def parse_stock_extra(root):
    out = {}
    for el in root.iter("STOCKITEM"):
        n = name_of(el)
        if not n:
            continue
        hsn = ""
        for path in ("HSNDETAILS.LIST", "GSTDETAILS.LIST"):
            blocks = el.findall(path)
            if blocks:
                b = sorted(blocks, key=lambda x: txt(x, "APPLICABLEFROM"))[-1]
                hsn = txt(b, "HSNCODE") or txt(b, "HSN")
                if hsn:
                    break
        out[n] = {"hsn": hsn or txt(el, "HSNCODE")}
    return out
