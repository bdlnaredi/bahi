"""SQLite storage, ingest of a sync run, and the report queries."""
import json
import os
import sqlite3
import threading
import time
from datetime import date, timedelta

DB_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "tally.db")
_lock = threading.Lock()

SCHEMA_VERSION = "5"
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS company(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, last_sync REAL, last_seen REAL,
  from_date TEXT, to_date TEXT, alt_vch TEXT, alt_mst TEXT, unbalanced INTEGER DEFAULT 0,
  bills_source TEXT DEFAULT 'vouchers', info TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS grp(
  company_id INT, name TEXT, parent TEXT, chain TEXT, PRIMARY KEY(company_id, name));
CREATE TABLE IF NOT EXISTS vtype(
  company_id INT, name TEXT, base TEXT, PRIMARY KEY(company_id, name));
CREATE TABLE IF NOT EXISTS ledger(
  company_id INT, name TEXT, parent TEXT, chain TEXT, opening REAL, closing REAL,
  phone TEXT, mobile TEXT, email TEXT, gstin TEXT, taxtype TEXT, gst_head TEXT, extra TEXT DEFAULT '{}',
  PRIMARY KEY(company_id, name));
CREATE TABLE IF NOT EXISTS stock(
  company_id INT, name TEXT, parent TEXT, unit TEXT, opening_qty REAL, opening_value REAL,
  closing_qty REAL, closing_value REAL, closing_rate REAL, hsn TEXT DEFAULT '', PRIMARY KEY(company_id, name));
CREATE TABLE IF NOT EXISTS voucher(
  id INTEGER PRIMARY KEY, company_id INT, guid TEXT, date TEXT, vtype TEXT, base TEXT,
  number TEXT, party TEXT, narration TEXT, amount REAL, balanced INT, reference TEXT, party_gstin TEXT,
  extra TEXT DEFAULT '{}', posting INT DEFAULT 1, imbalance REAL DEFAULT 0, status TEXT DEFAULT '',
  alterid INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_v_guid ON voucher(company_id, guid);
CREATE INDEX IF NOT EXISTS ix_v_date ON voucher(company_id, date);
CREATE TABLE IF NOT EXISTS vline(voucher_id INT, ledger TEXT, amount REAL);
CREATE INDEX IF NOT EXISTS ix_vl_l ON vline(ledger, voucher_id);
CREATE INDEX IF NOT EXISTS ix_vl_v ON vline(voucher_id);
CREATE TABLE IF NOT EXISTS vitem(voucher_id INT, item TEXT, qty REAL, unit TEXT, rate REAL, amount REAL,
  hsn TEXT DEFAULT '', disc REAL DEFAULT 0, descr TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_vi_i ON vitem(item, voucher_id);
CREATE INDEX IF NOT EXISTS ix_vi_v ON vitem(voucher_id);
CREATE TABLE IF NOT EXISTS vline_np(voucher_id INT, ledger TEXT, amount REAL);
CREATE INDEX IF NOT EXISTS ix_vlnp_v ON vline_np(voucher_id);
CREATE TABLE IF NOT EXISTS vitem_np(voucher_id INT, item TEXT, qty REAL, unit TEXT, rate REAL, amount REAL,
  hsn TEXT DEFAULT '', disc REAL DEFAULT 0, descr TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_vinp_v ON vitem_np(voucher_id);
CREATE TABLE IF NOT EXISTS vbill(voucher_id INT, ledger TEXT, name TEXT, btype TEXT, amount REAL, days INT);
CREATE INDEX IF NOT EXISTS ix_vb_v ON vbill(voucher_id);
CREATE INDEX IF NOT EXISTS ix_vb_l ON vbill(ledger);
CREATE TABLE IF NOT EXISTS bill(company_id INT, kind TEXT, party TEXT, ref TEXT, date TEXT, due TEXT, amount REAL);
CREATE INDEX IF NOT EXISTS ix_b ON bill(company_id, kind, party);
"""

BASE_TYPES = {"Sales", "Purchase", "Receipt", "Payment", "Journal", "Contra",
              "Credit Note", "Debit Note", "Stock Journal", "Delivery Note",
              "Receipt Note", "Rejections In", "Rejections Out", "Physical Stock",
              "Material In", "Material Out", "Sales Order", "Purchase Order", "Memorandum",
              "Reversing Journal", "Payroll", "Attendance", "Job Work In Order", "Job Work Out Order"}


# Vouchers Tally keeps out of the books (they never change ledger balances) and out of stock
NO_ACCOUNTS = {"Sales Order", "Purchase Order", "Memorandum", "Reversing Journal", "Job Work In Order",
               "Job Work Out Order", "Attendance"}
NO_STOCK = NO_ACCOUNTS | {"Physical Stock"}


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    """Create tables. An older database layout is dropped; the next sync refills it."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with conn() as c:
        ver = None
        try:
            r = c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            ver = r["value"] if r else None
        except sqlite3.OperationalError:
            pass
        if ver != SCHEMA_VERSION:
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                c.execute(f'DROP TABLE IF EXISTS "{t}"')
        c.executescript(SCHEMA)
        _migrate(c)
        c.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (SCHEMA_VERSION,))


def _chains(groups):
    parent = {g["name"]: g["parent"] for g in groups}
    out = {}
    for g in parent:
        seen, cur, path = set(), g, []
        while cur and cur not in seen:
            seen.add(cur)
            path.append(cur)
            cur = parent.get(cur, "")
        out[g] = "|" + "|".join(reversed(path)) + "|"
    return out


def _base_types(vtypes):
    parent = {v["name"]: v["parent"] for v in vtypes}
    out = {}
    for n in parent:
        cur, seen = n, set()
        while cur and cur not in BASE_TYPES and cur not in seen:
            seen.add(cur)
            cur = parent.get(cur, "")
        out[n] = cur if cur in BASE_TYPES else n
    return out


def company_id(c, name):
    r = c.execute("SELECT id FROM company WHERE name=?", (name,)).fetchone()
    if r:
        return r["id"]
    return c.execute("INSERT INTO company(name) VALUES(?)", (name,)).lastrowid


def heartbeat(names):
    with _lock, conn() as c:
        for n in names:
            cid = company_id(c, n)
            c.execute("UPDATE company SET last_seen=? WHERE id=?", (time.time(), cid))


def _migrate(c):
    cols = [r[1] for r in c.execute("PRAGMA table_info(company)")]
    if "keep_from" not in cols:
        c.execute("ALTER TABLE company ADD COLUMN keep_from TEXT DEFAULT ''")


def get_alt(name):
    with conn() as c:
        r = c.execute("SELECT alt_vch, alt_mst, from_date, last_sync, keep_from FROM company WHERE name=?", (name,)).fetchone()
        return dict(r) if r else {}


def keep_from(c, cid):
    r = c.execute("SELECT keep_from FROM company WHERE id=?", (cid,)).fetchone()
    return (r["keep_from"] if r else "") or ""


def purge_before(cid, day):
    """Delete vouchers dated before `day` and stop accepting them in future syncs."""
    with _lock, conn() as c:
        old = "SELECT id FROM voucher WHERE company_id=? AND date < ?"
        for t in ("vline", "vitem", "vbill", "vline_np", "vitem_np"):
            c.execute(f"DELETE FROM {t} WHERE voucher_id IN ({old})", (cid, day))
        n = c.execute("DELETE FROM voucher WHERE company_id=? AND date < ?", (cid, day)).rowcount
        c.execute("UPDATE company SET keep_from=?, from_date=MAX(COALESCE(from_date,''), ?) WHERE id=?", (day, day, cid))
    with conn() as c:
        c.execute("VACUUM")
    return n


def delete_company(cid):
    """Remove everything synced for a company. If it is still open in Tally, the next sync brings it back."""
    with _lock, conn() as c:
        ids = "SELECT id FROM voucher WHERE company_id=?"
        for t in ("vline", "vitem", "vbill", "vline_np", "vitem_np"):
            c.execute(f"DELETE FROM {t} WHERE voucher_id IN ({ids})", (cid,))
        for t in ("voucher", "grp", "vtype", "ledger", "stock", "bill"):
            c.execute(f"DELETE FROM {t} WHERE company_id=?", (cid,))
        c.execute("DELETE FROM company WHERE id=?", (cid,))
    with conn() as c:
        c.execute("VACUUM")


def _month_range(m, d_from, d_to):
    y, mo = int(m[:4]), int(m[5:7])
    last = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).isoformat()
    return max(f"{m}-01", d_from), min(last, d_to)


def plan(company, d_from, d_to, tally_list):
    """Compare Tally's list of (GUID, AlterID, date) with what is stored; return the months to resend."""
    with conn() as c:
        r = c.execute("SELECT id, from_date, to_date, keep_from FROM company WHERE name=? AND last_sync IS NOT NULL",
                      (company,)).fetchone()
        if not r or r["from_date"] != max(d_from, r["keep_from"] or "") or r["to_date"] != d_to:
            return {"full": True, "months": []}
        stored = {g: (a, d) for g, a, d in c.execute(
            "SELECT guid, alterid, date FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?", (r["id"], d_from, d_to))}
    if not stored:
        return {"full": True, "months": []}
    months, seen, counts_t, counts_s = set(), set(), {}, {}
    for g, a, d in tally_list:
        if not (d_from <= d <= d_to):
            continue
        counts_t[d[:7]] = counts_t.get(d[:7], 0) + 1
        s_ = stored.get(g) if g else None
        if s_ is None or s_[0] != a or s_[1] != d:
            months.add(d[:7])
            if s_:
                months.add(s_[1][:7])
        seen.add(g)
    for g, (a, d) in stored.items():
        counts_s[d[:7]] = counts_s.get(d[:7], 0) + 1
        if g not in seen:
            months.add(d[:7])          # deleted in Tally
    for m in set(counts_t) | set(counts_s):
        if counts_t.get(m, 0) != counts_s.get(m, 0):
            months.add(m)
    return {"full": False, "months": sorted(months)}


def ingest(company, d_from, d_to, alt_vch, alt_mst, groups, vtypes, ledgers, stock, vouchers,
           bills_rec=None, bills_pay=None, info=None, ledger_x=None, stock_x=None, months=None):
    """Store a sync. Masters are replaced when sent (groups/types/details are kept if a partial sync left them out).
    Vouchers are replaced for the whole [d_from, d_to] range, or only for `months` (YYYY-MM) on a partial sync."""
    with _lock, conn() as c:
        cid = company_id(c, company)
        kf = keep_from(c, cid)
        if kf and d_from < kf:
            d_from = kf
            vouchers = [v for v in vouchers if v["date"] >= kf]
        partial = months is not None
        if groups or not partial:
            chains = _chains(groups)
            c.execute("DELETE FROM grp WHERE company_id=?", (cid,))
            c.executemany("INSERT OR REPLACE INTO grp VALUES(?,?,?,?)",
                          [(cid, g["name"], g["parent"], chains[g["name"]]) for g in groups])
        else:
            chains = {r["name"]: r["chain"] for r in c.execute("SELECT name, chain FROM grp WHERE company_id=?", (cid,))}
        if vtypes or not partial:
            bases = _base_types(vtypes)
            c.execute("DELETE FROM vtype WHERE company_id=?", (cid,))
            c.executemany("INSERT OR REPLACE INTO vtype VALUES(?,?,?)", [(cid, n, b) for n, b in bases.items()])
        else:
            bases = {r["name"]: r["base"] for r in c.execute("SELECT name, base FROM vtype WHERE company_id=?", (cid,))}
        if not ledger_x and partial:
            ledger_x = {r["name"]: json.loads(r["extra"] or "{}") for r in
                        c.execute("SELECT name, extra FROM ledger WHERE company_id=?", (cid,))}
        if not stock_x and partial:
            stock_x = {r["name"]: {"hsn": r["hsn"]} for r in c.execute("SELECT name, hsn FROM stock WHERE company_id=?", (cid,))}
        ledger_x = ledger_x or {}
        stock_x = stock_x or {}
        if ledgers or not partial:
            c.execute("DELETE FROM ledger WHERE company_id=?", (cid,))
            c.executemany("INSERT OR REPLACE INTO ledger VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                (cid, l["name"], l["parent"],
                 chains.get(l["parent"], "|" + l["parent"] + "|") + l["name"] + "|",
                 round(l["opening"], 2), round(l["closing"], 2),
                 l["phone"], l["mobile"], l["email"], l["gstin"] or ledger_x.get(l["name"], {}).get("gstin", ""),
                 l.get("taxtype", ""), l.get("gst_head", ""), json.dumps(ledger_x.get(l["name"], {})))
                for l in ledgers])
        if stock or not partial:
            c.execute("DELETE FROM stock WHERE company_id=?", (cid,))
            c.executemany("INSERT OR REPLACE INTO stock VALUES(?,?,?,?,?,?,?,?,?,?)", [
                (cid, s["name"], s["parent"], s["unit"], s["opening_qty"], s["opening_value"],
                 s["closing_qty"], s["closing_value"], s["closing_rate"], stock_x.get(s["name"], {}).get("hsn", ""))
                for s in stock])

        ranges = [_month_range(m, d_from, d_to) for m in months] if partial else [(d_from, d_to)]
        ranges = [(a, b) for a, b in ranges if a <= b]
        for a, b in ranges:
            old = "SELECT id FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?"
            for t in ("vline", "vitem", "vbill", "vline_np", "vitem_np"):
                c.execute(f"DELETE FROM {t} WHERE voucher_id IN ({old})", (cid, a, b))
            c.execute("DELETE FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?", (cid, a, b))
        inserted = 0
        for v in vouchers:
            if not any(a <= v["date"] <= b for a, b in ranges):
                continue
            inserted += 1
            base = bases.get(v["vtype"], v["vtype"])
            status = v.get("status", "")
            posting = base not in NO_ACCOUNTS and not status
            vid = c.execute(
                "INSERT INTO voucher(company_id,guid,date,vtype,base,number,party,narration,amount,balanced,"
                "reference,party_gstin,extra,posting,imbalance,status,alterid) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, v["guid"], v["date"], v["vtype"], base, v["number"],
                 v["party"], v["narration"], v["amount"], 1 if (v["balanced"] or not posting) else 0,
                 v.get("reference", ""), v.get("party_gstin", ""), json.dumps(v.get("extra", {})),
                 1 if posting else 0, v.get("imbalance", 0), status, v.get("alterid", 0))).lastrowid
            agg = {}
            for ln, a in v["lines"]:
                agg[ln] = agg.get(ln, 0) + a
            c.executemany(f"INSERT INTO {'vline' if posting else 'vline_np'} VALUES(?,?,?)",
                          [(vid, ln, round(a, 2)) for ln, a in agg.items()])
            c.executemany(f"INSERT INTO {'vitem_np' if (base in NO_STOCK or status) else 'vitem'} VALUES(?,?,?,?,?,?,?,?,?)",
                          [(vid, i["item"], i["qty"], i["unit"], i["rate"], i["amount"],
                            i.get("hsn") or stock_x.get(i["item"], {}).get("hsn", ""), i.get("disc", 0), i.get("descr", ""))
                           for i in v["items"]])
            if posting:
                c.executemany("INSERT INTO vbill VALUES(?,?,?,?,?,?)",
                              [(vid, b["ledger"], b["name"], b["type"], round(b["amount"], 2), b["days"])
                               for b in v.get("bills", [])])

        if bills_rec is not None or bills_pay is not None or not partial:
            source = "vouchers"
            c.execute("DELETE FROM bill WHERE company_id=?", (cid,))
            if bills_rec is not None or bills_pay is not None:
                source = "tally"
                for kind, rows in (("receivable", bills_rec or []), ("payable", bills_pay or [])):
                    c.executemany("INSERT INTO bill VALUES(?,?,?,?,?,?,?)",
                                  [(cid, kind, b["party"], b["ref"], b["date"], b["due"], round(b["amount"], 2))
                                   for b in rows])
            c.execute("UPDATE company SET bills_source=? WHERE id=?", (source, cid))
        if info or not partial:
            c.execute("UPDATE company SET info=? WHERE id=?", (json.dumps(info or {}), cid))
        unbalanced = c.execute("SELECT COUNT(*) n FROM voucher WHERE company_id=? AND balanced=0", (cid,)).fetchone()["n"]
        now = time.time()
        c.execute("UPDATE company SET last_sync=?, last_seen=?, from_date=?, to_date=?, alt_vch=?, alt_mst=?,"
                  " unbalanced=? WHERE id=?", (now, now, d_from, d_to, alt_vch, alt_mst, unbalanced, cid))
        n_v = c.execute("SELECT COUNT(*) n FROM voucher WHERE company_id=?", (cid,)).fetchone()["n"]
    return {"ledgers": len(ledgers), "stock": len(stock), "vouchers": n_v, "unbalanced": unbalanced,
            "changed": inserted, "months": len(ranges) if partial else "all"}


