"""SQLite storage, ingest of a sync run, and the report queries."""
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import date, timedelta

DB_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "tally.db")
_lock = threading.Lock()

SCHEMA_VERSION = "7"
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS company(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, last_sync REAL, last_seen REAL,
  from_date TEXT, to_date TEXT, alt_vch TEXT, alt_mst TEXT, unbalanced INTEGER DEFAULT 0,
  bills_source TEXT DEFAULT 'vouchers', info TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS grp(
  company_id INT, name TEXT, parent TEXT, chain TEXT, revenue INT, gp INT, debit INT, PRIMARY KEY(company_id, name));
CREATE TABLE IF NOT EXISTS vtype(
  company_id INT, name TEXT, base TEXT, PRIMARY KEY(company_id, name));
CREATE TABLE IF NOT EXISTS ledger(
  company_id INT, name TEXT, parent TEXT, chain TEXT, opening REAL, closing REAL,
  phone TEXT, mobile TEXT, email TEXT, gstin TEXT, taxtype TEXT, gst_head TEXT, extra TEXT DEFAULT '{}',
  PRIMARY KEY(company_id, name));
CREATE TABLE IF NOT EXISTS stock(
  company_id INT, name TEXT, parent TEXT, unit TEXT, opening_qty REAL, opening_value REAL,
  closing_qty REAL, closing_value REAL, closing_rate REAL, hsn TEXT DEFAULT '', gst REAL, PRIMARY KEY(company_id, name));
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
  hsn TEXT DEFAULT '', disc REAL DEFAULT 0, descr TEXT DEFAULT '', tracked INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_vi_i ON vitem(item, voucher_id);
CREATE INDEX IF NOT EXISTS ix_vi_v ON vitem(voucher_id);
CREATE TABLE IF NOT EXISTS vline_np(voucher_id INT, ledger TEXT, amount REAL);
CREATE INDEX IF NOT EXISTS ix_vlnp_v ON vline_np(voucher_id);
CREATE TABLE IF NOT EXISTS vitem_np(voucher_id INT, item TEXT, qty REAL, unit TEXT, rate REAL, amount REAL,
  hsn TEXT DEFAULT '', disc REAL DEFAULT 0, descr TEXT DEFAULT '', tracked INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_vinp_v ON vitem_np(voucher_id);
CREATE TABLE IF NOT EXISTS vbill(voucher_id INT, ledger TEXT, name TEXT, btype TEXT, amount REAL, days INT);
CREATE INDEX IF NOT EXISTS ix_vb_v ON vbill(voucher_id);
CREATE INDEX IF NOT EXISTS ix_vb_l ON vbill(ledger);
CREATE TABLE IF NOT EXISTS vgodown(voucher_id INT, item TEXT, godown TEXT, qty REAL);
CREATE INDEX IF NOT EXISTS ix_vg_v ON vgodown(voucher_id);
CREATE INDEX IF NOT EXISTS ix_vg_i ON vgodown(item);
CREATE TABLE IF NOT EXISTS stock_godown_open(company_id INT, item TEXT, godown TEXT, qty REAL);
CREATE TABLE IF NOT EXISTS ledger_at(company_id INT, day TEXT, ledger TEXT, closing REAL, PRIMARY KEY(company_id, day, ledger));
CREATE TABLE IF NOT EXISTS unsent(company_id INT, guid TEXT, alterid INT, date TEXT, seen REAL, times INT DEFAULT 1,
  PRIMARY KEY(company_id, guid));
CREATE TABLE IF NOT EXISTS heal(company_id INT, month TEXT, at REAL, diff REAL, PRIMARY KEY(company_id, month));
CREATE TABLE IF NOT EXISTS stock_at(company_id INT, day TEXT, item TEXT, qty REAL, value REAL, PRIMARY KEY(company_id, day, item));
CREATE TABLE IF NOT EXISTS bill(company_id INT, kind TEXT, party TEXT, ref TEXT, date TEXT, due TEXT, amount REAL);
CREATE INDEX IF NOT EXISTS ix_b ON bill(company_id, kind, party);
"""

BASE_TYPES = {"Sales", "Purchase", "Receipt", "Payment", "Journal", "Contra",
              "Credit Note", "Debit Note", "Stock Journal", "Delivery Note",
              "Receipt Note", "Rejections In", "Rejections Out", "Physical Stock",
              "Material In", "Material Out", "Sales Order", "Purchase Order", "Memorandum",
              "Reversing Journal", "Payroll", "Attendance", "Job Work In Order", "Job Work Out Order"}


# Vouchers Tally keeps out of the books (they never change ledger balances) and out of stock
NO_STOCK = {"Sales Order", "Purchase Order", "Memorandum", "Reversing Journal", "Job Work In Order",
            "Job Work Out Order", "Attendance", "Physical Stock"}
# goods notes move stock only: their amounts never reach the ledgers (the invoice made against them does)
STOCK_ONLY = {"Receipt Note", "Delivery Note", "Rejections In", "Rejections Out", "Material In", "Material Out"}
NO_ACCOUNTS = (NO_STOCK - {"Physical Stock"}) | STOCK_ONLY


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
    done = {r[0] for r in c.execute("SELECT key FROM meta")}
    if "stock_only_notes" not in done:
        # 3.4.3: receipt/delivery notes and rejections were counted in ledger balances; move their lines out
        ph = ",".join("?" for _ in STOCK_ONLY)
        ids = [r[0] for r in c.execute(f"SELECT id FROM voucher WHERE posting=1 AND base IN ({ph})", sorted(STOCK_ONLY))]
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            q = ",".join("?" for _ in part)
            c.execute(f"INSERT INTO vline_np SELECT * FROM vline WHERE voucher_id IN ({q})", part)
            c.execute(f"DELETE FROM vline WHERE voucher_id IN ({q})", part)
            c.execute(f"DELETE FROM vbill WHERE voucher_id IN ({q})", part)
            c.execute(f"UPDATE voucher SET posting=0, balanced=1 WHERE id IN ({q})", part)
        c.execute("INSERT OR REPLACE INTO meta VALUES('stock_only_notes', '1')")
    cols = [r[1] for r in c.execute("PRAGMA table_info(company)")]
    if "keep_from" not in cols:
        c.execute("ALTER TABLE company ADD COLUMN keep_from TEXT DEFAULT ''")
    if "gst" not in [r[1] for r in c.execute("PRAGMA table_info(stock)")]:
        c.execute("ALTER TABLE stock ADD COLUMN gst REAL")         # item's GST rate from Tally (added in 3.4)
    gcols = [r[1] for r in c.execute("PRAGMA table_info(grp)")]
    for col in ("revenue", "gp", "debit"):        # Tally's nature of each group (added in 2.7)
        if col not in gcols:
            c.execute(f"ALTER TABLE grp ADD COLUMN {col} INT")


SYNC_FILE = os.path.join(os.path.dirname(DB_PATH), "sync.json")
SYNC_DEFAULT = {"mode": "auto", "every": 10, "requested": 0, "last_run": 0, "companies": {}, "agent_auto": True}
EVERY = [2, 5, 10, 15, 30, 60]


def sync_settings():
    """How the Tally PC syncs: mode auto (every N minutes) / manual (only on "Sync now") / paused,
    plus companies paused on their own. Kept outside the database so it survives rebuilds."""
    try:
        with open(SYNC_FILE) as f:
            return {**SYNC_DEFAULT, **json.load(f)}
    except (OSError, ValueError):
        return json.loads(json.dumps(SYNC_DEFAULT))


def _save_sync(d):
    tmp = SYNC_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, SYNC_FILE)


def update_sync(mode=None, every=None, company=None, company_paused=None, request=False, agent_version=None, agent_auto=None):
    with _lock:
        d = sync_settings()
        if agent_version:
            d["agent_version"], d["agent_seen"] = agent_version, time.time()
        if agent_auto is not None:
            d["agent_auto"] = bool(agent_auto)
        if mode in ("auto", "manual", "paused"):
            d["mode"] = mode
        if every is not None and int(every) in EVERY:
            d["every"] = int(every)
        if company:
            if company_paused:
                d["companies"][company] = time.time()
            else:
                d["companies"].pop(company, None)
        if request:
            d["requested"] = time.time()
        _save_sync(d)
        return d


def sync_due(forced=False):
    """Asked by the Tally PC every couple of minutes: should it sync now?"""
    with _lock:
        d = sync_settings()
        now = time.time()
        if d["mode"] == "paused":
            return {"run": False, "why": "paused"}
        asked = d["requested"] > d["last_run"]
        due = d["mode"] == "auto" and now - d["last_run"] >= d["every"] * 60 - 20
        if forced or asked or due:
            d["last_run"] = now
            _save_sync(d)
            return {"run": True, "why": "asked" if asked else "forced" if forced else "schedule"}
        return {"run": False, "why": "manual" if d["mode"] == "manual" else "not yet"}


def is_paused(name):
    d = sync_settings()
    return d["mode"] == "paused" or name in d["companies"]


def get_alt(name):
    with conn() as c:
        r = c.execute("SELECT alt_vch, alt_mst, from_date, last_sync, keep_from FROM company WHERE name=?", (name,)).fetchone()
        out = dict(r) if r else {}
    out["paused"] = is_paused(name)
    with conn() as c:     # groups synced before Bahi knew each group's nature: ask the PC to send them once more
        r = c.execute("""SELECT COUNT(*) n FROM grp g JOIN company co ON co.id=g.company_id
                         WHERE co.name=? AND g.parent='' AND g.revenue IS NULL""", (name,)).fetchone()
        out["need_groups"] = bool(r and r["n"])
        r = c.execute("""SELECT (SELECT COUNT(*) FROM stock s WHERE s.company_id=co.id) items,
                                (SELECT COUNT(*) FROM stock_at a WHERE a.company_id=co.id) snaps FROM company co WHERE co.name=?""",
                      (name,)).fetchone()
        out["need_stock"] = bool(r and r["items"] and not r["snaps"])     # stock synced before month-end stock existed
        r = c.execute("""SELECT (SELECT COUNT(*) FROM voucher v WHERE v.company_id=co.id) vch,
                                (SELECT COUNT(*) FROM ledger_at a WHERE a.company_id=co.id) snaps FROM company co WHERE co.name=?""",
                      (name,)).fetchone()
        out["need_ledgers"] = bool(r and r["vch"] and not r["snaps"])   # synced before the ledger check existed
    return out


def keep_from(c, cid):
    r = c.execute("SELECT keep_from FROM company WHERE id=?", (cid,)).fetchone()
    return (r["keep_from"] if r else "") or ""


def purge_before(cid, day):
    """Delete vouchers dated before `day` and stop accepting them in future syncs."""
    with _lock, conn() as c:
        old = "SELECT id FROM voucher WHERE company_id=? AND date < ?"
        for t in ("vline", "vitem", "vbill", "vline_np", "vitem_np", "vgodown"):
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
        for t in ("voucher", "grp", "vtype", "ledger", "stock", "bill", "stock_godown_open", "stock_at", "ledger_at", "heal"):
            c.execute(f"DELETE FROM {t} WHERE company_id=?", (cid,))
        c.execute("DELETE FROM company WHERE id=?", (cid,))
    with conn() as c:
        c.execute("VACUUM")


def _month_range(m, d_from, d_to):
    y, mo = int(m[:4]), int(m[5:7])
    last = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).isoformat()
    return max(f"{m}-01", d_from), min(last, d_to)


TOL = 0.5          # rupees: rounding


def month_list(a, b):
    return _months_between(a, b)


def _months_between(a, b):
    """YYYY-MM of every month from day a to day b."""
    out, y, m = [], int(a[:4]), int(a[5:7])
    while f"{y:04d}-{m:02d}" <= b[:7]:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def ledger_check(c, cid):
    """Each ledger's balance as Bahi works it out (Tally's closing less the entries after a day) against Tally's
    own balance on that day, at every month-end Bahi has. A difference that appears between two month-ends
    means an entry in that month is missing (or extra) here. Returns the differences, per ledger and month."""
    comp = c.execute("SELECT from_date, keep_from FROM company WHERE id=?", (cid,)).fetchone()
    if not comp:
        return {"checked": 0, "issues": []}
    sync_from = max(comp["from_date"] or "", comp["keep_from"] or "") or "2000-01-01"
    start = (date.fromisoformat(sync_from) - timedelta(days=1)).isoformat()
    days = [r["day"] for r in c.execute("SELECT DISTINCT day FROM ledger_at WHERE company_id=? AND day>=? ORDER BY day",
                                        (cid, start))]
    if not days:
        return {"checked": 0, "issues": []}
    # Tally's Profit & Loss A/c (the one ledger with no group) carries the profit earned so far in its balance,
    # which no entry explains: it is left out of this check
    closing = {r["name"]: r["closing"] for r in c.execute(
        "SELECT name, closing FROM ledger WHERE company_id=? AND parent<>'' AND name<>'Profit & Loss A/c'", (cid,))}
    diffs = {}             # ledger -> [(day, tally - bahi)]
    used = []
    for d in days:
        after = {r["ledger"]: r["s"] for r in c.execute("""SELECT vl.ledger, SUM(vl.amount) s FROM vline vl
            JOIN voucher v ON v.id=vl.voucher_id WHERE v.company_id=? AND v.date>? AND v.date>=? GROUP BY vl.ledger""",
                                                        (cid, d, sync_from))}
        tally = {r["ledger"]: r["closing"] for r in c.execute("SELECT ledger, closing FROM ledger_at WHERE company_id=? AND day=?",
                                                              (cid, d))}
        # a Tally that ignores the date sends today's balances for every day: then this day tells nothing
        moved = [n for n, s in after.items() if abs(s) > TOL and n in tally and n in closing]
        if len(moved) >= 5 and sum(abs(tally[n] - closing[n]) <= TOL for n in moved) > 0.9 * len(moved):
            continue
        used.append(d)
        for n, tv in tally.items():
            if n in closing:
                diffs.setdefault(n, []).append((d, tv - (closing[n] - after.get(n, 0.0))))
    today = date.today().isoformat()
    issues = []
    for n, rows in diffs.items():
        prev_day, prev = None, None
        for d, x in rows + [(today, 0.0)]:          # today Bahi has Tally's closing by definition
            if prev is not None and abs(x - prev) > TOL:
                frm = (date.fromisoformat(prev_day) + timedelta(days=1)).isoformat()
                issues.append({"ledger": n, "from": frm, "to": d, "months": _months_between(frm, d),
                               "amount": round(prev - x, 2)})
            elif prev is None and abs(x) > TOL and d == start:
                pass      # the opening day itself: shows up as a change at the next month-end
            prev_day, prev = d, x
    issues.sort(key=lambda i: (i["from"], i["ledger"].lower()))
    return {"checked": len(used), "ledgers": len(diffs), "issues": issues}


_CHECK = {}


def sync_issues(cid):
    with conn() as c:
        r = c.execute("SELECT last_sync FROM company WHERE id=?", (cid,)).fetchone()
        key = (cid, r["last_sync"] if r else None)
        if key not in _CHECK:                 # worked out once per sync
            _CHECK.clear()
            _CHECK[key] = ledger_check(c, cid)
        out = json.loads(json.dumps(_CHECK[key]))
        heals = {r["month"]: r["at"] for r in c.execute("SELECT month, at FROM heal WHERE company_id=?", (cid,))}
    for i in out["issues"]:
        i["refetched"] = max((heals.get(m, 0) for m in i["months"]), default=0)
    return out


EXPECT = {}       # company -> (when, {YYYY-MM: vouchers Tally listed}) from the latest plan


def check_complete(company, vouchers, months=None, d_from=None, d_to=None):
    """Months of this sync that must keep the copy already here, as "YYYY-MM: got of listed": a month is only
    replaced when every voucher Tally listed for it a moment ago, and that Bahi already holds, came back (a busy
    or misbehaving Tally can send part of a month). A voucher Tally lists but has never sent (deleted or damaged
    in Tally) doesn't hold the month up: it is remembered and, once missing from two syncs, left out of later
    comparisons and shown on the Sync check page."""
    when, counts, listed = EXPECT.get(company, (0, None, None))
    if not counts or time.time() - when > 3 * 3600:
        return []
    check = months if months is not None else [m for m in counts if (not d_from or m >= d_from[:7]) and (not d_to or m <= d_to[:7])]
    got, got_n = {}, {}
    for v in vouchers:
        m = v["date"][:7]
        got_n[m] = got_n.get(m, 0) + 1
        if v.get("guid"):
            got.setdefault(m, set()).add(v["guid"])
    short, unsent = [], []
    with _lock, conn() as c:
        r = c.execute("SELECT id FROM company WHERE name=?", (company,)).fetchone()
        cid = r["id"] if r else None
        for m in sorted(check):
            want = listed.get(m, {})
            if len(want) < counts.get(m, 0):           # vouchers without a GUID: only counts can be compared
                if got_n.get(m, 0) < counts.get(m, 0):
                    short.append(f"{m}: {got_n.get(m, 0)} of {counts[m]}")
                continue
            missing = set(want) - got.get(m, set())
            if not missing:
                continue
            have = set()
            if cid is not None:
                ph = ",".join("?" for _ in missing)
                have = {x[0] for x in c.execute(f"SELECT guid FROM voucher WHERE company_id=? AND guid IN ({ph})",
                                                [cid] + sorted(missing))}
            if have:
                short.append(f"{m}: {got_n.get(m, 0)} of {counts[m]}")
            else:
                unsent += [(g, want[g][0], want[g][1]) for g in missing]
        if short:
            print(f"{company}: kept the copy already here for " + "; ".join(short[:6]), file=sys.stderr, flush=True)
        if unsent and cid is not None:
            # counted per sync: only a voucher missing from two syncs is treated as one Tally never sends
            for g, a, d in unsent:
                c.execute("INSERT OR IGNORE INTO unsent(company_id, guid, alterid, date, seen, times) VALUES(?,?,?,?,?,0)",
                          (cid, g, a, d, time.time()))
                c.execute("UPDATE unsent SET times=times+1, seen=?, alterid=?, date=? WHERE company_id=? AND guid=?",
                          (time.time(), a, d, cid, g))
            print(f"{company}: {len(unsent)} voucher(s) Tally lists but doesn't send:", ", ".join(f"{d} {g}" for g, a, d in unsent[:5]),
                  file=sys.stderr, flush=True)
    return short


def plan(company, d_from, d_to, tally_list):
    """Compare Tally's list of (GUID, AlterID, date) with what is stored; return the months to resend."""
    # vouchers Tally lists but has never sent (unchanged since) are left out of every comparison
    with conn() as c:
        r = c.execute("SELECT id FROM company WHERE name=?", (company,)).fetchone()
        skip = {x["guid"]: x["alterid"] for x in c.execute("SELECT guid, alterid FROM unsent WHERE company_id=? AND times>=2",
                                                             (r["id"],))} if r else {}
    if skip:
        tally_list = [(g, a, d) for g, a, d in tally_list if not (g in skip and skip[g] == a)]
    counts, listed = {}, {}
    for g, a, d in tally_list:
        if d_from <= d <= d_to:
            counts[d[:7]] = counts.get(d[:7], 0) + 1
            if g:
                listed.setdefault(d[:7], {})[g] = (a, d)
    EXPECT[company] = (time.time(), counts, listed)
    with conn() as c:
        r = c.execute("SELECT id, from_date, to_date, keep_from FROM company WHERE name=? AND last_sync IS NOT NULL",
                      (company,)).fetchone()
        if not r or r["from_date"] != max(d_from, r["keep_from"] or "") or r["to_date"] != d_to:
            return {"full": True, "months": []}
        # 3.6.1: stock lines Tally sends twice (ALLINVENTORYENTRIES and INVENTORYENTRIES) were both kept;
        # every company's vouchers are read again once so the stored copies are right
        key = f"items_once:{r['id']}"
        if not c.execute("SELECT 1 FROM meta WHERE key=?", (key,)).fetchone():
            c.execute("INSERT OR REPLACE INTO meta VALUES(?, '1')", (key,))
            c.commit()
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
    # Voucher by voucher: only what was created, altered or deleted in Tally, when every voucher has a GUID
    # and, once those are applied, each month holds exactly as many vouchers as Tally has.
    in_range = [(g, a, d) for g, a, d in tally_list if d_from <= d <= d_to]
    changed = [g for g, a, d in in_range if g and (stored.get(g) is None or stored[g][0] != a or stored[g][1] != d)]
    deleted = [g for g in stored if g not in seen]
    after = {g: d for g, (a, d) in stored.items() if g not in set(deleted)}
    after.update({g: d for g, a, d in in_range if g in set(changed)})
    counts_a = {}
    for d in after.values():
        counts_a[d[:7]] = counts_a.get(d[:7], 0) + 1
    by_voucher = (all(g for g, a, d in in_range) and len(changed) + len(deleted) <= 100
                  and all(counts_a.get(m, 0) == counts_t.get(m, 0) for m in set(counts_a) | set(counts_t)))
    # Ledger balances that don't match Tally's at a month-end: fetch those months again (at most every 12 hours,
    # so something Bahi can't read doesn't make every sync slow; it shows on the Sync check page instead)
    with _lock, conn() as c:
        cid = c.execute("SELECT id FROM company WHERE name=?", (company,)).fetchone()["id"]
        heals = {r["month"]: r["at"] for r in c.execute("SELECT month, at FROM heal WHERE company_id=?", (cid,))}
        redo = set()
        for i in ledger_check(c, cid)["issues"]:
            for m in i["months"]:
                if d_from[:7] <= m <= d_to[:7] and time.time() - heals.get(m, 0) > 12 * 3600:
                    redo.add(m)
        for m in redo:
            c.execute("INSERT OR REPLACE INTO heal VALUES(?,?,?,?)", (cid, m, time.time(), 0))
    if redo:
        months |= redo
        by_voucher = False
    since = min([m + "-01" for m in redo] + [d for g, a, d in in_range if g in set(changed)] + [stored[g][1] for g in changed if g in stored]
                + [stored[g][1] for g in deleted] + [m + "-01" for m in months] or [""])
    return {"full": False, "months": sorted(months), "by_voucher": by_voucher, "since": since,
            "changed": changed if by_voucher else [], "deleted": deleted if by_voucher else []}


def merge_einv(company, einv):
    """e-invoice / e-way bill details of vouchers already stored (an e-way bill made after the invoice was
    synced, or a month kept as it was). Only adds to the voucher's printing details; nothing else changes."""
    if not einv:
        return 0
    n = 0
    with _lock, conn() as c:
        r = c.execute("SELECT id FROM company WHERE name=?", (company,)).fetchone()
        if not r:
            return 0
        for g, f_ in einv.items():
            row = c.execute("SELECT id, extra FROM voucher WHERE company_id=? AND guid=?", (r["id"], g)).fetchone()
            if not row:
                continue
            x = json.loads(row["extra"] or "{}")
            new = {**x, **f_}
            if new != x:
                c.execute("UPDATE voucher SET extra=? WHERE id=?", (json.dumps(new), row["id"]))
                n += 1
    return n


def ingest(company, d_from, d_to, alt_vch, alt_mst, groups, vtypes, ledgers, stock, vouchers,
           bills_rec=None, bills_pay=None, info=None, ledger_x=None, stock_x=None, months=None, guids=None, stock_at=None,
           stock_godown=None, ledger_at=None):
    """Store a sync. Masters are replaced when sent (groups/types/details are kept if a partial sync left them out).
    Vouchers are replaced for the whole [d_from, d_to] range, or only for `months` (YYYY-MM) on a partial sync."""
    with _lock, conn() as c:
        cid = company_id(c, company)
        kf = keep_from(c, cid)
        if months is None and guids is None:          # a full sync: nothing stored before it needs reading again
            c.execute("INSERT OR REPLACE INTO meta VALUES(?, '1')", (f"items_once:{cid}",))
        if kf and d_from < kf:
            d_from = kf
            vouchers = [v for v in vouchers if v["date"] >= kf]
        partial = months is not None or guids is not None
        if groups or not partial:
            chains = _chains(groups)
            c.execute("DELETE FROM grp WHERE company_id=?", (cid,))
            c.executemany("INSERT OR REPLACE INTO grp(company_id, name, parent, chain, revenue, gp, debit) VALUES(?,?,?,?,?,?,?)",
                          [(cid, g["name"], g["parent"], chains[g["name"]], g.get("revenue"), g.get("gp"), g.get("debit"))
                           for g in groups])
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
            stock_x = {r["name"]: {"hsn": r["hsn"], "gst": r["gst"]} for r in c.execute("SELECT name, hsn, gst FROM stock WHERE company_id=?", (cid,))}
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
            c.executemany("INSERT OR REPLACE INTO stock VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
                (cid, s["name"], s["parent"], s["unit"], s["opening_qty"], s["opening_value"],
                 s["closing_qty"], s["closing_value"], s["closing_rate"], stock_x.get(s["name"], {}).get("hsn", ""),
                 stock_x.get(s["name"], {}).get("gst"))
                for s in stock])

        if guids is not None:
            # only the vouchers that changed: drop their old copies (and deleted ones), then add what Tally sent
            gset = set(guids)
            for i in range(0, len(guids), 400):
                part = guids[i:i + 400]
                ph = ",".join("?" for _ in part)
                old = f"SELECT id FROM voucher WHERE company_id=? AND guid IN ({ph})"
                for t in ("vline", "vitem", "vbill", "vline_np", "vitem_np", "vgodown"):
                    c.execute(f"DELETE FROM {t} WHERE voucher_id IN ({old})", [cid] + part)
                c.execute(f"DELETE FROM voucher WHERE company_id=? AND guid IN ({ph})", [cid] + part)
            ranges = [(d_from, d_to)]
        else:
            gset = None
            ranges = [_month_range(m, d_from, d_to) for m in months] if months is not None else [(d_from, d_to)]
            ranges = [(a, b) for a, b in ranges if a <= b]
            for a, b in ranges:
                old = "SELECT id FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?"
                for t in ("vline", "vitem", "vbill", "vline_np", "vitem_np", "vgodown"):
                    c.execute(f"DELETE FROM {t} WHERE voucher_id IN ({old})", (cid, a, b))
                c.execute("DELETE FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?", (cid, a, b))
        inserted = 0
        # a voucher that arrives after all is no longer "listed but never sent"
        c.executemany("DELETE FROM unsent WHERE company_id=? AND guid=?", [(cid, v["guid"]) for v in vouchers if v.get("guid")])
        for v in vouchers:
            if not any(a <= v["date"] <= b for a, b in ranges):
                continue
            if gset is not None and v["guid"] not in gset:
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
            c.executemany(f"INSERT INTO {'vitem_np' if (base in NO_STOCK or status) else 'vitem'} VALUES(?,?,?,?,?,?,?,?,?,?)",
                          [(vid, i["item"], i["qty"], i["unit"], i["rate"], i["amount"],
                            i.get("hsn") or stock_x.get(i["item"], {}).get("hsn", ""), i.get("disc", 0), i.get("descr", ""),
                            1 if i.get("tracked") else 0)
                           for i in v["items"]])
            if not (base in NO_STOCK or status):
                c.executemany("INSERT INTO vgodown VALUES(?,?,?,?)",
                              [(vid, i["item"], g, q) for i in v["items"] if not i.get("tracked")
                               for g, q in (i.get("godowns") or [("", i["qty"])])])
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
        if stock_godown is not None:
            c.execute("DELETE FROM stock_godown_open WHERE company_id=?", (cid,))
            c.executemany("INSERT INTO stock_godown_open VALUES(?,?,?,?)",
                          [(cid, item, g, q) for item, rows in stock_godown.items() for g, q in rows])
        if not partial:
            c.execute("DELETE FROM ledger_at WHERE company_id=?", (cid,))
        for day, rows in (ledger_at or {}).items():
            c.execute("DELETE FROM ledger_at WHERE company_id=? AND day=?", (cid, day))
            c.executemany("INSERT OR REPLACE INTO ledger_at VALUES(?,?,?,?)", [(cid, day, n, v) for n, v in rows.items()])
        if not partial:
            c.execute("DELETE FROM stock_at WHERE company_id=?", (cid,))
        for day, rows in (stock_at or {}).items():
            # Tally's stock at the end of `day`; a change on an earlier date also replaces every later month-end
            c.execute("DELETE FROM stock_at WHERE company_id=? AND day=?", (cid, day))
            c.executemany("INSERT OR REPLACE INTO stock_at VALUES(?,?,?,?,?)",
                          [(cid, day, r["name"], r["closing_qty"], r["closing_value"] * (1 if r["closing_qty"] >= 0 else -1))
                           for r in rows])
        unbalanced = c.execute("SELECT COUNT(*) n FROM voucher WHERE company_id=? AND balanced=0", (cid,)).fetchone()["n"]
        now = time.time()
        c.execute("UPDATE company SET last_sync=?, last_seen=?, from_date=?, to_date=?, alt_vch=?, alt_mst=?,"
                  " unbalanced=? WHERE id=?", (now, now, d_from, d_to, alt_vch, alt_mst, unbalanced, cid))
        n_v = c.execute("SELECT COUNT(*) n FROM voucher WHERE company_id=?", (cid,)).fetchone()["n"]
    return {"ledgers": len(ledgers), "stock": len(stock), "vouchers": n_v, "unbalanced": unbalanced,
            "changed": inserted, "months": ("vouchers" if guids is not None else len(ranges)) if partial else "all"}


