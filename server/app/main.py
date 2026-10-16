"""Tally Mobile server: receives Tally data from the sync agent and serves the phone app.

Standard library only. Settings come from environment variables:
  APP_PASSWORD  password for the phone app (required)
  SYNC_TOKEN    secret the sync agent sends (required)
  DATA_DIR      where the database lives (default /data)
  PORT          default 8780
"""
import gzip
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(__file__))
import store  # noqa: E402
import tally_parse as tp  # noqa: E402
import pdf  # noqa: E402
import export  # noqa: E402
import notify  # noqa: E402
import backup  # noqa: E402
import users  # noqa: E402
import entries  # noqa: E402
import threading  # noqa: E402

DATA_DIR = os.environ.get("DATA_DIR", "/data")
STAGING = os.path.join(DATA_DIR, "staging")
STATIC = os.path.join(os.path.dirname(__file__), "static")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")
PORT = int(os.environ.get("PORT", "8780"))
SESSION_DAYS = 30
APP_VERSION = "2.6.3"
MAX_PART = 200 * 1024 * 1024
RUN_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


PW_FILE = os.path.join(DATA_DIR, "app_password.json")


def _stored_pw():
    try:
        with open(PW_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def check_password(pw):
    """A password changed in the app (stored hashed in the data folder) replaces APP_PASSWORD."""
    st = _stored_pw()
    if st:
        h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(st["salt"]), st["iter"]).hex()
        return hmac.compare_digest(h, st["hash"])
    return bool(APP_PASSWORD) and hmac.compare_digest(pw, APP_PASSWORD)


def set_password(pw):
    salt = secrets.token_bytes(16)
    it = 200_000
    data = {"salt": salt.hex(), "iter": it, "hash": hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it).hex(),
            "changed": time.time()}
    tmp = PW_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, PW_FILE)


def _secret():
    p = os.path.join(DATA_DIR, "secret.key")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(secrets.token_hex(32))
    with open(p) as f:
        st = _stored_pw()
        # changing the password signs every other phone out
        return (f.read().strip() + (st["hash"] if st else APP_PASSWORD)).encode()


