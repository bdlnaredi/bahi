"""Parse XML exported by TallyPrime's HTTP/XML server into plain Python dicts.

Sign convention used everywhere downstream: amounts are DEBIT-POSITIVE
(Tally itself writes debits as negative numbers, so we flip them here).
"""
import re
import xml.etree.ElementTree as ET

_BAD_REF = re.compile(r"&#(x[0-9a-fA-F]+|\d+);")
_PAIR = re.compile(r"&#(x[0-9a-fA-F]+|\d+);&#(x[0-9a-fA-F]+|\d+);")
_BAD_RAW = re.compile("[\x00-\x08\x0B\x0C\x0E-\x1F\ud800-\udfff\ufffe\uffff]")
_NUM = re.compile(r"-?\d[\d,]*\.?\d*|-?\.\d+")


def _ref_num(s):
    return int(s[1:], 16) if s[0] in "xX" else int(s)


def _join_pair(m):
    """Tally writes emoji as two UTF-16 halves (&#55357;&#56842;); XML needs the single real character."""
    hi, lo = _ref_num(m.group(1)), _ref_num(m.group(2))
    if 0xD800 <= hi <= 0xDBFF and 0xDC00 <= lo <= 0xDFFF:
        return "&#%d;" % (0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00))
    return m.group(0)


def _fix_ref(m):
    n = _ref_num(m.group(1))
    if (n < 32 and n not in (9, 10, 13)) or 0xD800 <= n <= 0xDFFF or n in (0xFFFE, 0xFFFF) or n > 0x10FFFF:
        return ""
    return m.group(0)


def decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif len(raw) > 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        text = raw.decode("utf-16-le", errors="replace")
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    text = _PAIR.sub(_join_pair, text)
    text = _BAD_REF.sub(_fix_ref, text)
    return _BAD_RAW.sub("", text)


_PREFIX_TAG = re.compile(r"<(/?)([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)")
_PREFIX_ATTR = re.compile(r"(\s)([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)(\s*=)")
_TAG = re.compile(r"<[^<>]+>")
_XMLNS = re.compile(r"\sxmlns(:[\w.-]+)?\s*=\s*(\"[^\"]*\"|'[^']*')")


def strip_prefixes(text):
    """Tally add-ons write <UDF:FIELD ...> without always declaring UDF; plain names parse everywhere."""
    def fix_tag(m):
        t = _XMLNS.sub("", m.group(0))
        t = _PREFIX_TAG.sub(r"<\1\2_\3", t)
        return _PREFIX_ATTR.sub(r"\1\2_\3\4", t)
    return _TAG.sub(fix_tag, text)   # only inside tags; text like "Mode:Cash = x" is left alone


def parse_xml(raw: bytes) -> ET.Element:
    text = strip_prefixes(decode(raw))
    # ElementTree refuses an encoding declaration on an already-decoded str
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        # last resort: drop every character reference and stray ampersand, keep the rest of the data
        text = re.sub(r"&#(x[0-9a-fA-F]+|\d+);", "", text)
        text = re.sub(r"&(?!(amp|lt|gt|quot|apos);)", "&amp;", text)
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


def _yn(el, tag):
    v = txt(el, tag).strip().lower()
    return 1 if v == "yes" else 0 if v == "no" else None


