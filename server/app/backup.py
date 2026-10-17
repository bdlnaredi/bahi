"""Nightly copy of the database and settings into DATA_DIR/backups (the last 7 are kept), and restoring one."""
import io
import json
import os
import shutil
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
EXTRA = ["telegram.json", "followups.json", "app_password.json", "users.json", "sync.json", "interest.json",
         "stock_min.json"]
DBS = ["tally.db", "entries.db"]          # copied with sqlite's own backup, safe while the app is running
NAME = re.compile(r"^bahi-\d{4}-\d{2}-\d{2}(-before-restore-\d{6})?\.zip$")
BANKREC = re.compile(r"^bankrec/[0-9a-f]{16}\.json$")
_lock = threading.Lock()


def listing():
    try:
        names = sorted((n for n in os.listdir(DIR) if NAME.match(n)), reverse=True, key=lambda n: os.path.getmtime(os.path.join(DIR, n)))
    except OSError:
        names = []
    return [{"name": n, "size": os.path.getsize(os.path.join(DIR, n)),
             "time": os.path.getmtime(os.path.join(DIR, n))} for n in names]


def path_of(name):
    return os.path.join(DIR, name) if NAME.match(name or "") and os.path.exists(os.path.join(DIR, name)) else None


def _copy_db(src_path, dst_path):
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _make(out):
    os.makedirs(DIR, exist_ok=True)
    with zipfile.ZipFile(out + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        for n in DBS:
            p = os.path.join(DATA_DIR, n)
            if os.path.exists(p):
                tmp = os.path.join(DIR, f".{n}.tmp")
                _copy_db(p, tmp)
                z.write(tmp, n)
                os.remove(tmp)
        for n in EXTRA:
            p = os.path.join(DATA_DIR, n)
            if os.path.exists(p):
                z.write(p, n)
        bdir = os.path.join(DATA_DIR, "bankrec")
        if os.path.isdir(bdir):
            for n in os.listdir(bdir):
                if BANKREC.match("bankrec/" + n):
                    z.write(os.path.join(bdir, n), "bankrec/" + n)
    os.replace(out + ".tmp", out)
    return out


def run():
    with _lock:
        out = _make(os.path.join(DIR, f"bahi-{time.strftime('%Y-%m-%d')}.zip"))
        daily = [b for b in listing() if "before-restore" not in b["name"]]
        for old in daily[KEEP:]:
            os.remove(os.path.join(DIR, old["name"]))
        return out


def check(raw):
    """What's in a backup file, or ValueError if it isn't a Bahi backup."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError("That isn't a Bahi backup (not a .zip file).")
    # a backup unzipped and zipped again on a PC may add folder entries, or put everything in one folder
    orig = [x for x in z.namelist() if not x.endswith("/") and "__MACOSX" not in x]
    files = [n.replace("\\", "/") for n in orig]
    tops = {n.split("/", 1)[0] for n in files if "/" in n}
    prefix = ""
    if "tally.db" not in files and len(tops) == 1 and f"{next(iter(tops))}/tally.db" in files:
        prefix = next(iter(tops)) + "/"
    m = {n[len(prefix):]: o for n, o in zip(files, orig) if n.startswith(prefix)}
    names = list(m)
    if "tally.db" not in names:
        raise ValueError("That isn't a Bahi backup: there's no tally.db inside.")
    bad = [n for n in names if n not in DBS + EXTRA and not BANKREC.match(n)]
    if bad:
        raise ValueError("That zip has files a Bahi backup never has: " + ", ".join(bad[:3]))
    read = lambda n: z.read(m[n])
    for n in DBS:
        if n in names:
            tmp = os.path.join(DIR, ".check.db")
            os.makedirs(DIR, exist_ok=True)
            with open(tmp, "wb") as f:
                f.write(read(n))
            try:
                c = sqlite3.connect(tmp)
                ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                c.close()
            except sqlite3.DatabaseError:
                ok, tables = False, set()
            finally:
                os.remove(tmp)
            if not ok:
                raise ValueError(f"The {n} inside that backup is damaged.")
            if n == "tally.db" and "voucher" not in tables:
                raise ValueError("That backup's database isn't from Bahi.")
    for n in EXTRA:
        if n in names:
            try:
                json.loads(read(n))
            except ValueError:
                raise ValueError(f"The {n} inside that backup is damaged.")
    return names, read


def restore(raw):
    """Put a backup back. A copy of things as they are now is saved first, so a restore can itself be undone."""
    names, read = check(raw)
    with _lock:
        safety = _make(os.path.join(DIR, f"bahi-{time.strftime('%Y-%m-%d')}-before-restore-{time.strftime('%H%M%S')}.zip"))
        for old in [b for b in listing() if "before-restore" in b["name"]][3:]:
            os.remove(os.path.join(DIR, old["name"]))
        for n in DBS:
            if n in names:
                tmp = os.path.join(DIR, f".restore-{n}")
                with open(tmp, "wb") as f:
                    f.write(read(n))
                with store._lock:              # copied into the live database, so open connections stay valid
                    _copy_db(tmp, os.path.join(DATA_DIR, n))
                os.remove(tmp)
        for n in EXTRA:
            if n in names:
                tmp = os.path.join(DATA_DIR, n + ".restore")
                with open(tmp, "wb") as f:
                    f.write(read(n))
                os.replace(tmp, os.path.join(DATA_DIR, n))
        bdir = os.path.join(DATA_DIR, "bankrec")
        if any(BANKREC.match(n) for n in names):
            shutil.rmtree(bdir, ignore_errors=True)
            os.makedirs(bdir, exist_ok=True)
            for n in names:
                if BANKREC.match(n):
                    with open(os.path.join(DATA_DIR, n), "wb") as f:
                        f.write(read(n))
    store.init()              # an older layout is set up again (the next sync refills it)
    return {"safety": os.path.basename(safety), "files": names}


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
