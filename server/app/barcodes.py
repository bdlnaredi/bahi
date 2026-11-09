"""Barcodes for stock items, kept by Bahi (barcodes.json next to the database): Tally's own item masters are
never changed. One item can have several barcodes (different pack sizes, a maker's code and your own)."""
import json
import os
import re
import threading

import store

PATH = os.path.join(os.path.dirname(store.DB_PATH), "barcodes.json")
CODE = re.compile(r"^[\x21-\x7e]{3,64}$")          # what scanners send: printable, no spaces
_lock = threading.Lock()


def _load():
    try:
        with open(PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, PATH)


def codes(company):
    """{barcode: item name} for one company."""
    return dict(_load().get(company, {}))


def for_item(company, item):
    return sorted(c for c, i in codes(company).items() if i == item)


def add(company, code, item):
    """Ties a barcode to an item. Returns the item it was on before (moved from), or None."""
    code = (code or "").strip()
    if not CODE.match(code):
        raise ValueError("That doesn't look like a barcode (3 to 64 letters or digits, no spaces).")
    if not item:
        raise ValueError("Pick the item for this barcode.")
    with _lock:
        d = _load()
        per = d.setdefault(company, {})
        before = per.get(code)
        per[code] = item
        _save(d)
    return before if before and before != item else None


def remove(company, code):
    with _lock:
        d = _load()
        per = d.get(company, {})
        if per.pop((code or "").strip(), None) is None:
            return False
        _save(d)
    return True
