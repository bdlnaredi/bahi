"""PDF output laid out like TallyPrime's printed Tax Invoice, voucher and Ledger Account.

Standard library only. Uses the built-in Helvetica fonts (text outside Western scripts
prints as '?'); the rupee sign is drawn as a small vector glyph.
"""
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

BLACK = (0, 0, 0)
GREY = (0.35, 0.35, 0.35)
STATE_CODES = {}


def width(s, size, bold=False):
    return sum(_W.get(ord(ch), 556) for ch in str(s)) * size / 1000 * (1.07 if bold else 1)


def fit(s, size, maxw, bold=False):
    s = str(s or "")
    if width(s, size, bold) <= maxw:
        return s
    while s and width(s + "...", size, bold) > maxw:
        s = s[:-1]
    return s + "..."


def wrap(s, size, maxw, bold=False):
    out = []
    for para in str(s or "").replace("\r", "").split("\n"):
        cur = ""
        for w in para.split(" "):
            t = (cur + " " + w).strip()
            if width(t, size, bold) <= maxw or not cur:
                cur = t
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return [x for x in out if x != ""] or [""]


def inr(n, dp=2):
    neg = n < 0
    whole, frac = f"{abs(n):.{dp}f}".split(".")
    if len(whole) > 3:
        head, tail, parts = whole[:-3], whole[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + "." + frac


def tdate(iso):
    """Tally's printed date style: 7-Apr-26"""
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return f"{d.day}-{d.strftime('%b')}-{d.strftime('%y')}"


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n):
    h, r = divmod(n, 100)
    return ((_ONES[h] + " Hundred" + (" " if r else "")) if h else "") + (_two(r) if r else "")


def words(n):
    """INR One Lakh Fourteen Thousand Six Hundred Forty Five and Eighty Four paise Only"""
    n = round(abs(n), 2)
    rupees, paise = int(n), int(round((n - int(n)) * 100))
    parts = []
    crore, rupees = divmod(rupees, 10 ** 7)
    lakh, rupees = divmod(rupees, 10 ** 5)
    thousand, rupees = divmod(rupees, 1000)
    if crore:
        parts.append((_three(crore) if crore < 1000 else words(crore).replace("INR ", "").replace(" Only", "")) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if rupees:
        parts.append(_three(rupees))
    s = "INR " + (" ".join(parts) if parts else "Zero")
    if paise:
        s += " and " + _two(paise) + " paise"
    return s + " Only"


class PDF:
    W, H = 595.28, 841.89

    def __init__(self):
        self.pages = []
        self.new_page()

    def new_page(self):
        self.cur = []
        self.pages.append(self.cur)

    @staticmethod
    def _esc(s):
        b = str(s).encode("cp1252", errors="replace")
        return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    def text(self, x, y, s, size=8, font="R", align="left", color=BLACK):
        s = str(s)
        bold = font in ("B", "BI")
        if align == "right":
            x -= width(s, size, bold)
        elif align == "center":
            x -= width(s, size, bold) / 2
        f = {"R": b"F1", "B": b"F2", "I": b"F3", "BI": b"F4"}[font]
        self.cur.append(b"BT %.3f %.3f %.3f rg /%s %.2f Tf %.2f %.2f Td (" % (*color, f, size, x, y)
                        + self._esc(s) + b") Tj ET")

    def line(self, x1, y1, x2, y2, w=0.5, color=BLACK):
        self.cur.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (*color, w, x1, y1, x2, y2))

    def box(self, x, y, w, h, lw=0.6):
        self.cur.append(b"0 0 0 RG %.2f w %.2f %.2f %.2f %.2f re S" % (lw, x, y, w, h))

    def rupee(self, x, y, size, bold=False):
        """Draws the rupee sign with its baseline at y; returns its advance width."""
        k = size / 1000
        lw = (85 if bold else 62) * k
        def P(px, py):
            return b"%.2f %.2f" % (x + px * k, y + py * k)
        self.cur.append(b"q 0 0 0 RG 1 J 1 j %.2f w " % lw +
                        P(60, 700) + b" m " + P(500, 700) + b" l " +
                        P(60, 590) + b" m " + P(500, 590) + b" l " +
                        P(60, 700) + b" m " + P(260, 700) + b" l " +
                        P(420, 700) + b" " + P(420, 450) + b" " + P(220, 450) + b" c " +
                        P(90, 450) + b" l " + P(400, 0) + b" l S Q")
        return 560 * k

    def money(self, x, y, n, size=8, bold=False, sign=True):
        """Right-aligned amount at x, optionally with the rupee sign in front."""
        s = inr(n)
        self.text(x, y, s, size, "B" if bold else "R", "right")
        if sign:
            self.rupee(x - width(s, size, bold) - 0.62 * size, y, size, bold)

    def output(self, footer=""):
        objs = []

        def add(b):
            objs.append(b)
            return len(objs)

        cat, pages_id = add(None), add(None)
        fonts = [add(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % n)
                 for n in (b"Helvetica", b"Helvetica-Bold", b"Helvetica-Oblique", b"Helvetica-BoldOblique")]
        kids, total = [], len(self.pages)
        for i, ops in enumerate(self.pages, 1):
            extra = []
            if footer:
                extra.append(b"BT 0 0 0 rg /F1 7.5 Tf %.2f 18 Td (" % (self.W / 2 - width(footer, 7.5) / 2)
                             + self._esc(footer) + b") Tj ET")
            if total > 1:
                pg = f"Page {i} of {total}"
                extra.append(b"BT 0 0 0 rg /F1 7.5 Tf %.2f 18 Td (" % (self.W - 28 - width(pg, 7.5)) + self._esc(pg) + b") Tj ET")
            stream = b"\n".join(ops + extra)
            cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R /F3 %d 0 R /F4 %d 0 R >> >> >>"
                            % (pages_id, self.W, self.H, cid, *fonts)))
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


