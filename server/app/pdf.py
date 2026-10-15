"""A tiny PDF writer (standard library only) for ledger statements and vouchers.
Uses the built-in Helvetica font, so text outside Western characters prints as '?'."""
from datetime import date

_W = {32: 278, 33: 278, 34: 355, 35: 556, 36: 556, 37: 889, 38: 667, 39: 191, 40: 333, 41: 333, 42: 389,
      43: 584, 44: 278, 45: 333, 46: 278, 47: 278, 58: 278, 59: 278, 60: 584, 61: 584, 62: 584, 63: 556,
      64: 1015, 65: 667, 66: 667, 67: 722, 68: 722, 69: 667, 70: 611, 71: 778, 72: 722, 73: 278, 74: 500,
      75: 667, 76: 556, 77: 833, 78: 722, 79: 778, 80: 667, 81: 778, 82: 722, 83: 667, 84: 611, 85: 722,
      86: 667, 87: 944, 88: 667, 89: 667, 90: 611, 91: 278, 92: 278, 93: 278, 94: 469, 95: 556, 96: 333,
      97: 556, 98: 556, 99: 500, 100: 556, 101: 556, 102: 278, 103: 556, 104: 556, 105: 222, 106: 222,
      107: 500, 108: 222, 109: 833, 110: 556, 111: 556, 112: 556, 113: 556, 114: 333, 115: 500, 116: 278,
      117: 556, 118: 500, 119: 722, 120: 500, 121: 500, 122: 500, 123: 334, 124: 260, 125: 334, 126: 584}
for _d in range(48, 58):
    _W[_d] = 556

INK = (0.11, 0.14, 0.2)
GREY = (0.45, 0.48, 0.55)
RED = (0.56, 0.11, 0.11)
RULE = (0.84, 0.88, 0.94)
MARGIN = (0.89, 0.65, 0.63)


def width(s, size, bold=False):
    w = sum(_W.get(ord(ch), 556) for ch in s)
    return w * size / 1000 * (1.06 if bold else 1)


def fit(s, size, maxw, bold=False):
    s = str(s or "")
    if width(s, size, bold) <= maxw:
        return s
    while s and width(s + "...", size, bold) > maxw:
        s = s[:-1]
    return s + "..."


def inr(n, dp=2):
    neg = n < 0
    n = abs(n)
    whole, frac = f"{n:.{dp}f}".split(".") if dp else (f"{n:.0f}", "")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + ("." + frac if dp else "")


def drcr(n):
    if abs(n) < 0.005:
        return "0.00"
    return f"{inr(abs(n))} {'Dr' if n > 0 else 'Cr'}"


def fdate(iso):
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return d.strftime("%d-%b-%Y")


class PDF:
    W, H = 595.28, 841.89

    def __init__(self, title=""):
        self.pages, self.cur, self.title = [], None, title
        self.new_page()

    def new_page(self):
        self.cur = []
        self.pages.append(self.cur)

    @staticmethod
    def _esc(s):
        b = str(s).encode("cp1252", errors="replace")
        return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    def text(self, x, y, s, size=9, bold=False, color=INK, align="left"):
        s = str(s)
        if align == "right":
            x -= width(s, size, bold)
        elif align == "center":
            x -= width(s, size, bold) / 2
        self.cur.append(b"BT %.3f %.3f %.3f rg /%s %.1f Tf %.2f %.2f Td (" % (
            *color, b"F2" if bold else b"F1", size, x, y) + self._esc(s) + b") Tj ET")

    def line(self, x1, y1, x2, y2, color=RULE, w=0.6):
        self.cur.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (*color, w, x1, y1, x2, y2))

    def rect(self, x, y, w, h, color):
        self.cur.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (*color, x, y, w, h))

    def output(self):
        objs = []

        def add(b):
            objs.append(b)
            return len(objs)

        cat = add(None)
        pages_id = add(None)
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        kids = []
        total = len(self.pages)
        for i, ops in enumerate(self.pages, 1):
            foot = b"BT %.3f %.3f %.3f rg /F1 7.5 Tf 36 22 Td (" % GREY + self._esc(
                f"{self.title}   Page {i} of {total}   Made with Bahi from Tally data") + b") Tj ET"
            stream = b"\n".join(ops + [foot])
            cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>" % (
                                pages_id, self.W, self.H, cid, f1, f2)))
        objs[cat - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
        objs[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % k for k in kids), len(kids))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offs = []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for o in offs:
            out += b"%010d 00000 n \n" % o
        out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
        return bytes(out)


