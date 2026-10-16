"""A fake TallyPrime XML server for testing the agent and server end to end."""
import random
import re
import sys
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from xml.sax.saxutils import escape

COMPANY = "Demo Traders 2026-27"
random.seed(7)

GROUPS = [  # name, parent
    ("Capital Account", ""), ("Current Assets", ""), ("Current Liabilities", ""), ("Fixed Assets", ""),
    ("Loans (Liability)", ""), ("Sales Accounts", ""), ("Purchase Accounts", ""), ("Direct Expenses", ""),
    ("Direct Incomes", ""), ("Indirect Expenses", ""), ("Indirect Incomes", ""), ("Suspense A/c", ""),
    ("Bank Accounts", "Current Assets"), ("Cash-in-Hand", "Current Assets"), ("Sundry Debtors", "Current Assets"),
    ("Stock-in-Hand", "Current Assets"), ("Sundry Creditors", "Current Liabilities"),
    ("Duties & Taxes", "Current Liabilities"), ("Bank OD A/c", "Loans (Liability)"),
    ("Mumbai Debtors", "Sundry Debtors"), ("Commission Earned", ""),
]
VTYPES = [("Sales", ""), ("Purchase", ""), ("Receipt", ""), ("Payment", ""), ("Journal", ""), ("Contra", ""),
          ("Credit Note", ""), ("Debit Note", ""), ("GST Sales", "Sales"),
          ("Stock Journal", ""), ("Sales Order", ""), ("Memorandum", ""), ("Delivery Note", "")]

DEBTORS = [("Sharma & Sons", "Sundry Debtors", 45000), ("Gupta Hardware", "Sundry Debtors", 0),
           ("Patel Enterprises", "Mumbai Debtors", 120000), ("Shree Ganesh Traders", "Sundry Debtors", 0),
           ("Krishna Agencies", "Mumbai Debtors", 18000), ("Verma Electricals", "Sundry Debtors", 0)]
CREDITORS = [("Asian Paints Distributor", 80000), ("Supreme Pipes Ltd", 0), ("Jindal Steel Depot", 25000)]
LEDGERS = {  # name: (parent, opening dr-positive)
    "Cash": ("Cash-in-Hand", 50000), "HDFC Bank": ("Bank Accounts", 300000), "SBI OD": ("Bank OD A/c", -150000),
    "Sales GST 18%": ("Sales Accounts", 0), "Purchase GST 18%": ("Purchase Accounts", 0),
    "Output CGST": ("Duties & Taxes", 0), "Output SGST": ("Duties & Taxes", 0),
    "Input CGST": ("Duties & Taxes", 0), "Input SGST": ("Duties & Taxes", 0),
    "Rent": ("Indirect Expenses", 0), "Salary": ("Indirect Expenses", 0), "Freight Inward": ("Direct Expenses", 0),
    "Discount Received": ("Indirect Incomes", 0), "Capital": ("Capital Account", 0),
    "Commission Received": ("Commission Earned", 0),
}
for n, g, o in DEBTORS:
    LEDGERS[n] = (g, o)
for n, o in CREDITORS:
    LEDGERS[n] = ("Sundry Creditors", -o)
# balance the opening trial balance through Capital
LEDGERS["Capital"] = ("Capital Account", -sum(o for _, o in LEDGERS.values()) - 0)
STOCK = [("PVC Pipe 1 inch", "Pipes", "Nos", 400, 120.0), ("PVC Pipe 2 inch", "Pipes", "Nos", 250, 210.0),
         ("Wall Paint 20L", "Paints", "Nos", 60, 3200.0), ("Primer 4L", "Paints", "Nos", 90, 650.0),
         ("TMT Bar 12mm", "Steel", "Kg", 1500, 62.0)]
# stock opening value is part of capital too (closing stock asset) - ignore for ledger TB in this mock
ADDR = {"Sharma & Sons": ["12, Station Road", "Nagpur 440001"], "Patel Enterprises": ["Unit 4, Andheri Industrial Estate", "Andheri East, Mumbai 400069"],
        "Gupta Hardware": ["Main Bazaar", "Wardha 442001"], "Krishna Agencies": ["Shop 7, Crawford Market", "Mumbai 400001"]}
HSN = {"PVC Pipe 1 inch": "39172390", "PVC Pipe 2 inch": "39172390", "Wall Paint 20L": "32091090", "Primer 4L": "32089090", "TMT Bar 12mm": "72142090"}
PHONES = {"Sharma & Sons": "9876543210", "Patel Enterprises": "9123456780", "Krishna Agencies": "9988776655"}

START, END = date(2026, 4, 1), date(2026, 10, 15)