def _state_line(state, gstin):
    code = gstin[:2] if gstin and gstin[:2].isdigit() else ""
    if state and code:
        return f"State Name : {state}, Code : {code}"
    return f"State Name : {state}" if state else ""


def _party_lines(name, addr, gstin, state, extra=()):
    lines = [(name, "B")] + [(a, "R") for a in addr]
    if gstin:
        lines.append((f"GSTIN/UIN : {gstin}", "R"))
    if state or gstin:
        sl = _state_line(state, gstin)
        if sl:
            lines.append((sl, "R"))
    lines += [(e, "R") for e in extra if e]
    return lines


# ---------------------------------------------------------------- Tax Invoice

def invoice_pdf(d):
    V, X = d["voucher"], d["voucher"].get("extra") or {}
    C = d.get("company_info") or {}
    P = d.get("party") or {}
    base = V.get("base") or V["vtype"]
    tax_lines = [l for l in d["lines"] if l["kind"] == "tax"]
    title = {"Credit Note": "Credit Note", "Debit Note": "Debit Note", "Purchase": "Purchase Invoice"}.get(
        base, "Tax Invoice" if tax_lines else "Invoice")
    p = PDF()
    L, R = 28, PDF.W - 28
    y = PDF.H - 34
    p.text(PDF.W / 2, y, title, 12, "B", "center")
    if X.get("irn"):
        y -= 12
        p.text(L, y, fit(f"IRN : {X['irn']}", 7.5, R - L), 7.5)
    top = y - 8

    # left column: seller, consignee, buyer
    mid = L + (R - L) * 0.52
    lw = mid - L - 8
    seller = _party_lines(d["company"], C.get("address", []), C.get("gstin", ""), C.get("state", ""),
                          [f"E-Mail : {C['email']}" if C.get("email") else "",
                           f"Contact : {C['phone']}" if C.get("phone") else ""])
    pname = X.get("buyer_name") or P.get("mailing_name") or V.get("party") or ""
    paddr = X.get("buyer_address") or P.get("address", [])
    pgst = X.get("buyer_gstin") or V.get("party_gstin") or P.get("gstin", "")
    pstate = X.get("buyer_state") or P.get("state", "")
    buyer = _party_lines(pname, paddr, pgst, pstate,
                         [f"Place of Supply : {X['place_of_supply']}" if X.get("place_of_supply") else ""])
    cname = X.get("consignee_name") or pname
    consignee = _party_lines(cname, X.get("consignee_address") or paddr, X.get("consignee_gstin") or pgst,
                             X.get("consignee_state") or pstate)
    who = ("Supplier (Bill from)", "Buyer (Bill to)") if base == "Purchase" else ("Consignee (Ship to)", "Buyer (Bill to)")

    def block_h(lines, label):
        return (10 if label else 0) + sum(10.5 for _ in lines) + 8

    def draw_block(y, lines, label):
        y -= 10
        if label:
            p.text(L + 4, y, label, 7)
            y -= 10
        for t, f in lines:
            for i, ln in enumerate(wrap(t, 8 if f == "R" else 9, lw, f == "B")):
                p.text(L + 4, y, ln, 8 if f == "R" else 9, f)
                y -= 10.5
        return y

    h1 = block_h(seller, None) + sum(10.5 * (len(wrap(t, 8, lw)) - 1) for t, f in seller)
    h2 = block_h(consignee, who[0]) + sum(10.5 * (len(wrap(t, 8, lw)) - 1) for t, f in consignee)
    h3 = block_h(buyer, who[1]) + sum(10.5 * (len(wrap(t, 8, lw)) - 1) for t, f in buyer)
    show_consignee = base != "Purchase"
    left_h = h1 + (h2 if show_consignee else 0) + h3

    # right column cells (label / value), two per row like Tally
    cells = [
        ("Invoice No." if base != "Purchase" else "Supplier Invoice No.", V["number"] if base != "Purchase" else (V.get("reference") or V["number"])),
        ("Dated", tdate(V["date"])),
        ("Delivery Note", X.get("delivery_note", "")), ("Mode/Terms of Payment", X.get("terms_payment", "")),
        ("Reference No. & Date.", " ".join(x for x in (V.get("reference", ""), tdate(X.get("reference_date", ""))) if x)),
        ("Other References", X.get("other_refs", "")),
        ("Buyer's Order No.", X.get("order_no", "")), ("Dated", tdate(X.get("order_date", ""))),
        ("Dispatch Doc No.", X.get("dispatch_doc", "")), ("Delivery Note Date", tdate(X.get("delivery_note_date", ""))),
        ("Dispatched through", X.get("dispatched_through", "")), ("Destination", X.get("destination", "")),
    ]
    row_h = 22
    grid_h = row_h * 6
    right_h = max(grid_h + 26, left_h)
    left_h = right_h
    bottom = top - right_h
    p.box(L, bottom, R - L, right_h)
    p.line(mid, top, mid, bottom)
    # left blocks
    y = draw_block(top, seller, None)
    yb = top - h1
    if show_consignee:
        p.line(L, yb, mid, yb)
        draw_block(yb, consignee, who[0])
        yb -= h2
    p.line(L, yb, mid, yb)
    draw_block(yb, buyer, who[1])
    # right grid
    cw = (R - mid) / 2
    for i, (lab, val) in enumerate(cells):
        r, ccol = divmod(i, 2)
        x0 = mid + ccol * cw
        y0 = top - r * row_h
        p.text(x0 + 3, y0 - 8, lab, 7)
        if val:
            p.text(x0 + 3, y0 - 18, fit(val, 8, cw - 6, True), 8, "B")
        p.line(mid, y0 - row_h, R, y0 - row_h)
    for r in range(6):
        p.line(mid + cw, top - r * row_h, mid + cw, top - (r + 1) * row_h)
    p.text(mid + 3, top - grid_h - 8, "Terms of Delivery", 7)
    if X.get("terms_delivery"):
        yy = top - grid_h - 18
        for ln in wrap(X["terms_delivery"], 8, R - mid - 6)[:4]:
            p.text(mid + 3, yy, ln, 8)
            yy -= 10

    # ---- items table
    has_disc = any(i.get("disc") for i in d["items"])
    cols = [("Sl\nNo.", 20, "center"), ("Description of Goods", 0, "left"), ("HSN/SAC", 50, "center"),
            ("Quantity", 62, "right"), ("Rate", 56, "right"), ("per", 26, "center")]
    if has_disc:
        cols.append(("Disc. %", 30, "right"))
    cols.append(("Amount", 76, "right"))
    fixed = sum(c[1] for c in cols)
    cols[1] = (cols[1][0], (R - L) - fixed, "left")
    xs = [L]
    for c in cols:
        xs.append(xs[-1] + c[1])
    ci = {c[0]: i for i, c in enumerate(cols)}

    taxable = sum(i["amount"] for i in d["items"])
    sales_lines = [l for l in d["lines"] if l["kind"] == "sales"]
    if not d["items"]:
        taxable = sum(abs(l["amount"]) for l in sales_lines)
    extra_lines = [l for l in d["lines"] if l["kind"] in ("tax", "other")]
    party_amt = next((abs(l["amount"]) for l in d["lines"] if l["kind"] == "party"), V["amount"])

    def table_header(y):
        p.box(L, y - 22, R - L, 22)
        for i, (lab, w, al) in enumerate(cols):
            parts = lab.split("\n")
            for j, part in enumerate(parts):
                yy = y - (9 if len(parts) > 1 else 13) - j * 8
                p.text((xs[i] + xs[i + 1]) / 2, yy, part, 7.5, "R", "center")
            if i:
                p.line(xs[i], y, xs[i], y - 22)
        return y - 22

    def col_lines(y_from, y_to):
        p.line(L, y_from, L, y_to)
        p.line(R, y_from, R, y_to)
        for x in xs[1:-1]:
            p.line(x, y_from, x, y_to)

    y = table_header(bottom)
    body_top = y
    y -= 4

    def need(h, y):
        nonlocal body_top
        if y - h < 40:
            col_lines(body_top, y - 4)
            p.line(L, y - 4, R, y - 4)
            p.text(R, y - 14, "continued ...", 7.5, "I", "right")
            p.new_page()
            yy = table_header(PDF.H - 34)
            body_top = yy
            return yy - 4
        return y

    def cell(y, name, s, font="R", size=8):
        i = ci[name]
        al = cols[i][2]
        x = xs[i] + 3 if al == "left" else xs[i + 1] - 3 if al == "right" else (xs[i] + xs[i + 1]) / 2
        p.text(x, y, s, size, font, al)

    qty_unit, qty_total = set(), 0.0
    items = d["items"] or [{"item": l["ledger"], "qty": 0, "unit": "", "rate": 0, "amount": abs(l["amount"]),
                            "hsn": "", "disc": 0, "descr": ""} for l in sales_lines]
    for n, it in enumerate(items, 1):
        desc_w = cols[1][1] - 6
        dl = wrap(it.get("descr", ""), 7.5, desc_w - 8) if it.get("descr") else []
        y = need(12 + 9 * len(dl), y)
        y -= 9
        cell(y, "Sl\nNo.", str(n))
        p.text(xs[1] + 3, y, fit(it["item"], 8.5, desc_w, True), 8.5, "B")
        cell(y, "HSN/SAC", it.get("hsn") or "")
        if it["qty"]:
            q = abs(it["qty"])
            cell(y, "Quantity", f"{q:g} {it['unit']}".strip(), "B")
            qty_total += q
            qty_unit.add(it["unit"])
        if it["rate"]:
            cell(y, "Rate", inr(it["rate"]))
            cell(y, "per", it["unit"] or "")
        if has_disc and it.get("disc"):
            cell(y, "Disc. %", f"{it['disc']:g} %")
        cell(y, "Amount", inr(it["amount"]), "B")
        for ln in dl:
            y -= 9
            p.text(xs[1] + 11, y, ln, 7.5, "I")
        y -= 3

    if extra_lines:
        y = need(14, y)
        p.line(xs[-2], y, R, y, 0.4)
        y -= 9
        cell(y, "Amount", inr(taxable))
        for l in extra_lines:
            y = need(12, y)
            y -= 11
            amt = -l["amount"] if base in ("Sales", "Debit Note") else l["amount"]
            p.text(xs[2] - 6, y, fit(l["ledger"], 8.5, cols[1][1] - 12, True), 8.5, "BI", "right")
            if l["kind"] == "tax" and taxable:
                rate = round(abs(amt) / taxable * 100, 2)
                if abs(rate - round(rate * 2) / 2) < 0.02:
                    cell(y, "Rate", f"{rate:g} %")
                    cell(y, "per", "%")
            cell(y, "Amount", ("(-)" if amt < 0 else "") + inr(abs(amt)), "B")

    # stretch the table so the footer sits at the page bottom, like Tally
    n_hsn = len({(i.get("hsn") or "") for i in items}) if tax_lines else 0
    foot_h = 18 + 30 + 11 * len(wrap(words(party_amt), 9, R - L - 8, True)) + \
        ((24 + 11 * (n_hsn + 1) + 24) if tax_lines else 0) + 96
    end = 34 + foot_h if y - 6 > 34 + foot_h else y - 6
    col_lines(body_top, end)
    p.line(L, end, R, end)
    y = end - 13
    p.text(xs[2] - 6, y, "Total", 9, "B", "right")
    if len(qty_unit) == 1 and qty_total:
        cell(y, "Quantity", f"{qty_total:g} {next(iter(qty_unit))}".strip(), "B")
    p.money(R - 3, y, party_amt, 9, True)
    col_lines(end, y - 5)
    p.line(L, y - 5, R, y - 5)
    y -= 5

    # ---- amount in words + tax summary + declaration (new page if needed)
    def ensure(h, y):
        if y - h < 34:
            p.new_page()
            return PDF.H - 34
        return y

    y = ensure(34, y)
    top2 = y
    p.text(L + 4, y - 9, "Amount Chargeable (in words)", 7)
    p.text(R - 4, y - 9, "E. & O.E", 7, "I", "right")
    for ln in wrap(words(party_amt), 9, R - L - 8, True):
        y -= 11
        p.text(L + 4, y - 9, ln, 9, "B")
    y -= 16

    if tax_lines:
        heads = {}
        for l in tax_lines:
            nm = l["ledger"].upper()
            hd = "Integrated Tax" if "IGST" in nm else "Central Tax" if "CGST" in nm else \
                 "State Tax" if ("SGST" in nm or "UTGST" in nm) else "Cess"
            heads[hd] = heads.get(hd, 0) + abs(l["amount"])
        order = [h for h in ("Integrated Tax", "Central Tax", "State Tax", "Cess") if h in heads]
        groups = {}
        for it in items:
            groups.setdefault(it.get("hsn") or "", 0.0)
            groups[it.get("hsn") or ""] += it["amount"]
        tw = [0.0]
        hx = [L, L + 120, L + 200]
        rest = (R - L - 200 - 70) / max(1, len(order))
        for _ in order:
            hx.append(hx[-1] + rest)
        hx.append(R)
        nrows = len(groups) + 1
        th = 24 + 11 * nrows + 4
        y = ensure(th + 20, y)
        p.line(L, y, R, y)
        p.text((hx[0] + hx[1]) / 2, y - 14, "HSN/SAC", 7.5, "R", "center")
        p.text((hx[1] + hx[2]) / 2, y - 10, "Taxable", 7.5, "R", "center")
        p.text((hx[1] + hx[2]) / 2, y - 18, "Value", 7.5, "R", "center")
        for k, hname in enumerate(order):
            a, b = hx[2 + k], hx[3 + k]
            p.text((a + b) / 2, y - 8, hname, 7.5, "R", "center")
            p.line(a, y - 11, b, y - 11)
            p.line((a + b) / 2 - 10, y - 11, (a + b) / 2 - 10, y - 24)
            p.text((a + (a + b) / 2 - 10) / 2, y - 20, "Rate", 7, "R", "center")
            p.text(((a + b) / 2 - 10 + b) / 2, y - 20, "Amount", 7, "R", "center")
        p.text((hx[-2] + hx[-1]) / 2, y - 10, "Total", 7.5, "R", "center")
        p.text((hx[-2] + hx[-1]) / 2, y - 18, "Tax Amount", 7.5, "R", "center")
        p.line(L, y - 24, R, y - 24)
        yy = y - 24
        tot_tax = 0.0
        for k, (hsn, val) in enumerate(list(groups.items()) + [("Total", taxable)]):
            yy -= 11
            bold = hsn == "Total"
            p.text(hx[0] + 3, yy + 2, hsn, 8, "B" if bold else "R")
            p.text(hx[2] - 3, yy + 2, inr(val), 8, "B" if bold else "R", "right")
            share = val / taxable if taxable else 0
            row_tax = 0.0
            for j, hname in enumerate(order):
                a, b = hx[2 + j], hx[3 + j]
                amt = heads[hname] * share
                row_tax += amt
                if not bold and taxable:
                    p.text((a + b) / 2 - 13, yy + 2, f"{round(heads[hname] / taxable * 100, 2):g}%", 8, "R", "right")
                p.text(b - 3, yy + 2, inr(amt), 8, "B" if bold else "R", "right")
            p.text(R - 3, yy + 2, inr(row_tax), 8, "B" if bold else "R", "right")
            if bold:
                tot_tax = row_tax
            p.line(L, yy - 2, R, yy - 2, 0.3)
        for x in hx[1:-1]:
            p.line(x, y, x, yy - 2)
        for j in range(len(order)):
            a, b = hx[2 + j], hx[3 + j]
            p.line((a + b) / 2 - 10, y - 24, (a + b) / 2 - 10, yy - 2)
        y = yy - 2
        p.text(L + 4, y - 11, "Tax Amount (in words) :", 8)
        p.text(L + 4 + width("Tax Amount (in words) : ", 8), y - 11, fit(words(tot_tax), 8.5, R - L - 110, True), 8.5, "B")
        y -= 18

    # declaration, bank, signature
    y = ensure(96, y)
    if y < top2:
        p.line(L, y, R, y, 0.3)
    half = L + (R - L) / 2
    yy = y - 12
    if C.get("pan"):
        p.text(L + 4, yy, "Company's PAN", 8)
        p.text(L + 70, yy, f":  {C['pan']}", 8, "B")
        yy -= 14
    bank = d.get("bank") or {}
    by = y - 12
    if bank.get("bank_account"):
        p.text(half + 4, by, "Company's Bank Details", 8)
        by -= 11
        for lab, val in (("Bank Name", bank.get("name", "")), ("A/c No.", bank.get("bank_account", "")),
                         ("Branch & IFS Code", " & ".join(x for x in (bank.get("branch", ""), bank.get("ifsc", "")) if x))):
            p.text(half + 4, by, lab, 8)
            p.text(half + 82, by, ":", 8)
            p.text(half + 90, by, fit(val, 8, R - half - 96, True), 8, "B")
            by -= 10
    p.text(L + 4, yy, "Declaration", 8)
    p.line(L + 4, yy - 1.5, L + 4 + width("Declaration", 8), yy - 1.5, 0.4)
    yy -= 10
    for ln in wrap("We declare that this invoice shows the actual price of the goods described and that all "
                   "particulars are true and correct.", 8, half - L - 10):
        p.text(L + 4, yy, ln, 8)
        yy -= 10
    sig_top = min(by, y - 12) - 2
    bottom_y = y - 92
    p.line(half, sig_top, R, sig_top, 0.6)
    p.line(half, sig_top, half, bottom_y, 0.6)
    p.text(R - 4, sig_top - 11, f"for {d['company']}", 8.5, "B", "right")
    p.text(R - 4, bottom_y + 6, "Authorised Signatory", 8, "R", "right")
    p.line(L, top2, L, bottom_y, 0.6)
    p.line(R, top2, R, bottom_y, 0.6)
    p.line(L, bottom_y, R, bottom_y, 0.6)
    return p.output("This is a Computer Generated Invoice")


