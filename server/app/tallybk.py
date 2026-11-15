"""TallyPrime's own backup files (Data > Backup / Schedule Backup, e.g. TSDBK1800_100000.001), copied here from the
backup folder on the Tally PC by Bahi Sync, so they can be downloaded and restored in Tally with Data > Restore.

Bahi never makes or changes these files: it keeps exact copies, file for file. A file that has gone from the PC's
folder (Tally keeps only its last few versions) is kept here for KEEP_GONE days more, then removed."""
import json
import os
import re
import threading
import time
import zipfile

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DIR = os.path.join(DATA_DIR, "tally-backups")
INDEX = os.path.join(DATA_DIR, "tally-backups.json")
KEEP_GONE = 30
MAX_FILE = 50 * 1024 ** 3
_lock = threading.Lock()
# a relative path inside the backup folder: plain names, at most 4 folders deep
_PART = re.compile(r"^[^<>:\"|?*\x00-\x1f/\\]{1,200}$")


def _load():
    try:
        with open(INDEX) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"files": {}, "pc": {}}


def _save(d):
    tmp = INDEX + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, INDEX)


def clean(rel):
    """The safe relative path (forward slashes) or ValueError."""
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or len(parts) > 5 or any(p == ".." or not _PART.match(p) or p != p.strip() for p in parts):
        raise ValueError("Not a file name in the backup folder.")
    return "/".join(parts)


def full(rel):
    return os.path.join(DIR, *clean(rel).split("/"))


def index():
    """What the server has, for Bahi Sync to compare with: {path: {size, mtime}}."""
    d = _load()
    return {"files": {k: {"size": v["size"], "mtime": v["mtime"]} for k, v in d["files"].items() if os.path.exists(full(k))}}


def receive(rel, size, mtime, offset, read, length):
    """Store a file sent in pieces (Cloudflare refuses bodies over 100 MB): each piece goes on the end of a hidden
    .part- file, and only the complete file replaces the earlier copy. read(n) gives the body of this piece."""
    rel = clean(rel)
    if size < 0 or size > MAX_FILE or length < 0 or offset < 0 or offset + length > size:
        raise ValueError("The file size doesn't match.")
    dst = full(rel)
    folder = os.path.dirname(dst)
    os.makedirs(folder, exist_ok=True)
    part = os.path.join(folder, ".part-" + os.path.basename(dst))
    with _lock:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if offset == 0:
            have = 0
        elif have != offset:
            return {"have": have, "restart": True}      # pieces out of step: Bahi Sync starts the file again
        got = 0
        with open(part, "r+b" if offset else "wb") as f:
            f.seek(offset)
            f.truncate()
            while got < length:
                chunk = read(min(1 << 20, length - got))
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
        if got != length:
            raise ValueError("A piece of the file arrived incomplete; it will be sent again.")
        have = offset + got
        if have < size:
            return {"have": have}
        os.utime(part, (mtime, mtime))
        os.replace(part, dst)
        d = _load()
        d["files"][rel] = {"size": size, "mtime": mtime, "got": time.time()}
        _save(d)
    return {"have": have, "done": True}


def present(names, folder="", note=""):
    """The files now in the PC's backup folder: anything else is marked gone (and removed after KEEP_GONE days)."""
    keep = set()
    for n in names or []:
        try:
            keep.add(clean(n))
        except ValueError:
            pass
    now = time.time()
    with _lock:
        d = _load()
        for k, v in list(d["files"].items()):
            if k in keep:
                v.pop("gone", None)
            elif not v.get("gone"):
                v["gone"] = now
            elif now - v["gone"] > KEEP_GONE * 86400:
                try:
                    os.remove(full(k))
                except OSError:
                    pass
                del d["files"][k]
        d["pc"] = {"folder": str(folder)[:300], "checked": now, "note": str(note)[:300], "count": len(keep)}
        _save(d)


def status():
    d = _load()
    rows = []
    for k, v in d["files"].items():
        if os.path.exists(full(k)):
            rows.append({"path": k, "size": v["size"], "mtime": v["mtime"], "got": v.get("got"), "gone": v.get("gone")})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return {"files": rows, "pc": d.get("pc") or {}, "total": sum(r["size"] for r in rows), "keep_gone": KEEP_GONE}


def zip_to(out_path, only=None):
    """All copies (or the ones in only) in one zip, folders as on the PC. Stored, not squeezed: Tally's files are compressed already."""
    st = status()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for r in st["files"]:
            if r.get("gone") or (only and r["path"] not in only):
                continue
            z.write(full(r["path"]), r["path"])
    return out_path