def make_vouchers():
    vs, n_sales, n_pur, n_rec, n_pay = [], 0, 0, 0, 0
    d = START
    while d <= END:
        for _ in range(random.randint(0, 3)):
            party = random.choice(DEBTORS)[0]
            items = random.sample(STOCK, random.randint(1, 2))
            lines_items, taxable = [], 0.0
            for it in items:
                q = random.randint(2, 20) if it[2] == "Nos" else random.randint(50, 300)
                rate = round(it[4] * 1.25, 2)
                amt = round(q * rate, 2)
                taxable += amt
                lines_items.append((it[0], q, it[2], rate, amt))
            tax = round(taxable * 0.09, 2)
            n_sales += 1
            vs.append({"kind": "sales", "date": d, "type": random.choice(["Sales", "GST Sales"]),
                       "no": f"S/{n_sales}", "party": party, "items": lines_items,
                       "ledgers": [(party, taxable + 2 * tax), ("Output CGST", -tax), ("Output SGST", -tax)],
                       "sales_ledger": "Sales GST 18%", "taxable": taxable})
        if random.random() < 0.25:
            party = random.choice(CREDITORS)[0]
            it = random.choice(STOCK)
            q = random.randint(20, 100) if it[2] == "Nos" else random.randint(300, 900)
            amt = round(q * it[4], 2)
            tax = round(amt * 0.09, 2)
            n_pur += 1
            vs.append({"kind": "purchase", "date": d, "type": "Purchase", "no": f"P/{n_pur}", "party": party,
                       "items": [(it[0], q, it[2], it[4], amt)],
                       "ledgers": [(party, -(amt + 2 * tax)), ("Input CGST", tax), ("Input SGST", tax)],
                       "sales_ledger": "Purchase GST 18%", "taxable": amt})
        if random.random() < 0.3:
            party = random.choice(DEBTORS)[0]
            amt = float(random.randint(5, 60) * 1000)
            n_rec += 1
            vs.append({"kind": "acct", "date": d, "type": "Receipt", "no": str(n_rec), "party": party,
                       "ledgers": [(random.choice(["HDFC Bank", "Cash"]), amt), (party, -amt)],
                       "narration": f"Received from {party}\r\nvia NEFT"})
        if d.day == 5:
            n_pay += 2
            vs.append({"kind": "acct", "date": d, "type": "Payment", "no": str(n_pay - 1), "party": "Rent",
                       "ledgers": [("Rent", 35000.0), ("HDFC Bank", -35000.0)], "narration": "Shop rent"})
            vs.append({"kind": "acct", "date": d, "type": "Payment", "no": str(n_pay), "party": "Salary",
                       "ledgers": [("Salary", 60000.0), ("HDFC Bank", -60000.0)], "narration": "Staff salary"})
        if d.day == 12:
            vs.append({"kind": "acct", "date": d, "type": "Payment", "no": f"E{d.month}", "party": "Freight Inward",
                       "ledgers": [("Freight Inward", 1000.0), ("Input CGST", 90.0), ("Input SGST", 90.0), ("Cash", -1180.0)],
                       "narration": "Freight with GST"})
        if d.day == 20 and d.month > 4:
            vs.append({"kind": "acct", "date": d, "type": "Payment", "no": f"T{d.month}", "party": "Output CGST",
                       "ledgers": [("Output CGST", 5000.0), ("HDFC Bank", -5000.0)], "narration": "GST challan"})
        if d.day == 28:
            vs.append({"kind": "acct", "date": d, "type": "Journal", "no": f"J{d.month}", "party": "Output SGST",
                       "ledgers": [("Output SGST", 500.0), ("Input SGST", -500.0)], "narration": "GST set-off"})
        if d.day == 20:
            party = random.choice(CREDITORS)[0]
            n_pay += 1
            vs.append({"kind": "acct", "date": d, "type": "Payment", "no": str(n_pay), "party": party,
                       "ledgers": [(party, 40000.0), ("HDFC Bank", -40000.0)], "narration": ""})
        d += timedelta(days=1)
    # one cancelled and one optional voucher that must be ignored
    vs.append({"kind": "acct", "date": date(2026, 6, 10), "type": "Payment", "no": "X1", "party": "Rent",
               "ledgers": [("Rent", 99999.0), ("Cash", -99999.0)], "cancelled": True})
    vs.append({"kind": "acct", "date": date(2026, 6, 11), "type": "Journal", "no": "X2", "party": "Rent",
               "ledgers": [("Rent", 77777.0), ("Cash", -77777.0)], "optional": True})
    # vouchers outside the books: stock journal, sales order, memorandum; and one broken journal
    vs.append({"kind": "sj", "date": date(2026, 7, 3), "type": "Stock Journal", "no": "SJ1", "party": "",
               "out": [("PVC Pipe 2 inch", 5, "Nos", 210.0, 1050.0)], "in": [("PVC Pipe 1 inch", 8, "Nos", 131.25, 1050.0)], "ledgers": []})
    # a godown transfer: 40 Primer out of the shop, into the back store
    vs.append({"kind": "sj", "date": date(2026, 9, 3), "type": "Stock Journal", "no": "SJ2", "party": "",
               "out": [("Primer 4L", 40, "Nos", 650.0, 26000.0)], "in": [("Primer 4L", 40, "Nos", 650.0, 26000.0)], "ledgers": []})
    # goods sent on a delivery note on 4 Sep, billed on 6 Sep against that note (stock moves once, on the note)
    vs.append({"kind": "dn", "date": date(2026, 9, 4), "type": "Delivery Note", "no": "DN1", "party": "Sharma & Sons",
               "out": [("TMT Bar 12mm", 100, "Kg", 77.5, 7750.0)], "in": [], "ledgers": []})
    vs.append({"kind": "sales", "date": date(2026, 9, 6), "type": "Sales", "no": "S/9001", "party": "Sharma & Sons",
               "items": [("TMT Bar 12mm", 100, "Kg", 77.5, 7750.0)], "tracked": "DN1",
               "ledgers": [("Sharma & Sons", 7750.0 + 2 * 697.5), ("Output CGST", -697.5), ("Output SGST", -697.5)],
               "sales_ledger": "Sales GST 18%", "taxable": 7750.0})
    vs.append({"kind": "order", "date": date(2026, 8, 9), "type": "Sales Order", "no": "SO1", "party": "Gupta Hardware",
               "items": [("Primer 4L", 30, "Nos", 800.0, 24000.0)], "ledgers": [], "nonposting": True})
    vs.append({"kind": "acct", "date": date(2026, 8, 10), "type": "Memorandum", "no": "M1", "party": "Rent",
               "ledgers": [("Rent", 5555.0), ("Cash", -5555.0)], "nonposting": True})
    vs.append({"kind": "acct", "date": date(2026, 8, 16), "type": "Receipt", "no": "C1", "party": "Commission Received",
               "ledgers": [("Cash", 2500.0), ("Commission Received", -2500.0)], "narration": "Commission"})
    vs.append({"kind": "acct", "date": date(2026, 9, 2), "type": "Journal", "no": "BAD1", "party": "Rent",
               "ledgers": [("Rent", 1000.0), ("Cash", -900.0)], "narration": "deliberately broken"})
    for i, v in enumerate(vs):
        v["guid"] = f"guid-{i:05d}"
        v["alterid"] = i + 1
    assign_bills(vs)
    return vs