# ---------------------------------------------------------------- reports

def _rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def companies():
    with conn() as c:
        return _rows(c, """SELECT id, name, last_sync, last_seen, from_date, to_date, unbalanced, keep_from,
            (SELECT MIN(date) FROM voucher v WHERE v.company_id=company.id) first_vch,
            (SELECT MAX(date) FROM voucher v WHERE v.company_id=company.id) last_vch,
            (SELECT COUNT(*) FROM ledger l WHERE l.company_id=company.id) ledgers,
            (SELECT COUNT(*) FROM voucher v WHERE v.company_id=company.id) vouchers
            FROM company WHERE last_sync IS NOT NULL ORDER BY name""")


def fy_bounds(day=None):
    d = day or date.today()
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-04-01", f"{y + 1}-03-31"


def period(c, cid, d_from, d_to):
    """Explicit dates win; otherwise the current financial year (April to March)."""
    if d_from and d_to:
        return d_from, d_to
    fs, fe = fy_bounds()
    r = c.execute("SELECT MAX(date) m FROM voucher WHERE company_id=?", (cid,)).fetchone()
    if r and r["m"] and r["m"] < fs:          # company's books end before this year (an old year's company)
        fs, fe = fy_bounds(date.fromisoformat(r["m"]))
    return d_from or fs, d_to or fe


