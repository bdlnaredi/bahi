"""UPI payment requests: each company's UPI ID, the upi://pay links and QR codes made from it.
The money goes straight from the customer's UPI app to that UPI ID; Bahi never touches it."""
import io
import json
import os
import re
import threading
from urllib.parse import quote

import store

PATH = os.path.join(os.path.dirname(store.DB_PATH), "upi.json")
VPA = re.compile(r"^[A-Za-z0-9.\-_]{2,256}@[A-Za-z][A-Za-z0-9.\-]{1,63}$")
_lock = threading.Lock()


def _load():
    try:
        with open(PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def all_():
    return _load()


def get(company):
    """{vpa, name} for the company, or None when no UPI ID is set."""
    c = _load().get(company)
    return c if c and c.get("vpa") else None


def set_(company, vpa, name):
    vpa = (vpa or "").strip()
    if vpa and not VPA.match(vpa):
        raise ValueError("That isn't a UPI ID. It looks like name@bank, e.g. shivshakti@okhdfcbank or 9876543210@ybl.")
    with _lock:
        d = _load()
        if vpa:
            d[company] = {"vpa": vpa, "name": (name or "").strip()[:60] or company}
        else:
            d.pop(company, None)
        tmp = PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, PATH)
    return get(company)


def uri(company, amount=None, note=""):
    """upi://pay?... that any UPI app (GPay, PhonePe, Paytm, BHIM, bank apps) opens with the amount filled in."""
    c = get(company)
    if not c:
        return None
    q = [("pa", c["vpa"]), ("pn", c["name"])]
    if amount and amount > 0:
        q.append(("am", f"{amount:.2f}"))
    q.append(("cu", "INR"))
    if note:
        q.append(("tn", re.sub(r"\s+", " ", note).strip()[:80]))
    return "upi://pay?" + "&".join(f"{k}={quote(v, safe='@.-_')}" for k, v in q)


def qr_svg(text, scale=6):
    """The QR code of text as an SVG string (dark modules on white, with the quiet border scanners need)."""
    import segno
    q = segno.make(text, error="m", micro=False)
    out = io.BytesIO()
    q.save(out, kind="svg", scale=scale, border=3, dark="#000000", light="#ffffff", xmldecl=False, svgns=True)
    return out.getvalue().decode()