OPEN_BILLS = {}


def assign_bills(vs):
    """Give vouchers Tally-style bill allocations, settling bills first-in first-out."""
    open_ = {}
    for n, g, o in DEBTORS:
        if o:
            open_[n] = [["OB/" + n[:3].upper(), date(2026, 3, 15), float(o), 30]]
    for n, o in CREDITORS:
        if o:
            open_[n] = [["SUP-OB/" + n[:3].upper(), date(2026, 2, 10), float(o), 45]]
    debtors = {n for n, _, _ in DEBTORS}
    creditors = {n for n, _ in CREDITORS}
    for v in vs:
        if v.get("cancelled") or v.get("optional"):
            continue
        p = v["party"]
        amt = dict(v["ledgers"]).get(p)
        if amt is None or (p not in debtors and p not in creditors):
            continue
        if v["kind"] in ("sales", "purchase"):
            ref = v["no"] if v["kind"] == "sales" else "INV-" + v["no"]
            days = 30 if v["kind"] == "sales" else 45
            open_.setdefault(p, []).append([ref, v["date"], abs(amt), days])
            v["billalloc"] = [(ref, "New Ref", amt, days)]
        else:
            left, allocs = abs(amt), []
            for b in open_.get(p, []):
                if left <= 0.005:
                    break
                take = min(b[2], left)
                if take > 0.005:
                    b[2] -= take
                    left -= take
                    allocs.append((b[0], "Agst Ref", take * (1 if amt > 0 else -1), 0))
            if left > 0.005:
                allocs.append(("", "On Account", left * (1 if amt > 0 else -1), 0))
            v["billalloc"] = allocs
    OPEN_BILLS.clear()
    for p, bl in open_.items():
        OPEN_BILLS[p] = [b for b in bl if b[2] > 0.005]


VOUCHERS = make_vouchers()


def ledger_lines(v):
    """All ledger effects (dr-positive), including the sales/purchase ledger inside inventory."""
    out = list(v["ledgers"])
    if v["kind"] == "sales":
        out.append((v["sales_ledger"], -v["taxable"]))
    elif v["kind"] == "purchase":
        out.append((v["sales_ledger"], v["taxable"]))
    return out


def live(v):
    return not v.get("cancelled") and not v.get("optional") and not v.get("nonposting")


def closing_balances(to):
    bal = {n: o for n, (_, o) in LEDGERS.items()}
    for v in VOUCHERS:
        if live(v) and v["date"] <= to:
            for ln, a in ledger_lines(v):
                bal[ln] = bal.get(ln, 0) + a
    return bal


