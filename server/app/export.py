"""Spreadsheet downloads (CSV that opens in Excel and Google Sheets)."""
import csv
import io

import store


def _csv(title, headers, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    if title:
        w.writerow([title])
        w.writerow([])
    w.writerow(headers)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")   # BOM so Excel reads ₹ and Indian names correctly


def _drcr(n):
    return (round(abs(n), 2), "Dr" if n > 0 else "Cr" if n < 0 else "")


def build(cid, what, q):
    f, t = q.get("from"), q.get("to")
    co = next((c["name"] for c in store.companies() if c["id"] == cid), "")
    if what == "ledger":
        d = store.ledger(cid, q.get("name", ""), f, t)
        if not d:
            return None
        rows = [[d["from"], "Opening balance", "", "", *(_drcr(d["opening"])), "", ""]]
        for e in d["entries"]:
            rows.append([e["date"], e.get("against") or "", e["vtype"], e["number"],
                         e["amount"] if e["amount"] > 0 else "", -e["amount"] if e["amount"] < 0 else "",
                         *_drcr(e["balance"]), e.get("narration") or ""])
        rows.append([d["to"], "Closing balance", "", "", d["debit"], d["credit"], *_drcr(d["closing"]), ""])
        return f"{d['ledger']['name']} ledger", _csv(f"{co} - {d['ledger']['name']} - {d['from']} to {d['to']}",
            ["Date", "Particulars", "Voucher type", "Voucher no.", "Debit", "Credit", "Balance", "Dr/Cr", "Narration"], rows)
    if what == "vouchers":
        rows, off = [], 0
        while True:
            d = store.vouchers(cid, q.get("q", ""), f, t, q.get("type", ""), off, q.get("sub", ""))
            rows += [[v["date"], v["vtype"], v["number"], v["party"], v["amount"], v.get("status") or "", v.get("narration") or ""]
                     for v in d["vouchers"]]
            off += len(d["vouchers"])
            if not d["vouchers"] or off >= d["total"]:
                break
        return "vouchers", _csv(f"{co} - vouchers {d['from']} to {d['to']}",
                                ["Date", "Type", "Number", "Party", "Amount", "Status", "Narration"], rows)
    if what == "outstanding":
        kind = q.get("kind", "receivable")
        d = store.outstanding(cid, kind)
        rows = []
        for p in d["parties"]:
            for b in p["bills"]:
                rows.append([p["name"], b["ref"], b["date"] or "", b["due"] or "", b["amount"], b["age"], b["overdue"] or "",
                             p["mobile"] or p["phone"] or ""])
        return f"{kind} bills", _csv(f"{co} - {'to receive' if kind == 'receivable' else 'to pay'}",
                                     ["Party", "Bill", "Bill date", "Due date", "Amount", "Days old", "Days overdue", "Phone"], rows)
    if what == "stock":
        d = store.stock(cid, "", f, t)
        return "stock", _csv(f"{co} - stock summary {d['from']} to {d['to']}",
                             ["Item", "Group", "Unit", "Opening qty", "Opening value (approx.)", "Inward qty", "Outward qty",
                              "Closing qty", "Rate", "Closing value"],
                             [[i["name"], i["parent"], i["unit"], i["open_qty"], i["open_value"], i["in_qty"], i["out_qty"],
                               i["close_qty"], i["rate"], i["close_value"]] for i in d["items"]])
    if what == "daily":
        kind = q.get("kind", "sales")
        d = store.daily(cid, kind, f, t, q.get("sub", ""))
        return f"{kind} by day", _csv(f"{co} - {kind} by day {d['from']} to {d['to']}",
                                      ["Date", "Bills", "With tax", "Before tax", "Returns"],
                                      [[x["date"], x["bills"], x["total"], x["net"], x["returns"]] for x in d["days"]])
    if what == "a_parties":
        kind = q.get("kind", "sales")
        d = store.analysis_parties(cid, kind, f, t)
        return f"{kind} by party", _csv(f"{co} - {kind} by party {d['from']} to {d['to']}",
                                        ["Party", "Bills", "Value", "Share %", "Same period last year", "Change %", "Last bill"],
                                        [[r["party"], r["bills"], r["total"], r["share"], r["prev"], r["change"], r["last"]]
                                         for r in d["parties"]])
    if what == "a_items":
        d = store.analysis_items(cid, f, t)
        return "sales by item", _csv(f"{co} - sales by item {d['from']} to {d['to']}",
                                     ["Item", "Quantity", "Unit", "Value", "Avg sale rate", "Avg purchase rate", "Margin %", "Share %", "In hand"],
                                     [[r["item"], r["qty"], r["unit"], r["value"], r["rate"], r["buy_rate"], r["margin"], r["share"], r["in_hand"]]
                                      for r in d["items"]])
    if what == "a_slow":
        d = store.slow_stock(cid, int(q.get("days", 60) or 60))
        return "slow stock", _csv(f"{co} - stock not sold for {d['days']}+ days", ["Item", "Quantity", "Unit", "Value", "Last sold", "Days idle"],
                                  [[i["name"], i["closing_qty"], i["unit"], i["closing_value"], i["last_out"] or "never", i["idle"]]
                                   for i in d["items"]])
    return None