def make_session(user=None):
    """Owner: "exp.sig". Staff: "name-hex.gen.exp.sig" - changing their password or switching them off
    bumps gen, which signs them out."""
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    body = exp if not user or user["owner"] else f"{user['name'].encode().hex()}.{user['gen']}.{exp}"
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def check_session(tok):
    """The logged-in user (owner or staff), or None."""
    try:
        body, sig = tok.rsplit(".", 1)
        good = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        parts = body.split(".")
        if int(parts[-1]) < time.time():
            return None
        if len(parts) == 1:
            return dict(users.OWNER)
        u = users.get(bytes.fromhex(parts[0]).decode())
        return u if u and str(u["gen"]) == parts[1] else None
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "TallyMobile/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("QUIET") != "1":
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # ------------------------------------------------------------ helpers
    def send_json(self, obj, status=200, headers=None):
        body = json.dumps(obj, default=str).encode()
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 1024
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_pdf(self, data, title):
        safe = re.sub(r"[^A-Za-z0-9 _.-]+", "", title).strip()[:80] or "statement"
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{safe}.pdf"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def telegram(self, method, path):
        s = notify.load()
        data = json.loads(self.body(8192) or b"{}") if method == "POST" else {}
        try:
            if path == "/api/telegram" and method == "GET":
                return self.send_json(notify.public(s))
            if path == "/api/telegram" and method == "POST":
                if data.get("token"):
                    s["token"] = data["token"].strip()
                for k in ("chat_id", "time"):
                    if k in data:
                        s[k] = str(data[k]).strip()
                for k in ("daily", "alerts"):
                    if k in data:
                        s[k] = bool(data[k])
                if "alert_min" in data:
                    s["alert_min"] = max(0, float(data["alert_min"] or 0))
                if data.get("off"):
                    s["token"], s["chat_id"] = "", ""
                notify.save(s)
                return self.send_json(notify.public(s))
            if path == "/api/telegram/find" and method == "POST":
                token = (data.get("token") or s["token"]).strip()
                chat = notify.find_chat(token)
                if not chat:
                    return self.send_json({"error": "No message found yet. Open your bot in Telegram, tap Start or send it any message, then try again."}, 400)
                s["token"], s["chat_id"] = token, chat["chat_id"]
                s["last_daily"] = time.strftime("%Y-%m-%d")  # the connect message already went out today
                notify.save(s)
                return self.send_json({**notify.public(s), "chat_name": chat["name"]})
            if path == "/api/telegram/test" and method == "POST":
                cid = int(data.get("cid") or 0)
                notify.send(notify.summary_text(cid) if cid else "Bahi is connected to this chat.", s)
                return self.send_json({"ok": True})
        except Exception as e:
            return self.send_json({"error": f"Telegram: {e}"}, 400)
        return self.send_json({"error": "not found"}, 404)

    def body(self, limit=MAX_PART):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        data = self.rfile.read(n) if n else b""
        if self.headers.get("X-Gzip") == "1":
            data = gzip.decompress(data)
        return data

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def authed(self):
        self.user = check_session(self.cookie("tm_session"))
        return self.user

    def cookie_header(self, user):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return {"Set-Cookie": f"tm_session={make_session(user)}; Path=/; HttpOnly; SameSite=Lax; "
                              f"Max-Age={SESSION_DAYS * 86400}{secure}"}

    def allowed(self, cid, what, q, arg):
        """Can the logged-in user see this? The owner sees everything."""
        u = self.user
        if u["owner"]:
            return True
        co = next((c for c in store.companies() if c["id"] == cid), None)
        if not co or not users.can_company(u, co["name"]):
            return False
        need = {"dashboard": "accounts", "daily": "sales", "group": "accounts", "stock": "stock", "stock_item": "stock",
                "outstanding": "dues", "collections": "dues", "followup": "dues", "vouchers": "vouchers", "daybook": "vouchers",
                "gst": "accounts", "pl": "accounts", "bs": "accounts", "cashbank": "accounts", "a_parties": "accounts",
                "a_items": "accounts", "a_years": "accounts", "a_slow": "accounts"}
        if what == "export":
            w = q.get("what", "")
            what = {"outstanding": "outstanding", "stock": "stock", "daily": "daily", "vouchers": "vouchers",
                    "ledger": "ledger"}.get(w, "a_items" if w.startswith("a_") else "")
            if not what:
                return False
        if what in need:
            return users.can(u, need[what])
        if what == "ledgers":
            return users.can(u, "ledgers") or users.can(u, "parties")
        if what in ("ledger", "ledger_pdf"):
            return users.can(u, "ledgers") or (users.can(u, "parties") and unquote(q.get("name", "")) in store.party_names(cid))
        if what in ("voucher", "voucher_pdf"):
            if users.can(u, "vouchers"):
                return True
            return (users.can(u, "parties") or users.can(u, "dues")) and arg and \
                store.voucher_party(cid, int(arg)) in store.party_names(cid)
        if what in ("entry_form", "party_bills", "entries", "entry"):
            return any(users.can(u, p) for p in entries.PERM.values())
        return False

    def agent_ok(self):
        auth = self.headers.get("Authorization") or ""
        return bool(SYNC_TOKEN) and hmac.compare_digest(auth, "Bearer " + SYNC_TOKEN)

    def serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            full = os.path.join(STATIC, "index.html")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------ routing
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        u = urlparse(self.path)
        path = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if path.startswith("/agent/"):
                return self.agent(method, path, q)
            if path.startswith("/api/"):
                return self.api(method, path, q)
            if method == "GET":
                return self.serve_static(path)
            self.send_json({"error": "not found"}, 404)
        except Exception as e:
            traceback.print_exc()
            tb = traceback.extract_tb(e.__traceback__)
            where = f" (in {tb[-1].name}, {os.path.basename(tb[-1].filename)} line {tb[-1].lineno})" if tb else ""
            self.send_json({"error": f"{type(e).__name__}: {e}{where} [server {APP_VERSION}]"}, 500)

    # ------------------------------------------------------------ agent endpoints
    def agent(self, method, path, q):
        if not self.agent_ok():
            return self.send_json({"error": "bad sync token"}, 401)
        if path == "/agent/ping":
            return self.send_json({"ok": True, "time": time.time()})
        if path == "/agent/plan" and method == "POST":
            items = tp.parse_voucher_list(tp.parse_xml(self.body()))
            return self.send_json(store.plan(q.get("company", ""), q.get("from", ""), q.get("to", ""), items))
        if path == "/agent/stats" and method == "GET":
            return self.send_json(store.agent_stats())
        if path == "/agent/state" and method == "GET":
            return self.send_json(store.get_alt(q.get("company", "")))
        if path == "/agent/schedule" and method == "GET":
            return self.send_json(store.sync_due(q.get("force") == "1"))
        if path == "/agent/outbox" and method == "GET":
            if store.is_paused(q.get("company", "")):
                return self.send_json({"entries": [], "paused": True})
            return self.send_json({"entries": entries.outbox(q.get("company", ""))})
        if path == "/agent/outbox/result" and method == "POST":
            r = json.loads(self.body(65536) or b"{}")
            entries.result(int(r.get("id", 0)), bool(r.get("ok")), str(r.get("error") or ""), bool(r.get("retry")))
            return self.send_json({"ok": True})
        if path == "/agent/heartbeat" and method == "POST":
            store.heartbeat(json.loads(self.body(1 << 20) or b"{}").get("companies", []))
            return self.send_json({"ok": True})
        if path == "/agent/part" and method == "POST":
            run, kind = q.get("run", ""), q.get("kind", "")
            if not RUN_RE.match(run) or kind not in ("groups", "vtypes", "ledgers", "stock", "daybook", "bills_rec", "bills_pay",
                                                             "company", "ledger_x", "stock_x"):
                return self.send_json({"error": "bad part"}, 400)
            d = os.path.join(STAGING, run)
            os.makedirs(d, exist_ok=True)
            n = len(os.listdir(d))
            with open(os.path.join(d, f"{n:04d}_{kind}.xml"), "wb") as f:
                f.write(self.body())
            return self.send_json({"ok": True})
        if path == "/agent/commit" and method == "POST":
            meta = json.loads(self.body(1 << 20))
            run = meta.get("run", "")
            if store.is_paused(meta.get("company", "")):     # an agent too old to know about pausing
                shutil.rmtree(os.path.join(STAGING, run), ignore_errors=True) if RUN_RE.match(run) else None
                return self.send_json({"error": "Syncing is paused in the app (Reports, Settings). Nothing was changed."}, 409)
            if not RUN_RE.match(run):
                return self.send_json({"error": "bad run"}, 400)
            d = os.path.join(STAGING, run)
            try:
                res = self.commit(d, meta)
            finally:
                shutil.rmtree(d, ignore_errors=True)
            threading.Thread(target=notify.alert_new_receipts, daemon=True).start()
            return self.send_json(res)
        self.send_json({"error": "not found"}, 404)

    def commit(self, d, meta):
        parts = {"groups": [], "vtypes": [], "ledgers": [], "stock": [], "daybook": [],
                 "bills_rec": None, "bills_pay": None, "company": {}, "ledger_x": {}, "stock_x": {}}
        skipped = []
        extra_fns = {"company": tp.parse_company_info, "ledger_x": tp.parse_ledger_extra, "stock_x": tp.parse_stock_extra}
        fns = {"groups": tp.parse_groups, "vtypes": tp.parse_vtypes, "ledgers": tp.parse_ledgers,
               "stock": tp.parse_stock, "daybook": tp.parse_vouchers}
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            kind = fn.split("_", 1)[1].rsplit(".", 1)[0]
            with open(os.path.join(d, fn), "rb") as f:
                raw = f.read()
            if kind in extra_fns:
                try:
                    parts[kind].update(extra_fns[kind](tp.parse_xml(raw)))
                except Exception as e:  # printing details are optional
                    print(f"{kind} not usable:", e, file=sys.stderr)
                continue
            if kind in ("bills_rec", "bills_pay"):
                try:
                    parts[kind] = tp.parse_bill_report(tp.parse_xml(raw))
                except Exception as e:  # report not available in this Tally - fall back to vouchers
                    print("bill report not usable:", e, file=sys.stderr)
                continue
            try:
                parts[kind] += fns[kind](tp.parse_xml(raw))
            except Exception as e:
                if kind != "daybook":
                    raise ValueError(f"could not read the {kind} data from Tally: {e}") from e
                skipped.append(str(e)[:200])
                print("voucher part skipped:", e, file=sys.stderr)
        if not parts["ledgers"]:
            raise ValueError("No ledgers received - is the right company open in Tally?")
        seen, vouchers = set(), []
        for v in parts["daybook"]:
            key = v["guid"] or id(v)
            if key in seen:
                continue
            seen.add(key)
            vouchers.append(v)
        if skipped:
            raise ValueError("Some voucher data from Tally could not be read: " + skipped[0])
        return store.ingest(meta["company"], meta["from"], meta["to"], meta.get("alt_vch", ""),
                            meta.get("alt_mst", ""), parts["groups"], parts["vtypes"],
                            parts["ledgers"], parts["stock"], vouchers, parts["bills_rec"], parts["bills_pay"],
                            parts["company"].get(meta["company"]) or next(iter(parts["company"].values()), {}),
                            parts["ledger_x"], parts["stock_x"],
                            meta.get("months") if isinstance(meta.get("months"), list) else None)

    # ------------------------------------------------------------ app endpoints
    def api(self, method, path, q):
        if path == "/api/login" and method == "POST":
            data = json.loads(self.body(4096) or b"{}")
            name, pw = str(data.get("name", "")).strip(), str(data.get("password", ""))
            if not name and check_password(pw):
                return self.send_json({"ok": True}, headers=self.cookie_header(None))
            u = users.check(name, pw) if name else None
            if u:
                return self.send_json({"ok": True}, headers=self.cookie_header(u))
            time.sleep(1.5)
            return self.send_json({"error": "Wrong name or password" if name else "Wrong password"}, 401)
        if path == "/api/logout":
            return self.send_json({"ok": True}, headers={"Set-Cookie": "tm_session=; Path=/; Max-Age=0"})
        if not self.authed():
            return self.send_json({"error": "login required"}, 401)

        u = self.user
        if path == "/api/me":
            out = {"name": u["name"], "owner": u["owner"], "perms": u["perms"], "version": APP_VERSION}
            if u["owner"]:
                out["perm_list"] = users.PERMS
            return self.send_json(out)

        if path == "/api/password" and method == "POST" and not u["owner"]:
            data = json.loads(self.body(4096) or b"{}")
            cur, new = str(data.get("current", "")), str(data.get("new", ""))
            if not users.check(u["name"], cur):
                time.sleep(1.5)
                return self.send_json({"error": "Your current password isn't right."}, 400)
            if len(new) < 6:
                return self.send_json({"error": "Use at least 6 characters for the new password."}, 400)
            users.save(u["name"], password=new)
            return self.send_json({"ok": True}, headers=self.cookie_header(users.get(u["name"])))

        if path == "/api/sync/now" and method == "POST":
            self.body(4096)
            d = store.sync_settings()
            if d["mode"] == "paused":
                return self.send_json({"error": "Syncing is paused. Resume it in Settings first."}, 400)
            store.update_sync(request=True)
            return self.send_json({"ok": True})

        if path == "/api/companies":
            return self.send_json({"companies": [c for c in store.companies() if users.can_company(u, c["name"])],
                                   "now": time.time(), "sync": {k: v for k, v in store.sync_settings().items() if k != "companies"},
                                   "approvals": sum(entries.pending_count(c["name"]) for c in store.companies()) if u["owner"] else 0})

        # everything below the staff list is for the owner only, except the company screens
        if not u["owner"] and not path.startswith("/api/c/"):
            return self.send_json({"error": "Only the owner can do that."}, 403)
        if not u["owner"] and re.match(r"^/api/c/\d+/(purge|delete)$", path):
            return self.send_json({"error": "Only the owner can do that."}, 403)

        if path == "/api/sync" and method == "POST":
            data = json.loads(self.body(4096) or b"{}")
            d = store.update_sync(mode=data.get("mode"), every=data.get("every"), company=str(data.get("company") or ""),
                                  company_paused=bool(data.get("paused")))
            return self.send_json(d)

        if path == "/api/users":
            if method == "POST":
                data = json.loads(self.body(8192) or b"{}")
                try:
                    if data.get("remove"):
                        users.remove(data.get("name", ""))
                    else:
                        users.save(data.get("name", ""), password=data.get("password") or None,
                                   perms=data.get("perms"), companies=data.get("companies"),
                                   active=data.get("active"), new=bool(data.get("new")))
                except ValueError as e:
                    return self.send_json({"error": str(e)}, 400)
            return self.send_json({"users": users.listing(), "perms": users.PERMS})

        if path == "/api/password" and method == "POST":
            data = json.loads(self.body(4096) or b"{}")
            cur, new = str(data.get("current", "")), str(data.get("new", ""))
            if not check_password(cur):
                time.sleep(1.5)
                return self.send_json({"error": "Your current password isn't right."}, 400)
            if len(new) < 8:
                return self.send_json({"error": "Use at least 8 characters for the new password."}, 400)
            set_password(new)
            return self.send_json({"ok": True}, headers=self.cookie_header(None))

        if path.startswith("/api/telegram"):
            return self.telegram(method, path)

        if path == "/api/backups":
            if method == "POST":
                self.body(4096)
                backup.run()
            return self.send_json({"backups": backup.listing(), "keep": backup.KEEP, "at": backup.AT})
        if path.startswith("/api/backups/"):
            p = backup.path_of(path.rsplit("/", 1)[-1])
            if not p:
                return self.send_json({"error": "not found"}, 404)
            with open(p, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(p)}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        mp = re.match(r"^/api/c/(\d+)/entry(?:/(\d+)/([a-z]+))?$", path)
        if mp and method == "POST":
            cid = int(mp.group(1))
            if not self.allowed(cid, "entry", q, None):
                return self.send_json({"error": "You can't make entries."}, 403)
            try:
                if mp.group(2):
                    e = entries.get(int(mp.group(2)))
                    co = next((c for c in store.companies() if c["id"] == cid), None)
                    if not e or not co or e["company"] != co["name"]:
                        return self.send_json({"error": "not found"}, 404)
                    self.body(4096)
                    return self.send_json({"entry": entries.action(e["id"], mp.group(3), u)})
                data = json.loads(self.body(65536) or b"{}")
                kind = data.get("kind", "")
                if kind not in entries.PERM or not users.can(u, entries.PERM[kind]):
                    return self.send_json({"error": "You can't make this kind of entry."}, 403)
                return self.send_json({"entry": entries.create(cid, kind, data, u)})
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)

        mp = re.match(r"^/api/c/(\d+)/followup$", path)
        if mp and method == "POST":
            if not self.allowed(int(mp.group(1)), "followup", q, None):
                return self.send_json({"error": "not allowed"}, 403)
            data = json.loads(self.body(4096) or b"{}")
            promise = str(data.get("promise", "") or "")
            if promise and not re.match(r"^\d{4}-\d{2}-\d{2}$", promise):
                return self.send_json({"error": "Pick a date."}, 400)
            ok = store.set_followup(int(mp.group(1)), str(data.get("party", "")), str(data.get("note", "")).strip(), promise)
            return self.send_json({"ok": ok})

        mp = re.match(r"^/api/c/(\d+)/(purge|delete)$", path)
        if mp and method == "POST":
            cid = int(mp.group(1))
            if mp.group(2) == "delete":
                store.delete_company(cid)
                return self.send_json({"ok": True})
            data = json.loads(self.body(4096) or b"{}")
            day = str(data.get("before", ""))
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
                return self.send_json({"error": "Pick a date."}, 400)
            return self.send_json({"ok": True, "deleted": store.purge_before(cid, day)})

        m = re.match(r"^/api/c/(\d+)/([a-z_]+)(?:/(\d+))?$", path)
        if not m:
            return self.send_json({"error": "not found"}, 404)
        cid, what, arg = int(m.group(1)), m.group(2), m.group(3)
        if not self.allowed(cid, what, q, arg):
            return self.send_json({"error": "You don't have access to this. Ask the owner."}, 403)
        f, t = q.get("from"), q.get("to")
        name = unquote(q.get("name", ""))
        if what == "ledgers" and not users.can(u, "ledgers"):
            pn = store.party_names(cid)
            return self.send_json({"ledgers": [r for r in store.ledgers(cid, q.get("q", ""), q.get("sort", "name")) if r["name"] in pn]})
        if what == "entry_form":
            k = q.get("kind", "")
            if k not in entries.PERM or not users.can(u, entries.PERM[k]):
                return self.send_json({"error": "You can't make this kind of entry."}, 403)
            return self.send_json(entries.form(cid, k))
        if what == "party_bills":
            return self.send_json(entries.party_bills(cid, name))
        if what == "entries":
            co = next((c for c in store.companies() if c["id"] == cid), None)
            return self.send_json({"entries": entries.listing(co["name"], u) if co else []})
        if what == "dashboard":
            out = store.dashboard(cid, f, t)
        elif what == "ledgers":
            out = {"ledgers": store.ledgers(cid, q.get("q", ""), q.get("sort", "name"))}
        elif what == "daily":
            out = store.daily(cid, q.get("kind", "sales"), f, t)
        elif what == "ledger":
            out = store.ledger(cid, name, f, t)
        elif what == "group":
            out = store.group(cid, name)
        elif what == "stock":
            out = store.stock(cid, q.get("q", ""), f, t)
        elif what == "stock_item":
            out = store.stock_item(cid, name, f, t)
        elif what == "outstanding":
            out = store.outstanding(cid, q.get("kind", "receivable"))
        elif what == "vouchers":
            out = store.vouchers(cid, q.get("q", ""), f, t, q.get("type", ""), q.get("offset", 0))
        elif what == "gst":
            out = store.gst(cid, f, t)
        elif what == "ledger_pdf":
            d = store.ledger(cid, name, f, t)
            if d:
                return self.send_pdf(pdf.ledger_pdf(d), d["ledger"]["name"] + " ledger")
            out = None
        elif what == "voucher_pdf" and arg:
            d = store.voucher(cid, int(arg))
            if d:
                v = d["voucher"]
                return self.send_pdf(pdf.voucher_pdf(d), f"{v['vtype']} {v['number']}")
            out = None
        elif what == "daybook":
            out = store.daybook(cid, f, t, q.get("type", ""), q.get("offset", 0))
        elif what == "voucher" and arg:
            out = store.voucher(cid, int(arg))
        elif what == "export":
            r = export.build(cid, q.get("what", ""), {k: unquote(v) for k, v in q.items()})
            if r:
                name, data = r
                safe = re.sub(r"[^A-Za-z0-9 _.-]+", "", name).strip()[:80] or "export"
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{safe}.csv"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            out = None
        elif what == "a_parties":
            out = store.analysis_parties(cid, q.get("kind", "sales"), f, t)
        elif what == "a_items":
            out = store.analysis_items(cid, f, t)
        elif what == "a_years":
            out = store.analysis_years(cid)
        elif what == "a_slow":
            out = store.slow_stock(cid, int(q.get("days", 60) or 60))
        elif what == "check":
            out = store.sync_check(cid)
        elif what == "bs":
            out = store.balance_sheet(cid)
        elif what == "cashbank":
            out = store.cash_bank(cid, f, t)
        elif what == "collections":
            out = store.collections(cid, int(q.get("days", 7) or 7))
        elif what == "pl":
            out = store.profit_loss(cid, f, t)
        else:
            out = None
        if out is None:
            return self.send_json({"error": "not found"}, 404)
        self.send_json(out)


def main():
    if not APP_PASSWORD or not SYNC_TOKEN:
        print("Set APP_PASSWORD and SYNC_TOKEN environment variables.", file=sys.stderr)
        sys.exit(1)
    os.makedirs(STAGING, exist_ok=True)
    shutil.rmtree(STAGING, ignore_errors=True)
    os.makedirs(STAGING, exist_ok=True)
    store.init()
    notify.start()
    backup.start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Tally Mobile listening on :{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