def ledger_pdf(company, d):
    L = d["ledger"]
    p = PDF(f"{L['name']} - ledger statement")
    left, right = 36, PDF.W - 36
    cols = {"date": left + 2, "part": left + 68, "vch": 300, "dr": 418, "cr": 488, "bal": right - 4}

    def header(first):
        y = PDF.H - 48
        p.rect(0, PDF.H - 8, PDF.W, 8, RED)
        p.text(left, y, fit(company, 15, 380, True), 15, True)
        p.text(right, y, "Ledger statement", 10, False, GREY, "right")
        y -= 22
        p.text(left, y, fit(L["name"], 12, 400, True), 12, True)
        y -= 14
        info = [x for x in (L.get("parent"), f"GSTIN {L['gstin']}" if L.get("gstin") else "",
                            L.get("mobile") or L.get("phone")) if x]
        p.text(left, y, "   ".join(info), 8.5, False, GREY)
        p.text(right, y, f"{fdate(d['from'])} to {fdate(d['to'])}", 8.5, False, GREY, "right")
        y -= 22
        if first:
            boxes = [("Opening", drcr(d["opening"])), ("Debits", inr(d["debit"])),
                     ("Credits", inr(d["credit"])), ("Closing", drcr(d["closing"]))]
            bw = (right - left) / 4
            for i, (k, v) in enumerate(boxes):
                x = left + i * bw
                p.text(x + 6, y, k, 8, False, GREY)
                p.text(x + 6, y - 14, v, 11, True)
            y -= 34
        p.rect(left, y - 4, right - left, 16, (0.95, 0.96, 0.98))
        for k, lbl, al in (("date", "Date", "left"), ("part", "Particulars", "left"), ("vch", "Voucher", "left"),
                           ("dr", "Debit", "right"), ("cr", "Credit", "right"), ("bal", "Balance", "right")):
            p.text(cols[k], y, lbl, 8, True, GREY, al)
        return y - 18

    y = header(True)

    def row(y, dt, part, vch, dr, cr, bal, bold=False):
        p.line(left + 58, y + 11, left + 58, y - 4, MARGIN, 0.5)
        p.line(left + 61, y + 11, left + 61, y - 4, MARGIN, 0.5)
        p.text(cols["date"], y, dt, 8.5, bold)
        p.text(cols["part"], y, fit(part, 8.5, cols["vch"] - cols["part"] - 6, bold), 8.5, bold)
        p.text(cols["vch"], y, fit(vch, 8, cols["dr"] - cols["vch"] - 50, bold), 8, bold, GREY)
        if dr:
            p.text(cols["dr"], y, dr, 8.5, bold, INK, "right")
        if cr:
            p.text(cols["cr"], y, cr, 8.5, bold, INK, "right")
        p.text(cols["bal"], y, bal, 8.5, bold, INK, "right")
        p.line(left, y - 4, right, y - 4)
        return y - 15

    y = row(y, fdate(d["from"]), "Opening balance", "", "", "", drcr(d["opening"]), True)
    for e in d["entries"]:
        if y < 50:
            p.new_page()
            y = header(False)
        a = e["amount"]
        y = row(y, fdate(e["date"]), e.get("against") or e["vtype"], f"{e['vtype']} {e['number']}",
                inr(a) if a > 0 else "", inr(-a) if a < 0 else "", drcr(e["balance"]))
    if y < 70:
        p.new_page()
        y = header(False)
    y = row(y, fdate(d["to"]), "Closing balance", "", inr(d["debit"]), inr(d["credit"]), drcr(d["closing"]), True)

    bills = [b for b in d.get("bills") or [] if b["amount"] > 0.5]
    if bills:
        y -= 16
        if y < 90:
            p.new_page()
            y = PDF.H - 60
        p.text(left, y, "Pending bills", 10, True)
        y -= 16
        for b in bills:
            if y < 50:
                p.new_page()
                y = PDF.H - 60
            od = f"{b['overdue']} days overdue" if b.get("overdue") else (f"{b['age']} days old" if b.get("age") is not None else "")
            p.text(left + 4, y, fit(b["ref"], 8.5, 150), 8.5)
            p.text(left + 160, y, fdate(b["date"]), 8.5, False, GREY)
            p.text(left + 250, y, od, 8.5, False, RED if b.get("overdue") else GREY)
            p.text(cols["bal"], y, inr(b["amount"]), 8.5, False, INK, "right")
            p.line(left, y - 4, right, y - 4)
            y -= 15
    return p.output()


