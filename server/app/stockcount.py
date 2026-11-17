"""Stock count on the phone: count what's on the shelves (type it, or scan barcodes) and compare with the stock in
Tally. Kept in Bahi only: Tally's stock isn't changed. Several people can count in the same count at once."""
import json
import os
import threading
import time

import store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
FILE = os.path.join(DATA_DIR, "stockcount.json")
_lock = threading.Lock()


def _load():
    try:
        with open(FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    with open(FILE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(FILE + ".tmp", FILE)


def _co(d, cid):
    return d.setdefault(str(cid), {"next": 1, "counts": []})


def listing(cid):
    out = [{"id": x["id"], "name": x["name"], "started": x["started"], "by": x["by"], "status": x["status"],
            "items": len(x["items"])} for x in _co(_load(), cid)["counts"]]
    return {"counts": sorted(out, key=lambda x: -x["started"])}


def new(cid, name, by=""):
    with _lock:
        d = _load()
        co = _co(d, cid)
        x = {"id": co["next"], "name": (name or "").strip()[:80] or time.strftime("Count of %d %b %Y"), "started": time.time(),
             "by": by, "status": "open", "items": {}}
        co["next"] += 1
        co["counts"].append(x)
        _save(d)
    return x


def _find(co, kid):
    x = next((x for x in co["counts"] if x["id"] == kid), None)
    if not x:
        raise ValueError("No such count.")
    return x


def put(cid, kid, item, qty, by=""):
    """Set (or with qty None, remove) the counted quantity of one item."""
    with store.conn() as c:
        if not c.execute("SELECT 1 FROM stock WHERE company_id=? AND name=?", (cid, item)).fetchone():
            raise ValueError("No such item in Tally.")
    with _lock:
        d = _load()
        x = _find(_co(d, cid), kid)
        if x["status"] != "open":
            raise ValueError("This count is finished. Open it again to change it.")
        if qty is None:
            x["items"].pop(item, None)
        else:
            q = float(qty)
            if q < 0 or q > 1e9:
                raise ValueError("Check the quantity.")
            x["items"][item] = {"qty": round(q, 3), "by": by, "at": time.time()}
        _save(d)
    return {"ok": True}


def set_status(cid, kid, status):
    with _lock:
        d = _load()
        co = _co(d, cid)
        if status == "delete":
            co["counts"] = [x for x in co["counts"] if x["id"] != kid]
        elif status in ("open", "done"):
            _find(co, kid)["status"] = status
        else:
            raise ValueError("Unknown status.")
        _save(d)
    return {"ok": True}


def get(cid, kid):
    x = _find(_co(_load(), cid), kid)
    with store.conn() as c:
        stock = {r["name"]: dict(r) for r in c.execute(
            "SELECT name, parent, unit, closing_qty, closing_value, closing_rate FROM stock WHERE company_id=? ORDER BY name", (cid,))}
    rows = []
    for name, s in stock.items():
        got = x["items"].get(name)
        tq = round(s["closing_qty"] or 0, 3)
        rate = s["closing_rate"] or (s["closing_value"] / s["closing_qty"] if s["closing_qty"] else 0) or 0
        r = {"item": name, "group": s["parent"] or "", "unit": s["unit"] or "", "tally": tq, "rate": round(abs(rate), 2)}
        if got:
            diff = round(got["qty"] - tq, 3)
            r.update({"counted": got["qty"], "diff": diff, "value": round(diff * abs(rate), 2), "by": got["by"], "at": got["at"]})
        rows.append(r)
    counted = [r for r in rows if "counted" in r]
    off = [r for r in counted if abs(r["diff"]) > 0.0005]
    return {"id": x["id"], "name": x["name"], "status": x["status"], "started": x["started"], "by": x["by"],
            "rows": rows, "counted": len(counted), "total": len(rows), "differ": len(off),
            "short_value": round(-sum(r["value"] for r in off if r["value"] < 0), 2),
            "extra_value": round(sum(r["value"] for r in off if r["value"] > 0), 2)}
