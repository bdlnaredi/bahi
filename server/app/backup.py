"""Nightly copy of the database and settings into DATA_DIR/backups (the last 7 are kept)."""
import os
import re
import sqlite3
import threading
import time
import zipfile

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DIR = os.path.join(DATA_DIR, "backups")
KEEP = 7
AT = os.environ.get("BACKUP_TIME", "02:30")
EXTRA = ["telegram.json", "followups.json", "app_password.json"]
NAME = re.compile(r"^bahi-\d{4}-\d{2}-\d{2}\.zip$")
_lock = threading.Lock()


def listing():
    try:
        names = sorted((n for n in os.listdir(DIR) if NAME.match(n)), reverse=True)
    except OSError:
        names = []
    return [{"name": n, "size": os.path.getsize(os.path.join(DIR, n)),
             "time": os.path.getmtime(os.path.join(DIR, n))} for n in names]


def path_of(name):
    return os.path.join(DIR, name) if NAME.match(name or "") and os.path.exists(os.path.join(DIR, name)) else None


def run():
    with _lock:
        os.makedirs(DIR, exist_ok=True)
        day = time.strftime("%Y-%m-%d")
        tmp_db = os.path.join(DIR, ".tally.db.tmp")
        src = store.conn()
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        out = os.path.join(DIR, f"bahi-{day}.zip")
        with zipfile.ZipFile(out + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_db, "tally.db")
            for n in EXTRA:
                p = os.path.join(DATA_DIR, n)
                if os.path.exists(p):
                    z.write(p, n)
        os.replace(out + ".tmp", out)
        os.remove(tmp_db)
        for old in listing()[KEEP:]:
            os.remove(os.path.join(DIR, old["name"]))
        return out


def _loop():
    while True:
        try:
            have = listing()
            today = time.strftime("%Y-%m-%d")
            if time.strftime("%H:%M") >= AT and not (have and have[0]["name"] == f"bahi-{today}.zip"):
                run()
        except Exception as e:
            print("backup failed, trying again in an hour:", e, flush=True)
            time.sleep(3600)
        time.sleep(60)


def start():
    threading.Thread(target=_loop, daemon=True).start()