def _sum_group(c, cid, group, f, t):
    r = c.execute("""SELECT COALESCE(SUM(vl.amount),0) s FROM vline vl
        JOIN voucher v ON v.id=vl.voucher_id
        JOIN ledger l ON l.company_id=v.company_id AND l.name=vl.ledger
        WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND l.chain LIKE ?""",
                  (cid, f, t, f"%|{group}|%")).fetchone()
    return r["s"]


def _closing_group(c, cid, group):
    return c.execute("SELECT COALESCE(SUM(closing),0) s FROM ledger WHERE company_id=? AND chain LIKE ?",
                     (cid, f"%|{group}|%")).fetchone()["s"]


def dashboard(cid, d_from=None, d_to=None):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        today = date.today().isoformat()
        month_start = today[:8] + "01"
        sales = -_sum_group(c, cid, "Sales Accounts", f, t)
        purchase = _sum_group(c, cid, "Purchase Accounts", f, t)
        sales_m = -_sum_group(c, cid, "Sales Accounts", max(f, month_start), today)
        monthly = _rows(c, """SELECT substr(v.date,1,7) m, -SUM(vl.amount) s FROM vline vl
            JOIN voucher v ON v.id=vl.voucher_id
            JOIN ledger l ON l.company_id=v.company_id AND l.name=vl.ledger
            WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND l.chain LIKE '%|Sales Accounts|%'
            GROUP BY m ORDER BY m""", (cid, f, t))
        banks = _rows(c, """SELECT name, closing FROM ledger WHERE company_id=?
            AND (chain LIKE '%|Bank Accounts|%' OR chain LIKE '%|Bank OD A/c|%') ORDER BY closing DESC""", (cid,))
        top_debtors = _rows(c, """SELECT name, closing, mobile FROM ledger WHERE company_id=?
            AND chain LIKE '%|Sundry Debtors|%' AND closing > 0.5 ORDER BY closing DESC LIMIT 5""", (cid,))
        recent = _rows(c, """SELECT id, date, vtype, base, number, party, amount, status FROM voucher
            WHERE company_id=? ORDER BY date DESC, id DESC LIMIT 8""", (cid,))
        info = dict(c.execute("SELECT name, last_sync, last_seen, from_date, to_date, unbalanced FROM company WHERE id=?",
                              (cid,)).fetchone())
        return {
            "company": info, "from": f, "to": t,
            "sales": sales, "sales_month": sales_m, "purchase": purchase,
            "receivable": _closing_group(c, cid, "Sundry Debtors"),
            "payable": -_closing_group(c, cid, "Sundry Creditors"),
            "cash": _closing_group(c, cid, "Cash-in-Hand"),
            "bank_total": sum(b["closing"] for b in banks),
            "banks": banks,
            "stock_value": c.execute("SELECT COALESCE(SUM(closing_value),0) s FROM stock WHERE company_id=?",
                                     (cid,)).fetchone()["s"],
            "monthly_sales": monthly, "top_debtors": top_debtors, "recent": recent,
        }


