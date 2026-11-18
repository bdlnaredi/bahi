"""Who did what in the app: every change made by the owner or staff (entries, quotations, reminders, settings,
logins), one line each in activity.log, newest kept. Only the owner sees it. Nothing here touches Tally."""
import json
import os
import re
import threading
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
FILE = os.path.join(DATA_DIR, "activity.log")
KEEP = 5000
_lock = threading.Lock()
_n = [0]

KINDS = {"receipt": "receipt", "payment": "payment", "sales": "sales invoice", "order": "sales order",
         "purchase": "purchase", "expense": "expense", "contra": "contra", "journal": "journal", "stockitem": "new stock item"}


def _money(v):
    try:
        return f" ₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


def describe(path, data, companies):
    """A plain sentence for a change, or None when it isn't worth logging."""
    d = data if isinstance(data, dict) else {}
    party = str(d.get("party") or d.get("name") or "")[:80]
    m = re.match(r"^/api/c/(\d+)/(.*)$", path)
    co = companies.get(int(m.group(1)), "") if m else ""
    rest = m.group(2) if m else path[5:]
    if path == "/api/login":
        return "Logged in", ""
    if rest == "entry":
        kind = KINDS.get(str(d.get("kind", "")), str(d.get("kind", "entry")))
        amt = d.get("amount") or sum(float(x.get("amount") or 0) for x in d.get("items") or [] if isinstance(x, dict)) or None
        return f"Made a {kind}" + (f" for {party}" if party else "") + (_money(amt) if amt else ""), co
    mm = re.match(r"^entry/(\d+)/([a-z]+)$", rest)
    if mm:
        return f"{mm.group(2).capitalize()} phone entry #{mm.group(1)}", co
    if rest.startswith("quotes"):
        if rest.endswith("/delete"):
            return "Deleted a quotation", co
        if rest.endswith("/status"):
            return f"Marked a quotation {d.get('status', '')}", co
        return "Saved a quotation" + (f" for {party}" if party else "") , co
    simple = {"followup": f"Noted a follow-up for {party}", "barcodes": "Changed item barcodes",
              "stock_min": "Changed minimum stock levels", "brs": "Worked on bank reconciliation"}
    if rest == "entry_photo":
        return None                              # the entry it belongs to is logged
    if rest.startswith("gstr_one_tally/"):
        return ("Removed" if rest.endswith("/delete") else "Uploaded") + f" Tally's GSTR-1 for {rest.split('/')[1]}", co
    if rest.startswith("gstr_three_tally/"):
        return ("Removed" if rest.endswith("/delete") else "Uploaded") + f" Tally's GSTR-3B for {rest.split('/')[1]}", co
    if rest == "cheques":
        return f"Wrote down a cheque {'from' if d.get('kind') != 'out' else 'to'} {party} #{d.get('number', '')}" + _money(d.get("amount")), co
    if rest.startswith("cheques/"):
        return f"Marked a cheque {d.get('status', '')}", co
    if rest == "stockcount":
        return "Started a stock count", co
    if rest.startswith("stockcount/"):
        if rest.endswith("/status"):
            return f"Stock count: {'finished' if d.get('status') == 'done' else d.get('status', '')}", co
        return None                              # each item counted isn't worth a line
    if rest in simple:
        return simple[rest], co
    top = {"/api/statement_sent": f"Sent month-end statement to {party}", "/api/reminded": f"Sent payment reminder to {party}",
           "/api/target": "Changed the sales target", "/api/sync/now": "Asked for a sync now", "/api/sync": "Changed sync settings",
           "/api/password": "Changed a password", "/api/backups/restore": "Restored a backup",
           "/api/telegram": "Changed Telegram settings", "/api/credit": "Changed credit warning settings"}
    if path in top:
        cid = d.get("cid")
        try:
            co = companies.get(int(cid), "") if cid not in (None, "") else ""
        except (TypeError, ValueError):
            co = ""
        return top[path], co
    if path.startswith("/api/"):
        what = (rest if m else path[5:]).split("/")[0].replace("_", " ")
        return f"Changed {what}", co
    return None


def log(user, path, raw, companies, ip=""):
    try:
        data = json.loads(raw or b"{}") if raw and len(raw) < 200000 else {}
    except ValueError:
        data = {}
    r = describe(path, data, companies)
    if not r:
        return
    text, co = r
    line = json.dumps({"t": round(time.time()), "user": user or "Owner", "text": text, "company": co, "ip": ip}, ensure_ascii=False)
    with _lock:
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        _n[0] += 1
        if _n[0] % 200 == 0:                    # now and then, keep only the newest lines
            try:
                with open(FILE, encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > KEEP:
                    with open(FILE + ".tmp", "w", encoding="utf-8") as f:
                        f.writelines(lines[-KEEP:])
                    os.replace(FILE + ".tmp", FILE)
            except OSError:
                pass


def listing(user="", limit=300):
    try:
        with open(FILE, encoding="utf-8") as f:
            lines = f.readlines()[-KEEP:]
    except OSError:
        lines = []
    out, people = [], set()
    for ln in reversed(lines):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        people.add(r.get("user", ""))
        if user and r.get("user") != user:
            continue
        if len(out) < limit:
            out.append(r)
    return {"items": out, "people": sorted(p for p in people if p)}
