"""Receipts, payments and sales orders made on the phone. They wait here until the Tally PC agent
puts them into Tally (on its next run). Staff entries wait for the owner's approval first."""
import re
import json
import os
import sqlite3
import time
import uuid
from datetime import date
from xml.sax.saxutils import escape as _esc


def escape(t):
    return _esc(str(t), {'"': "&quot;", "'": "&apos;"})

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB = os.path.join(DATA_DIR, "entries.db")
KINDS = {"receipt": "Receipt", "payment": "Payment", "order": "Sales Order"}
PERM = {"receipt": "e_receipt", "payment": "e_payment", "order": "e_order"}
RESEND_AFTER = 15 * 60       # an entry handed to the agent but never reported back is offered again


def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS entry(id INTEGER PRIMARY KEY, uid TEXT, company TEXT, kind TEXT, data TEXT,
        status TEXT, by TEXT, created REAL, approved_by TEXT, sent REAL, done REAL, error TEXT, tries INT DEFAULT 0)""")
    return c


def _row(r):
    d = dict(r)
    d["data"] = json.loads(d["data"])
    return d


# ---------------------------------------------------------------- form data
def form(cid, kind):
    with store.conn() as c:
        base = KINDS[kind]
        vtypes = [r["name"] for r in c.execute("SELECT name FROM vtype WHERE company_id=? AND base=? ORDER BY name<>?, name",
                                               (cid, base, base))] or [base]
        cash_bank = [r["name"] for r in c.execute(
            """SELECT name FROM ledger WHERE company_id=? AND (chain LIKE '%|Cash-in-Hand|%' OR chain LIKE '%|Bank Accounts|%'
               OR chain LIKE '%|Bank OD A/c|%') ORDER BY chain LIKE '%|Cash-in-Hand|%' DESC, name""", (cid,))]
        if kind == "order":
            parties = [r["name"] for r in c.execute(
                "SELECT name FROM ledger WHERE company_id=? AND chain LIKE '%|Sundry Debtors|%' ORDER BY name", (cid,))]
        else:
            first = "Sundry Debtors" if kind == "receipt" else "Sundry Creditors"
            parties = [r["name"] for r in c.execute(
                f"""SELECT name FROM ledger WHERE company_id=? AND NOT (chain LIKE '%|Cash-in-Hand|%' OR chain LIKE '%|Bank Accounts|%'
                    OR chain LIKE '%|Bank OD A/c|%') ORDER BY chain LIKE ? DESC, name""", (cid, f"%|{first}|%"))]
        out = {"kind": kind, "vtypes": vtypes, "accounts": cash_bank, "parties": parties, "today": date.today().isoformat()}
        if kind == "order":
            # each item's last selling rate, else its stock rate
            last = {r["item"]: r["rate"] for r in c.execute(
                """SELECT vi.item, vi.rate FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
                   WHERE v.company_id=? AND v.base='Sales' ORDER BY v.date""", (cid,))}
            out["items"] = [{"name": r["name"], "unit": r["unit"], "rate": round(last.get(r["name"]) or r["closing_rate"] or 0, 2),
                             "in_hand": r["closing_qty"]}
                            for r in c.execute("SELECT name, unit, closing_rate, closing_qty FROM stock WHERE company_id=? ORDER BY name", (cid,))]
            out["sales_ledgers"] = [r["name"] for r in c.execute(
                """SELECT l.name, (SELECT COUNT(*) FROM vline vl WHERE vl.ledger=l.name) n FROM ledger l
                   WHERE l.company_id=? AND l.chain LIKE '%|Sales Accounts|%' ORDER BY n DESC, l.name""", (cid,))]
        return out


def party_bills(cid, name):
    with store.conn() as c:
        kind, bills = store.ledger_bills(c, cid, name)
    return {"kind": kind, "bills": [b for b in bills if b["amount"] > 0.5 and b["ref"] not in ("On account", "Advance / unadjusted")]}


# ---------------------------------------------------------------- checking and saving
def _num(x, what):
    try:
        v = round(float(x), 2)
    except (TypeError, ValueError):
        raise ValueError(f"Enter the {what}.")
    if v <= 0:
        raise ValueError(f"The {what} must be more than zero.")
    return v


def clean(cid, kind, d):
    if kind not in KINDS:
        raise ValueError("Unknown entry type.")
    f = form(cid, kind)
    day = str(d.get("date") or "")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ValueError("Pick a date.")
    vtype = d.get("vtype") or f["vtypes"][0]
    if vtype not in f["vtypes"]:
        raise ValueError("Pick a voucher type.")
    party = str(d.get("party") or "")
    if party not in f["parties"]:
        raise ValueError("Pick a party from the list.")
    out = {"date": day, "vtype": vtype, "party": party, "narration": str(d.get("narration") or "").strip()[:500]}
    if kind == "order":
        items = []
        known = {i["name"]: i for i in f["items"]}
        for it in d.get("items") or []:
            if not it.get("item"):
                continue
            if it["item"] not in known:
                raise ValueError(f"{it['item']} isn't a stock item in Tally.")
            q = _num(it.get("qty"), f"quantity of {it['item']}")
            r = _num(it.get("rate"), f"rate of {it['item']}")
            items.append({"item": it["item"], "unit": known[it["item"]]["unit"], "qty": q, "rate": r, "amount": round(q * r, 2)})
        if not items:
            raise ValueError("Add at least one item.")
        sl = d.get("sales_ledger") or (f["sales_ledgers"][0] if f["sales_ledgers"] else "")
        if sl not in f["sales_ledgers"]:
            raise ValueError("Pick a sales ledger.")
        due = str(d.get("due") or "")
        if due:
            date.fromisoformat(due)
        out.update(items=items, sales_ledger=sl, due=due, amount=round(sum(i["amount"] for i in items), 2))
    else:
        acc = str(d.get("account") or "")
        if acc not in f["accounts"]:
            raise ValueError("Pick the cash or bank account.")
        amount = _num(d.get("amount"), "amount")
        bills = []
        if d.get("bills"):
            pend = {b["ref"]: b for b in party_bills(cid, party)["bills"]}
            for b in d["bills"]:
                if b.get("ref") not in pend:
                    raise ValueError(f"Bill {b.get('ref')} is not pending for {party}.")
                bills.append({"ref": b["ref"], "amount": _num(b.get("amount"), f"amount against {b['ref']}")})
            if sum(b["amount"] for b in bills) > amount + 0.005:
                raise ValueError("The bills add up to more than the amount.")
        out.update(account=acc, amount=amount, bills=bills)
    return out


def create(cid, kind, data, user):
    co = next((x for x in store.companies() if x["id"] == cid), None)
    if not co:
        raise ValueError("Company not found.")
    d = clean(cid, kind, data)
    direct = user["owner"] or "e_direct" in user["perms"]
    with conn() as c:
        cur = c.execute("""INSERT INTO entry(uid, company, kind, data, status, by, created, approved_by)
            VALUES(?,?,?,?,?,?,?,?)""", (uuid.uuid4().hex, co["name"], kind, json.dumps(d),
                                         "queued" if direct else "approval", user["name"] or "Owner", time.time(),
                                         (user["name"] or "Owner") if direct else ""))
        new_id = cur.lastrowid
    return get(new_id)


def get(eid):
    with conn() as c:
        r = c.execute("SELECT * FROM entry WHERE id=?", (eid,)).fetchone()
        return _row(r) if r else None


def listing(company, user, limit=100):
    with conn() as c:
        if user["owner"]:
            rows = c.execute("SELECT * FROM entry WHERE company=? ORDER BY id DESC LIMIT ?", (company, limit))
        else:
            rows = c.execute("SELECT * FROM entry WHERE company=? AND by=? ORDER BY id DESC LIMIT ?", (company, user["name"], limit))
        return [_row(r) for r in rows]


def action(eid, what, user):
    e = get(eid)
    if not e:
        raise ValueError("Entry not found.")
    mine = (e["by"] == (user["name"] or "Owner"))
    with conn() as c:
        if what == "approve" and user["owner"] and e["status"] == "approval":
            c.execute("UPDATE entry SET status='queued', approved_by='Owner' WHERE id=?", (eid,))
        elif what == "reject" and user["owner"] and e["status"] == "approval":
            c.execute("UPDATE entry SET status='rejected' WHERE id=?", (eid,))
        elif what == "cancel" and (user["owner"] or mine) and e["status"] in ("approval", "queued", "failed"):
            c.execute("UPDATE entry SET status='cancelled' WHERE id=?", (eid,))
        elif what == "retry" and (user["owner"] or mine) and e["status"] == "failed":
            direct = user["owner"] or "e_direct" in user["perms"]
            c.execute("UPDATE entry SET status=?, error='' WHERE id=?", ("queued" if direct else "approval", eid))
        else:
            raise ValueError("That can't be done to this entry now.")
    return get(eid)


def pending_count(company):
    with conn() as c:
        return c.execute("SELECT COUNT(*) n FROM entry WHERE company=? AND status='approval'", (company,)).fetchone()["n"]


# ---------------------------------------------------------------- for the Tally PC agent
def _amt(x):
    return f"{x:.2f}"


def _d(iso):
    return iso.replace("-", "")


def build_xml(e):
    d = e["data"]
    co = escape(e["company"])
    vt = escape(d["vtype"])
    who = "owner" if e["by"] == "Owner" else e["by"]
    nar = escape((d.get("narration") + " " if d.get("narration") else "") + f"(entered on phone by {who})")
    head = (f'<VOUCHER VCHTYPE="{vt}" ACTION="Create" OBJVIEW="{"Invoice Voucher View" if e["kind"] == "order" else "Accounting Voucher View"}">'
            f'<DATE>{_d(d["date"])}</DATE><EFFECTIVEDATE>{_d(d["date"])}</EFFECTIVEDATE><VOUCHERTYPENAME>{vt}</VOUCHERTYPENAME>'
            f'<PARTYLEDGERNAME>{escape(d["party"])}</PARTYLEDGERNAME><NARRATION>{nar}</NARRATION>')
    body = ""
    if e["kind"] in ("receipt", "payment"):
        rec = e["kind"] == "receipt"
        # Tally XML: a debit is a negative amount with ISDEEMEDPOSITIVE Yes
        p_amt, a_amt = (d["amount"], -d["amount"]) if rec else (-d["amount"], d["amount"])
        bills = ""
        if d["bills"]:
            sign = 1 if rec else -1
            for b in d["bills"]:
                bills += (f'<BILLALLOCATIONS.LIST><NAME>{escape(b["ref"])}</NAME><BILLTYPE>Agst Ref</BILLTYPE>'
                          f'<AMOUNT>{_amt(sign * b["amount"])}</AMOUNT></BILLALLOCATIONS.LIST>')
            rest = round(d["amount"] - sum(b["amount"] for b in d["bills"]), 2)
            if rest > 0.005:
                bills += (f'<BILLALLOCATIONS.LIST><NAME></NAME><BILLTYPE>On Account</BILLTYPE>'
                          f'<AMOUNT>{_amt(sign * rest)}</AMOUNT></BILLALLOCATIONS.LIST>')
        body += (f'<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(d["party"])}</LEDGERNAME>'
                 f'<ISDEEMEDPOSITIVE>{"No" if rec else "Yes"}</ISDEEMEDPOSITIVE><ISPARTYLEDGER>Yes</ISPARTYLEDGER>'
                 f'<AMOUNT>{_amt(p_amt)}</AMOUNT>{bills}</ALLLEDGERENTRIES.LIST>'
                 f'<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(d["account"])}</LEDGERNAME>'
                 f'<ISDEEMEDPOSITIVE>{"Yes" if rec else "No"}</ISDEEMEDPOSITIVE>'
                 f'<AMOUNT>{_amt(a_amt)}</AMOUNT></ALLLEDGERENTRIES.LIST>')
    else:
        order_no = f"PH-{e['id']}"
        head += f"<REFERENCE>{order_no}</REFERENCE><PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW><ISINVOICE>Yes</ISINVOICE>"
        due = d.get("due") or d["date"]
        due_t = date.fromisoformat(due).strftime("%-d-%b-%Y")
        body += (f'<LEDGERENTRIES.LIST><LEDGERNAME>{escape(d["party"])}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>'
                 f'<ISPARTYLEDGER>Yes</ISPARTYLEDGER><AMOUNT>{_amt(-d["amount"])}</AMOUNT></LEDGERENTRIES.LIST>')
        for it in d["items"]:
            q = f' {it["qty"]:g} {escape(it["unit"])}'
            body += (f'<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{escape(it["item"])}</STOCKITEMNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                     f'<RATE>{it["rate"]:.2f}/{escape(it["unit"])}</RATE><AMOUNT>{_amt(it["amount"])}</AMOUNT>'
                     f'<ACTUALQTY>{q}</ACTUALQTY><BILLEDQTY>{q}</BILLEDQTY>'
                     f'<BATCHALLOCATIONS.LIST><GODOWNNAME>Main Location</GODOWNNAME><ORDERNO>{order_no}</ORDERNO>'
                     f'<ORDERDUEDATE P="{due_t}">{due_t}</ORDERDUEDATE><AMOUNT>{_amt(it["amount"])}</AMOUNT>'
                     f'<ACTUALQTY>{q}</ACTUALQTY><BILLEDQTY>{q}</BILLEDQTY></BATCHALLOCATIONS.LIST>'
                     f'<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>{escape(d["sales_ledger"])}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                     f'<AMOUNT>{_amt(it["amount"])}</AMOUNT></ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>')
    return ("<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC>"
            f"<REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>{co}</SVCURRENTCOMPANY></STATICVARIABLES>"
            '</REQUESTDESC><REQUESTDATA><TALLYMESSAGE xmlns:UDF="TallyUDF">'
            + head + body + "</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")


_UNSAFE = re.compile(r'<(GUID|REMOTEID|MASTERID|ALTERID|VOUCHERKEY|VCHKEY|ISDELETED|ISCANCELLED|IMPORTDUPS)[\s>]|REMOTEID\s*=|VCHKEY\s*='
                     r'|TAGNAME|TAGVALUE|<TDL|<DELETE|<ALTER|<CANCEL', re.I)


def safe_for_tally(xml):
    """Only new vouchers, never a change to or deletion of anything already in Tally (the Tally PC checks again)."""
    actions = re.findall(r'ACTION\s*=\s*"([^"]*)"', xml, re.I)
    objs = re.findall(r'<TALLYMESSAGE[^>]*>\s*<([A-Za-z.]+)', xml)
    return (bool(actions) and all(a.lower() == "create" for a in actions) and objs and all(o.upper() == "VOUCHER" for o in objs)
            and "<REPORTNAME>Vouchers</REPORTNAME>" in xml and not _UNSAFE.search(xml))


def outbox(company):
    """Entries ready for Tally. Marked as being sent, so two agent runs never both send one."""
    now = time.time()
    with conn() as c:
        rows = c.execute("""SELECT * FROM entry WHERE company=? AND (status='queued' OR (status='sending' AND sent < ?))
            ORDER BY id LIMIT 20""", (company, now - RESEND_AFTER)).fetchall()
        out = []
        for r in rows:
            e = _row(r)
            xml = build_xml(e)
            if not safe_for_tally(xml):
                c.execute("UPDATE entry SET status='failed', error=? WHERE id=?",
                          ("Not sent: it would have changed something already in Tally.", e["id"]))
                continue
            c.execute("UPDATE entry SET status='sending', sent=?, tries=tries+1 WHERE id=?", (now, e["id"]))
            out.append({"id": e["id"], "uid": e["uid"], "kind": e["kind"], "label": label(e), "xml": xml})
        return out


def result(eid, ok, error="", retry=False):
    with conn() as c:
        if ok:
            c.execute("UPDATE entry SET status='done', done=?, error='' WHERE id=?", (time.time(), eid))
        elif retry:     # Tally couldn't be reached: try again next run
            c.execute("UPDATE entry SET status='queued', error=? WHERE id=?", (error[:500], eid))
        else:
            c.execute("UPDATE entry SET status='failed', error=? WHERE id=?", (error[:500], eid))


def label(e):
    d = e["data"]
    return f"{d['vtype']} {d['party']} {d['amount']:.2f}"