def stock_closing(to):
    out = {}
    for name, grp, unit, oq, rate in STOCK:
        q, val = oq, oq * rate
        for v in VOUCHERS:
            if live(v) and v["date"] <= to and v["kind"] == "dn":
                for it in v["out"]:
                    if it[0] == name:
                        q -= it[1]
                        val -= it[1] * rate
            if live(v) and v["date"] <= to and v["kind"] in ("sales", "purchase") and not v.get("tracked"):
                for it in v["items"]:
                    if it[0] == name:
                        if v["kind"] == "purchase":
                            q += it[1]
                            val += it[4]
                        else:
                            q -= it[1]
                            val -= it[1] * rate
        out[name] = (q, round(max(val, 0), 2), round(val / q, 2) if q else 0)
    return out


def amt(x):  # Tally writes debits negative
    return f"{-x:.2f}"


def xml_voucher(v):
    dt = v["date"].strftime("%Y%m%d")
    flags = ("<ISCANCELLED>Yes</ISCANCELLED>" if v.get("cancelled") else "<ISCANCELLED>No</ISCANCELLED>") + \
            ("<ISOPTIONAL>Yes</ISOPTIONAL>" if v.get("optional") else "")
    nar = escape(v.get("narration", "")).replace("\r\n", "&#13;&#10;")
    if v["kind"] == "sales" and v["date"] >= date(2026, 4, 1) and int(v["no"].split("/")[-1]) % 7 == 0:
        nar += " Thank you &#55357;&#56842; &#xD83D;&#xDE4F; &#65535;"   # emoji as Tally writes them (surrogate pairs)
    head = (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER REMOTEID="{v["guid"]}" VCHTYPE="{escape(v["type"])}" '
            f'ACTION="Create" OBJVIEW="{"Invoice Voucher View" if v["kind"] != "acct" else "Accounting Voucher View"}">'
            f'<DATE>{dt}</DATE><GUID>{v["guid"]}</GUID><ALTERID> {v["alterid"]}</ALTERID><NARRATION>{nar}</NARRATION>'
            f'<VOUCHERTYPENAME>{escape(v["type"])}</VOUCHERTYPENAME><VOUCHERNUMBER>{v["no"]}</VOUCHERNUMBER>'
            f'<PARTYLEDGERNAME>{escape(v["party"])}</PARTYLEDGERNAME>{flags}'
            f'<REFERENCE>{"PO-" + v["no"] if v["kind"] == "sales" else ""}</REFERENCE>'
            f'<PARTYGSTIN>{"27ABCDE1234F1Z5" if v["party"] == "Patel Enterprises" else ""}</PARTYGSTIN>'
            + (f'<BASICBUYERNAME>{escape(v["party"])}</BASICBUYERNAME><STATENAME>Maharashtra</STATENAME><PLACEOFSUPPLY>Maharashtra</PLACEOFSUPPLY>'
               f'<BASICBUYERADDRESS.LIST>{"".join(f"<BASICBUYERADDRESS>{escape(a)}</BASICBUYERADDRESS>" for a in ADDR.get(v["party"], []))}</BASICBUYERADDRESS.LIST>'
               f'<BASICDUEDATEOFPYMT>30 Days</BASICDUEDATEOFPYMT><BASICSHIPDOCUMENTNO>LR-{v["no"][2:]}</BASICSHIPDOCUMENTNO>'
               f'<BASICSHIPPEDBY>VRL Logistics</BASICSHIPPEDBY><BASICFINALDESTINATION>{escape((ADDR.get(v["party"]) or ["Nagpur"])[-1].split(" ")[0])}</BASICFINALDESTINATION>'
               if v["kind"] == "sales" else ""))
    body = ""
    def ba(ln):
        if ln != v["party"]:
            return ""
        return "".join(f"<BILLALLOCATIONS.LIST><NAME>{escape(r)}</NAME><BILLTYPE>{t}</BILLTYPE>"
                       f"{f'<BILLCREDITPERIOD JD=\"0\" P=\"{dd} Days\">{dd} Days</BILLCREDITPERIOD>' if dd else ''}"
                       f"<AMOUNT>{amt(a)}</AMOUNT></BILLALLOCATIONS.LIST>" for r, t, a, dd in v.get("billalloc", []))
    if v["kind"] in ("sj", "dn"):
        for tag, rows, sign in (("INVENTORYENTRIESOUT.LIST", v["out"], -1), ("INVENTORYENTRIESIN.LIST", v["in"], 1)):
            for name, q, unit, rate, a in rows:
                body += (f"<{tag}><STOCKITEMNAME>{escape(name)}</STOCKITEMNAME><RATE>{rate:.2f}/{unit}</RATE>"
                         f"<AMOUNT>{amt(sign * a)}</AMOUNT><ACTUALQTY> {q} {unit}</ACTUALQTY></{tag}>")
    elif v["kind"] == "order":
        for name, q, unit, rate, a in v["items"]:
            body += (f"<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{escape(name)}</STOCKITEMNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>"
                     f"<RATE>{rate:.2f}/{unit}</RATE><AMOUNT>{a:.2f}</AMOUNT><ACTUALQTY> {q} {unit}</ACTUALQTY></ALLINVENTORYENTRIES.LIST>")
    elif v["kind"] == "acct":
        for ln, a in v["ledgers"]:
            body += (f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(ln)}</LEDGERNAME>"
                     f"<ISDEEMEDPOSITIVE>{'Yes' if a > 0 else 'No'}</ISDEEMEDPOSITIVE>"
                     f"<AMOUNT>{amt(a)}</AMOUNT>{ba(ln)}</ALLLEDGERENTRIES.LIST>")
    else:
        inward = v["kind"] == "purchase"
        for name, q, unit, rate, a in v["items"]:
            sign = 1 if inward else -1
            body += (f"<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{escape(name)}</STOCKITEMNAME>"
                     f"<ISDEEMEDPOSITIVE>{'Yes' if inward else 'No'}</ISDEEMEDPOSITIVE>"
                     f"<RATE>{rate:.2f}/{unit}</RATE><AMOUNT>{amt(sign * a)}</AMOUNT>"
                     f"<ACTUALQTY> {q} {unit}</ACTUALQTY><BILLEDQTY> {q} {unit}</BILLEDQTY>"
                     + f"<BATCHALLOCATIONS.LIST><GODOWNNAME>Main Location</GODOWNNAME><TRACKINGNUMBER>{v.get('tracked') or '&#4; Not Applicable'}</TRACKINGNUMBER></BATCHALLOCATIONS.LIST>"
                     + ("<BASICUSERDESCRIPTION.LIST><BASICUSERDESCRIPTION>Asian Paints Apex, colour: Ivory</BASICUSERDESCRIPTION></BASICUSERDESCRIPTION.LIST>" if name == "Wall Paint 20L" else "")
                     + 
                     f"<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>{escape(v['sales_ledger'])}</LEDGERNAME>"
                     f"<AMOUNT>{amt(sign * a)}</AMOUNT></ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>")
        for ln, a in v["ledgers"]:
            body += (f"<LEDGERENTRIES.LIST><LEDGERNAME>{escape(ln)}</LEDGERNAME>"
                     f"<AMOUNT>{amt(a)}</AMOUNT>{ba(ln)}</LEDGERENTRIES.LIST>")
    if v["no"] == "S/9001":     # an e-invoiced sale with an e-way bill, as TallyPrime exports it
        body += ("<IRN>2d46b1e7bd54fbcd324bf6b675d1d3cc3eedb31212b5bafaa301a8a1ce2fe048</IRN><IRNACKNO>172621382927422</IRNACKNO>"
                 "<IRNACKDATE>20260906</IRNACKDATE><IRNQRCODE>eyJhbGciOiJSUzI1NiJ9.eyJkYXRhIjoidGVzdCJ9.c2lnbmF0dXJl</IRNQRCODE>"
                 "<EWAYBILLDETAILS.LIST><BILLNUMBER>741678385270</BILLNUMBER><BILLDATE>20260906</BILLDATE>"
                 "<CONSIGNORPLACE>Nagpur</CONSIGNORPLACE><CONSIGNEEPLACE>Nagpur</CONSIGNEEPLACE><SUBTYPE>Supply</SUBTYPE>"
                 "<TRANSPORTDETAILS.LIST><TRANSPORTMODE>1 - Road</TRANSPORTMODE><DISTANCE>12</DISTANCE>"
                 "<VEHICLENUMBER>MH31AB1234</VEHICLENUMBER></TRANSPORTDETAILS.LIST></EWAYBILLDETAILS.LIST>")
    return head + body + "</VOUCHER></TALLYMESSAGE>"