def parse_groups(root):
    """Name, parent, and Tally's own nature of the group: revenue (P&L) or not, above the gross profit line,
    and debit nature (assets / expenses)."""
    return [{"name": name_of(el), "parent": clean_parent(txt(el, "PARENT")), "revenue": _yn(el, "ISREVENUE"),
             "gp": _yn(el, "AFFECTSGROSSPROFIT"), "debit": _yn(el, "ISDEEMEDPOSITIVE")}
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


def parse_stock_godowns(root):
    """{item: [(godown, opening qty)]} from stock item masters' opening batch allocations."""
    out = {}
    for el in root.iter("STOCKITEM"):
        n = name_of(el)
        if not n:
            continue
        for b in el.findall("BATCHALLOCATIONS.LIST"):
            g = (b.findtext("GODOWNNAME") or "").strip().lstrip("\x04").strip()
            q = txt(b, "OPENINGBALANCE")
            if g and q:
                out.setdefault(n, []).append((g, num(q)))
    return out


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
    # Invoice line made against a delivery / receipt note: Tally moved the stock on the note already
    tracked = any((t.text or "").strip().lstrip("\x04").strip().lower() not in ("", "not applicable")
                  for t in e.findall("BATCHALLOCATIONS.LIST/TRACKINGNUMBER"))
    # where the stock went: godown and quantity of each batch allocation (same sign as the line)
    sign = 1 if inward else -1
    godowns = []
    for b in e.findall("BATCHALLOCATIONS.LIST"):
        g = (b.findtext("GODOWNNAME") or "").strip().lstrip("\x04").strip()
        bq = txt(b, "ACTUALQTY") or txt(b, "BILLEDQTY")
        if g:
            godowns.append((g, sign * abs(num(bq)) if bq else None))
    if godowns and any(q is None for _, q in godowns):
        godowns = [(g, sign * qty / len(godowns)) for g, _ in godowns] if len(godowns) > 1 else [(godowns[0][0], sign * qty)]
    return {
        "tracked": tracked,
        "godowns": godowns,
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
        if yes(v, "ISDELETED"):
            continue
        status = "cancelled" if yes(v, "ISCANCELLED") else "optional" if yes(v, "ISOPTIONAL") else ""
        date = tdate(txt(v, "DATE"))
        if not date:
            continue
        all_le = v.findall("ALLLEDGERENTRIES.LIST")
        le = v.findall("LEDGERENTRIES.LIST")
        # Tally can send the same stock lines twice, as ALLINVENTORYENTRIES and INVENTORYENTRIES (the voucher
        # collection does): use one of them, never both
        inv_lists = v.findall("ALLINVENTORYENTRIES.LIST") or v.findall("INVENTORYENTRIES.LIST")
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
        # stock inside ledger lines (accounting-mode invoices), only when the voucher has no stock lines of its
        # own, and again from one of the two lists: Tally repeats the same stock under several names
        if not items:
            in_all = [ia for e in all_le for ia in e.findall("INVENTORYALLOCATIONS.LIST")]
            for ia in in_all or [ia for e in le for ia in e.findall("INVENTORYALLOCATIONS.LIST")]:
                r = _inv_row(ia)
                if r:
                    items.append(r)
        # stock journals and manufacturing: items consumed and produced
        if not items:
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
            "status": status,
            "alterid": int(num(txt(v, "ALTERID"))),
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
    }
    x.update(einvoice_fields(v))
    return {k: val for k, val in x.items() if val}


# e-invoice (IRN) and e-way bill details. TallyPrime releases name these slightly differently, so every
# likely tag is tried, anywhere inside the voucher.
EINV_TAGS = {
    "irn": ("IRN", "IRNNUMBER", "IRNNO"),
    "ack_no": ("IRNACKNO", "ACKNO", "IRNACKNUMBER", "ACKNUMBER"),
    "ack_date": ("IRNACKDATE", "ACKDATE", "IRNACKDT"),
    "qr": ("IRNQRCODE", "SIGNEDQRCODE", "IRNSIGNEDQRCODE", "QRCODE", "EINVQRCODE"),
    "ewb_no": ("EWAYBILLNO", "EWAYBILLNUMBER", "EWBNO", "BILLNUMBER"),
    "ewb_date": ("EWAYBILLDATE", "EWBDATE", "BILLDATE"),
    "ewb_generated": ("GENERATEDON", "UPDATEDDATE"),
    "ewb_from_addr": ("CONSIGNORADDRESS",),
    "ewb_to_addr": ("CONSIGNEEADDRESS",),
    "ewb_from_state": ("SHIPPEDFROMSTATE",),
    "ewb_to_state": ("SHIPPEDTOSTATE",),
    "irn_cancelled": ("IRNCANCELLED",),
    "ewb_cancelled": ("ISCANCELLED",),
    "ewb_valid": ("VALIDUPTO", "EWAYBILLVALIDUPTO", "BILLVALIDUPTO", "EWBVALIDUPTO", "VALIDTILL"),
    "ewb_mode": ("TRANSPORTMODE", "MODEOFTRANSPORT", "MODE"),
    "ewb_distance": ("DISTANCE", "APPROXDISTANCE", "TRANSPORTDISTANCE"),
    "ewb_vehicle": ("VEHICLENUMBER", "VEHICLENO"),
    "ewb_vehicle_type": ("VEHICLETYPE",),
    "ewb_transporter": ("TRANSPORTERNAME",),
    "ewb_transporter_id": ("TRANSPORTERID",),
    "ewb_doc_no": ("TRANSPORTDOCNO", "DOCUMENTNUMBER", "TRANSPORTERDOCNO"),
    "ewb_doc_date": ("TRANSPORTDOCDATE", "DOCUMENTDATE", "TRANSPORTERDOCDATE"),
    "ewb_from_place": ("CONSIGNORPLACE", "DISPATCHFROMPLACE", "FROMPLACE"),
    "ewb_to_place": ("CONSIGNEEPLACE", "SHIPTOPLACE", "TOPLACE"),
    "ewb_from_pin": ("CONSIGNORPINCODE", "DISPATCHFROMPINCODE"),
    "ewb_to_pin": ("CONSIGNEEPINCODE", "SHIPTOPINCODE"),
    "ewb_sub_type": ("SUBTYPE", "EWAYBILLSUBTYPE"),
    "ewb_doc_type": ("DOCUMENTTYPE", "EWAYBILLDOCTYPE"),
    "ewb_status": ("EWAYBILLSTATUS", "EWBSTATUS"),
    "irn_status": ("IRNSTATUS",),
}


def _tally_datetime(s):
    """'20261017235900000' (Tally's date-time) -> '17-Oct-26 11:59 PM'."""
    import datetime as _dt
    s = (s or "").strip()
    if re.match(r"^\d{12,17}$", s) and not s.startswith("0000"):
        try:
            t = _dt.datetime.strptime(s[:12], "%Y%m%d%H%M")
            return f"{t.day}-{t.strftime('%b-%y')} {t.strftime('%I:%M %p').lstrip('0')}"
        except ValueError:
            return ""
    if re.match(r"^0+$", s):
        return ""
    return s
EWB_LISTS = ("EWAYBILLDETAILS.LIST", "EWAYBILLDETAIL.LIST", "EWAYBILL.LIST")


def einvoice_fields(v):
    flat = {}
    def walk(el, inside_ewb):
        for ch in el:
            tag = ch.tag.upper()
            ewb = inside_ewb or tag in EWB_LISTS
            if len(ch):
                walk(ch, ewb)
            else:
                t = (ch.text or "").strip()
                if t and not t.startswith("\x04"):
                    # plain BILLNUMBER/BILLDATE/MODE etc. only count inside the e-way bill block
                    flat.setdefault((tag, ewb), t)
    walk(v, False)
    out = {}
    for key, tags in EINV_TAGS.items():
        generic = key.startswith("ewb_") and key not in ("ewb_no", "ewb_valid", "ewb_vehicle", "ewb_transporter", "ewb_transporter_id")
        for t in tags:
            val = flat.get((t, True)) or (None if (generic or t in ("BILLNUMBER", "BILLDATE")) else flat.get((t, False)))
            if val:
                out[key] = val
                break
    for k in ("ack_date", "ewb_date", "ewb_doc_date"):
        if out.get(k):
            out[k] = tdate(out[k].split(" ")[0][:8]) or out[k]
    for k in ("ewb_valid", "ewb_generated"):
        if out.get(k):
            out[k] = _tally_datetime(out[k])
    if out.get("ewb_distance"):
        out["ewb_distance"] = out["ewb_distance"].strip()
    for k in ("irn_cancelled", "ewb_cancelled"):        # keep only a real "Yes"
        if out.get(k, "").lower() != "yes":
            out.pop(k, None)
    out = {k: v for k, v in out.items() if v}
    if out.get("irn") and not re.match(r"^[0-9a-fA-F]{64}$", out["irn"].strip()):
        out.pop("irn")          # not an IRN (64 hex characters)
    return out


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
        # GST rate: the integrated rate in the latest GST details (CGST and SGST are half of it each)
        gst = None
        blocks = el.findall("GSTDETAILS.LIST")
        if blocks:
            b = sorted(blocks, key=lambda x: txt(x, "APPLICABLEFROM"))[-1]
            for r in b.iter("RATEDETAILS.LIST"):
                head = txt(r, "GSTRATEDUTYHEAD").lower()
                if head in ("igst", "integrated tax") and txt(r, "GSTRATE"):
                    gst = num(txt(r, "GSTRATE"))
                    break
        out[n] = {"hsn": hsn or txt(el, "HSNCODE"), "gst": gst}
    return out


def parse_voucher_list(root):
    """Light list (GUID, AlterID, date) of every voucher - used to work out which months changed."""
    out = []
    for v in root.iter("VOUCHER"):
        d = tdate(txt(v, "DATE"))
        if d:
            out.append((txt(v, "GUID") or v.get("REMOTEID") or "", int(num(txt(v, "ALTERID"))), d))
    return out