LEDGER_SORTS = {"name": "name COLLATE NOCASE", "balance": "ABS(closing) DESC, name COLLATE NOCASE",
                "recent": "last_txn IS NULL, last_txn DESC, name COLLATE NOCASE"}


def ledgers(cid, q="", sort="name"):
    order = LEDGER_SORTS.get(sort, LEDGER_SORTS["name"])
    with conn() as c:
        return _rows(c, f"""SELECT l.name, l.parent, l.closing,
            (SELECT MAX(v.date) FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
              WHERE vl.ledger=l.name AND v.company_id=l.company_id) last_txn
            FROM ledger l WHERE l.company_id=? AND l.name LIKE ? ORDER BY {order}""", (cid, f"%{q}%"))


def daily(cid, kind="sales", d_from=None, d_to=None):
    """Day-by-day sales (or purchases): bills, value with tax, value before tax, returns."""
    base, ret, grp, sign = (("Sales", "Credit Note", "Sales Accounts", -1) if kind == "sales"
                            else ("Purchase", "Debit Note", "Purchase Accounts", 1))
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        days = {}
        for r in c.execute("""SELECT date, COUNT(*) n, SUM(amount) total FROM voucher
                WHERE company_id=? AND base=? AND posting=1 AND date BETWEEN ? AND ? GROUP BY date""", (cid, base, f, t)):
            days[r["date"]] = {"date": r["date"], "bills": r["n"], "total": round(r["total"] or 0, 2), "net": 0.0, "returns": 0.0}
        for r in c.execute("""SELECT date, SUM(amount) total FROM voucher
                WHERE company_id=? AND base=? AND posting=1 AND date BETWEEN ? AND ? GROUP BY date""", (cid, ret, f, t)):
            d = days.setdefault(r["date"], {"date": r["date"], "bills": 0, "total": 0.0, "net": 0.0, "returns": 0.0})
            d["returns"] = round(r["total"] or 0, 2)
        for r in c.execute("""SELECT v.date, SUM(vl.amount) s FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
                JOIN ledger l ON l.company_id=v.company_id AND l.name=vl.ledger
                WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND l.chain LIKE ? GROUP BY v.date""",
                             (cid, f, t, f"%|{grp}|%")):
            d = days.setdefault(r["date"], {"date": r["date"], "bills": 0, "total": 0.0, "net": 0.0, "returns": 0.0})
            d["net"] = round(sign * (r["s"] or 0), 2)
    rows = sorted(days.values(), key=lambda d: d["date"], reverse=True)
    best = max(rows, key=lambda d: d["total"], default=None)
    active = [d for d in rows if d["bills"]]
    return {"kind": kind, "from": f, "to": t, "days": rows,
            "total": round(sum(d["total"] for d in rows), 2), "net": round(sum(d["net"] for d in rows), 2),
            "returns": round(sum(d["returns"] for d in rows), 2), "bills": sum(d["bills"] for d in rows),
            "avg": round(sum(d["total"] for d in active) / len(active), 2) if active else 0,
            "best": best}


def ledger(cid, name, d_from=None, d_to=None):
    with conn() as c:
        info = c.execute("SELECT * FROM ledger WHERE company_id=? AND name=?", (cid, name)).fetchone()
        if not info:
            return None
        info = dict(info)
        info["extra"] = json.loads(info.get("extra") or "{}")
        comp = c.execute("SELECT from_date, to_date, name, info FROM company WHERE id=?", (cid,)).fetchone()
        sync_from = comp["from_date"] or "2000-01-01"
        f, t = period(c, cid, d_from, d_to)
        f = max(f, sync_from)
        total_synced = c.execute("""SELECT COALESCE(SUM(vl.amount),0) s FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
            WHERE v.company_id=? AND vl.ledger=? AND v.date >= ?""", (cid, name, sync_from)).fetchone()["s"]
        # Opening at the start of synced data = Tally's closing minus every synced movement.
        opening_sync = info["closing"] - total_synced
        before = c.execute("""SELECT COALESCE(SUM(vl.amount),0) s FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
            WHERE v.company_id=? AND vl.ledger=? AND v.date >= ? AND v.date < ?""",
                           (cid, name, sync_from, f)).fetchone()["s"]
        opening = opening_sync + before
        rows = _rows(c, """SELECT v.id, v.date, v.vtype, v.number, v.narration, SUM(vl.amount) amount
            FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
            WHERE v.company_id=? AND vl.ledger=? AND v.date BETWEEN ? AND ?
            GROUP BY v.id ORDER BY v.date, v.id""", (cid, name, f, t))
        # "Particulars" like Tally: the biggest ledger on the opposite side of this entry
        for r in rows:
            opp = c.execute("""SELECT ledger FROM vline WHERE voucher_id=? AND ledger<>? AND amount * ? < 0
                ORDER BY ABS(amount) DESC LIMIT 1""", (r["id"], name, r["amount"])).fetchone()
            r["against"] = opp["ledger"] if opp else ""
        bal = opening
        dr = cr = 0.0
        for r in rows:
            bal += r["amount"]
            r["balance"] = round(bal, 2)
            if r["amount"] > 0:
                dr += r["amount"]
            else:
                cr -= r["amount"]
        kind, bills = ledger_bills(c, cid, name)
        return {"ledger": info, "from": f, "to": t, "opening": round(opening, 2),
                "debit": round(dr, 2), "credit": round(cr, 2), "closing": round(bal, 2), "entries": rows,
                "bill_kind": kind, "bills": bills,
                "company": comp["name"], "company_info": json.loads(comp["info"] or "{}")}


