"""Staff logins. The owner logs in with the app password and can do everything;
staff log in with their name and their own password and see only what the owner allows."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
FILE = os.path.join(DATA_DIR, "users.json")
_lock = threading.Lock()

# what a staff member can be allowed, in the order the app shows them
PERMS = [
    ("accounts", "Money figures: Home dashboard, Profit & Loss, Balance Sheet, cash and bank, GST, sales analysis"),
    ("sales", "Sales by day"),
    ("ledgers", "All ledgers"),
    ("parties", "Customer and supplier ledgers only"),
    ("vouchers", "Vouchers and Day Book"),
    ("dues", "Dues and follow-up list"),
    ("stock", "Stock"),
    ("e_receipt", "Enter receipts"),
    ("e_payment", "Enter payments"),
    ("e_order", "Enter sales orders"),
    ("e_journal", "Enter journals"),
    ("e_contra", "Enter contra (cash and bank transfers)"),
    ("e_direct", "Their entries go to Tally without your approval"),
]
PERM_KEYS = {k for k, _ in PERMS}
OWNER = {"name": "", "owner": True, "perms": sorted(PERM_KEYS), "companies": []}


def _load():
    try:
        with open(FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"users": {}}


def _save(d):
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, FILE)


def _hash(pw, salt, it=200_000):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it).hex()


def key(name):
    return " ".join((name or "").split()).lower()


def public(u):
    return {"name": u["name"], "perms": u["perms"], "companies": u.get("companies", []),
            "active": u.get("active", True), "created": u.get("created"), "last_login": u.get("last_login")}


def listing():
    return [public(u) for u in sorted(_load()["users"].values(), key=lambda x: x["name"].lower())]


def get(name):
    """The staff member for a session, or None when removed or switched off."""
    u = _load()["users"].get(key(name))
    if not u or not u.get("active", True):
        return None
    return {"name": u["name"], "owner": False, "perms": u["perms"], "companies": u.get("companies", []),
            "gen": u.get("gen", 0)}


def check(name, pw):
    u = _load()["users"].get(key(name))
    if not u or not u.get("active", True):
        _hash(pw, b"0" * 16)          # same time either way, so a wrong name isn't obvious
        return None
    if not hmac.compare_digest(_hash(pw, bytes.fromhex(u["salt"]), u["iter"]), u["hash"]):
        return None
    with _lock:
        d = _load()
        d["users"][key(name)]["last_login"] = time.time()
        _save(d)
    return get(name)


def save(name, password=None, perms=None, companies=None, active=None, new=False):
    name = " ".join((name or "").split())
    if not name or len(name) > 40:
        raise ValueError("Give the staff member a name (up to 40 letters).")
    if password is not None and len(password) < 6:
        raise ValueError("Use at least 6 characters for the password.")
    with _lock:
        d = _load()
        k = key(name)
        u = d["users"].get(k)
        if new and u:
            raise ValueError("There is already a staff member with that name.")
        if not u:
            if password is None:
                raise ValueError("Set a password.")
            u = {"name": name, "created": time.time(), "gen": 0, "active": True, "perms": [], "companies": []}
        if password is not None:
            salt = secrets.token_bytes(16)
            u.update(salt=salt.hex(), iter=200_000, hash=_hash(password, salt))
            u["gen"] = u.get("gen", 0) + 1            # signs them out everywhere
        if perms is not None:
            u["perms"] = [p for p in perms if p in PERM_KEYS]
        if companies is not None:
            u["companies"] = [str(c) for c in companies]
        if active is not None:
            u["active"] = bool(active)
            if not active:
                u["gen"] = u.get("gen", 0) + 1
        d["users"][k] = u
        _save(d)
        return public(u)


def remove(name):
    with _lock:
        d = _load()
        d["users"].pop(key(name), None)
        _save(d)


def can(user, perm):
    return bool(user) and (user["owner"] or perm in user["perms"])


def can_company(user, company_name):
    return user["owner"] or not user.get("companies") or company_name in user["companies"]
