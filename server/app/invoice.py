"""Sales invoices and purchase vouchers entered on the phone: the form's data, checking what was entered
(every figure is worked out again here, never taken from the phone), and the Tally voucher to create.

GST: each line's rate comes from the item in Tally (or, when Tally has none, from the item's earlier
invoices); CGST + SGST within the state, IGST when the party is in another state. Tax and sales/purchase
ledgers are the company's own, picked by the rate in their name when they have one (e.g. "Output CGST 9%"),
otherwise the ones its earlier invoices used most.
"""
import json
import re
from datetime import date
from xml.sax.saxutils import escape as _esc

import store

SLABS = [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28, 40]
HEADS = {"c": "Central Tax", "s": "State Tax", "i": "Integrated Tax"}


def escape(t):
    return _esc(str(t), {'"': "&quot;", "'": "&apos;"})


def _snap(x):
    best = min(SLABS, key=lambda s: abs(s - x))
    return best if abs(best - x) <= 0.3 else None


def _rates_in(name):
    """Rates written in a ledger's name: 'Output CGST 9%', 'Sales @18', 'IGST-28' -> {9.0} etc."""
    return {float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", name or "")} | \
           {float(x) for x in re.findall(r"@\s*(\d+(?:\.\d+)?)", name or "")}


def _head(l):
    g = (l["gst_head"] or "").lower()
    n = l["name"].lower()
    if "integrated" in g or "igst" in n:
        return "i"
    if "central" in g or "cgst" in n:
        return "c"
    if "state" in g or "sgst" in n or "utgst" in n:
        return "s"
    return None


def _next_number(last):
    m = re.match(r"^(.*?)(\d+)(\D*)$", last or "")
    if not m:
        return ""
    n = str(int(m.group(2)) + 1).zfill(len(m.group(2)))
    return m.group(1) + n + m.group(3)


def form(cid, kind):
    sales = kind == "sales"
    base = "Sales" if sales else "Purchase"
    with store.conn() as c:
        co = c.execute("SELECT info FROM company WHERE id=?", (cid,)).fetchone()
        co_state = (json.loads(co["info"] or "{}") if co else {}).get("state", "")
        vtypes = [r["name"] for r in c.execute("SELECT name FROM vtype WHERE company_id=? AND base=? ORDER BY name<>?, name",
                                               (cid, base, base))] or [base]
        leds = [dict(r) for r in c.execute("SELECT name, chain, gstin, gst_head, extra FROM ledger WHERE company_id=?", (cid,))]
        used = {r["ledger"]: (r["n"], r["s"]) for r in c.execute("""SELECT vl.ledger, COUNT(*) n, SUM(vl.amount) s FROM vline vl
            JOIN voucher v ON v.id=vl.voucher_id WHERE v.company_id=? AND v.base=? GROUP BY vl.ledger""", (cid, base))}
        # parties: customers (or suppliers) first, then cash and bank (cash sales), then everything else
        first = "|Sundry Debtors|" if sales else "|Sundry Creditors|"
        skip = ("|Duties & Taxes|", "|Sales Accounts|", "|Purchase Accounts|")
        rank = lambda l: (0 if first in l["chain"] else 1 if ("|Cash-in-Hand|" in l["chain"] or "|Bank Accounts|" in l["chain"]) else 2,
                          l["name"].lower())
        parties = sorted([l for l in leds if not any(s in l["chain"] for s in skip)], key=rank)
        pinfo = {}
        for l in parties:
            x = json.loads(l["extra"] or "{}")
            if x.get("state") or l["gstin"] or x.get("gstin"):
                pinfo[l["name"]] = {"state": x.get("state", ""), "gstin": l["gstin"] or x.get("gstin", "")}
        acct = "|Sales Accounts|" if sales else "|Purchase Accounts|"
        item_ledgers = sorted([l["name"] for l in leds if acct in l["chain"]], key=lambda n: (-used.get(n, (0, 0))[0], n.lower()))
        taxes = []
        for l in leds:
            if "|Duties & Taxes|" in l["chain"] and _head(l):
                n, s = used.get(l["name"], (0, 0))
                # sales credit output tax (negative here), purchases debit input tax
                side_ok = (s < 0) if sales else (s > 0)
                hint = 1 if (("output" in l["name"].lower()) if sales else ("input" in l["name"].lower())) else 0
                taxes.append({"name": l["name"], "head": _head(l), "rates": sorted(_rates_in(l["name"])),
                              "score": (n if side_ok else 0) * 10 + hint})
        taxes.sort(key=lambda t: (-t["score"], t["name"].lower()))
        round_off = next((l["name"] for l in sorted(leds, key=lambda l: -used.get(l["name"], (0, 0))[0])
                          if re.search(r"round", l["name"], re.I)), "")
        # GST rate of each item: Tally's, else from its earlier invoices (a single-item invoice says it best)
        tax_names = [t["name"] for t in taxes]
        inferred, weak = {}, {}
        if tax_names:
            ph = ",".join("?" for _ in tax_names)
            for r in c.execute(f"""SELECT v.id, (SELECT GROUP_CONCAT(DISTINCT item) FROM vitem WHERE voucher_id=v.id) items,
                    (SELECT SUM(ABS(amount)) FROM vitem WHERE voucher_id=v.id) taxable,
                    (SELECT SUM(ABS(amount)) FROM vline WHERE voucher_id=v.id AND ledger IN ({ph})) tax
                    FROM voucher v WHERE v.company_id=? AND v.base IN ('Sales', 'Purchase')
                    ORDER BY v.date, v.id""", tax_names + [cid]):
                if not r["items"] or not r["taxable"]:
                    continue
                g = _snap((r["tax"] or 0) / r["taxable"] * 100)
                if g is None:
                    continue
                names = r["items"].split(",")
                for it in names:
                    (inferred if len(names) == 1 else weak)[it] = g
        last = {r["item"]: r["rate"] for r in c.execute(
            """SELECT vi.item, vi.rate FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
               WHERE v.company_id=? AND v.base=? AND vi.rate>0 ORDER BY v.date, v.id""", (cid, base))}
        items = []
        for r in c.execute("SELECT name, unit, hsn, gst, closing_rate, closing_qty FROM stock WHERE company_id=? ORDER BY name", (cid,)):
            g = r["gst"] if r["gst"] is not None else inferred.get(r["name"], weak.get(r["name"]))
            items.append({"name": r["name"], "unit": r["unit"], "hsn": r["hsn"], "gst": g, "gst_from_tally": r["gst"] is not None,
                          "rate": round(last.get(r["name"]) or r["closing_rate"] or 0, 2), "in_hand": r["closing_qty"]})
        godowns = sorted({r[0] for r in c.execute(
            "SELECT DISTINCT godown FROM vgodown g JOIN voucher v ON v.id=g.voucher_id WHERE v.company_id=? AND godown<>''", (cid,))}
            | {r[0] for r in c.execute("SELECT DISTINCT godown FROM stock_godown_open WHERE company_id=?", (cid,))}) or ["Main Location"]
        nums = {}
        for vt in vtypes:
            r = c.execute("SELECT number FROM voucher WHERE company_id=? AND vtype=? AND number<>'' ORDER BY date DESC, id DESC LIMIT 1",
                          (cid, vt)).fetchone()
            nums[vt] = _next_number(r["number"]) if r and sales else ""
    # where each item mostly is now, to start its godown there
    where = {}
    for row in store.godown_stock(cid)["rows"]:
        if row["godown"] != store.NO_GODOWN and row["qty"] > where.get(row["item"], ("", 0))[1]:
            where[row["item"]] = (row["godown"], row["qty"])
    for it in items:
        it["godown"] = where.get(it["name"], (godowns[0],))[0] if where.get(it["name"]) else ("Main Location" if "Main Location" in godowns else godowns[0])
    return {"kind": kind, "vtypes": vtypes, "today": date.today().isoformat(), "company_state": co_state,
            "parties": [p["name"] for p in parties], "party_info": pinfo, "item_ledgers": item_ledgers, "taxes": taxes,
            "round_off": round_off, "items": items, "godowns": godowns, "next_number": nums, "slabs": SLABS}


def _rate_for(amount, qty):
    """The rate for a typed amount: as few decimals as possible (2 to 6) so that quantity x rate gives the amount back."""
    for dp in (2, 3, 4, 5, 6):
        r = round(amount / qty, dp)
        if round(qty * r, 2) == amount:
            return r
    return round(amount / qty, 6)


def _fmt_rate(r):
    s_ = f"{r:.6f}".rstrip("0")
    whole, _, dec = s_.partition(".")
    return whole + "." + dec.ljust(2, "0")


def _pick_tax(f, head, rate):
    cands = [t for t in f["taxes"] if t["head"] == head]
    exact = [t for t in cands if rate in t["rates"]]
    plain = [t for t in cands if not t["rates"]]
    for group in (exact, plain, cands):
        if group:
            return group[0]["name"]
    return None


def _pick_item_ledger(f, chosen, rate):
    if chosen:
        return chosen
    exact = [n for n in f["item_ledgers"] if rate in _rates_in(n)]
    plain = [n for n in f["item_ledgers"] if not _rates_in(n)]
    for group in (exact, plain, f["item_ledgers"]):
        if group:
            return group[0]
    return None


def clean(cid, kind, d, f, num):
    sales = kind == "sales"
    party = str(d.get("party") or "")
    if party not in f["parties"]:
        raise ValueError("Pick a party from the list.")
    chosen = str(d.get("ledger") or "")
    if chosen and chosen not in f["item_ledgers"]:
        raise ValueError("Pick a sales ledger from the list." if sales else "Pick a purchase ledger from the list.")
    if not f["item_ledgers"]:
        raise ValueError(f"There's no ledger under {'Sales' if sales else 'Purchase'} Accounts in Tally.")
    pstate = f["party_info"].get(party, {}).get("state", "")
    other_state = d.get("igst")
    if other_state is None:
        other_state = bool(pstate and f["company_state"] and pstate.lower() != f["company_state"].lower())
    other_state = bool(other_state)
    known = {i["name"]: i for i in f["items"]}
    lines, taxes = [], {}
    for x in d.get("lines") or []:
        name = str(x.get("item") or "").strip()
        if not name:
            continue
        if name not in known:
            raise ValueError(f"{name} isn't a stock item in Tally.")
        qty = num(x.get("qty"), f"quantity of {name}")
        if x.get("amount") not in (None, ""):
            # taxable amount typed in: it stays exactly as entered, and the rate is worked out from it
            amount = num(x.get("amount"), f"amount of {name}")
            rate = _rate_for(amount, qty)
        else:
            rate = num(x.get("rate"), f"rate of {name}")
            amount = round(qty * rate, 2)
        try:
            g = float(x.get("gst"))
        except (TypeError, ValueError):
            raise ValueError(f"Pick the GST rate for {name}.")
        if g not in SLABS:
            raise ValueError(f"{g}% isn't a GST rate.")
        godown = str(x.get("godown") or known[name]["godown"])
        if godown not in f["godowns"]:
            raise ValueError(f"Pick a godown for {name}.")
        ledger = _pick_item_ledger(f, chosen, g)
        lines.append({"item": name, "qty": qty, "unit": known[name]["unit"], "rate": rate, "amount": amount,
                      "gst": g, "godown": godown, "ledger": ledger})
        if g:
            parts = [("i", g, amount * g / 100)] if other_state else [("c", g / 2, amount * g / 200), ("s", g / 2, amount * g / 200)]
            for head, r, t in parts:
                tl = _pick_tax(f, head, r)
                if not tl:
                    raise ValueError(f"There's no {HEADS[head]} ledger under Duties & Taxes in Tally. Create one in Tally first.")
                taxes[tl] = taxes.get(tl, 0.0) + t
    if not lines:
        raise ValueError("Add at least one item.")
    taxes = [{"ledger": k, "amount": round(v, 2)} for k, v in taxes.items() if round(v, 2)]
    taxable = round(sum(l["amount"] for l in lines), 2)
    total = round(taxable + sum(t["amount"] for t in taxes), 2)
    rnd = 0.0
    if d.get("round") and f["round_off"]:
        rnd = round(round(total) - total, 2)
    out = {"party": party, "lines": lines, "taxes": taxes, "igst": other_state, "taxable": taxable,
           "round_off": rnd, "round_ledger": f["round_off"] if rnd else "", "amount": round(total + rnd, 2),
           "party_state": pstate, "company_state": f["company_state"],
           "party_gstin": f["party_info"].get(party, {}).get("gstin", "")}
    number = str(d.get("number") or "").strip()[:40]
    if sales:
        out["number"] = number
    else:
        if not number:
            raise ValueError("Enter the supplier's invoice number.")
        ref_date = str(d.get("ref_date") or "")
        try:
            date.fromisoformat(ref_date)
        except ValueError:
            raise ValueError("Pick the supplier's invoice date.")
        out["number"], out["ref_date"] = number, ref_date
    return out


def body_xml(e):
    """The Tally voucher (head fields after VOUCHER, and its entries) for an invoice entry."""
    d = e["data"]
    sales = e["kind"] == "sales"
    dt = d["date"].replace("-", "")

    def amt(x):
        return f"{x:.2f}"

    def line(tag, ledger, dr, extra=""):
        # dr > 0 is a debit; Tally writes a debit as a negative amount with ISDEEMEDPOSITIVE Yes
        return (f"<{tag}><LEDGERNAME>{escape(ledger)}</LEDGERNAME><ISDEEMEDPOSITIVE>{'Yes' if dr > 0 else 'No'}</ISDEEMEDPOSITIVE>"
                f"{extra}<AMOUNT>{amt(-dr)}</AMOUNT></{tag}>")

    head = ""
    if sales and d.get("number"):
        head += f"<VOUCHERNUMBER>{escape(d['number'])}</VOUCHERNUMBER>"
    if not sales:
        head += (f"<REFERENCE>{escape(d['number'])}</REFERENCE>"
                 f"<REFERENCEDATE>{d['ref_date'].replace('-', '')}</REFERENCEDATE>")
    if d.get("party_gstin"):
        head += f"<PARTYGSTIN>{escape(d['party_gstin'])}</PARTYGSTIN>"
    pos = d.get("party_state") if sales else d.get("company_state")
    if d.get("party_state"):
        head += f"<STATENAME>{escape(d['party_state'])}</STATENAME>"
    if pos:
        head += f"<PLACEOFSUPPLY>{escape(pos)}</PLACEOFSUPPLY>"
    head += ("<COUNTRYOFRESIDENCE>India</COUNTRYOFRESIDENCE><PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>"
             "<ISINVOICE>Yes</ISINVOICE><VCHENTRYMODE>Item Invoice</VCHENTRYMODE>")
    if sales:
        head += f"<BASICBUYERNAME>{escape(d['party'])}</BASICBUYERNAME>"
    sign = 1 if sales else -1              # sales: party debited, items and tax credited; purchase the other way
    bill_name = d.get("number") or ""
    bills = ""
    if bill_name:
        bills = (f"<BILLALLOCATIONS.LIST><NAME>{escape(bill_name)}</NAME><BILLTYPE>New Ref</BILLTYPE>"
                 f"<AMOUNT>{amt(-sign * d['amount'])}</AMOUNT></BILLALLOCATIONS.LIST>")
    body = line("LEDGERENTRIES.LIST", d["party"], sign * d["amount"], "<ISPARTYLEDGER>Yes</ISPARTYLEDGER>")
    body = body.replace("</LEDGERENTRIES.LIST>", bills + "</LEDGERENTRIES.LIST>", 1)
    for l in d["lines"]:
        q = f" {l['qty']:g} {escape(l['unit'])}"
        a = -sign * l["amount"]             # sales: credit (positive in Tally); purchase: debit (negative)
        deemed = "No" if sales else "Yes"
        body += (f"<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{escape(l['item'])}</STOCKITEMNAME>"
                 f"<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE><RATE>{_fmt_rate(l['rate'])}/{escape(l['unit'])}</RATE>"
                 f"<AMOUNT>{amt(-a)}</AMOUNT><ACTUALQTY>{q}</ACTUALQTY><BILLEDQTY>{q}</BILLEDQTY>"
                 f"<BATCHALLOCATIONS.LIST><GODOWNNAME>{escape(l['godown'])}</GODOWNNAME><BATCHNAME>Primary Batch</BATCHNAME>"
                 f"<AMOUNT>{amt(-a)}</AMOUNT><ACTUALQTY>{q}</ACTUALQTY><BILLEDQTY>{q}</BILLEDQTY></BATCHALLOCATIONS.LIST>"
                 f"<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>{escape(l['ledger'])}</LEDGERNAME><ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE>"
                 f"<AMOUNT>{amt(-a)}</AMOUNT></ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>")
    for t in d["taxes"]:
        body += line("LEDGERENTRIES.LIST", t["ledger"], -sign * t["amount"])
    if d.get("round_off"):
        body += line("LEDGERENTRIES.LIST", d["round_ledger"], -sign * d["round_off"])
    return head, body