def group(cid, name=""):
    with conn() as c:
        if name:
            g = c.execute("SELECT chain FROM grp WHERE company_id=? AND name=?", (cid, name)).fetchone()
            chain = g["chain"] if g else "|" + name + "|"
            kids = _rows(c, "SELECT name FROM grp WHERE company_id=? AND parent=? ORDER BY name", (cid, name))
            leds = _rows(c, """SELECT name, closing FROM ledger WHERE company_id=? AND parent=?
                AND ABS(closing) > 0.005 ORDER BY ABS(closing) DESC""", (cid, name))
        else:
            chain = ""
            kids = _rows(c, "SELECT name FROM grp WHERE company_id=? AND parent='' ORDER BY name", (cid,))
            leds = []
        out = []
        for k in kids:
            s = _closing_group(c, cid, k["name"])
            n = c.execute("SELECT COUNT(*) n FROM ledger WHERE company_id=? AND chain LIKE ?",
                          (cid, f"%|{k['name']}|%")).fetchone()["n"]
            if n:
                out.append({"name": k["name"], "closing": round(s, 2), "count": n})
        out.sort(key=lambda x: -abs(x["closing"]))
        total = _closing_group(c, cid, name) if name else 0
        return {"name": name, "path": [p for p in chain.split("|") if p][:-1] if name else [],
                "total": round(total, 2), "groups": out, "ledgers": leds}


def stock(cid, q=""):
    with conn() as c:
        items = _rows(c, """SELECT name, parent, unit, closing_qty, closing_value, closing_rate FROM stock
            WHERE company_id=? AND name LIKE ? ORDER BY name COLLATE NOCASE""", (cid, f"%{q}%"))
        return {"items": items, "total": sum(i["closing_value"] for i in items)}


def stock_item(cid, name, d_from=None, d_to=None):
    with conn() as c:
        info = c.execute("SELECT * FROM stock WHERE company_id=? AND name=?", (cid, name)).fetchone()
        if not info:
            return None
        f, t = period(c, cid, d_from, d_to)
        rows = _rows(c, """SELECT v.id, v.date, v.vtype, v.number, v.party, SUM(vi.qty) qty, MAX(vi.rate) rate,
            SUM(vi.amount) amount FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
            WHERE v.company_id=? AND vi.item=? AND v.date BETWEEN ? AND ?
            GROUP BY v.id ORDER BY v.date DESC, v.id DESC""", (cid, name, f, t))
        inward = sum(r["qty"] for r in rows if r["qty"] > 0)
        outward = -sum(r["qty"] for r in rows if r["qty"] < 0)
        return {"item": dict(info), "from": f, "to": t, "inward": inward, "outward": outward, "moves": rows}


BUCKETS = ["0-30 days", "31-60 days", "61-90 days", "Over 90 days", "No bill date"]


def _bucket(age):
    if age is None:
        return BUCKETS[4]
    return BUCKETS[0] if age <= 30 else BUCKETS[1] if age <= 60 else BUCKETS[2] if age <= 90 else BUCKETS[3]


def _iso_add(d, days):
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def _bill_links(c, cid):
    """(party, bill name) -> id of the voucher that created the bill; also (party, voucher no.)."""
    links = {}
    for r in c.execute("""SELECT b.ledger, b.name, v.id FROM vbill b JOIN voucher v ON v.id=b.voucher_id
            WHERE v.company_id=? AND b.btype='New Ref' ORDER BY v.date DESC""", (cid,)):
        links[(r["ledger"], r["name"])] = r["id"]
    for r in c.execute("SELECT party, number, id FROM voucher WHERE company_id=? AND number<>''", (cid,)):
        links.setdefault((r["party"], r["number"]), r["id"])
    return links


def _bills_from_vouchers(c, party, sign):
    """Rebuild pending bills of one party from bill allocations in synced vouchers."""
    rows = c.execute("""SELECT b.name, b.btype, b.amount, b.days, v.date FROM vbill b
        JOIN voucher v ON v.id=b.voucher_id WHERE b.ledger=? ORDER BY v.date, v.id""", (party,)).fetchall()
    bills = {}
    for r in rows:
        if r["btype"] in ("Advance", "On Account") or not r["name"]:
            continue
        b = bills.setdefault(r["name"], {"ref": r["name"], "date": None, "due": None, "amount": 0.0})
        b["amount"] += r["amount"] * sign
        if r["btype"] == "New Ref" and not b["date"]:
            b["date"] = r["date"]
            if r["days"]:
                b["due"] = _iso_add(r["date"], r["days"])
    return [b for b in bills.values() if b["amount"] > 0.5]


def _party_bills(c, cid, kind, source):
    grp_name, sign = ("Sundry Debtors", 1) if kind == "receivable" else ("Sundry Creditors", -1)
    parties = _rows(c, """SELECT l.name, l.closing * ? amount, l.mobile, l.phone,
        (SELECT MAX(v.date) FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
          WHERE v.company_id=l.company_id AND vl.ledger=l.name) last_txn
        FROM ledger l WHERE l.company_id=? AND l.chain LIKE ? AND l.closing * ? > 0.5""",
                    (sign, cid, f"%|{grp_name}|%", sign))
    tally = {}
    if source == "tally":
        for r in c.execute("SELECT party, ref, date, due, amount FROM bill WHERE company_id=? AND kind=?",
                           (cid, kind)):
            tally.setdefault(r["party"], []).append(
                {"ref": r["ref"], "date": r["date"] or None, "due": r["due"] or None, "amount": r["amount"]})
    today = date.today()
    links = _bill_links(c, cid)
    for p in parties:
        bills = tally.get(p["name"], []) if source == "tally" else _bills_from_vouchers(c, p["name"], sign)
        diff = round(p["amount"] - sum(b["amount"] for b in bills), 2)
        if abs(diff) > 0.5:
            bills.append({"ref": "On account" if diff > 0 else "Advance / unadjusted",
                          "date": None, "due": None, "amount": diff})
        for b in bills:
            b["age"] = (today - date.fromisoformat(b["date"])).days if b["date"] else None
            b["overdue"] = (today - date.fromisoformat(b["due"])).days if b["due"] else None
            if b["overdue"] is not None and b["overdue"] <= 0:
                b["overdue"] = 0
            b["bucket"] = _bucket(b["age"])
            b["vid"] = links.get((p["name"], b["ref"]))
            b["amount"] = round(b["amount"], 2)
        bills.sort(key=lambda b: (b["date"] is None, b["date"] or ""))
        p["bills"] = bills
        ages = [b["age"] for b in bills if b["age"] is not None and b["amount"] > 0]
        p["oldest_days"] = max(ages) if ages else None
        p["overdue_amount"] = round(sum(b["amount"] for b in bills if (b["overdue"] or 0) > 0), 2)
    return parties


def outstanding(cid, kind):
    with conn() as c:
        source = (c.execute("SELECT bills_source FROM company WHERE id=?", (cid,)).fetchone() or {"bills_source": "vouchers"})["bills_source"]
        parties = _party_bills(c, cid, kind, source)
    buckets = {k: 0.0 for k in BUCKETS}
    for p in parties:
        for b in p["bills"]:
            buckets[b["bucket"]] += b["amount"]
    parties.sort(key=lambda p: -p["amount"])
    return {"kind": kind, "source": source, "total": round(sum(p["amount"] for p in parties), 2),
            "overdue": round(sum(p["overdue_amount"] for p in parties), 2),
            "buckets": [{"label": k, "amount": round(v, 2)} for k, v in buckets.items() if abs(v) > 0.005],
            "parties": parties}