import os
from datetime import datetime
DAYBOOK_BUG = os.environ.get("DAYBOOK_BUG") == "1"   # behave like a Tally that ignores the Day Book dates


def tdate(s):
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return datetime.strptime(s, "%d-%b-%Y").date()


EDITS = [0]


def apply_edit():
    """Simulate a day's work in Tally: change one voucher, add one, delete one."""
    EDITS[0] += 1
    top = max(v["alterid"] for v in VOUCHERS)
    target = next(v for v in VOUCHERS if v["kind"] == "acct" and v["type"] == "Receipt" and v["date"] < date(2026, 6, 1))
    target["narration"] = "edited in Tally"
    target["alterid"] = top + 1
    newv = dict(next(v for v in VOUCHERS if v["kind"] == "acct" and v["type"] == "Payment"))
    newv.update({"guid": "guid-new-%d" % EDITS[0], "no": "N%d" % EDITS[0], "alterid": top + 2,
                 "date": date(2026, 9, 9), "narration": "new entry"})
    VOUCHERS.append(newv)
    victim = next(v for v in VOUCHERS if v["kind"] == "acct" and v["type"] == "Payment" and v["date"].month == 7)
    VOUCHERS.remove(victim)
    return target["date"], newv["date"], victim["date"]


IMPORTED = []