# ---------------------------------------------------------------- Receipt / Payment / Journal

def _company_header(p, d, y):
    C = d.get("company_info") or {}
    p.text(PDF.W / 2, y, d["company"], 12, "B", "center")
    for a in C.get("address", [])[:4]:
        y -= 10
        p.text(PDF.W / 2, y, a, 8, "R", "center")
    extra = [x for x in (C.get("state") and f"State Name : {C['state']}" + (f", Code : {C['gstin'][:2]}" if C.get("gstin") else ""),
                         C.get("gstin") and f"GSTIN/UIN: {C['gstin']}", C.get("email") and f"E-Mail : {C['email']}") if x]
    for e in extra:
        y -= 10
        p.text(PDF.W / 2, y, e, 8, "R", "center")
    return y


def accounting_pdf(d):
    V = d["voucher"]
    base = V.get("base") or V["vtype"]
    p = PDF()
    L, R = 48, PDF.W - 48
    y = _company_header(p, d, PDF.H - 48)
    y -= 26
    title = f"{base} Voucher" if base in ("Receipt", "Payment", "Contra", "Journal") else V["vtype"]
    p.text(PDF.W / 2, y, title, 11, "B", "center")
    y -= 22
    p.text(L, y, "No. :", 8.5)
    p.text(L + 26, y, V["number"], 8.5, "B")
    p.text(R - 70, y, "Dated :", 8.5, "R", "right")
    p.text(R, y, tdate(V["date"]), 8.5, "B", "right")
    y -= 10
    p.line(L, y, R, y, 0.8)
    two_col = base not in ("Receipt", "Payment", "Contra")
    y -= 12
    p.text(L + 4, y, "Particulars", 8.5, "B")
    if two_col:
        p.text(R - 90, y, "Debit", 8.5, "B", "right")
        p.text(R, y, "Credit", 8.5, "B", "right")
    else:
        p.text(R, y, "Amount", 8.5, "B", "right")
    y -= 6
    p.line(L, y, R, y, 0.5)
    y -= 14
    lines = d["lines"]
    if two_col:
        for l in sorted(lines, key=lambda l: -l["amount"]):
            p.text(L + 4, y, "To" if l["amount"] > 0 else "By", 8.5, "R")
            p.text(L + 24, y, fit(l["ledger"], 9, R - L - 200, True), 9, "B")
            p.text(R - 90 if l["amount"] > 0 else R, y, inr(abs(l["amount"])), 8.5, "R", "right")
            y -= 14
        total = sum(l["amount"] for l in lines if l["amount"] > 0)
    else:
        main = [l for l in lines if not l.get("cashbank")] if base != "Contra" else [l for l in lines if l["amount"] > 0]
        through = [l for l in lines if l not in main]
        p.text(L + 4, y, "Account :", 8)
        y -= 13
        for l in main:
            p.text(L + 20, y, fit(l["ledger"], 9, R - L - 140, True), 9, "B")
            p.text(R, y, inr(abs(l["amount"])), 8.5, "R", "right")
            y -= 13
            for b in [b for b in d.get("bills", []) if b["ledger"] == l["ledger"]]:
                p.text(L + 32, y, f"{b['btype']}  {b['name']}".strip(), 8, "I")
                p.text(R - 100, y, f"{inr(abs(b['amount']))} {'Dr' if b['amount'] > 0 else 'Cr'}", 8, "I", "right")
                y -= 11
        if through:
            y -= 4
            p.text(L + 4, y, "Through :", 8)
            y -= 13
            for l in through:
                p.text(L + 20, y, fit(l["ledger"], 9, R - L - 140, True), 9, "B")
                y -= 13
        total = V["amount"]
    if V.get("narration"):
        y -= 4
        p.text(L + 4, y, "On Account of :", 8)
        y -= 12
        for ln in wrap(V["narration"], 8.5, R - L - 140):
            p.text(L + 20, y, ln, 8.5, "I")
            y -= 11
    y -= 6
    p.text(L + 4, y, "Amount (in words) :", 8)
    y -= 12
    for ln in wrap(words(total), 9, R - L - 140, True):
        p.text(L + 20, y, ln, 9, "B")
        y -= 11
    y -= 2
    p.line(L, y, R, y, 0.5)
    y -= 13
    if two_col:
        p.money(R - 90, y, total, 9, True)
        p.money(R, y, total, 9, True)
    else:
        p.money(R, y, total, 9, True)
    y -= 6
    p.line(L, y, R, y, 0.8)
    y -= 60
    left_sig = {"Receipt": "Receiver's Signature :", "Payment": "Receiver's Signature :"}.get(base, "")
    if left_sig:
        p.text(L, y, left_sig, 8.5)
    p.text(R, y, "Authorised Signatory", 8.5, "R", "right")
    return p.output()