def ledger_bills(c, cid, name):
    l = c.execute("SELECT chain FROM ledger WHERE company_id=? AND name=?", (cid, name)).fetchone()
    if not l:
        return None, []
    kind = "receivable" if "|Sundry Debtors|" in l["chain"] else "payable" if "|Sundry Creditors|" in l["chain"] else None
    if not kind:
        return None, []
    source = c.execute("SELECT bills_source FROM company WHERE id=?", (cid,)).fetchone()["bills_source"]
    for p in _party_bills(c, cid, kind, source):
        if p["name"] == name:
            return kind, p["bills"]
    return kind, []


PAGE = 200


def daybook(cid, d_from=None, d_to=None, base="", offset=0):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        args = [cid, f, t]
        extra = ""
        if base:
            extra = " AND base=?"
            args.append(base)
        rows = _rows(c, f"""SELECT id, date, vtype, base, number, party, amount, status FROM voucher
            WHERE company_id=? AND date BETWEEN ? AND ?{extra} ORDER BY date DESC, id DESC LIMIT ? OFFSET ?""",
                     args + [PAGE, int(offset)])
        total = c.execute(f"SELECT COUNT(*) n FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?{extra}", args).fetchone()["n"]
        types = [r["base"] for r in c.execute(
            "SELECT DISTINCT base FROM voucher WHERE company_id=? ORDER BY base", (cid,))]
        return {"from": f, "to": t, "vouchers": rows, "types": types, "total": total, "offset": int(offset)}


def vouchers(cid, q="", d_from=None, d_to=None, base="", offset=0):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        where, args = ["company_id=?", "date BETWEEN ? AND ?"], [cid, f, t]
        if base:
            where.append("base=?")
            args.append(base)
        q = (q or "").strip()
        if q:
            like = f"%{q}%"
            cond = "(party LIKE ? OR number LIKE ? OR narration LIKE ? OR reference LIKE ? OR vtype LIKE ?"
            args += [like] * 5
            try:
                n = float(q.replace(",", ""))
                cond += " OR ABS(amount - ?) < 1"
                args.append(n)
            except ValueError:
                pass
            where.append(cond + ")")
        rows = _rows(c, f"""SELECT id, date, vtype, base, number, party, amount, narration, status FROM voucher
            WHERE {' AND '.join(where)} ORDER BY (number = ?) DESC, date DESC, id DESC LIMIT ? OFFSET ?""",
                     args + [q, PAGE, int(offset)])
        total = c.execute(f"SELECT COUNT(*) n FROM voucher WHERE {' AND '.join(where)}", args).fetchone()["n"]
        types = [r["base"] for r in c.execute(
            "SELECT DISTINCT base FROM voucher WHERE company_id=? ORDER BY base", (cid,))]
        return {"from": f, "to": t, "vouchers": rows, "types": types, "q": q, "total": total, "offset": int(offset)}


def _is_tax(l):
    import re as _re
    return bool(l) and "|Duties & Taxes|" in (l["chain"] or "") and (
        (l["taxtype"] or "").upper() == "GST" or bool(l["gst_head"])
        or bool(_re.search(r"GST|CESS", l["name"] or "", _re.I)))


def voucher(cid, vid):
    with conn() as c:
        v = c.execute("SELECT * FROM voucher WHERE company_id=? AND id=?", (cid, vid)).fetchone()
        if not v:
            return None
        v = dict(v)
        lines = _rows(c, """SELECT vl.ledger, vl.amount, l.chain, l.taxtype, l.gst_head, l.name
            FROM (SELECT * FROM vline WHERE voucher_id=? UNION ALL SELECT * FROM vline_np WHERE voucher_id=?) vl
            LEFT JOIN ledger l ON l.company_id=? AND l.name=vl.ledger
            ORDER BY ABS(vl.amount) DESC""", (vid, vid, cid))
        for ln in lines:
            chain = ln.pop("chain") or ""
            ln["cashbank"] = any(g in chain for g in ("|Bank Accounts|", "|Cash-in-Hand|", "|Bank OD A/c|"))
            ln["kind"] = ("party" if ln["ledger"] == v["party"] else
                          "tax" if _is_tax({**ln, "chain": chain}) else
                          "sales" if "|Sales Accounts|" in chain or "|Purchase Accounts|" in chain else "other")
            for k in ("taxtype", "gst_head", "name"):
                ln.pop(k, None)
        party = c.execute("SELECT name, gstin, mobile, phone, email, chain, extra FROM ledger WHERE company_id=? AND name=?",
                          (cid, v["party"])).fetchone()
        crow = c.execute("SELECT name, info FROM company WHERE id=?", (cid,)).fetchone()
        v["extra"] = json.loads(v.get("extra") or "{}")
        bank = None
        for b in c.execute("""SELECT name, extra FROM ledger WHERE company_id=? AND chain LIKE '%|Bank Accounts|%'
                ORDER BY ABS(closing) DESC""", (cid,)):
            bx = json.loads(b["extra"] or "{}")
            if bx.get("bank_account"):
                bank = {"name": b["name"], **bx}
                break
        pinfo = None
        if party:
            pinfo = {k: party[k] for k in ("name", "gstin", "mobile", "phone", "email")}
            pinfo.update(json.loads(party["extra"] or "{}"))
            pinfo["gstin"] = party["gstin"] or pinfo.get("gstin", "")
        return {"company": crow["name"], "company_info": json.loads(crow["info"] or "{}"), "bank": bank,
                "voucher": v, "lines": lines,
                "items": _rows(c, """SELECT item, qty, unit, rate, amount, hsn, disc, descr FROM vitem WHERE voucher_id=?
                    UNION ALL SELECT item, qty, unit, rate, amount, hsn, disc, descr FROM vitem_np WHERE voucher_id=?""", (vid, vid)),
                "bills": [dict(b, vid=(c.execute("""SELECT v.id FROM vbill x JOIN voucher v ON v.id=x.voucher_id
                    WHERE v.company_id=? AND x.ledger=? AND x.name=? AND x.btype='New Ref' AND v.id<>? LIMIT 1""",
                    (cid, b["ledger"], b["name"], vid)).fetchone() or {"id": None})["id"])
                    for b in _rows(c, "SELECT ledger, name, btype, amount, days FROM vbill WHERE voucher_id=?", (vid,))],
                "party": pinfo}


GST_HEADS = ["IGST", "CGST", "SGST", "Cess"]


def _gst_head(l):
    h = (l["gst_head"] or "").lower()
    n = l["name"].upper()
    if "integrated" in h or "IGST" in n:
        return "IGST"
    if "central" in h or "CGST" in n:
        return "CGST"
    if "state" in h or "ut tax" in h or "SGST" in n or "UTGST" in n:
        return "SGST"
    return "Cess"