# ---------------------------------------------------------------- reports

def _rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def companies():
    with conn() as c:
        rows = _rows(c, """SELECT id, name, last_sync, last_seen, from_date, to_date, unbalanced, keep_from,
            (SELECT MIN(date) FROM voucher v WHERE v.company_id=company.id) first_vch,
            (SELECT MAX(date) FROM voucher v WHERE v.company_id=company.id) last_vch,
            (SELECT COUNT(*) FROM ledger l WHERE l.company_id=company.id) ledgers,
            (SELECT COUNT(*) FROM voucher v WHERE v.company_id=company.id) vouchers
            FROM company WHERE last_sync IS NOT NULL ORDER BY name""")
    p = sync_settings()
    for r in rows:
        r["paused"] = p["mode"] == "paused" or r["name"] in p["companies"]
    return rows


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


def daily(cid, kind="sales", d_from=None, d_to=None, sub=""):
    """Day-by-day sales (or purchases): bills, value with tax, value before tax, returns."""
    base, ret, grp, sign = (("Sales", "Credit Note", "Sales Accounts", -1) if kind == "sales"
                            else ("Purchase", "Debit Note", "Purchase Accounts", 1))
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        days = {}
        vt = " AND vtype=?" if sub else ""
        va = [sub] if sub else []
        for r in c.execute(f"""SELECT date, COUNT(*) n, SUM(amount) total FROM voucher
                WHERE company_id=? AND base=? AND posting=1 AND date BETWEEN ? AND ?{vt} GROUP BY date""", [cid, base, f, t] + va):
            days[r["date"]] = {"date": r["date"], "bills": r["n"], "total": round(r["total"] or 0, 2), "net": 0.0, "returns": 0.0}
        for r in ([] if sub else c.execute("""SELECT date, SUM(amount) total FROM voucher
                WHERE company_id=? AND base=? AND posting=1 AND date BETWEEN ? AND ? GROUP BY date""", (cid, ret, f, t))):
            d = days.setdefault(r["date"], {"date": r["date"], "bills": 0, "total": 0.0, "net": 0.0, "returns": 0.0})
            d["returns"] = round(r["total"] or 0, 2)
        vt2 = " AND v.vtype=?" if sub else ""
        for r in c.execute(f"""SELECT v.date, SUM(vl.amount) s FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
                JOIN ledger l ON l.company_id=v.company_id AND l.name=vl.ledger
                WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND l.chain LIKE ?{vt2} GROUP BY v.date""",
                             [cid, f, t, f"%|{grp}|%"] + va):
            d = days.setdefault(r["date"], {"date": r["date"], "bills": 0, "total": 0.0, "net": 0.0, "returns": 0.0})
            d["net"] = round(sign * (r["s"] or 0), 2)
        subs = [r["vtype"] for r in c.execute("""SELECT vtype, COUNT(*) n FROM voucher WHERE company_id=? AND base=?
            GROUP BY vtype ORDER BY n DESC""", (cid, base))]
    rows = sorted(days.values(), key=lambda d: d["date"], reverse=True)
    best = max(rows, key=lambda d: d["total"], default=None)
    active = [d for d in rows if d["bills"]]
    return {"kind": kind, "from": f, "to": t, "days": rows, "sub": sub, "subs": subs if len(subs) > 1 else [],
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
        # Opening as Tally has it (its month-end balance plus the entries after it); nothing is adjusted
        opening = _opening_at(c, cid, name, info["closing"], sync_from, f)
        opening_from_tally = c.execute("SELECT 1 FROM ledger_at WHERE company_id=? LIMIT 1", (cid,)).fetchone() is not None
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
        # Tally's own closing for the end of the period, to show (not hide) any difference with the entries here
        last_vch = c.execute("SELECT MAX(date) d FROM voucher WHERE company_id=?", (cid,)).fetchone()["d"] or ""
        tally_close = _tally_at(c, cid, name, t)
        if tally_close is None and t >= max(last_vch, date.today().isoformat()):
            tally_close = info["closing"]
        diff = round(tally_close - bal, 2) if tally_close is not None and opening_from_tally else 0.0
        # closing shown is Tally's own figure whenever Tally gave one; the entries are listed exactly as they are
        shown_close = tally_close if tally_close is not None else bal
        kind, bills = ledger_bills(c, cid, name)
        return {"mismatch": [i for i in sync_issues(cid)["issues"] if i["ledger"] == name], "ledger": info, "from": f, "to": t, "opening": round(opening, 2),
                "tally_closing": None if tally_close is None else round(tally_close, 2), "difference": diff if abs(diff) > 0.5 else 0.0,
                "debit": round(dr, 2), "credit": round(cr, 2), "closing": round(shown_close, 2), "entries_total": round(bal, 2),
                "entries": rows,
                "bill_kind": kind, "bills": bills, "interest": round(sum(b.get("interest", 0) for b in bills), 2),
                "interest_rate": interest_settings()["rate"] if interest_settings()["on"] else 0,
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


def _stock_moves(c, cid, f, t, item=None):
    """Per item: quantity moved after f and after t (to work back from Tally's closing), and in/out within f..t.
    Each voucher counts once per item with its net quantity, so a transfer between godowns (out of one, into
    another) moves nothing; lines on an invoice made against a delivery/receipt note are left out, because
    Tally moved that stock on the note."""
    extra, args = ("AND vi.item=?", [item]) if item else ("", [])
    return {r["item"]: r for r in c.execute(f"""WITH net AS (
            SELECT vi.item, v.date, SUM(vi.qty) q, SUM(CASE WHEN vi.qty > 0 THEN ABS(vi.amount) ELSE 0 END) inamt
            FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
            WHERE v.company_id=? AND vi.tracked=0 {extra} GROUP BY vi.voucher_id, vi.item)
        SELECT item,
            COALESCE(SUM(CASE WHEN date >= ? THEN q END), 0) after_f,
            COALESCE(SUM(CASE WHEN date > ? THEN q END), 0) after_t,
            COALESCE(SUM(CASE WHEN date BETWEEN ? AND ? AND q > 0 THEN q END), 0) in_q,
            COALESCE(-SUM(CASE WHEN date BETWEEN ? AND ? AND q < 0 THEN q END), 0) out_q,
            COALESCE(SUM(CASE WHEN date BETWEEN ? AND ? AND q > 0 THEN inamt END), 0) in_v
        FROM net GROUP BY item""", [cid] + args + [f, t, f, t, f, t, f, t])}


def _stock_row(i, m, t, today):
    """Opening and closing quantity for the period, worked back from Tally's current closing.
    Values: Tally's own closing value when the period runs to today, otherwise quantity x average rate."""
    after_f = m["after_f"] if m else 0
    after_t = m["after_t"] if m else 0
    rate = i["closing_rate"] or (i["closing_value"] / i["closing_qty"] if i["closing_qty"] else 0) or \
        (i["opening_value"] / i["opening_qty"] if i["opening_qty"] else 0)
    oq = i["closing_qty"] - after_f
    cq = i["closing_qty"] - after_t
    exact_close = t >= today and abs(after_t) < 1e-9
    return {**i, "rate": round(rate, 2), "open_qty": round(oq, 3), "open_value": round(oq * rate, 2),
            "in_qty": round(m["in_q"], 3) if m else 0, "out_qty": round(m["out_q"], 3) if m else 0,
            "in_value": round(m["in_v"], 2) if m else 0,
            "close_qty": round(cq, 3), "close_value": round(i["closing_value"] if exact_close else cq * rate, 2),
            "close_exact": exact_close}


def _stock_at(c, cid, day):
    """Each item's stock at the end of `day`: Tally's own month-end figure when `day` is a month-end Bahi has,
    otherwise the nearest earlier month-end plus the vouchers after it (marked as worked out)."""
    r = c.execute("SELECT MAX(day) d FROM stock_at WHERE company_id=? AND day<=?", (cid, day)).fetchone()
    base = r["d"] if r else None
    if not base:
        return {}
    snap = {x["item"]: (x["qty"], x["value"]) for x in c.execute(
        "SELECT item, qty, value FROM stock_at WHERE company_id=? AND day=?", (cid, base))}
    if base == day:
        return {k: (q, v, True) for k, (q, v) in snap.items()}
    nxt = (date.fromisoformat(base) + timedelta(days=1)).isoformat()
    mv = _stock_moves(c, cid, nxt, day)
    rate = {x["name"]: x["closing_rate"] for x in c.execute("SELECT name, closing_rate FROM stock WHERE company_id=?", (cid,))}
    out = {}
    for k, (q, v) in snap.items():
        m = mv.get(k)
        dq = (m["in_q"] - m["out_q"]) if m else 0
        r_ = (v / q) if q else (rate.get(k) or 0)
        out[k] = (q + dq, v + dq * r_, abs(dq) < 1e-9)
    return out


def _apply_tally_stock(row, before_f, at_t):
    """Replace worked-out figures with Tally's own month-end stock where Bahi has it."""
    row["open_exact"] = False
    if row["name"] in before_f:
        q, v, ex = before_f[row["name"]]
        row["open_qty"], row["open_value"], row["open_exact"] = round(q, 3), round(v, 2), ex
    if not row["close_exact"] and row["name"] in at_t:
        q, v, ex = at_t[row["name"]]
        row["close_qty"], row["close_value"], row["close_exact"] = round(q, 3), round(v, 2), ex
    return row


STOCKMIN_FILE = os.path.join(os.path.dirname(DB_PATH), "stock_min.json")


def stock_mins(company=None):
    try:
        with open(STOCKMIN_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return d.get(company, {}) if company is not None else d


def set_stock_min(cid, item, minimum):
    co = next((x for x in companies() if x["id"] == cid), None)
    if not co:
        return False
    with _lock:
        d = stock_mins()
        per = d.setdefault(co["name"], {})
        if minimum is None or minimum == "" or float(minimum) <= 0:
            per.pop(item, None)
        else:
            per[item] = float(minimum)
        tmp = STOCKMIN_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, STOCKMIN_FILE)
    return True


def stock_problems(cid):
    """Items below the minimum you set, or below zero (all godowns together), as Tally has them now."""
    co = next((x for x in companies() if x["id"] == cid), None)
    mins = stock_mins(co["name"]) if co else {}
    out = []
    with conn() as c:
        for r in c.execute("SELECT name, unit, closing_qty FROM stock WHERE company_id=? ORDER BY name", (cid,)):
            m = mins.get(r["name"])
            if r["closing_qty"] < -1e-9:
                out.append({"name": r["name"], "unit": r["unit"], "qty": r["closing_qty"], "min": m, "state": "negative"})
            elif m is not None and r["closing_qty"] < m:
                out.append({"name": r["name"], "unit": r["unit"], "qty": r["closing_qty"], "min": m, "state": "low"})
    return out


def stock(cid, q="", d_from=None, d_to=None):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        items = _rows(c, """SELECT name, parent, unit, opening_qty, opening_value, closing_qty, closing_value, closing_rate FROM stock
            WHERE company_id=? AND name LIKE ? ORDER BY name COLLATE NOCASE""", (cid, f"%{q}%"))
        moves = _stock_moves(c, cid, f, t)
        before_f = _stock_at(c, cid, (date.fromisoformat(f) - timedelta(days=1)).isoformat())
        at_t = _stock_at(c, cid, t) if t < date.today().isoformat() else {}
    today = date.today().isoformat()
    rows = [_apply_tally_stock(_stock_row(i, moves.get(i["name"]), t, today), before_f, at_t) for i in items]
    co = next((x for x in companies() if x["id"] == cid), None)
    mins = stock_mins(co["name"]) if co else {}
    for r in rows:      # flags are about stock now, whatever period is shown
        r["min"] = mins.get(r["name"])
        r["flag"] = "negative" if r["closing_qty"] < -1e-9 else "low" if r["min"] is not None and r["closing_qty"] < r["min"] else ""
    return {"from": f, "to": t, "items": rows, "total": round(sum(i["close_value"] for i in rows), 2),
            "open_total": round(sum(i["open_value"] for i in rows), 2), "close_exact": all(i["close_exact"] for i in rows),
            "open_exact": all(i["open_exact"] for i in rows)}


def stock_item(cid, name, d_from=None, d_to=None):
    with conn() as c:
        info = c.execute("SELECT * FROM stock WHERE company_id=? AND name=?", (cid, name)).fetchone()
        if not info:
            return None
        f, t = period(c, cid, d_from, d_to)
        rows = _rows(c, """SELECT v.id, v.date, v.vtype, v.number, v.party, SUM(vi.qty) qty, MAX(vi.rate) rate,
            SUM(vi.amount) amount, MIN(vi.qty) lo, MAX(vi.qty) hi, MAX(vi.tracked) tracked
            FROM vitem vi JOIN voucher v ON v.id=vi.voucher_id
            WHERE v.company_id=? AND vi.item=? AND v.date BETWEEN ? AND ?
            GROUP BY v.id ORDER BY v.date DESC, v.id DESC""", (cid, name, f, t))
        for r in rows:
            r["transfer"] = r["lo"] < 0 < r["hi"] and abs(r["qty"]) < 1e-9     # out of one godown, into another
        moving = [r for r in rows if not r["tracked"]]
        inward = sum(r["qty"] for r in moving if r["qty"] > 0)
        outward = -sum(r["qty"] for r in moving if r["qty"] < 0)
        m = _stock_moves(c, cid, f, t, name).get(name)
        before_f = _stock_at(c, cid, (date.fromisoformat(f) - timedelta(days=1)).isoformat())
        at_t = _stock_at(c, cid, t) if t < date.today().isoformat() else {}
    row = _apply_tally_stock(_stock_row(dict(info), m, t, date.today().isoformat()), before_f, at_t)
    co = next((x for x in companies() if x["id"] == cid), None)
    row["min"] = stock_mins(co["name"]).get(name) if co else None
    gd = godown_stock(cid, name)
    return {"item": dict(info), "period": row, "godowns": gd["rows"] if gd["split"] else [], "from": f, "to": t, "inward": inward, "outward": outward, "moves": rows}


NO_GODOWN = "Not split by godown"


def godown_stock(cid, item=None):
    """Stock now in each godown: each item's opening in that godown (from Tally's item master) plus every
    synced voucher's movement in or out of it. Whatever doesn't add up to Tally's own closing for the item
    (vouchers from before the sync start, lines Tally didn't give a godown) is shown as not split.
    Total per item is always Tally's closing; a godown going negative is shown, not hidden."""
    with conn() as c:
        extra, args = ("AND name=?", [item]) if item else ("", [])
        items = {r["name"]: r for r in _rows(c, f"""SELECT name, parent, unit, closing_qty, closing_value, closing_rate
            FROM stock WHERE company_id=? {extra}""", [cid] + args)}
        per = {}
        for r in c.execute(f"SELECT item, godown, qty FROM stock_godown_open WHERE company_id=? {extra.replace('name', 'item')}",
                           [cid] + args):
            per.setdefault(r["item"], {}).setdefault(r["godown"], 0.0)
            per[r["item"]][r["godown"]] += r["qty"]
        for r in c.execute(f"""SELECT g.item, g.godown, SUM(g.qty) q FROM vgodown g JOIN voucher v ON v.id=g.voucher_id
                WHERE v.company_id=? {extra.replace('name', 'g.item')} GROUP BY g.item, g.godown""", [cid] + args):
            per.setdefault(r["item"], {}).setdefault(r["godown"] or NO_GODOWN, 0.0)
            per[r["item"]][r["godown"] or NO_GODOWN] += r["q"]
    out = []
    for name, i in items.items():
        gs = {g: q for g, q in per.get(name, {}).items() if abs(q) > 1e-9}
        rest = i["closing_qty"] - sum(gs.values())
        if abs(rest) > 1e-6:
            gs[NO_GODOWN] = gs.get(NO_GODOWN, 0) + rest
        rate = i["closing_rate"] or (i["closing_value"] / i["closing_qty"] if i["closing_qty"] else 0)
        for g, q in gs.items():
            if abs(q) > 1e-9:
                out.append({"item": name, "parent": i["parent"], "unit": i["unit"], "godown": g,
                            "qty": round(q, 3), "value": round(q * rate, 2)})
    godowns = {}
    for r in out:
        d = godowns.setdefault(r["godown"], {"godown": r["godown"], "items": 0, "value": 0.0, "negative": 0})
        d["items"] += 1
        d["value"] += r["value"]
        d["negative"] += r["qty"] < 0
    gl = sorted(godowns.values(), key=lambda d: (d["godown"] == NO_GODOWN, d["godown"].lower()))
    for d in gl:
        d["value"] = round(d["value"], 2)
    return {"godowns": gl, "rows": sorted(out, key=lambda r: (r["godown"] == NO_GODOWN, r["godown"].lower(), r["item"].lower())),
            "split": any(d["godown"] != NO_GODOWN for d in gl)}


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


INTEREST_FILE = os.path.join(os.path.dirname(DB_PATH), "interest.json")
INTEREST_DEFAULT = {"on": False, "rate": 18.0, "grace": 0}


def interest_settings():
    try:
        with open(INTEREST_FILE) as f:
            return {**INTEREST_DEFAULT, **json.load(f)}
    except (OSError, ValueError):
        return dict(INTEREST_DEFAULT)


def set_interest(on=None, rate=None, grace=None):
    d = interest_settings()
    if on is not None:
        d["on"] = bool(on)
    if rate is not None:
        d["rate"] = max(0.0, min(60.0, float(rate)))
    if grace is not None:
        d["grace"] = max(0, min(365, int(grace)))
    tmp = INTEREST_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, INTEREST_FILE)
    return d


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
        ist = interest_settings()
        for b in bills:
            # simple interest from the due date (or the bill date when the bill has no credit period), after grace days
            late = b["overdue"] if b["due"] else b["age"]
            days = (late or 0) - ist["grace"]
            b["interest_days"] = days if ist["on"] and b["amount"] > 0 and days > 0 else 0
            b["interest"] = round(b["amount"] * ist["rate"] / 100 * b["interest_days"] / 365, 2) if b["interest_days"] else 0.0
        p["interest"] = round(sum(b["interest"] for b in bills), 2)
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
    ist = interest_settings()
    return {"kind": kind, "source": source, "total": round(sum(p["amount"] for p in parties), 2),
            "interest": round(sum(p["interest"] for p in parties), 2), "interest_rate": ist["rate"] if ist["on"] else 0,
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


def type_tree(c, cid):
    """Voucher types as Tally groups them: each main type (Sales, Receipt...) with the company's own types under it,
    e.g. Sales -> Sales, GST Sales, Counter Sales. Counts are over all synced vouchers."""
    tree = {}
    for r in c.execute("""SELECT base, vtype, COUNT(*) n FROM voucher WHERE company_id=? GROUP BY base, vtype
                          ORDER BY base, n DESC""", (cid,)):
        b = tree.setdefault(r["base"], {"base": r["base"], "n": 0, "subs": []})
        b["n"] += r["n"]
        b["subs"].append({"name": r["vtype"], "n": r["n"]})
    out = sorted(tree.values(), key=lambda b: -b["n"])
    for b in out:     # only worth offering when there is more than one, or the one has its own name
        if len(b["subs"]) == 1 and b["subs"][0]["name"] == b["base"]:
            b["subs"] = []
    return out


def daybook(cid, d_from=None, d_to=None, base="", offset=0, sub=""):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        args = [cid, f, t]
        extra = ""
        if base:
            extra = " AND base=?"
            args.append(base)
        if sub:
            extra += " AND vtype=?"
            args.append(sub)
        rows = _rows(c, f"""SELECT id, date, vtype, base, number, party, amount, status FROM voucher
            WHERE company_id=? AND date BETWEEN ? AND ?{extra} ORDER BY date DESC, id DESC LIMIT ? OFFSET ?""",
                     args + [PAGE, int(offset)])
        total = c.execute(f"SELECT COUNT(*) n FROM voucher WHERE company_id=? AND date BETWEEN ? AND ?{extra}", args).fetchone()["n"]
        return {"from": f, "to": t, "vouchers": rows, "types": type_tree(c, cid), "total": total, "offset": int(offset)}


def vouchers(cid, q="", d_from=None, d_to=None, base="", offset=0, sub=""):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        where, args = ["company_id=?", "date BETWEEN ? AND ?"], [cid, f, t]
        if base:
            where.append("base=?")
            args.append(base)
        if sub:
            where.append("vtype=?")
            args.append(sub)
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
        return {"from": f, "to": t, "vouchers": rows, "types": type_tree(c, cid), "q": q, "total": total, "offset": int(offset)}


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


def voucher_ids(cid, d_from=None, d_to=None):
    """Ids of the vouchers in a period (for downloading them to view offline)."""
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        return {"from": f, "to": t, "ids": [r[0] for r in c.execute(
            "SELECT id FROM voucher WHERE company_id=? AND date BETWEEN ? AND ? ORDER BY date DESC, id DESC", (cid, f, t))]}


def sync_check(cid):
    """Vouchers whose debits and credits did not add up, grouped by voucher type."""
    with conn() as c:
        rows = _rows(c, """SELECT id, date, vtype, number, party, imbalance FROM voucher
            WHERE company_id=? AND balanced=0 ORDER BY vtype, date DESC""", (cid,))
        counts = _rows(c, """SELECT vtype, MAX(base) base, COUNT(*) n FROM voucher WHERE company_id=? GROUP BY vtype ORDER BY n DESC""", (cid,))
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
    bal = sync_issues(cid)
    with conn() as c:
        unsent = _rows(c, "SELECT date, guid FROM unsent WHERE company_id=? AND times>=2 ORDER BY date", (cid,))
    return {"balances": bal, "unsent": unsent, "unbalanced": len(rows), "groups": out, "types": counts, "months": months}


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
              WHERE v.company_id=s.company_id AND vi.item=s.name AND v.base IN ('Sales', 'Delivery Note')) last_out
            FROM stock s WHERE s.company_id=? AND s.closing_qty > 0""", (cid,))
    out = []
    for it in items:
        it["idle"] = (today - date.fromisoformat(it["last_out"])).days if it["last_out"] else None
        if it["idle"] is None or it["idle"] >= days:
            out.append(it)
    out.sort(key=lambda x: -x["closing_value"])
    return {"days": days, "value": round(sum(x["closing_value"] for x in out), 2), "items": out}


# ---------------------------------------------------------------- balance sheet
LIAB_PRIMARY = ["Capital Account", "Loans (Liability)", "Current Liabilities", "Branch / Divisions", "Suspense A/c"]
ASSET_PRIMARY = ["Fixed Assets", "Investments", "Current Assets", "Misc. Expenses (ASSET)"]
PL_PRIMARY = {"Sales Accounts", "Purchase Accounts", "Direct Incomes", "Direct Expenses",
              "Indirect Incomes", "Indirect Expenses"}


def balance_sheet(cid):
    """As on the last sync, from Tally's closing balances. Profit & Loss A/c is what makes both sides equal:
    its opening (last years' profit) comes from Tally, the rest is this period's profit."""
    with conn() as c:
        prim = [r["name"] for r in c.execute("SELECT name FROM grp WHERE company_id=? AND parent=''", (cid,))]
        sides = {"liabilities": [], "assets": []}
        plain_assets = plain_liab = 0.0
        for g in prim:
            if g in PL_PRIMARY:
                continue
            total = _closing_group(c, cid, g)
            if g in LIAB_PRIMARY:
                side = "liabilities"
            elif g in ASSET_PRIMARY:
                side = "assets"
            else:                                   # a primary group the user made: place it by its balance
                side = "assets" if total >= 0 else "liabilities"
            sign = 1 if side == "assets" else -1
            subs = []
            for k in c.execute("SELECT name FROM grp WHERE company_id=? AND parent=? ORDER BY name", (cid, g)):
                v = _closing_group(c, cid, k["name"])
                if abs(v) > 0.5:
                    subs.append({"name": k["name"], "amount": round(v * sign, 2), "group": True})
            for l in c.execute("SELECT name, closing FROM ledger WHERE company_id=? AND parent=? AND ABS(closing) > 0.5",
                               (cid, g)):
                subs.append({"name": l["name"], "amount": round(l["closing"] * sign, 2), "group": False})
            subs.sort(key=lambda x: -abs(x["amount"]))
            if abs(total) > 0.5 or subs:
                sides[side].append({"name": g, "amount": round(total * sign, 2), "lines": subs})
            if side == "assets":
                plain_assets += total
            else:
                plain_liab -= total
        # ledgers outside every group: Tally's own "Profit & Loss A/c", or anything unusual
        known = set(prim)
        pl_open = 0.0
        for l in c.execute("SELECT name, chain, closing FROM ledger WHERE company_id=?", (cid,)):
            top = (l["chain"] or "||").split("|")[1] if l["chain"] else ""
            if top in known:
                continue
            if abs(l["closing"]) < 0.005:
                continue
            if "profit" in l["name"].lower() and "loss" in l["name"].lower():
                pl_open += -l["closing"]
            else:
                side = "assets" if l["closing"] >= 0 else "liabilities"
                amt = abs(l["closing"])
                sides[side].append({"name": l["name"], "amount": round(amt, 2), "lines": [], "ledger": True})
                if side == "assets":
                    plain_assets += amt
                else:
                    plain_liab += amt
        # closing stock: from stock items, unless stock is kept in ledgers (accounts not linked with inventory)
        stock_in_ledgers = c.execute("""SELECT COUNT(*) n FROM ledger WHERE company_id=? AND chain LIKE '%|Stock-in-Hand|%'
            AND ABS(closing) > 0.5""", (cid,)).fetchone()["n"] > 0
        stock_val = 0.0 if stock_in_ledgers else c.execute(
            "SELECT COALESCE(SUM(closing_value),0) s FROM stock WHERE company_id=?", (cid,)).fetchone()["s"]
        if stock_val:
            ca = next((x for x in sides["assets"] if x["name"] == "Current Assets"), None)
            if not ca:
                ca = {"name": "Current Assets", "amount": 0.0, "lines": []}
                sides["assets"].append(ca)
            ca["amount"] = round(ca["amount"] + stock_val, 2)
            ca["lines"].insert(0, {"name": "Closing stock", "amount": round(stock_val, 2), "group": False, "stock": True})
            plain_assets += stock_val
        profit_total = plain_assets - plain_liab
        pl = {"name": "Profit & Loss A/c", "amount": round(abs(profit_total), 2), "pl": True, "loss": profit_total < 0,
              "lines": [{"name": "Opening balance", "amount": round(pl_open if profit_total >= 0 else -pl_open, 2)},
                        {"name": "This period", "amount": round((profit_total - pl_open) * (1 if profit_total >= 0 else -1), 2)}]}
        sides["assets" if profit_total < 0 else "liabilities"].append(pl)
        order = {n: i for i, n in enumerate(LIAB_PRIMARY + ASSET_PRIMARY + ["Profit & Loss A/c"])}
        for s in sides.values():
            s.sort(key=lambda x: (order.get(x["name"], 50), -x["amount"]))
        comp = c.execute("SELECT to_date, last_sync FROM company WHERE id=?", (cid,)).fetchone()
        total = round(sum(x["amount"] for x in sides["assets"]), 2)
        unbalanced = c.execute("SELECT unbalanced FROM company WHERE id=?", (cid,)).fetchone()["unbalanced"]
        return {"unbalanced": unbalanced, "pl_this_period": pl["lines"][1]["amount"] * (-1 if pl["loss"] else 1),
                "as_on": min(date.today().isoformat(), comp["to_date"] or date.today().isoformat()),
                "last_sync": comp["last_sync"], "liabilities": sides["liabilities"], "assets": sides["assets"],
                "total": total, "stock_in_ledgers": stock_in_ledgers}


# ---------------------------------------------------------------- cash and bank book
CASH_BANK = ("Cash-in-Hand", "Bank Accounts", "Bank OD A/c")


def _tally_at(c, cid, name, day):
    """Tally's own balance of a ledger at the end of `day`, when Tally sent one for that month-end, else None."""
    r = c.execute("SELECT closing FROM ledger_at WHERE company_id=? AND ledger=? AND day=?", (cid, name, day)).fetchone()
    return r["closing"] if r else None


def _opening_at(c, cid, name, closing, sync_from, day):
    """Balance at the start of `day`, from Tally's own figures: its balance at the last month-end before `day`
    plus the entries after it, exactly as they are in Tally. Only when Tally hasn't sent month-end balances yet
    is it worked back from Tally's closing."""
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    start = (date.fromisoformat(sync_from) - timedelta(days=1)).isoformat()
    snap = c.execute("""SELECT day, closing FROM ledger_at WHERE company_id=? AND ledger=? AND day<=? AND day>=?
        ORDER BY day DESC LIMIT 1""", (cid, name, prev, start)).fetchone()
    if snap:
        moved = c.execute("""SELECT COALESCE(SUM(vl.amount),0) s FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
            WHERE v.company_id=? AND vl.ledger=? AND v.date > ? AND v.date < ?""", (cid, name, snap["day"], day)).fetchone()["s"]
        return snap["closing"] + moved
    moved = c.execute("""SELECT COALESCE(SUM(CASE WHEN v.date < ? THEN vl.amount ELSE 0 END),0) b, COALESCE(SUM(vl.amount),0) a
        FROM vline vl JOIN voucher v ON v.id=vl.voucher_id WHERE v.company_id=? AND vl.ledger=? AND v.date >= ?""",
                      (day, cid, name, sync_from)).fetchone()
    return closing - moved["a"] + moved["b"]


def cash_bank(cid, d_from=None, d_to=None):
    with conn() as c:
        comp = c.execute("SELECT from_date FROM company WHERE id=?", (cid,)).fetchone()
        sync_from = (comp and comp["from_date"]) or "2000-01-01"
        f, t = period(c, cid, d_from, d_to)
        f = max(f, sync_from)
        t = min(t, date.today().isoformat()) if t >= date.today().isoformat() else t
        where = " OR ".join("chain LIKE ?" for _ in CASH_BANK)
        args = [f"%|{g}|%" for g in CASH_BANK]
        leds = _rows(c, f"SELECT name, closing, chain FROM ledger WHERE company_id=? AND ({where}) ORDER BY name",
                     [cid] + args)
        names = [l["name"] for l in leds]
        out_l = []
        for l in leds:
            op = _opening_at(c, cid, l["name"], l["closing"], sync_from, f)
            mv = c.execute("""SELECT COALESCE(SUM(CASE WHEN vl.amount>0 THEN vl.amount END),0) i,
                COALESCE(-SUM(CASE WHEN vl.amount<0 THEN vl.amount END),0) o
                FROM vline vl JOIN voucher v ON v.id=vl.voucher_id WHERE v.company_id=? AND vl.ledger=? AND v.date BETWEEN ? AND ?""",
                           (cid, l["name"], f, t)).fetchone()
            kind = "Cash" if "|Cash-in-Hand|" in l["chain"] else "Bank"
            if abs(op) > 0.005 or mv["i"] or mv["o"] or abs(l["closing"]) > 0.005:
                # closing as Tally has it: its month-end figure, or its current balance for a period running to today
                tc = _tally_at(c, cid, l["name"], t)
                if tc is None and t >= date.today().isoformat():
                    tc = l["closing"]
                worked = op + mv["i"] - mv["o"]
                cl = worked if tc is None else tc
                out_l.append({"name": l["name"], "kind": kind, "opening": round(op, 2), "in": round(mv["i"], 2),
                              "out": round(mv["o"], 2), "closing": round(cl, 2),
                              "difference": round(cl - worked, 2) if abs(cl - worked) > 0.5 else 0.0})
        opening = sum(x["opening"] for x in out_l)
        days = {}
        if names:
            ph = ",".join("?" for _ in names)
            for r in c.execute(f"""SELECT v.id, v.date, v.vtype, v.number, v.party, v.narration, SUM(vl.amount) net,
                    GROUP_CONCAT(vl.ledger, '|') leds
                    FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
                    WHERE v.company_id=? AND v.date BETWEEN ? AND ? AND vl.ledger IN ({ph})
                    GROUP BY v.id ORDER BY v.date, v.id""", [cid, f, t] + names):
                d = days.setdefault(r["date"], {"date": r["date"], "in": 0.0, "out": 0.0, "entries": []})
                net = r["net"] or 0
                if net > 0:
                    d["in"] += net
                else:
                    d["out"] -= net
                d["entries"].append({"id": r["id"], "vtype": r["vtype"], "number": r["number"],
                                     "party": r["party"] or r["narration"][:60], "amount": round(net, 2),
                                     "transfer": abs(net) < 0.005, "ledgers": sorted(set(r["leds"].split("|")))})
        bal = opening
        rows = []
        for k in sorted(days):
            d = days[k]
            d["opening"] = round(bal, 2)
            bal += d["in"] - d["out"]
            d["closing"] = round(bal, 2)
            d["in"], d["out"] = round(d["in"], 2), round(d["out"], 2)
            rows.append(d)
        rows.reverse()
        return {"from": f, "to": t, "ledgers": out_l, "opening": round(opening, 2),
                "in": round(sum(x["in"] for x in out_l), 2), "out": round(sum(x["out"] for x in out_l), 2),
                "closing": round(sum(x["closing"] for x in out_l), 2), "entries_total": round(bal, 2),
                "difference": round(sum(x["difference"] for x in out_l), 2), "days": rows}


# ---------------------------------------------------------------- collection follow-up
FOLLOW = os.path.join(os.path.dirname(DB_PATH), "followups.json")
_flock = threading.Lock()


def _follow_all():
    try:
        with open(FOLLOW) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def set_followup(cid, party, note, promise):
    co = next((x for x in companies() if x["id"] == cid), None)
    if not co:
        return False
    with _flock:
        allf = _follow_all()
        per = allf.setdefault(co["name"], {})
        if note or promise:
            per[party] = {"note": note[:300], "promise": promise, "updated": time.time()}
        else:
            per.pop(party, None)
        tmp = FOLLOW + ".tmp"
        with open(tmp, "w") as f:
            json.dump(allf, f)
        os.replace(tmp, FOLLOW)
    return True


def collections(cid, days=7):
    """Who should pay: overdue bills and bills falling due in the next few days, with your notes."""
    co = next((x for x in companies() if x["id"] == cid), None)
    notes = _follow_all().get(co["name"], {}) if co else {}
    today = date.today()
    soon = (today + timedelta(days=days)).isoformat()
    t = today.isoformat()
    d = outstanding(cid, "receivable")
    out = []
    for p in d["parties"]:
        od, due_soon = [], []
        for b in p["bills"]:
            if b["amount"] <= 0.5:
                continue
            due = b["due"] or b["date"]
            if not due:
                continue
            if due < t:
                od.append({**b, "late": (today - date.fromisoformat(due)).days})
            elif due <= soon:
                due_soon.append({**b, "in_days": (date.fromisoformat(due) - today).days})
        n = notes.get(p["name"])
        if not od and not due_soon and not n:
            continue
        od.sort(key=lambda b: -b["late"])
        due_soon.sort(key=lambda b: b["in_days"])
        out.append({"name": p["name"], "mobile": p["mobile"], "phone": p["phone"], "balance": p["amount"],
                    "interest": p.get("interest", 0),
                    "overdue": round(sum(b["amount"] for b in od), 2), "due_soon": round(sum(b["amount"] for b in due_soon), 2),
                    "late": od[0]["late"] if od else 0, "overdue_bills": od, "soon_bills": due_soon,
                    "note": n.get("note", "") if n else "", "promise": n.get("promise", "") if n else "",
                    "promise_missed": bool(n and n.get("promise") and n["promise"] < t and od)})
    out.sort(key=lambda x: (not x["promise_missed"], -x["overdue"], -x["due_soon"]))
    return {"days": days, "today": t, "overdue": round(sum(x["overdue"] for x in out), 2),
            "due_soon": round(sum(x["due_soon"] for x in out), 2),
            "promised_today": [x["name"] for x in out if x["promise"] == t],
            "parties": out}


def party_names(cid):
    with conn() as c:
        return {r["name"] for r in c.execute("""SELECT name FROM ledger WHERE company_id=?
            AND (chain LIKE '%|Sundry Debtors|%' OR chain LIKE '%|Sundry Creditors|%')""", (cid,))}


def voucher_party(cid, vid):
    with conn() as c:
        r = c.execute("SELECT party FROM voucher WHERE company_id=? AND id=?", (cid, vid)).fetchone()
        return r["party"] if r else None



# ---------------------------------------------------------------- Tally-style Profit & Loss and Balance Sheet
# Where a group goes is decided the way Tally decides it, from the group's own nature:
#   revenue  -> Profit & Loss (else Balance Sheet)
#   gp       -> above the Gross Profit line (trading part)
#   debit    -> left side of P&L (expenses), right side of Balance Sheet (assets)
DEFAULT_NATURE = {
    "Sales Accounts": (1, 1, 0), "Purchase Accounts": (1, 1, 1), "Direct Incomes": (1, 1, 0), "Direct Expenses": (1, 1, 1),
    "Indirect Incomes": (1, 0, 0), "Indirect Expenses": (1, 0, 1),
    "Capital Account": (0, 0, 0), "Loans (Liability)": (0, 0, 0), "Current Liabilities": (0, 0, 0), "Branch / Divisions": (0, 0, 0),
    "Suspense A/c": (0, 0, 0), "Fixed Assets": (0, 0, 1), "Investments": (0, 0, 1), "Current Assets": (0, 0, 1),
    "Misc. Expenses (ASSET)": (0, 0, 1),
}
BS_ORDER = ["Capital Account", "Loans (Liability)", "Current Liabilities", "Branch / Divisions", "Suspense A/c",
            "Fixed Assets", "Investments", "Current Assets", "Misc. Expenses (ASSET)"]
PL_ORDER = ["Purchase Accounts", "Direct Expenses", "Sales Accounts", "Direct Incomes", "Indirect Expenses", "Indirect Incomes"]


def _natures(c, cid, values):
    out = {}
    for g in c.execute("SELECT name, revenue, gp, debit FROM grp WHERE company_id=? AND parent=''", (cid,)):
        d = DEFAULT_NATURE.get(g["name"])
        if g["revenue"] is not None:
            out[g["name"]] = (g["revenue"], g["gp"] or 0, g["debit"] or 0)
        elif d:
            out[g["name"]] = d
        else:      # unknown own group without Tally's flags (older agent): Balance Sheet, side by balance
            out[g["name"]] = (0, 0, 1 if values.get(("grp", g["name"]), 0) >= 0 else 0)
    return out


def _tree(c, cid, values):
    """Totals per group (all ledgers below it) and the direct children of each group."""
    groups = {g["name"]: g["parent"] for g in c.execute("SELECT name, parent FROM grp WHERE company_id=?", (cid,))}
    tot = {}
    led = c.execute("SELECT name, parent, chain FROM ledger WHERE company_id=?", (cid,)).fetchall()
    for l in led:
        v = values.get(l["name"], 0)
        for g in (l["chain"] or "").strip("|").split("|"):
            if g:
                tot[g] = tot.get(g, 0) + v
    kids = {}
    for g, p in groups.items():
        if p:
            kids.setdefault(p, []).append(("group", g))
    for l in led:
        if l["parent"] in groups:
            kids.setdefault(l["parent"], []).append(("ledger", l["name"]))
    return tot, kids, led


def _lines(name, tot, kids, values, sign):
    rows = []
    for kind, n in kids.get(name, []):
        v = (tot.get(n, 0) if kind == "group" else values.get(n, 0)) * sign
        if abs(v) > 0.005:
            rows.append({"name": n, "amount": round(v, 2), "group": kind == "group"})
    rows.sort(key=lambda r: (not r["group"], -abs(r["amount"])))
    return rows


def _period_stock(cid, f, t):
    """Opening stock at f and closing stock at t; exact where Tally's own figure is known."""
    st = stock(cid, "", f, t)
    with conn() as c:
        master = {r["name"]: r for r in c.execute("SELECT name, opening_qty, opening_value FROM stock WHERE company_id=?", (cid,))}
    if st["open_exact"]:
        return st["open_total"], True, st["total"], st["close_exact"]
    same = st["items"] and all(abs(i["open_qty"] - (master.get(i["name"]) or {"opening_qty": 0})["opening_qty"]) < 0.001 for i in st["items"])
    if same:     # nothing moved before f: Tally's own opening value applies
        return round(sum(m["opening_value"] for m in master.values()), 2), True, st["total"], st["close_exact"]
    return st["open_total"], False, st["total"], st["close_exact"]


def tally_pl(cid, d_from=None, d_to=None):
    with conn() as c:
        f, t = period(c, cid, d_from, d_to)
        mv = {r["ledger"]: r["s"] for r in c.execute("""SELECT vl.ledger, SUM(vl.amount) s FROM vline vl JOIN voucher v ON v.id=vl.voucher_id
            WHERE v.company_id=? AND v.date BETWEEN ? AND ? GROUP BY vl.ledger""", (cid, f, t))}
        tot, kids, _ = _tree(c, cid, mv)
        nat = _natures(c, cid, {("grp", k): v for k, v in tot.items()})
        prims = [g for g, n in nat.items() if n[0]]
    prims.sort(key=lambda g: (PL_ORDER.index(g) if g in PL_ORDER else 50, g))
    o_stock, o_exact, c_stock, c_exact = _period_stock(cid, f, t)

    def side(gp, debit):
        sign = 1 if debit else -1
        return [{"name": g, "amount": round(tot.get(g, 0) * sign, 2), "lines": _lines(g, tot, kids, mv, sign)}
                for g in prims if nat[g][1] == gp and nat[g][2] == debit and abs(tot.get(g, 0)) > 0.005]
    tr_dr = [{"name": "Opening Stock", "amount": round(o_stock, 2), "lines": [], "stock": True, "approx": not o_exact}] + side(1, 1)
    tr_cr = side(1, 0) + [{"name": "Closing Stock", "amount": round(c_stock, 2), "lines": [], "stock": True, "approx": not c_exact}]
    gross = sum(x["amount"] for x in tr_cr) - sum(x["amount"] for x in tr_dr)
    if gross >= 0:
        tr_dr.append({"name": "Gross Profit c/o", "amount": round(gross, 2), "lines": [], "result": True})
    else:
        tr_cr.append({"name": "Gross Loss c/o", "amount": round(-gross, 2), "lines": [], "result": True})
    t1 = round(max(sum(x["amount"] for x in tr_dr), sum(x["amount"] for x in tr_cr)), 2)
    pl_dr = ([{"name": "Gross Loss b/f", "amount": round(-gross, 2), "lines": [], "result": True}] if gross < 0 else []) + side(0, 1)
    pl_cr = ([{"name": "Gross Profit b/f", "amount": round(gross, 2), "lines": [], "result": True}] if gross >= 0 else []) + side(0, 0)
    nett = sum(x["amount"] for x in pl_cr) - sum(x["amount"] for x in pl_dr)
    if nett >= 0:
        pl_dr.append({"name": "Nett Profit", "amount": round(nett, 2), "lines": [], "result": True})
    else:
        pl_cr.append({"name": "Nett Loss", "amount": round(-nett, 2), "lines": [], "result": True})
    t2 = round(max(sum(x["amount"] for x in pl_dr), sum(x["amount"] for x in pl_cr)), 2)
    return {"from": f, "to": t, "trading": {"dr": tr_dr, "cr": tr_cr, "total": t1}, "pl": {"dr": pl_dr, "cr": pl_cr, "total": t2},
            "gross_profit": round(gross, 2), "net_profit": round(nett, 2), "stock_exact": o_exact and c_exact}


def tally_bs(cid):
    today = date.today().isoformat()
    with conn() as c:
        fs, fe = period(c, cid, None, None)
        as_at = min(today, fe)
        cl = {r["name"]: r["closing"] for r in c.execute("SELECT name, closing FROM ledger WHERE company_id=?", (cid,))}
        tot, kids, led = _tree(c, cid, cl)
        nat = _natures(c, cid, {("grp", k): v for k, v in tot.items()})
        prims = [g for g, n in nat.items() if not n[0]]
        stock_in_ledgers = c.execute("""SELECT COUNT(*) n FROM ledger WHERE company_id=? AND chain LIKE '%|Stock-in-Hand|%'
            AND ABS(closing) > 0.5""", (cid,)).fetchone()["n"] > 0
        stock_val = 0.0 if stock_in_ledgers else c.execute(
            "SELECT COALESCE(SUM(closing_value),0) s FROM stock WHERE company_id=?", (cid,)).fetchone()["s"]
        known = set(nat)
        loose = [l for l in led if ((l["chain"] or "||").split("|")[1] if l["chain"] else "") not in known and abs(cl.get(l["name"], 0)) > 0.005]
        unbalanced = c.execute("SELECT unbalanced FROM company WHERE id=?", (cid,)).fetchone()["unbalanced"]
    prims.sort(key=lambda g: (BS_ORDER.index(g) if g in BS_ORDER else 50, g))
    liab, assets = [], []
    for g in prims:
        debit = nat[g][2]
        sign = 1 if debit else -1
        lines = _lines(g, tot, kids, cl, sign)
        amt = tot.get(g, 0) * sign
        if g == "Current Assets" and stock_val:
            lines.insert(0, {"name": "Closing Stock", "amount": round(stock_val, 2), "group": False, "stock": True})
            amt += stock_val
        if abs(amt) > 0.005 or lines:
            (assets if debit else liab).append({"name": g, "amount": round(amt, 2), "lines": lines})
    if stock_val and not any(x["name"] == "Current Assets" for x in assets):
        assets.append({"name": "Current Assets", "amount": round(stock_val, 2),
                       "lines": [{"name": "Closing Stock", "amount": round(stock_val, 2), "group": False, "stock": True}]})
    for l in loose:      # ledgers outside every group, e.g. Tally's own "Profit & Loss A/c"
        if "profit" in l["name"].lower() and "loss" in l["name"].lower():
            continue
        v = cl[l["name"]]
        (assets if v >= 0 else liab).append({"name": l["name"], "amount": round(abs(v), 2), "lines": [], "ledger": True})
    a_tot = sum(x["amount"] for x in assets)
    l_tot = sum(x["amount"] for x in liab)
    pl_total = a_tot - l_tot                  # what makes both sides equal
    current = tally_pl(cid, fs, as_at)["net_profit"]
    liab.append({"name": "Profit & Loss A/c", "amount": round(pl_total, 2), "pl": True,
                 "lines": [{"name": "Opening Balance", "amount": round(pl_total - current, 2)},
                           {"name": "Current Period", "amount": round(current, 2)}]})
    return {"as_at": as_at, "period_from": fs, "liabilities": liab, "assets": assets, "total": round(a_tot, 2),
            "stock_in_ledgers": stock_in_ledgers, "unbalanced": unbalanced}