def voucher_pdf(d):
    base = d["voucher"].get("base") or d["voucher"]["vtype"]
    if d["items"] or base in ("Sales", "Purchase", "Credit Note", "Debit Note"):
        return invoice_pdf(d)
    return accounting_pdf(d)


# ---------------------------------------------------------------- Ledger Account

def ledger_pdf(d):
    Lg = d["ledger"]
    X = Lg.get("extra") or {}
    p = PDF()
    L, R = 36, PDF.W - 36
    cx = {"date": L, "part": L + 52, "type": 318, "no": 382, "dr": 480, "cr": R}
    page = [1]

    def header(first):
        y = _company_header(p, d, PDF.H - 40)
        y -= 22
        p.text(PDF.W / 2, y, Lg["name"], 11, "B", "center")
        y -= 11
        p.text(PDF.W / 2, y, "Ledger Account", 8.5, "R", "center")
        for a in X.get("address", [])[:3]:
            y -= 10
            p.text(PDF.W / 2, y, a, 8, "R", "center")
        y -= 14
        p.text(R, y, f"{tdate(d['from'])} to {tdate(d['to'])}", 8.5, "B", "right")
        y -= 6
        p.line(L, y, R, y, 0.6)
        y -= 11
        for k, lab, al in (("date", "Date", "left"), ("part", "Particulars", "left"), ("type", "Vch Type", "left"),
                           ("no", "Vch No.", "left"), ("dr", "Debit", "right"), ("cr", "Credit", "right")):
            p.text(cx[k], y, lab, 8.5, "I" if k in ("dr", "cr") else "R", al)
        y -= 5
        p.line(L, y, R, y, 0.6)
        return y - 13

    y = header(True)
    dr_tot = cr_tot = 0.0

    def row(y, dt, toby, part, vtype, vno, amt, narr="", bold=False):
        nonlocal dr_tot, cr_tot
        if dt:
            p.text(cx["date"], y, dt, 8.5)
        if toby:
            p.text(cx["part"], y, toby, 8.5)
        p.text(cx["part"] + 16, y, fit(part, 9, cx["type"] - cx["part"] - 22, True), 9, "B")
        p.text(cx["type"], y, fit(vtype, 8.5, cx["no"] - cx["type"] - 4), 8.5)
        p.text(cx["no"], y, fit(vno, 8.5, cx["dr"] - cx["no"] - 60), 8.5)
        if amt > 0:
            p.text(cx["dr"], y, inr(amt), 8.5, "B" if bold else "R", "right")
            dr_tot += amt
        elif amt < 0:
            p.text(cx["cr"], y, inr(-amt), 8.5, "B" if bold else "R", "right")
            cr_tot -= amt
        y -= 12
        if narr:
            for ln in wrap(narr.replace("\r", " ").replace("\n", " "), 7.5, cx["type"] - cx["part"] - 22)[:3]:
                p.text(cx["part"] + 16, y + 2, ln, 7.5, "I", color=GREY)
                y -= 9
            y -= 2
        return y

    if abs(d["opening"]) > 0.005:
        y = row(y, tdate(d["from"]), "", "Opening Balance", "", "", d["opening"], bold=True)
    for e in d["entries"]:
        if y < 70:
            p.text(R, y - 4, "Continued...", 7.5, "I", "right")
            p.new_page()
            y = header(False)
        a = e["amount"]
        y = row(y, tdate(e["date"]), "To" if a > 0 else "By", e.get("against") or e["vtype"], e["vtype"],
                e["number"], a, e.get("narration") or "")
    if y < 110:
        p.new_page()
        y = header(False)
    y += 4
    p.line(cx["dr"] - 70, y, R, y, 0.5)
    y -= 11
    p.text(cx["dr"], y, inr(dr_tot), 8.5, "R", "right")
    p.text(cx["cr"], y, inr(cr_tot), 8.5, "R", "right")
    y -= 14
    closing = round(dr_tot - cr_tot, 2)
    if abs(closing) > 0.005:
        p.text(cx["part"], y, "By" if closing > 0 else "To", 8.5)
        p.text(cx["part"] + 16, y, "Closing Balance", 9, "B")
        p.text(cx["cr"] if closing > 0 else cx["dr"], y, inr(abs(closing)), 8.5, "B", "right")
        y -= 6
    p.line(cx["dr"] - 70, y, R, y, 0.5)
    y -= 11
    grand = max(dr_tot, cr_tot)
    p.money(cx["dr"], y, grand, 8.5, True)
    p.money(cx["cr"], y, grand, 8.5, True)
    y -= 5
    p.line(cx["dr"] - 70, y, R, y, 0.5)
    p.line(cx["dr"] - 70, y - 2, R, y - 2, 0.5)
    return p.output()