def gst(cid, d_from=None, d_to=None):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        led = {r["name"]: r for r in c.execute(
            "SELECT name, chain, taxtype, gst_head, closing FROM ledger WHERE company_id=?", (cid,))}
        tax = {n: l for n, l in led.items() if _is_tax(l)}
        if not tax:
            return {"from": f, "to": t, "months": [], "total": None, "ledgers": []}
        # which side is each tax ledger on?
        use = {r["ledger"]: (r["s"], r["p"]) for r in c.execute("""SELECT vl.ledger,
            SUM(CASE WHEN v.base IN ('Sales','Debit Note') THEN 1 ELSE 0 END) s,
            SUM(CASE WHEN v.base IN ('Purchase','Credit Note') THEN 1 ELSE 0 END) p
            FROM vline vl JOIN voucher v ON v.id=vl.voucher_id WHERE v.company_id=? GROUP BY vl.ledger""", (cid,))}
        side = {}
        for n, l in tax.items():
            low = n.lower()
            if "input" in low or "itc" in low:
                side[n] = "input"
            elif "output" in low:
                side[n] = "output"
            else:
                s_, p_ = use.get(n, (0, 0))
                side[n] = "output" if s_ > p_ else "input" if p_ > s_ else ("output" if l["closing"] < 0 else "input")
        cashbank = {n for n, l in led.items() if any(g in (l["chain"] or "") for g in
                    ("|Bank Accounts|", "|Cash-in-Hand|", "|Bank OD A/c|"))}
        months = {}
        vids = c.execute("""SELECT DISTINCT v.id, v.date, v.base FROM voucher v JOIN vline vl ON vl.voucher_id=v.id
            WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND vl.ledger IN (%s)""" % ",".join("?" * len(tax)),
                         [cid, f, t, *tax.keys()]).fetchall()
        for v in vids:
            lines = c.execute("SELECT ledger, amount FROM vline WHERE voucher_id=?", (v["id"],)).fetchall()
            others = [x["ledger"] for x in lines if x["ledger"] not in tax]
            if not others:
                continue  # set-off between tax ledgers
            if v["base"] in ("Payment", "Receipt", "Journal", "Contra") and all(o in cashbank for o in others):
                continue  # tax paid to / refunded by the government
            m = months.setdefault(v["date"][:7], {"month": v["date"][:7], "output": {h: 0.0 for h in GST_HEADS},
                                                  "input": {h: 0.0 for h in GST_HEADS}})
            for x in lines:
                if x["ledger"] in tax:
                    sd = side[x["ledger"]]
                    m[sd][_gst_head(tax[x["ledger"]])] += -x["amount"] if sd == "output" else x["amount"]
        for m in months.values():
            for sd in ("output", "input"):
                m[sd] = {h: round(x, 2) for h, x in m[sd].items()}
            m["output_total"] = round(sum(m["output"].values()), 2)
            m["input_total"] = round(sum(m["input"].values()), 2)
            m["net"] = round(m["output_total"] - m["input_total"], 2)
            m["sales"] = -_sum_group(c, cid, "Sales Accounts", m["month"] + "-01", m["month"] + "-31")
            m["purchase"] = _sum_group(c, cid, "Purchase Accounts", m["month"] + "-01", m["month"] + "-31")
        ms = sorted(months.values(), key=lambda m: m["month"], reverse=True)
        total = {"output": {h: round(sum(m["output"][h] for m in ms), 2) for h in GST_HEADS},
                 "input": {h: round(sum(m["input"][h] for m in ms), 2) for h in GST_HEADS}}
        total["output_total"] = round(sum(total["output"].values()), 2)
        total["input_total"] = round(sum(total["input"].values()), 2)
        total["net"] = round(total["output_total"] - total["input_total"], 2)
        return {"from": f, "to": t, "months": ms, "total": total,
                "ledgers": [{"name": n, "side": side[n], "head": _gst_head(l)} for n, l in sorted(tax.items())]}


PL_SECTIONS = [("Sales Accounts", -1), ("Direct Incomes", -1), ("Purchase Accounts", 1),
               ("Direct Expenses", 1), ("Indirect Incomes", -1), ("Indirect Expenses", 1)]


def profit_loss(cid, d_from=None, d_to=None):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        sec = {}
        for g, sign in PL_SECTIONS:
            rows = _rows(c, """SELECT vl.ledger name, SUM(vl.amount) * ? amount FROM vline vl
                JOIN voucher v ON v.id=vl.voucher_id
                JOIN ledger l ON l.company_id=v.company_id AND l.name=vl.ledger
                WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND l.chain LIKE ?
                GROUP BY vl.ledger HAVING ABS(SUM(vl.amount)) > 0.005 ORDER BY 2 DESC""",
                         (sign, cid, f, t, f"%|{g}|%"))
            sec[g] = {"total": round(sum(r["amount"] for r in rows), 2), "ledgers": rows}
        st = c.execute("""SELECT COALESCE(SUM(opening_value),0) o, COALESCE(SUM(closing_value),0) cl
            FROM stock WHERE company_id=?""", (cid,)).fetchone()
        gross = (sec["Sales Accounts"]["total"] + sec["Direct Incomes"]["total"] + st["cl"]
                 - st["o"] - sec["Purchase Accounts"]["total"] - sec["Direct Expenses"]["total"])
        net = gross + sec["Indirect Incomes"]["total"] - sec["Indirect Expenses"]["total"]
        return {"from": f, "to": t, "sections": sec, "opening_stock": st["o"], "closing_stock": st["cl"],
                "gross_profit": round(gross, 2), "net_profit": round(net, 2)}


def sync_check(cid):
    """Vouchers whose debits and credits did not add up, grouped by voucher type."""
    with conn() as c:
        rows = _rows(c, """SELECT id, date, vtype, number, party, imbalance FROM voucher
            WHERE company_id=? AND balanced=0 ORDER BY vtype, date DESC""", (cid,))
        counts = _rows(c, """SELECT vtype, COUNT(*) n FROM voucher WHERE company_id=? GROUP BY vtype ORDER BY n DESC""", (cid,))
    groups = {}
    for r in rows:
        g = groups.setdefault(r["vtype"], {"vtype": r["vtype"], "count": 0, "examples": []})
        g["count"] += 1
        if len(g["examples"]) < 8:
            g["examples"].append(r)
    total = {x["vtype"]: x["n"] for x in counts}
    out = sorted(groups.values(), key=lambda g: -g["count"])
    for g in out:
        g["of"] = total.get(g["vtype"], 0)
    with conn() as c:
        months = _rows(c, """SELECT substr(date,1,7) m, COUNT(*) n, SUM(CASE WHEN base='Sales' THEN 1 ELSE 0 END) sales,
            SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) cancelled
            FROM voucher WHERE company_id=? GROUP BY m ORDER BY m DESC""", (cid,))
    return {"unbalanced": len(rows), "groups": out, "types": counts, "months": months}


