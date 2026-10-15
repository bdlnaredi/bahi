"""Telegram: a daily summary each morning, and an alert when a large payment comes in."""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
SETTINGS = os.path.join(DATA_DIR, "telegram.json")
API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")
_lock = threading.Lock()

DEFAULTS = {"token": "", "chat_id": "", "daily": True, "time": "09:00", "alert_min": 50000,
            "alerts": True, "last_daily": "", "alerted": []}


def load():
    try:
        with open(SETTINGS) as f:
            return {**DEFAULTS, **json.load(f)}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(s):
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, SETTINGS)


def public(s):
    """Settings for the app screen - the bot token is never sent back, only whether one is set."""
    return {"configured": bool(s["token"] and s["chat_id"]), "has_token": bool(s["token"]),
            "chat_id": s["chat_id"], "daily": s["daily"], "time": s["time"],
            "alert_min": s["alert_min"], "alerts": s["alerts"]}


def _call(token, method, params):
    url = f"{API}/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
        return json.loads(r.read().decode())


def send(text, s=None):
    s = s or load()
    if not (s["token"] and s["chat_id"]):
        raise ValueError("Telegram isn't set up yet.")
    res = _call(s["token"], "sendMessage", {"chat_id": s["chat_id"], "text": text, "parse_mode": "HTML",
                                            "disable_web_page_preview": "true"})
    if not res.get("ok"):
        raise ValueError(res.get("description", "Telegram refused the message."))


def find_chat(token):
    """After you send any message to your bot, this finds the chat it came from."""
    res = _call(token, "getUpdates", {"limit": 20})
    if not res.get("ok"):
        raise ValueError(res.get("description", "That bot token was not accepted."))
    for u in reversed(res.get("result", [])):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            return {"chat_id": str(chat["id"]), "name": chat.get("title") or chat.get("first_name") or chat.get("username") or ""}
    return None


def _inr(n):
    n = round(abs(n or 0))
    s = str(int(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return "₹" + s


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def summary_text(cid, day=None):
    day = day or (date.today() - timedelta(days=1))
    d = day.isoformat()
    month_start = date.today().replace(day=1).isoformat()
    co = next((c for c in store.companies() if c["id"] == cid), None)
    if not co:
        return ""
    with store.conn() as c:
        def one(sql, args):
            r = c.execute(sql, args).fetchone()
            return (r[0] or 0, r[1] or 0)
        s_amt, s_n = one("SELECT SUM(amount), COUNT(*) FROM voucher WHERE company_id=? AND base='Sales' AND posting=1 AND date=?", (cid, d))
        r_amt, r_n = one("SELECT SUM(amount), COUNT(*) FROM voucher WHERE company_id=? AND base='Receipt' AND posting=1 AND date=?", (cid, d))
        p_amt, p_n = one("SELECT SUM(amount), COUNT(*) FROM voucher WHERE company_id=? AND base='Payment' AND posting=1 AND date=?", (cid, d))
        m_amt, m_n = one("SELECT SUM(amount), COUNT(*) FROM voucher WHERE company_id=? AND base='Sales' AND posting=1 AND date>=?",
                         (cid, month_start))
    dash = store.dashboard(cid)
    rec = store.outstanding(cid, "receivable")
    pay = store.outstanding(cid, "payable")
    worst = sorted([p for p in rec["parties"] if p["overdue_amount"] > 0], key=lambda p: -p["overdue_amount"])[:3]
    lines = [f"<b>{_esc(co['name'])}</b>", f"{day.strftime('%a %d %b %Y')}", "",
             f"Sales: <b>{_inr(s_amt)}</b> ({s_n} bills)",
             f"Received: <b>{_inr(r_amt)}</b> ({r_n} receipts)",
             f"Paid out: {_inr(p_amt)} ({p_n} payments)",
             f"Sales this month so far: {_inr(m_amt)} ({m_n} bills)", "",
             f"Cash {_inr(dash['cash'])}, bank {_inr(dash['bank_total'])}",
             f"To receive: <b>{_inr(rec['total'])}</b>, overdue {_inr(rec['overdue'])}",
             f"To pay: {_inr(pay['total'])}, overdue {_inr(pay['overdue'])}"]
    if worst:
        lines += ["", "Biggest overdue:"]
        lines += [f"  {_esc(p['name'])}: {_inr(p['overdue_amount'])}" for p in worst]
    if co.get("last_sync") and time.time() - co["last_sync"] > 36 * 3600:
        lines += ["", "Note: Tally hasn't synced for over a day, so these figures may be out of date."]
    return "\n".join(lines)


def alert_new_receipts():
    """Called after every sync: one message per large receipt dated today or yesterday."""
    s = load()
    if not (s["token"] and s["chat_id"] and s["alerts"]):
        return
    since = (date.today() - timedelta(days=1)).isoformat()
    sent = set(s["alerted"])
    new = []
    for co in store.companies():
        with store.conn() as c:
            for v in c.execute("""SELECT guid, date, number, party, amount FROM voucher WHERE company_id=? AND base='Receipt'
                    AND posting=1 AND date>=? AND amount>=? ORDER BY date, id""", (co["id"], since, float(s["alert_min"] or 0))):
                key = f"{co['id']}:{v['guid'] or v['number']}"
                if key not in sent:
                    new.append((key, co["name"], dict(v)))
    for key, cname, v in new[:20]:
        try:
            send(f"Payment received: <b>{_inr(v['amount'])}</b> from {_esc(v['party'])}\n"
                 f"Receipt {_esc(v['number'])}, {v['date']}\n{_esc(cname)}", s)
            sent.add(key)
        except Exception as e:
            print("telegram alert failed:", e)
            break
    with _lock:
        s2 = load()
        s2["alerted"] = list(sent)[-500:]
        save(s2)


def _loop():
    while True:
        try:
            s = load()
            now = time.localtime()
            today = time.strftime("%Y-%m-%d", now)
            if s["token"] and s["chat_id"] and s["daily"] and s["last_daily"] != today \
                    and time.strftime("%H:%M", now) >= (s["time"] or "09:00"):
                for co in store.companies():
                    send(summary_text(co["id"]), s)
                with _lock:
                    s2 = load()
                    s2["last_daily"] = today
                    save(s2)
        except Exception as e:
            print("telegram daily summary failed, trying again in 15 minutes:", e)
            time.sleep(900)
        time.sleep(30)


def start():
    threading.Thread(target=_loop, daemon=True).start()