def voucher_pdf(d):
    V = d["voucher"]
    p = PDF(f"{V['vtype']} {V['number']}")
    left, right = 36, PDF.W - 36
    p.rect(0, PDF.H - 8, PDF.W, 8, RED)
    y = PDF.H - 48
    p.text(left, y, fit(d["company"], 15, 360, True), 15, True)
    p.text(right, y, V["vtype"], 12, True, RED, "right")
    y -= 16
    p.text(right, y, f"No. {V['number']}    {fdate(V['date'])}", 9, False, GREY, "right")
    if V.get("reference"):
        y -= 12
        p.text(right, y, f"Ref. {V['reference']}", 9, False, GREY, "right")
    y -= 26
    party = d.get("party") or {}
    if V.get("party"):
        p.text(left, y, "Party", 8, False, GREY)
        y -= 14
        p.text(left, y, fit(V["party"], 12, 400, True), 12, True)
        gst = V.get("party_gstin") or party.get("gstin")
        if gst:
            y -= 13
            p.text(left, y, f"GSTIN {gst}", 9, False, GREY)
        y -= 24
    if d["items"]:
        p.rect(left, y - 4, right - left, 16, (0.95, 0.96, 0.98))
        for x, lbl, al in ((left + 4, "Item", "left"), (360, "Quantity", "right"), (450, "Rate", "right"),
                           (right - 4, "Amount", "right")):
            p.text(x, y, lbl, 8, True, GREY, al)
        y -= 18
        for it in d["items"]:
            if y < 80:
                p.new_page()
                y = PDF.H - 60
            p.text(left + 4, y, fit(it["item"], 9, 250), 9)
            p.text(360, y, f"{abs(it['qty']):g} {it['unit'] or ''}".strip(), 9, False, INK, "right")
            p.text(450, y, inr(it["rate"]) if it["rate"] else "", 9, False, INK, "right")
            p.text(right - 4, y, inr(it["amount"]), 9, False, INK, "right")
            p.line(left, y - 5, right, y - 5)
            y -= 16
        y -= 8
    p.text(left + 4, y, "Accounts", 8, True, GREY)
    p.text(450, y, "Debit", 8, True, GREY, "right")
    p.text(right - 4, y, "Credit", 8, True, GREY, "right")
    y -= 16
    for ln in d["lines"]:
        if y < 80:
            p.new_page()
            y = PDF.H - 60
        p.text(left + 4, y, fit(ln["ledger"], 9, 300, ln["kind"] == "party"), 9, ln["kind"] == "party")
        a = ln["amount"]
        p.text(450 if a > 0 else right - 4, y, inr(abs(a)), 9, ln["kind"] == "party", INK, "right")
        p.line(left, y - 5, right, y - 5)
        y -= 16
    y -= 6
    p.line(left, y + 8, right, y + 8, INK, 1)
    p.text(left + 4, y - 6, "Total", 11, True)
    p.text(right - 4, y - 6, "Rs. " + inr(V["amount"]), 11, True, INK, "right")
    y -= 30
    if d.get("bills"):
        p.text(left, y, "Bill references", 8, True, GREY)
        y -= 14
        for b in d["bills"]:
            p.text(left + 4, y, f"{b['btype']}  {b['name']}", 9)
            p.text(right - 4, y, drcr(b["amount"]), 9, False, INK, "right")
            y -= 13
        y -= 8
    if V.get("narration"):
        p.text(left, y, "Narration", 8, True, GREY)
        y -= 14
        for para in V["narration"].replace("\r", "").split("\n"):
            words, cur = para.split(" "), ""
            for w in words:
                if width(cur + " " + w, 9) > right - left - 8:
                    p.text(left + 4, y, cur.strip(), 9)
                    y -= 12
                    cur = w
                else:
                    cur += " " + w
            p.text(left + 4, y, cur.strip(), 9)
            y -= 12
    return p.output()
