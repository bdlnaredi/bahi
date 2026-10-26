"""Telegram questions: send the bot a party's name (spelt any way) and it answers with that ledger.

Only the chat Telegram was connected to in Settings gets answers; anyone else who finds the bot gets nothing.
A name that matches one ledger clearly gets the summary straight away; otherwise the closest ledgers come back
as buttons to choose from. Under a summary are buttons for the statement PDF (this month or this year).
"""
import difflib
import json
import re
import secrets
import threading
import time
import urllib.request
import uuid
from datetime import date

import notify
import pdf
import store

PICKS = {}            # short button code -> (company id, ledger name); buttons from before a restart just ask again
_picks_lock = threading.Lock()
HELP = ("Send me a party's name, or part of it, and I'll reply with their ledger: balance, this month's "
        "entries and pending bills. Spelling doesn't need to be exact.\n\n"
        "/summary - yesterday's business summary\n/help - this message")


# ---------------------------------------------------------------- finding a ledger from a rough name
_WORDS = {"m/s": "", "ms": "", "and": "&", "pvt": "", "private": "", "ltd": "", "limited": "", "co": "", "the": ""}


def _norm(s):
    s = (s or "").lower().replace("&", " & ")
    s = re.sub(r"[^\w&ऀ-ॿ]+", " ", s)
    return " ".join(_WORDS.get(w, w) for w in s.split() if _WORDS.get(w, w))


def _skeleton(s):
    """Spelling-proof form for Indian names in English letters: Sharma/Sarma, Bhandar/Bandar, Aggarwal/Agarwal."""
    s = _norm(s)
    for a, b in (("ph", "f"), ("sh", "s"), ("ch", "c"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("th", "t"),
                 ("jh", "j"), ("w", "v"), ("z", "j"), ("q", "k"), ("ck", "k"), ("x", "ks"), ("y", "i"),
                 ("ee", "i"), ("oo", "u"), ("aa", "a"), ("ou", "u")):
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)                       # double letters
    s = re.sub(r"(?<=[^aeiou ])h", "", s)                 # leftover aspirates
    return s


def _score(q, name):
    nq, nn = _norm(q), _norm(name)
    if not nq or not nn:
        return 0.0
    if nq == nn:
        return 1.0
    if nn.startswith(nq):
        return 0.95
    if f" {nq}" in f" {nn}":
        return 0.9
    cq, cn = nq.replace(" ", ""), nn.replace(" ", "")      # "sr industries" for "S R Industries"
    if len(cq) >= 3 and cn.startswith(cq):
        return 0.92
    if len(cq) >= 4 and cq in cn:
        return 0.88
    sq, sn = _skeleton(q), _skeleton(name)
    if sq and (sn.startswith(sq) or f" {sq}" in f" {sn}"):
        return 0.86
    # each word typed against the best-matching word of the name
    words = sn.split()
    parts = []
    for w in sq.split():
        best = max((difflib.SequenceMatcher(None, w, x).ratio() + (0.1 if x.startswith(w[:3]) else 0) for x in words), default=0)
        parts.append(min(best, 1.0))
    word_score = sum(parts) / len(parts) if parts else 0
    whole = difflib.SequenceMatcher(None, sq, sn).ratio()
    return max(word_score * 0.85, whole * 0.8)


def search(q, limit=8):
    """[(score, company id, company name, ledger name, group)] best first."""
    found = []
    cos = store.companies()
    with store.conn() as c:
        for co in cos:
            for r in c.execute("SELECT name, parent FROM ledger WHERE company_id=?", (co["id"],)):
                sc = _score(q, r["name"])
                if sc >= 0.55:
                    found.append((sc, co["id"], co["name"], r["name"], r["parent"]))
    # best score first; on a tie, the company with the latest vouchers (usually the current year), then by name
    latest = {co["id"]: co.get("last_vch") or "" for co in cos}
    found.sort(key=lambda x: x[3].lower())
    found.sort(key=lambda x: latest.get(x[1], ""), reverse=True)
    found.sort(key=lambda x: -x[0])
    return found[:limit]