def agent_stats():
    """Counts only (no names of parties or amounts) for the diagnostic tool on the Tally PC."""
    with conn() as c:
        out = []
        for co in _rows(c, "SELECT id, name, from_date, to_date, keep_from, last_sync FROM company"):
            co["months"] = _rows(c, """SELECT substr(date,1,7) m, COUNT(*) n FROM voucher WHERE company_id=?
                GROUP BY m ORDER BY m""", (co["id"],))
            out.append(co)
        return {"companies": out}


# ---------------------------------------------------------------- analysis

def _year_back(d):
    x = date.fromisoformat(d)
    try:
        return x.replace(year=x.year - 1).isoformat()
    except ValueError:            # 29 Feb
        return x.replace(year=x.year - 1, day=28).isoformat()


def analysis_parties(cid, kind="sales", d_from=None, d_to=None):
    base = "Sales" if kind == "sales" else "Purchase"
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        pf, pt = _year_back(f), _year_back(t)
        q = """SELECT party, COUNT(*) n, SUM(amount) total, MAX(date) last FROM voucher
               WHERE company_id=? AND base=? AND posting=1 AND date BETWEEN ? AND ? AND party<>'' GROUP BY party"""
        cur = {r["party"]: dict(r) for r in c.execute(q, (cid, base, f, t))}
        prev = {r["party"]: dict(r) for r in c.execute(q, (cid, base, pf, pt))}
        has_prev = c.execute("SELECT 1 FROM voucher WHERE company_id=? AND date <= ? LIMIT 1", (cid, pt)).fetchone() is not None
    total = sum(r["total"] for r in cur.values()) or 1
    rows = []
    for p in set(cur) | set(prev):
        a, b = cur.get(p, {}), prev.get(p, {})
        now_, before = round(a.get("total") or 0, 2), round(b.get("total") or 0, 2)
        rows.append({"party": p, "total": now_, "bills": a.get("n", 0), "last": a.get("last") or b.get("last"),
                     "share": round(now_ / total * 100, 1), "prev": before,
                     "change": round((now_ - before) / before * 100, 1) if before else None})
    rows.sort(key=lambda r: (-r["total"], -r["prev"]))
    return {"kind": kind, "from": f, "to": t, "prev_from": pf, "prev_to": pt, "has_prev": has_prev,
            "total": round(sum(r["total"] for r in rows), 2), "prev_total": round(sum(r["prev"] for r in rows), 2),
            "parties": rows}


def analysis_items(cid, d_from=None, d_to=None):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        sold = _rows(c, """SELECT vi.item, -SUM(vi.qty) qty, SUM(vi.amount) value, MAX(vi.unit) unit, COUNT(DISTINCT v.id) bills
            FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
            WHERE v.company_id=? AND v.base='Sales' AND v.date BETWEEN ? AND ? GROUP BY vi.item""", (cid, f, t))
        cost = {r["item"]: r for r in c.execute("""SELECT vi.item, SUM(vi.qty) qty, SUM(vi.amount) value FROM vitem vi
            JOIN voucher v ON v.id=vi.voucher_id WHERE v.company_id=? AND v.base='Purchase' AND v.date <= ? GROUP BY vi.item""",
                                                  (cid, t))}
        stock = {r["name"]: r for r in c.execute("SELECT name, closing_qty, closing_value, closing_rate FROM stock WHERE company_id=?", (cid,))}
    total = sum(r["value"] for r in sold) or 1
    for r in sold:
        r["rate"] = round(r["value"] / r["qty"], 2) if r["qty"] else 0
        p = cost.get(r["item"])
        st_ = stock.get(r["item"])
        buy = (p["value"] / p["qty"]) if p and p["qty"] else (st_["closing_rate"] if st_ and st_["closing_rate"] else None)
        r["buy_rate"] = round(buy, 2) if buy else None
        r["margin"] = round((r["rate"] - buy) / r["rate"] * 100, 1) if buy and r["rate"] else None
        r["share"] = round(r["value"] / total * 100, 1)
        s = stock.get(r["item"])
        r["in_hand"] = s["closing_qty"] if s else None
    sold.sort(key=lambda r: -r["value"])
    return {"from": f, "to": t, "total": round(sum(r["value"] for r in sold), 2), "items": sold}


def analysis_years(cid):
    """Sales before tax by month: this financial year against the previous one."""
    fs, fe = fy_bounds()
    with conn() as c:
        r = c.execute("SELECT MAX(date) m FROM voucher WHERE company_id=?", (cid,)).fetchone()
        if r and r["m"] and r["m"] < fs:
            fs, fe = fy_bounds(date.fromisoformat(r["m"]))
        ps, pe = _year_back(fs), _year_back(fe)

        def monthly(a, b):
            return {x["m"]: -x["s"] for x in c.execute("""SELECT substr(v.date,6,2) m, SUM(vl.amount) s FROM vline vl
                JOIN voucher v ON v.id=vl.voucher_id JOIN ledger l ON l.company_id=v.company_id AND l.name=vl.ledger
                WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND l.chain LIKE '%|Sales Accounts|%' GROUP BY m""", (cid, a, b))}
        cur, prev = monthly(fs, fe), monthly(ps, pe)
        has_prev = c.execute("SELECT 1 FROM voucher WHERE company_id=? AND date BETWEEN ? AND ? LIMIT 1", (cid, ps, pe)).fetchone() is not None
    order = ["04", "05", "06", "07", "08", "09", "10", "11", "12", "01", "02", "03"]
    rows = [{"month": m, "this": round(cur.get(m, 0), 2), "last": round(prev.get(m, 0), 2)} for m in order]
    return {"this_label": f"{fs[:4]}-{fe[2:4]}", "last_label": f"{ps[:4]}-{pe[2:4]}", "has_prev": has_prev,
            "months": rows, "this_total": round(sum(cur.values()), 2), "last_total": round(sum(prev.values()), 2)}


def slow_stock(cid, days=60):
    today = date.today()
    with conn() as c:
        items = _rows(c, """SELECT s.name, s.unit, s.closing_qty, s.closing_value,
            (SELECT MAX(v.date) FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
              WHERE v.company_id=s.company_id AND vi.item=s.name AND vi.qty < 0) last_out
            FROM stock s WHERE s.company_id=? AND s.closing_qty > 0""", (cid,))
    out = []
    for it in items:
        it["idle"] = (today - date.fromisoformat(it["last_out"])).days if it["last_out"] else None
        if it["idle"] is None or it["idle"] >= days:
            out.append(it)
    out.sort(key=lambda x: -x["closing_value"])
    return {"days": days, "value": round(sum(x["closing_value"] for x in out), 2), "items": out}