def import_voucher(req):
    """Tally's Import Data for one voucher, with the checks Tally makes."""
    import xml.etree.ElementTree as ET
    def err(msg):
        return (f"<RESPONSE><LINEERROR>{escape(msg)}</LINEERROR><CREATED>0</CREATED><ALTERED>0</ALTERED>"
                f"<ERRORS>1</ERRORS></RESPONSE>")
    root = ET.fromstring(req)
    co = root.findtext(".//SVCURRENTCOMPANY") or ""
    if co != COMPANY:
        return err(f"Could not set 'SVCurrentCompany' to '{co}'")
    v = root.find(".//VOUCHER")
    vt = v.findtext("VOUCHERTYPENAME")
    if vt not in {n for n, _ in VTYPES}:
        return err(f"Voucher Type '{vt}' does not exist!")
    d = tdate(v.findtext("DATE"))
    party = v.findtext("PARTYLEDGERNAME")
    base = dict(VTYPES).get(vt) or vt
    same = [x for x in VOUCHERS if x["type"] == vt]
    nv = {"date": d, "type": vt, "no": str(len(same) + 1), "party": party, "narration": v.findtext("NARRATION") or "",
          "guid": f"guid-imp-{len(IMPORTED) + 1}", "alterid": max(x["alterid"] for x in VOUCHERS) + 1}
    if base == "Sales Order":
        items = []
        for ie in v.findall("ALLINVENTORYENTRIES.LIST"):
            name = ie.findtext("STOCKITEMNAME")
            st = next((x for x in STOCK if x[0] == name), None)
            if not st:
                return err(f"Stock Item '{name}' does not exist!")
            if ie.find("BATCHALLOCATIONS.LIST/GODOWNNAME") is None:
                return err("Godown not specified")
            for al in ie.findall("ACCOUNTINGALLOCATIONS.LIST"):
                if al.findtext("LEDGERNAME") not in LEDGERS:
                    return err(f"Ledger '{al.findtext('LEDGERNAME')}' does not exist!")
            q = float(ie.findtext("ACTUALQTY").split()[0])
            a = float(ie.findtext("AMOUNT"))
            items.append((name, q, st[2], round(a / q, 2), a))
        if party not in LEDGERS:
            return err(f"Ledger '{party}' does not exist!")
        nv.update(kind="order", items=items, ledgers=[], nonposting=True)
    else:
        lines, allocs = [], []
        for le in v.findall("ALLLEDGERENTRIES.LIST"):
            ln = le.findtext("LEDGERNAME")
            if ln not in LEDGERS:
                return err(f"Ledger '{ln}' does not exist!")
            amt_ = -float(le.findtext("AMOUNT"))      # back to debit-positive
            lines.append((ln, amt_))
            for b in le.findall("BILLALLOCATIONS.LIST"):
                ref, bt, ba_ = b.findtext("NAME") or "", b.findtext("BILLTYPE"), -float(b.findtext("AMOUNT"))
                allocs.append((ref, bt, ba_, 0))
                if bt == "Agst Ref":
                    for ob in OPEN_BILLS.get(ln, []):
                        if ob[0] == ref:
                            ob[2] -= abs(ba_)
                    OPEN_BILLS[ln] = [ob for ob in OPEN_BILLS.get(ln, []) if ob[2] > 0.005]
        if abs(sum(a for _, a in lines)) > 0.005:
            return err("Voucher totals do not match!")
        nv.update(kind="acct", ledgers=lines, billalloc=allocs)
    VOUCHERS.append(nv)
    IMPORTED.append(nv)
    return ("<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><DELETED>0</DELETED><LASTVCHID>%d</LASTVCHID>"
            "<LASTMID>0</LASTMID><COMBINED>0</COMBINED><IGNORED>0</IGNORED><ERRORS>0</ERRORS><CANCELLED>0</CANCELLED></RESPONSE>" % (9000 + len(IMPORTED)))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/edit":
            r = apply_edit()
            data = ("edited months: %s" % ", ".join(sorted({d.strftime("%Y-%m") for d in r}))).encode()
        else:
            data = b"<RESPONSE>TallyPrime Server is Running</RESPONSE>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        req = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8")
        g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", req, re.S) or [None, ""])[1]
        typ, rid = g("TYPE"), g("ID")
        f, t = tdate(g("SVFROMDATE")), tdate(g("SVTODATE"))
        co = g("SVCURRENTCOMPANY").replace("&amp;", "&")
        if "<TALLYREQUEST>Import Data</TALLYREQUEST>" in req:
            out = import_voucher(req)
        elif co and co != COMPANY:
            out = "<ENVELOPE><LINEERROR>Could not find Company</LINEERROR></ENVELOPE>"
        elif typ == "Data" and rid in ("Bills Receivable", "Bills Payable"):
            want = {n for n, _, _ in DEBTORS} if rid == "Bills Receivable" else {n for n, _ in CREDITORS}
            out = "<ENVELOPE>"
            for p, bl in OPEN_BILLS.items():
                if p not in want:
                    continue
                for ref, dt, left, days in bl:
                    due = dt + timedelta(days=days)
                    od = max(0, (date.today() - due).days)
                    out += (f"<BILLFIXED><BILLDATE>{dt.day}-{dt.strftime('%b-%y')}</BILLDATE><BILLREF>{escape(ref)}</BILLREF>"
                            f"<BILLPARTY>{escape(p)}</BILLPARTY></BILLFIXED><BILLCL>{-left if rid == 'Bills Receivable' else left:.2f}</BILLCL>"
                            f"<BILLDUE>{due.day}-{due.strftime('%b-%y')}</BILLDUE><BILLOVERDUE>{od}</BILLOVERDUE>")
            out += "</ENVELOPE>"
        elif typ == "Data" and rid == "List of Accounts":
            at = g("ACCOUNTTYPE")
            out = "<ENVELOPE><BODY><IMPORTDATA><REQUESTDATA>"
            if at == "Ledgers":
                for n, (par, o) in LEDGERS.items():
                    out += f'<TALLYMESSAGE><LEDGER NAME="{escape(n)}"><PARENT>{escape(par)}</PARENT>'
                    if n in ADDR and n == "Patel Enterprises":   # TallyPrime 3+ style
                        out += ("<LEDMAILINGDETAILS.LIST><APPLICABLEFROM>20200401</APPLICABLEFROM><ADDRESS.LIST>"
                                + "".join(f"<ADDRESS>{escape(a)}</ADDRESS>" for a in ADDR[n])
                                + "</ADDRESS.LIST><STATE>Maharashtra</STATE><PINCODE>400069</PINCODE></LEDMAILINGDETAILS.LIST>"
                                + "<LEDGSTREGDETAILS.LIST><GSTIN>27ABCDE1234F1Z5</GSTIN></LEDGSTREGDETAILS.LIST>")
                    elif n in ADDR:                                      # older style
                        out += ("<ADDRESS.LIST>" + "".join(f"<ADDRESS>{escape(a)}</ADDRESS>" for a in ADDR[n])
                                + "</ADDRESS.LIST><LEDSTATENAME>Maharashtra</LEDSTATENAME>")
                    if n == "HDFC Bank":
                        out += "<BANKDETAILS>50200012345678</BANKDETAILS><IFSCODE>HDFC0001234</IFSCODE><BANKBRANCHNAME>Sitabuldi, Nagpur</BANKBRANCHNAME>"
                    out += "</LEDGER></TALLYMESSAGE>"
            elif at == "Stock Items":
                for name, grp, unit, oq, rate in STOCK:
                    tag = "HSNDETAILS.LIST" if "Paint" in name else "GSTDETAILS.LIST"
                    out += (f'<TALLYMESSAGE><STOCKITEM NAME="{escape(name)}"><{tag}><APPLICABLEFROM>20170701</APPLICABLEFROM>'
                            f'<HSNCODE>{HSN[name]}</HSNCODE></{tag}></STOCKITEM></TALLYMESSAGE>')
            out += "</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
        elif typ == "Data" and rid == "Day Book":
            if DAYBOOK_BUG:
                f = t = m_today = max(v["date"] for v in VOUCHERS)
            vs = "".join(xml_voucher(v) for v in VOUCHERS if f <= v["date"] <= t)
            out = f"<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA>{vs}</DATA></BODY></ENVELOPE>"
        else:
            ctype = re.search(r"<COLLECTION[^>]*>.*?<TYPE>(.*?)</TYPE>", req, re.S).group(1)
            out = "<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA><COLLECTION>"
            if ctype == "Voucher":
                light = "AllLedgerEntries" not in req
                picked = set() if os.environ.get("NO_GUID_FILTER") == "1" else set(re.findall(r'\$GUID = "([^"]+)"', req))
                for v in VOUCHERS:
                    if picked and v["guid"] not in picked:
                        continue
                    if f <= v["date"] <= t:
                        if light:
                            out += (f'<VOUCHER><DATE TYPE="Date">{v["date"].strftime("%Y%m%d")}</DATE><GUID>{v["guid"]}</GUID><ALTERID> {v["alterid"]}</ALTERID>'
                                    f'<ISCANCELLED>{"Yes" if v.get("cancelled") else "No"}</ISCANCELLED>'
                                    f'<ISOPTIONAL>{"Yes" if v.get("optional") else "No"}</ISOPTIONAL></VOUCHER>')
                        else:
                            x = xml_voucher(v).replace('<TALLYMESSAGE xmlns:UDF="TallyUDF">', "").replace("</TALLYMESSAGE>", "")
                            # user-defined fields from a Tally add-on, without the namespace declaration
                            x = x.replace("</NARRATION>", '</NARRATION><UDF:TRANSPORTER.LIST DESC="`Transporter`" ISLIST="YES" TYPE="String" INDEX="30">'
                                          '<UDF:TRANSPORTER DESC="`Transporter`">VRL</UDF:TRANSPORTER></UDF:TRANSPORTER.LIST>', 1)
                            out += x
            elif ctype == "Company":
                out += (f'<COMPANY NAME="{escape(COMPANY)}"><NAME>{escape(COMPANY)}</NAME>'
                        f'<ADDRESS.LIST><ADDRESS>Plot 21, Wardhaman Nagar</ADDRESS><ADDRESS>Central Avenue, Nagpur 440008</ADDRESS></ADDRESS.LIST>'
                        f'<STATENAME>Maharashtra</STATENAME><EMAIL>accounts@demotraders.in</EMAIL><INCOMETAXNUMBER>AABCD1234E</INCOMETAXNUMBER>'
                        f'<GSTREGISTRATIONNUMBER>27AABCD1234E1Z9</GSTREGISTRATIONNUMBER>'
                        f'<ALTVCHID TYPE="Number"> {431 if os.environ.get("STUCK_ALTVCH") == "1" else max(v["alterid"] for v in VOUCHERS) + EDITS[0]}</ALTVCHID><ALTMSTID TYPE="Number"> 87</ALTMSTID></COMPANY>')
            elif ctype == "Group":
                for n, p in GROUPS:
                    par = escape(p) if p else "&#4; Primary"
                    top = n
                    while dict(GROUPS).get(top):
                        top = dict(GROUPS)[top]
                    rev = top in ("Sales Accounts", "Purchase Accounts", "Direct Expenses", "Direct Incomes", "Indirect Expenses", "Indirect Incomes", "Commission Earned")
                    gp = top in ("Sales Accounts", "Purchase Accounts", "Direct Expenses", "Direct Incomes")
                    dr = top in ("Purchase Accounts", "Direct Expenses", "Indirect Expenses", "Current Assets", "Fixed Assets", "Investments")
                    yn = lambda b: "Yes" if b else "No"
                    out += (f'<GROUP NAME="{escape(n)}"><PARENT TYPE="String">{par}</PARENT><ISREVENUE TYPE="Logical">{yn(rev)}</ISREVENUE>'
                            f'<AFFECTSGROSSPROFIT TYPE="Logical">{yn(gp)}</AFFECTSGROSSPROFIT><ISDEEMEDPOSITIVE TYPE="Logical">{yn(dr)}</ISDEEMEDPOSITIVE></GROUP>')
            elif ctype == "VoucherType":
                for n, p in VTYPES:
                    out += f'<VOUCHERTYPE NAME="{escape(n)}"><PARENT TYPE="String">{escape(p)}</PARENT></VOUCHERTYPE>'
            elif ctype == "Ledger" and os.environ.get("BROKEN_LEDGERS") == "1":
                out += '<LEDGER NAME="Bad <"><PARENT>x</PARENT></LEDGER>'
            elif ctype == "Ledger":
                bal = closing_balances(t or END)
                for n, (p, o) in LEDGERS.items():
                    ph = PHONES.get(n, "")
                    out += (f'<LEDGER NAME="{escape(n)}"><PARENT TYPE="String">{escape(p)}</PARENT>'
                            f'<OPENINGBALANCE TYPE="Amount">{amt(o)}</OPENINGBALANCE>'
                            f'<CLOSINGBALANCE TYPE="Amount">{amt(bal[n])}</CLOSINGBALANCE>'
                            f'<LEDGERMOBILE TYPE="String">{ph}</LEDGERMOBILE>'
                            f'<TAXTYPE>{"GST" if "GST" in n else ""}</TAXTYPE>'
                            f'<GSTDUTYHEAD>{"Central Tax" if "CGST" in n else "State Tax" if "SGST" in n else ""}</GSTDUTYHEAD></LEDGER>')
            elif ctype == "StockItem":
                cl = stock_closing(t or END)
                for name, grp, unit, oq, rate in STOCK:
                    q, val, r = cl[name]
                    out += (f'<STOCKITEM NAME="{escape(name)}"><PARENT TYPE="String">{grp}</PARENT>'
                            f'<BASEUNITS TYPE="String">{unit}</BASEUNITS>'
                            f'<OPENINGBALANCE TYPE="Quantity"> {oq} {unit}</OPENINGBALANCE>'
                            f'<OPENINGVALUE TYPE="Amount">-{oq * rate:.2f}</OPENINGVALUE>'
                            f'<CLOSINGBALANCE TYPE="Quantity"> {q} {unit}</CLOSINGBALANCE>'
                            f'<CLOSINGVALUE TYPE="Amount">-{val:.2f}</CLOSINGVALUE>'
                            f'<CLOSINGRATE TYPE="Rate">{r:.2f}/{unit}</CLOSINGRATE></STOCKITEM>')
            out += "</COLLECTION></DATA></BODY></ENVELOPE>"
        data = out.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    HTTPServer(("127.0.0.1", port), H).serve_forever()
