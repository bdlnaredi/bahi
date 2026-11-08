"""Copies of the nightly backups in the owner's Google Drive or OneDrive (with rclone), so the books survive
the server itself. Connected once from the Tally PC (Bahi Sync, Tools) or by pasting rclone's sign-in text."""
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONF_DIR = os.path.join(DATA_DIR, "rclone")
CONF = os.path.join(CONF_DIR, "rclone.conf")
STATE = os.path.join(DATA_DIR, "cloud.json")
KINDS = {"drive": "Google Drive", "onedrive": "OneDrive"}
KEEP = 30
NAME = re.compile(r"^bahi-\d{4}-\d{2}-\d{2}\.zip$")
_lock = threading.Lock()


def _state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, STATE)


def _rclone(*args, timeout=600):
    r = subprocess.run(["rclone", "--config", CONF, *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(msg[-1][-300:] if msg else f"rclone failed ({r.returncode})")
    return r.stdout


def available():
    try:
        subprocess.run(["rclone", "version"], capture_output=True, timeout=20)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def folder():
    return _state().get("folder") or "Bahi Backups"


def status():
    s = _state()
    on = bool(s.get("kind")) and os.path.exists(CONF)
    return {"on": on, "kind": s.get("kind", ""), "service": KINDS.get(s.get("kind", ""), ""), "folder": folder(),
            "keep": KEEP, "last": s.get("last"), "connected": s.get("connected"), "rclone": available()}


def token_from(text):
    """The token JSON out of whatever was pasted: rclone authorize's whole output, or just the {...} part."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("That isn't rclone's sign-in text: it has no {...} part.")
    try:
        tok = json.loads(m.group(0))
    except ValueError:
        raise ValueError("The sign-in text is cut short. Copy all of it, from { to }.")
    if not tok.get("access_token") or not tok.get("refresh_token"):
        raise ValueError("The sign-in text has no access or refresh token.")
    return tok


def connect(kind, text, label=""):
    if kind not in KINDS:
        raise ValueError("Choose Google Drive or OneDrive.")
    tok = token_from(text)
    lines = ["[cloud]"]
    if kind == "drive":
        lines += ["type = drive", "scope = drive"]
    else:
        # OneDrive needs to know which drive: the signed-in account's own
        req = urllib.request.Request("https://graph.microsoft.com/v1.0/me/drive",
                                     headers={"Authorization": "Bearer " + tok["access_token"]})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                drv = json.loads(r.read())
        except Exception as e:
            raise ValueError(f"OneDrive didn't accept the sign-in ({e}). Sign in again.")
        lines += ["type = onedrive", f"drive_id = {drv['id']}", f"drive_type = {drv.get('driveType', 'personal')}"]
    lines.append("token = " + json.dumps(tok, separators=(",", ":")))
    # two Bahi servers on one Drive (Bahi Sync's "Also sync to") keep their backups apart
    label = re.sub(r"[^A-Za-z0-9 .\-]", "", label or "")[:60].strip()
    with _lock:
        s0 = _state()
        s0["folder"] = f"Bahi Backups ({label})" if label else "Bahi Backups"
        _save(s0)
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(CONF + ".tmp", "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(CONF + ".tmp", 0o600)
        os.replace(CONF + ".tmp", CONF)
        try:
            _rclone("mkdir", f"cloud:{folder()}", timeout=120)
        except Exception as e:
            os.remove(CONF)
            raise ValueError(f"Couldn't reach {KINDS[kind]} with that sign-in: {e}")
        s = _state()
        s.update({"kind": kind, "connected": time.time(), "last": None})
        _save(s)
    return status()


def disconnect():
    with _lock:
        for p in (CONF, STATE):
            try:
                os.remove(p)
            except OSError:
                pass
    return status()


def _note(ok, msg):
    s = _state()
    s["last"] = {"time": time.time(), "ok": ok, "msg": msg}
    _save(s)


def upload(path):
    """Copy one backup up, then keep only the newest KEEP there. Never raises: the result is noted for Settings."""
    if not status()["on"]:
        return False
    name = os.path.basename(path)
    with _lock:
        try:
            _rclone("copyto", path, f"cloud:{folder()}/{name}")
            have = sorted((n for n in remote_names() if NAME.match(n)), reverse=True)
            for old in have[KEEP:]:
                _rclone("deletefile", f"cloud:{folder()}/{old}", timeout=120)
            _note(True, f"{name} copied to {KINDS[_state().get('kind', '')]}")
            return True
        except Exception as e:
            _note(False, f"{name} not copied: {e}")
            print("cloud backup failed:", e, flush=True)
            return False


def upload_later(path):
    threading.Thread(target=upload, args=(path,), daemon=True).start()


def remote_names():
    out = _rclone("lsf", "--files-only", f"cloud:{folder()}", timeout=120)
    return [l.strip() for l in out.splitlines() if l.strip()]


def remote_list():
    if not status()["on"]:
        return []
    out = _rclone("lsjson", "--files-only", f"cloud:{folder()}", timeout=120)
    rows = [{"name": x["Name"], "size": x.get("Size", 0), "time": x.get("ModTime", "")} for x in json.loads(out or "[]")
            if NAME.match(x.get("Name", ""))]
    return sorted(rows, key=lambda r: r["name"], reverse=True)


def fetch(name, dest_dir):
    """Bring one backup down into the local backups folder (then it can be restored like any other)."""
    if not NAME.match(name or ""):
        raise ValueError("Not a Bahi backup name.")
    os.makedirs(dest_dir, exist_ok=True)
    _rclone("copyto", f"cloud:{folder()}/{name}", os.path.join(dest_dir, name))
    return name