# ---------------------------------------------------------------- what is sent back
def _drcr(n):
    return f"{notify._inr(n)} {'Dr' if n >= 0 else 'Cr'}" if abs(n or 0) >= 0.5 else "₹0"


def ledger_text(cid, name):
    today = date.today()
    f, t = today.replace(day=1).isoformat(), today.isoformat()
    d = store.ledger(cid, name, f, t)
    if not d:
        return None
    L = d["ledger"]
    co = next((c["name"] for c in store.companies() if c["id"] == cid), "")
    lines = [f"<b>{notify._esc(L['name'])}</b>", f"<i>{notify._esc(L.get('parent') or '')}" + (f" · {notify._esc(co)}" if len(store.companies()) > 1 else "") + "</i>"]
    contact = L.get("mobile") or L.get("phone")
    if contact:
        lines.append(f"📞 {notify._esc(contact)}")
    lines.append("")
    lines.append(f"Balance now: <b>{_drcr(L['closing'])}</b>")
    lines.append(f"This month: opening {_drcr(d['opening'])}, debits {notify._inr(d['debit'])}, credits {notify._inr(d['credit'])}")
    if d.get("difference"):
        lines.append(f"⚠ Entries here differ from Tally by {notify._inr(d['difference'])} (see Sync check in the app)")
    if d["entries"]:
        lines.append("")
        lines.append("<b>Latest entries</b>")
        for e in d["entries"][-6:]:
            amt = e["amount"]
            dd = date.fromisoformat(e["date"]).strftime("%d %b")
            lines.append(f"{dd}  {notify._esc(e['vtype'])} {notify._esc(e['number'])}  {notify._inr(amt)} {'Dr' if amt > 0 else 'Cr'}")
    else:
        lines.append("No entries this month.")
    bills = [b for b in (d.get("bills") or []) if abs(b.get("amount", 0)) >= 0.5]
    if bills:
        due = sum(b["amount"] for b in bills)
        od = [b for b in bills if (b.get("overdue") or 0) > 0]
        lines.append("")
        lines.append(f"<b>Pending bills</b>: {len(bills)}, {notify._inr(due)}" + (f", overdue {notify._inr(sum(b['amount'] for b in od))}" if od else ""))
        for b in sorted(bills, key=lambda b: -(b.get("overdue") or 0))[:5]:
            when = f"{b['overdue']} days overdue" if (b.get("overdue") or 0) > 0 else (f"{b['age']} days old" if b.get("age") is not None else "")
            lines.append(f"• {notify._esc(b['ref'])}  {notify._inr(b['amount'])}  {when}")
    return "\n".join(lines)


def _code(cid, name):
    k = secrets.token_hex(4)
    with _picks_lock:
        if len(PICKS) > 2000:
            PICKS.clear()
        PICKS[k] = (cid, name)
    return k


def _keyboard(rows):
    return json.dumps({"inline_keyboard": rows})


def _send(s, text, buttons=None):
    p = {"chat_id": s["chat_id"], "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if buttons:
        p["reply_markup"] = _keyboard(buttons)
    notify._call(s["token"], "sendMessage", p)


def _send_pdf(s, data, filename, caption):
    """Telegram's sendDocument needs a multipart upload."""
    b = "----bahi" + uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", s["chat_id"]), ("caption", caption)):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    safe = re.sub(r'[^\w .()-]+', " ", filename).strip() or "ledger.pdf"
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="document"; filename="{safe}"\r\n'
                 f'Content-Type: application/pdf\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"{notify.API}/bot{s['token']}/sendDocument", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def answer_ledger(s, cid, name):
    text = ledger_text(cid, name)
    if not text:
        _send(s, "That ledger isn't in Bahi any more. Send the name again.")
        return
    k = _code(cid, name)
    _send(s, text, [[{"text": "📄 This month PDF", "callback_data": f"m:{k}"},
                     {"text": "📄 This year PDF", "callback_data": f"y:{k}"}]])


def answer_text(s, text):
    t = (text or "").strip()
    if not t:
        return
    low = t.lower()
    if low in ("/start", "/help", "help"):
        _send(s, HELP)
        return
    if low.startswith("/summary"):
        for co in store.companies():
            _send(s, notify.summary_text(co["id"]))
        return
    if low.startswith("/ledger"):
        t = t[7:].strip()
    elif t.startswith("/"):
        _send(s, HELP)
        return
    if len(_norm(t)) < 2:
        _send(s, "Send at least two letters of the name.")
        return
    found = search(t)
    if not found:
        _send(s, f"No ledger like “{notify._esc(t)}”. Try another part of the name.")
        return
    best = found[0]
    # answer straight away when one ledger name stands out (the same name in an older year's company doesn't count)
    rivals = [f_ for f_ in found[1:] if f_[3] != best[3] and f_[0] >= best[0] - 0.08]
    if not rivals and (best[0] >= 0.9 or (best[0] >= 0.7 and len({f_[3] for f_ in found}) == 1)):
        answer_ledger(s, best[1], best[3])
        return
    many_cos = len({f_[1] for f_ in found}) > 1
    rows = [[{"text": (f"{name} · {co}" if many_cos else name)[:60], "callback_data": f"l:{_code(cid, name)}"}]
            for sc, cid, co, name, grp in found]
    _send(s, f"Which one did you mean by “{notify._esc(t)}”?", rows)


def answer_button(s, data):
    kind, _, k = (data or "").partition(":")
    with _picks_lock:
        pick = PICKS.get(k)
    if not pick:
        _send(s, "That list is from before the server restarted. Send the name again.")
        return
    cid, name = pick
    if kind == "l":
        answer_ledger(s, cid, name)
    elif kind in ("m", "y"):
        today = date.today()
        f = today.replace(day=1) if kind == "m" else date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        d = store.ledger(cid, name, f.isoformat(), today.isoformat())
        if not d:
            _send(s, "That ledger isn't in Bahi any more.")
            return
        r = _send_pdf(s, pdf.ledger_pdf(d), f"{name} {f:%b %Y}{'' if kind == 'm' else ' to ' + today.strftime('%b %Y')}.pdf",
                      f"{name}: {f:%d %b %Y} to {today:%d %b %Y}")
        if not r.get("ok"):
            _send(s, "Couldn't send the PDF: " + notify._esc(r.get("description", "")))


# ---------------------------------------------------------------- listening
def _poll_once(s):
    res = notify._call(s["token"], "getUpdates", {"offset": s.get("offset", 0), "timeout": 25,
                                                  "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=40)
    if not res.get("ok"):
        raise ValueError(res.get("description", "getUpdates failed"))
    last = None
    for u in res.get("result", []):
        last = u["update_id"]
        try:
            msg, cb = u.get("message"), u.get("callback_query")
            chat = str(((msg or {}).get("chat") or ((cb or {}).get("message") or {}).get("chat") or {}).get("id", ""))
            if chat != str(s["chat_id"]):
                continue                                  # only the owner's chat gets answers
            if cb:
                try:
                    notify._call(s["token"], "answerCallbackQuery", {"callback_query_id": cb["id"]})
                except Exception:
                    pass
                answer_button(s, cb.get("data"))
            elif msg and msg.get("text"):
                answer_text(s, msg["text"])
        except Exception as e:
            print("telegram question failed:", e, flush=True)
            try:
                _send(s, "Sorry, that didn't work. Try again in a minute.")
            except Exception:
                pass
    if last is not None:
        with notify._lock:
            s2 = notify.load()
            s2["offset"] = last + 1
            notify.save(s2)


def _loop():
    while True:
        s = notify.load()
        if not (s["token"] and s["chat_id"] and s.get("questions", True)):
            time.sleep(20)
            continue
        try:
            _poll_once(s)
        except Exception as e:
            print("telegram questions: waiting a minute after", e, flush=True)
            time.sleep(60)


def start():
    threading.Thread(target=_loop, daemon=True).start()
