/* Bahi — phone app for Tally data synced to your server */
"use strict";
const APP_VERSION = "2.0";

const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const S = {
  companies: [], cid: null, period: null, // period: {key, from, to} or null = full synced year
  dueKind: "receivable", dayType: "", cache: {},
};
try { S.cid = Number(localStorage.getItem("cid")) || null; } catch (e) {}
try { S.lsort = localStorage.getItem("lsort") || "name"; S.esort = localStorage.getItem("esort") || "old"; } catch (e) { S.lsort = "name"; S.esort = "old"; }
function savePref(k, v) { S[k] = v; try { localStorage.setItem(k, v); } catch (e) {} }
function sortChips(id, opts, cur) {
  return `<div class="toolbar sortbar" id="${id}" role="group" aria-label="Sort"><span class="sortlabel">Sort</span>${opts.map(([k, l]) =>
    `<button class="chip ${k === cur ? "on" : ""}" data-sort="${k}" aria-pressed="${k === cur}">${l}</button>`).join("")}</div>`;
}
try { const p = JSON.parse(localStorage.getItem("period") || "null"); if (p && p.key !== "custom") S.period = p; } catch (e) {}

/* ---------------------------------------------------------------- formatting */
const nf2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const nfq = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });
const h = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;

function rupees(n, dp = true) { return "₹" + (dp ? nf2 : nf0).format(Math.abs(n || 0)); }
function short(n) {
  const a = Math.abs(n || 0), s = n < 0 ? "−" : "";
  if (a >= 1e7) return s + "₹" + (a / 1e7).toFixed(a >= 1e9 ? 0 : 2) + " Cr";
  if (a >= 1e5) return s + "₹" + (a / 1e5).toFixed(2) + " L";
  return s + "₹" + nf0.format(a);
}
/* debit-positive amount -> "1,234.00 Dr" */
function drcr(n, opts = {}) {
  const v = Math.round((n || 0) * 100) / 100;
  if (Math.abs(v) < 0.005) return `<span class="amt">${opts.short ? "₹0" : "0.00"}</span>`;
  const side = v > 0 ? "Dr" : "Cr";
  return `<span class="amt ${side.toLowerCase()}">${opts.short ? short(Math.abs(v)) : nf2.format(Math.abs(v))}<span class="side">${side}</span></span>`;
}
function money(n, cls = "") { return `<span class="amt ${cls}">${nf2.format(n || 0)}</span>`; }
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fdate(iso) { if (!iso) return ""; const [y, m, d] = iso.split("-"); return `${+d} ${MON[+m - 1]} ${y}`; }
function ago(ts) {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " hr ago";
  return Math.round(s / 86400) + " days ago";
}
function daysSince(iso) { if (!iso) return null; return Math.floor((Date.now() - new Date(iso + "T00:00:00")) / 864e5); }
function qty(q, unit) { return `${nfq.format(q || 0)} ${h(unit || "")}`.trim(); }
function digits(p) { let d = String(p || "").replace(/\D/g, ""); if (d.length === 10) d = "91" + d; if (d.length === 11 && d[0] === "0") d = "91" + d.slice(1); return d.length >= 11 ? d : ""; }
function iso(d) { return d.toISOString().slice(0, 10); }

/* ---------------------------------------------------------------- data */
let offlineSeen = false;
async function api(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  if (r.headers.get("X-From-Cache")) offlineSeen = true;
  if (r.status === 401) { throw Object.assign(new Error("login"), { login: true }); }
  if (r.status === 503 && !r.headers.get("X-From-Cache")) throw new Error("offline");
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Server error " + r.status);
  return r.json();
}
function cpath(what, params = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, v);
  const s = q.toString();
  return `/api/c/${S.cid}/${what}${s ? "?" + s : ""}`;
}
function periodParams() { return S.period ? { from: S.period.from, to: S.period.to } : {}; }

async function loadCompanies() {
  const d = await api("/api/companies");
  S.companies = d.companies;
  if (!S.companies.find((c) => c.id === S.cid)) {
    // start with the company holding the most recent vouchers (usually the current year's)
    const latest = S.companies.slice().sort((a, b) => (b.last_vch || "").localeCompare(a.last_vch || ""))[0];
    S.cid = latest?.id ?? null;
  }
  renderCover();
}

function renderCover() {
  const c = S.companies.find((x) => x.id === S.cid);
  $("#company").textContent = c ? c.name : "Bahi";
  if (c && S.companies.length > 1) $("#company").insertAdjacentHTML("beforeend", ' <span class="caret" aria-hidden="true">▾</span>');
  const st = $("#status");
  if (!c) { st.innerHTML = ""; return; }
  const online = c.last_seen && Date.now() / 1000 - c.last_seen < 30 * 60;
  st.innerHTML = `<span class="dot ${online ? "" : "off"}"></span>` +
    (online ? `Tally connected. Last change synced ${ago(c.last_sync)}` :
      `Tally offline since ${ago(c.last_seen)}. Figures as of ${new Date(c.last_sync * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}`);
}

/* ---------------------------------------------------------------- shared bits */
const ICON = {
  call: '<svg viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
  wa: '<svg viewBox="0 0 24 24"><path d="M4 20l1.3-4A8 8 0 1 1 8 18.7z M9 9.5c.5 2 2.5 4 5 5l1.2-1.2 1.8.9-.4 1.6c-3.5.2-8-4.3-8-7.8L10.2 7l.9 1.8z"/></svg>',
  share: '<svg viewBox="0 0 24 24"><path d="M12 3v12 M7 8l5-5 5 5 M5 14v6h14v-6"/></svg>',
  print: '<svg viewBox="0 0 24 24"><path d="M7 9V3h10v6 M7 17H4v-7h16v7h-3 M7 14h10v7H7z"/></svg>',
};

const PERIODS = [
  ["year", "This year"], ["month", "This month"], ["last", "Last month"], ["quarter", "This quarter"], ["all", "All dates"], ["custom", "Custom"],
];
function periodFor(key) {
  const t = new Date(); const y = t.getFullYear(), m = t.getMonth();
  if (key === "all") return { key, from: "2000-01-01", to: "2099-12-31" };
  if (key === "month") return { key, from: iso(new Date(Date.UTC(y, m, 1))), to: iso(new Date(Date.UTC(y, m + 1, 0))) };
  if (key === "last") return { key, from: iso(new Date(Date.UTC(y, m - 1, 1))), to: iso(new Date(Date.UTC(y, m, 0))) };
  if (key === "quarter") { const q0 = m - ((m - 3 + 12) % 3); return { key, from: iso(new Date(Date.UTC(y, q0, 1))), to: iso(new Date(Date.UTC(y, q0 + 3, 0))) }; }
  return null;
}
function periodBar(from, to) {
  const key = S.period ? S.period.key : "year";
  return `<div class="toolbar" role="group" aria-label="Period">${PERIODS.map(([k, l]) =>
    `<button class="chip ${k === key ? "on" : ""}" data-period="${k}" aria-pressed="${k === key}">${l}</button>`).join("")}</div>
    ${key === "custom" ? `<div class="dates"><input type="date" id="pf" value="${from}" aria-label="From date"> to <input type="date" id="pt" value="${to}" aria-label="To date"> <button class="chip" id="papply">Show</button></div>` :
      `<p class="subtitle">${key === "all" ? "All synced dates" : `${fdate(from)} to ${fdate(to)}`}</p>`}`;
}
function wirePeriod(from, to) {
  view.querySelectorAll("[data-period]").forEach((b) => b.onclick = () => {
    const k = b.dataset.period;
    S.period = k === "year" ? null : k === "custom" ? { key: "custom", from: from < "2001" ? iso(new Date(Date.now() - 30 * 864e5)) : from, to: to > "2098" ? iso(new Date()) : to } : periodFor(k);
    try { localStorage.setItem("period", JSON.stringify(S.period)); } catch (e) {}
    route();
  });
  const ap = $("#papply");
  if (ap) ap.onclick = () => { S.period = { key: "custom", from: $("#pf").value, to: $("#pt").value }; route(); };
}

function loading() { view.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>'; }
function setTitle(back) {
  $("#back").hidden = !back;
  const tab = (location.hash.split("/")[1] || "home").split("?")[0];
  const map = { "": "home", ledger: "parties", group: "parties", item: "reports", daybook: "reports", voucher: "vouchers", pl: "reports", gst: "reports", check: "reports", settings: "reports", day: "sales", stock: "reports", groups: "reports" };
  const on = map[tab] || tab;
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === on));
}

/* ---------------------------------------------------------------- views */
async function vHome() {
  setTitle(false);
  const d = await api(cpath("dashboard", periodParams()));
  const thisMonth = new Date().toISOString().slice(0, 7);
  view.innerHTML = `
  <section class="page">
    <div class="hero">
      <a href="#/dues/receivable"><div class="label">You will receive</div><div class="big">${short(d.receivable)}</div></a>
      <a href="#/dues/payable"><div class="label">You owe</div><div class="big owe">${short(d.payable)}</div></a>
    </div>
    <div class="tiles">
      <a href="#/group/${enc("Cash-in-Hand")}"><div class="label">Cash</div><div class="val">${short(d.cash)}</div></a>
      <a href="#/group/${enc("Bank Accounts")}"><div class="label">Bank</div><div class="val">${short(d.bank_total)}</div></a>
      <a href="#/stock"><div class="label">Stock</div><div class="val">${short(d.stock_value)}</div></a>
    </div>
  </section>

  <section class="page">
    <div class="block-title">Sales <a href="#/sales">Sales by day</a></div>
    <div class="sales-head">
      <div><div class="val">${short(d.sales)}</div><div class="label">${S.period ? "in this period" : "this financial year"}</div></div>
      <div><div class="val">${short(d.sales_month)}</div><div class="label">this month</div></div>
      <div><div class="val">${short(d.purchase)}</div><div class="label">purchases${S.period ? "" : " this year"}</div></div>
    </div>
    <div class="chart" id="chart"></div>
  </section>

  ${d.banks.length > 1 ? `<section class="page"><div class="block-title">Bank balances</div>
    ${d.banks.map((b) => `<a class="row" href="#/ledger/${enc(b.name)}"><div class="main name">${h(b.name)}</div><div class="end">${drcr(b.closing)}</div><span class="chev"></span></a>`).join("")}
  </section>` : ""}

  <section class="page">
    <div class="block-title">Biggest dues <a href="#/dues/receivable">All dues</a></div>
    ${d.top_debtors.length ? d.top_debtors.map((p) => `<a class="row" href="#/ledger/${enc(p.name)}"><div class="main name">${h(p.name)}</div><div class="end">${drcr(p.closing)}</div><span class="chev"></span></a>`).join("")
      : '<div class="empty">Nobody owes you money right now.</div>'}
  </section>

  <section class="page">
    <div class="block-title">Latest entries <a href="#/daybook">Day Book</a></div>
    ${d.recent.map(vrow).join("") || '<div class="empty">No vouchers synced yet.</div>'}
  </section>
  ${d.company.unbalanced ? `<p class="note warn">${d.company.unbalanced} vouchers didn't add up during the last sync, so some figures may be off.</p>` : ""}`;
  drawSales($("#chart"), d.monthly_sales, thisMonth);
}

function vrow(v) {
  return `<a class="row" href="#/voucher/${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}</div>
    <div class="meta">${fdate(v.date)}, ${h(v.vtype)} ${h(v.number)}</div></div><div class="end">${money(v.amount)}</div><span class="chev"></span></a>`;
}

/* monthly sales — single series, so no legend; tap a bar for the figure */
function drawSales(el, rows, thisMonth) {
  if (!rows.length) { el.innerHTML = '<div class="empty">No sales in this period.</div>'; return; }
  const W = Math.max(280, el.clientWidth - 16), H = 150, padB = 22, padT = 18, gap = 2;
  const max = Math.max(...rows.map((r) => r.s), 1);
  const bw = Math.min(46, (W - gap * (rows.length - 1)) / rows.length);
  const total = bw * rows.length + gap * (rows.length - 1), x0 = (W - total) / 2;
  const bars = rows.map((r, i) => {
    const hgt = Math.max(2, (Math.max(r.s, 0) / max) * (H - padB - padT));
    const x = x0 + i * (bw + gap), y = H - padB - hgt, rad = Math.min(4, bw / 2, hgt);
    const [yy, mm] = r.m.split("-");
    const label = MON[+mm - 1];
    const cur = r.m === thisMonth;
    return `<g data-i="${i}" tabindex="0" role="img" aria-label="${label} ${yy}: ${rupees(r.s, false)}">
      <rect x="${x - gap / 2}" y="${padT}" width="${bw + gap}" height="${H - padT}" fill="transparent"/>
      <path d="M${x},${H - padB} V${y + rad} Q${x},${y} ${x + rad},${y} H${x + bw - rad} Q${x + bw},${y} ${x + bw},${y + rad} V${H - padB} Z"
        fill="var(--bar)" opacity="${cur ? 1 : 0.55}"/>
      <text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle" font-size="12" fill="var(--ink-3)">${label}</text>
      ${cur ? `<text x="${x + bw / 2}" y="${y - 5}" text-anchor="middle" font-size="12" font-weight="600" fill="var(--ink-2)">${short(r.s)}</text>` : ""}
    </g>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" aria-label="Sales by month">
    <line x1="0" x2="${W}" y1="${H - padB}" y2="${H - padB}" stroke="var(--rule)"/>${bars}</svg><div class="tip" hidden></div>`;
  const tip = $(".tip", el), svg = $("svg", el);
  const show = (g) => {
    const r = rows[+g.dataset.i], [yy, mm] = r.m.split("-");
    const box = g.getBBox(), sc = svg.clientWidth / W;
    tip.hidden = false; tip.textContent = `${MON[+mm - 1]} ${yy}: ${rupees(r.s, false)}`;
    tip.style.left = Math.min(Math.max((box.x + box.width / 2) * sc + 8, 70), svg.clientWidth - 60) + "px";
    tip.style.top = (padT + 6) * (svg.clientHeight / H) + "px";
  };
  svg.querySelectorAll("g[data-i]").forEach((g) => {
    g.addEventListener("pointerenter", () => show(g)); g.addEventListener("click", () => show(g));
    g.addEventListener("focus", () => show(g)); g.addEventListener("blur", () => tip.hidden = true);
  });
  svg.addEventListener("pointerleave", () => tip.hidden = true);
}

let searchTimer;
async function vParties(q) {
  setTitle(false);
  if (q !== undefined) S.lq = q;
  const d = await api(cpath("ledgers", { q: S.lq || "", sort: S.lsort }));
  if (!$("#lsearch")) {
    view.innerHTML = `<input class="search" id="lsearch" type="search" placeholder="Search ledgers" aria-label="Search ledgers" value="${h(S.lq || "")}">
      <div class="toolbar"><a class="chip" href="#/group/${enc("Sundry Debtors")}">Debtors</a><a class="chip" href="#/group/${enc("Sundry Creditors")}">Creditors</a>
      <a class="chip" href="#/group/${enc("Bank Accounts")}">Banks</a><a class="chip" href="#/groups">All groups</a></div>
      <div id="lsortbar"></div><section class="page" id="llist"></section>`;
    $("#lsearch").oninput = (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => vParties(e.target.value).catch(fail), 200); };
  }
  $("#lsortbar").innerHTML = sortChips("lsorts", [["name", "Name"], ["balance", "Balance"], ["recent", "Recent activity"]], S.lsort);
  $("#lsortbar").querySelectorAll("[data-sort]").forEach((b) => b.onclick = () => { savePref("lsort", b.dataset.sort); vParties().catch(fail); });
  const list = d.ledgers;
  $("#llist").innerHTML = (list.length ? "" : '<div class="empty">No ledger matches that name.</div>') +
    list.slice(0, 300).map((l) => `<a class="row" href="#/ledger/${enc(l.name)}"><div class="main"><div class="name">${h(l.name)}</div>
      <div class="meta">${h(l.parent)}${l.last_txn ? `, last entry ${fdate(l.last_txn)}` : ""}</div></div>
      <div class="end">${drcr(l.closing)}</div></a>`).join("") +
    (list.length > 300 ? `<div class="note">Showing 300 of ${list.length}. Type to narrow down.</div>` : "");
}

async function sharePdf(url, name) {
  toast("Preparing PDF");
  let blob;
  try {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error();
    blob = await r.blob();
  } catch (e) { toast("Couldn't make the PDF. Check your connection."); return; }
  const file = new File([blob], name.replace(/[^\w .-]+/g, "").slice(0, 80) + ".pdf", { type: "application/pdf" });
  try {
    if (navigator.canShare && navigator.canShare({ files: [file] })) { await navigator.share({ files: [file], title: name }); return; }
  } catch (e) { if (e.name === "AbortError") return; }
  const u = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = u; a.download = file.name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 60000);
}

function billRows(bills, rec = true) {
  return bills.map((b) => {
    const od = b.overdue > 0 ? `<span class="od">${b.overdue} days overdue</span>` :
      b.age !== null && b.age !== undefined ? `${b.age} days old` : "";
    const inner = `<div><div class="ref">${h(b.ref)}</div><div class="meta">${b.date ? fdate(b.date) : "No bill date"}${b.due ? `, due ${fdate(b.due)}` : ""}</div></div>
      <div class="end">${money(b.amount, b.amount < 0 ? "cr" : "")}<div class="meta">${od}</div></div>${b.vid ? '<span class="chev"></span>' : ""}`;
    return b.vid ? `<a class="bill" href="#/voucher/${b.vid}">${inner}</a>` : `<div class="bill">${inner}</div>`;
  }).join("");
}

function sortEntries(list) {
  const e = list.slice();
  if (S.esort === "new") e.reverse();
  else if (S.esort === "amount") e.sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
  return e;
}

async function vLedger(name) {
  setTitle(true);
  const d = await api(cpath("ledger", { name, ...periodParams() }));
  const L = d.ledger, phone = digits(L.mobile || L.phone);
  const co = S.companies.find((c) => c.id === S.cid)?.name || "";
  const isDebtor = d.closing > 0.5 && d.bill_kind === "receivable";
  const overdue = (d.bills || []).filter((b) => b.overdue > 0 && b.amount > 0);
  const waText = isDebtor ? reminderText(L.name, co, d.closing, overdue) : `Dear ${L.name}, greetings from ${co}.`;
  const pdfUrl = cpath("ledger_pdf", { name, ...periodParams() });
  const pending = (d.bills || []).filter((b) => Math.abs(b.amount) > 0.5);
  view.innerHTML = `
    <div class="crumbs"><a href="#/group/${enc(L.parent)}">${h(L.parent)}</a></div>
    <h1 class="title">${h(L.name)}</h1>
    ${periodBar(d.from, d.to)}
    <section class="page">
      ${L.gstin || L.mobile || L.phone || L.email ? `<div class="info" style="padding-top:12px">${L.gstin ? `<div>GSTIN ${h(L.gstin)}</div>` : ""}${L.mobile || L.phone ? `<div>${h(L.mobile || L.phone)}</div>` : ""}${L.email ? `<div>${h(L.email)}</div>` : ""}</div>` : ""}
      <div class="actions" style="${L.gstin || L.mobile || L.phone || L.email ? "" : "padding-top:12px"}">
        <button class="btn primary" id="sharepdf">${ICON.share}Share PDF</button>
        <a class="btn" href="${pdfUrl}" target="_blank" rel="noopener">${ICON.print}View PDF</a>
        ${phone ? `<a class="btn wa" href="https://wa.me/${phone}?text=${enc(waText)}" target="_blank" rel="noopener">${ICON.wa}${isDebtor ? "Remind" : "WhatsApp"}</a><a class="btn" href="tel:+${phone}">${ICON.call}Call</a>` : ""}
      </div>
      <div class="totals">
        <div><div class="label">Opening</div>${drcr(d.opening)}</div>
        <div><div class="label">Closing</div>${drcr(d.closing)}</div>
        <div><div class="label">Debits</div>${money(d.debit)}</div>
        <div><div class="label">Credits</div>${money(d.credit)}</div>
      </div>
    </section>
    ${pending.length ? `<section class="page"><div class="block-title">Pending bills <span>${overdue.length ? `${overdue.length} overdue` : ""}</span></div>${billRows(pending.slice(0, 5))}
      ${pending.length > 5 ? `<div id="morebills" hidden>${billRows(pending.slice(5))}</div><button class="row" id="showbills" style="justify-content:center;color:var(--ink-2);font-weight:500">Show all ${pending.length} bills</button>` : ""}</section>` : ""}
    ${d.entries.length > 1 ? sortChips("esorts", [["old", "Oldest first"], ["new", "Newest first"], ["amount", "Largest amount"]], S.esort) : ""}
    <section class="page ruled">
      <div class="carry"><span>Opening balance</span>${drcr(d.opening)}</div>
      ${sortEntries(d.entries).map((e) => `<a class="entry" href="#/voucher/${e.id}">
          <span class="d">${fdate(e.date)}</span>
          <span class="p">${h(e.against || e.vtype)}</span>${drcr(e.amount)}
          <span class="v">${h(e.vtype)} ${h(e.number)}</span><span class="bal">Bal ${drcr(e.balance)}</span>
        </a>`).join("") || '<div class="empty">No entries in this period.</div>'}
      <div class="closing"><span>Closing balance</span>${drcr(d.closing)}</div>
    </section>`;
  wirePeriod(d.from, d.to);
  $("#sharepdf").onclick = () => sharePdf(pdfUrl, `${L.name} statement`);
  view.querySelectorAll("#esorts [data-sort]").forEach((b) => b.onclick = () => {
    const y = window.scrollY; savePref("esort", b.dataset.sort); vLedger(name).then(() => window.scrollTo(0, y)).catch(fail);
  });
  const sb = $("#showbills");
  if (sb) sb.onclick = () => { $("#morebills").hidden = false; sb.remove(); };
}

function reminderText(name, co, total, overdue) {
  let t = `Dear ${name}, your balance with ${co} is ${rupees(total)}.`;
  if (overdue && overdue.length) {
    const top = overdue.slice().sort((a, b) => b.overdue - a.overdue).slice(0, 5);
    t += ` Overdue bills: ` + top.map((b) => `${b.ref} dated ${fdate(b.date)} for ${rupees(b.amount)} (${b.overdue} days overdue)`).join("; ") +
      (overdue.length > 5 ? ` and ${overdue.length - 5} more` : "") + ".";
  }
  return t + " Kindly arrange the payment. Thank you.";
}

async function vGroup(name) {
  setTitle(true);
  const d = await api(cpath("group", { name }));
  view.innerHTML = `
    ${name ? `<div class="crumbs"><a href="#/groups">All groups</a>${d.path.map((p) => ` / <a href="#/group/${enc(p)}">${h(p)}</a>`).join("")}</div>` : ""}
    <h1 class="title">${name ? h(name) : "Group summary"}</h1>
    <p class="subtitle">Closing balances as per Tally${name ? `. Total ₹${nf2.format(Math.abs(d.total))} ${d.total >= 0 ? "Dr" : "Cr"}` : ""}</p>
    ${d.groups.length ? `<section class="page">${d.groups.map((g) => `<a class="row" href="#/group/${enc(g.name)}"><div class="main"><div class="name">${h(g.name)}</div><div class="meta">${g.count} ledgers</div></div><div class="end">${drcr(g.closing)}</div><span class="chev"></span></a>`).join("")}</section>` : ""}
    ${d.ledgers.length ? `<section class="page">${d.ledgers.map((l) => `<a class="row" href="#/ledger/${enc(l.name)}"><div class="main name">${h(l.name)}</div><div class="end">${drcr(l.closing)}</div></a>`).join("")}</section>` : ""}
    ${!d.groups.length && !d.ledgers.length ? '<div class="empty">Every ledger in this group has a zero balance.</div>' : ""}`;
}

/* ageing: one stacked bar, light to dark red as bills get older; amounts listed beside each step */
function ageingBar(buckets, total) {
  const order = ["0-30 days", "31-60 days", "61-90 days", "Over 90 days", "No bill date"];
  const shade = { "0-30 days": "var(--age1)", "31-60 days": "var(--age2)", "61-90 days": "var(--age3)", "Over 90 days": "var(--age4)", "No bill date": "var(--age0)" };
  const bs = order.map((k) => buckets.find((b) => b.label === k)).filter((b) => b && b.amount > 0.5);
  const sum = bs.reduce((a, b) => a + b.amount, 0) || 1;
  return `<div class="age-bar" role="img" aria-label="Dues by age">${bs.map((b) =>
    `<span style="flex:${b.amount / sum};background:${shade[b.label]}" title="${b.label}: ${rupees(b.amount, false)}"></span>`).join("")}</div>
    <div class="age-legend">${bs.map((b) => `<div><span class="sw" style="background:${shade[b.label]}"></span><span class="lbl">${b.label}</span><span class="amt">${short(b.amount)}</span></div>`).join("")}</div>`;
}

async function vDues(kind) {
  setTitle(false);
  S.dueKind = kind || S.dueKind;
  const d = await api(cpath("outstanding", { kind: S.dueKind }));
  const co = S.companies.find((c) => c.id === S.cid)?.name || "";
  const rec = S.dueKind === "receivable";
  view.innerHTML = `
    <div class="toolbar" role="group" aria-label="Dues">
      <a class="chip ${rec ? "on" : ""}" href="#/dues/receivable" aria-pressed="${rec}">To receive</a>
      <a class="chip ${!rec ? "on" : ""}" href="#/dues/payable" aria-pressed="${!rec}">To pay</a>
    </div>
    <section class="page">
      <div class="hero"><div><div class="label">${rec ? "You will receive" : "You owe"}</div>
      <div class="big ${rec ? "" : "owe"}">${short(d.total)}</div></div>
      <div><div class="label">Overdue</div><div class="big owe">${short(d.overdue)}</div></div></div>
      <div style="padding:0 16px 14px">${ageingBar(d.buckets, d.total)}</div>
    </section>
    <section class="page">
      ${d.parties.map((p, i) => {
        const ph = digits(p.mobile || p.phone);
        const od = p.bills.filter((b) => b.overdue > 0 && b.amount > 0);
        return `<div class="party">
          <button class="row" aria-expanded="false" data-p="${i}"><div class="main"><div class="name">${h(p.name)}</div>
            <div class="meta">${p.overdue_amount > 0.5 ? `<span class="od">${rupees(p.overdue_amount, false)} overdue</span>, ` : ""}${p.oldest_days !== null ? `oldest bill ${p.oldest_days} days` : "no bill dates"}</div></div>
            <div class="end">${money(p.amount)}</div><span class="chev down"></span></button>
          <div class="bills" id="pb${i}" hidden>${billRows(p.bills)}
            <div class="actions" style="padding-top:10px"><a class="btn" href="#/ledger/${enc(p.name)}">Open ledger</a>
            ${rec && ph ? `<a class="btn wa" href="https://wa.me/${ph}?text=${enc(reminderText(p.name, co, p.amount, od))}" target="_blank" rel="noopener">${ICON.wa}Remind</a>` : ""}</div></div>
        </div>`;
      }).join("") || `<div class="empty">${rec ? "Nobody owes you money right now." : "You don't owe anyone right now."}</div>`}
    </section>
    <p class="note" style="border:0">${d.source === "tally" ? "Bills as calculated by Tally's outstanding report." : "Bills worked out from the bill references in your vouchers."} Ages count from the bill date.</p>`;
  view.querySelectorAll("[data-p]").forEach((b) => b.onclick = () => {
    const el = document.getElementById("pb" + b.dataset.p); el.hidden = !el.hidden;
    b.setAttribute("aria-expanded", String(!el.hidden)); b.querySelector(".chev").classList.toggle("up", !el.hidden);
  });
}

async function vStock(q = "") {
  setTitle(false);
  const d = await api(cpath("stock", { q }));
  if (!$("#ssearch")) {
    view.innerHTML = `<input class="search" id="ssearch" type="search" placeholder="Search items" aria-label="Search stock items" value="${h(q)}"><div id="slist"></div>`;
    $("#ssearch").oninput = (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => vStock(e.target.value).catch(fail), 200); };
  }
  $("#slist").innerHTML = `<section class="page"><div class="hero" style="grid-template-columns:1fr"><div class="label">Closing stock value</div><div class="big">${rupees(d.total)}</div><div class="label">${d.items.length} items</div></div></section>
    <section class="page">${d.items.map((i) => `<a class="row" href="#/item/${enc(i.name)}"><div class="main"><div class="name">${h(i.name)}</div>
      <div class="meta">${qty(i.closing_qty, i.unit)}${i.closing_rate ? ` at ₹${nf2.format(i.closing_rate)}` : ""}</div></div><div class="end">${money(i.closing_value)}</div></a>`).join("")
      || '<div class="empty">No stock item matches that name.</div>'}</section>`;
}

async function vItem(name) {
  setTitle(true);
  const d = await api(cpath("stock_item", { name, ...periodParams() }));
  const I = d.item;
  view.innerHTML = `
    <div class="crumbs">${h(I.parent || "Stock")}</div>
    <h1 class="title">${h(I.name)}</h1>
    ${periodBar(d.from, d.to)}
    <section class="page"><div class="totals">
      <div><div class="label">In hand now</div><span class="amt">${qty(I.closing_qty, I.unit)}</span></div>
      <div><div class="label">Value</div>${money(I.closing_value)}</div>
      <div><div class="label">Came in</div><span class="amt">${qty(d.inward, I.unit)}</span></div>
      <div><div class="label">Went out</div><span class="amt">${qty(d.outward, I.unit)}</span></div>
    </div></section>
    <section class="page"><div class="block-title">Movements</div>
      ${d.moves.map((m) => `<a class="row" href="#/voucher/${m.id}"><div class="main"><div class="name">${h(m.party || m.vtype)}</div>
        <div class="meta">${fdate(m.date)}, ${h(m.vtype)} ${h(m.number)}${m.rate ? `, ₹${nf2.format(m.rate)}` : ""}</div></div>
        <div class="end"><span class="amt ${m.qty < 0 ? "cr" : ""}">${m.qty > 0 ? "+" : "−"}${qty(Math.abs(m.qty), I.unit)}</span></div></a>`).join("")
        || '<div class="empty">No movement in this period.</div>'}
    </section>`;
  wirePeriod(d.from, d.to);
}

function vReports() {
  setTitle(false);
  const c = S.companies.find((x) => x.id === S.cid);
  view.innerHTML = `<section class="page">
    <a class="row" href="#/vouchers"><div class="main"><div class="name">Vouchers</div><div class="meta">Search and open any voucher</div></div><span class="chev"></span></a>
    <a class="row" href="#/daybook"><div class="main"><div class="name">Day Book</div><div class="meta">Every voucher by date</div></div><span class="chev"></span></a>
    <a class="row" href="#/pl"><div class="main"><div class="name">Profit &amp; Loss</div><div class="meta">Sales, purchases, expenses and profit</div></div><span class="chev"></span></a>
    <a class="row" href="#/gst"><div class="main"><div class="name">GST summary</div><div class="meta">Output tax, input credit and net payable by month</div></div><span class="chev"></span></a>
    <a class="row" href="#/groups"><div class="main"><div class="name">Group summary</div><div class="meta">Balances by Tally group, like the Balance Sheet</div></div><span class="chev"></span></a>
    <a class="row" href="#/dues/receivable"><div class="main"><div class="name">Outstanding</div><div class="meta">Bill-wise dues with ageing</div></div><span class="chev"></span></a>
    <a class="row" href="#/stock"><div class="main"><div class="name">Stock summary</div><div class="meta">Quantity and value of every item</div></div><span class="chev"></span></a>
  </section>
  ${c ? `<section class="page"><div class="block-title">Sync</div><div class="info">
    <div>Data from ${fdate(c.from_date)} to ${fdate(c.to_date)}</div><div>${c.ledgers} ledgers, ${c.vouchers} vouchers</div>
    <div>Last change synced ${ago(c.last_sync)}. Tally last checked ${ago(c.last_seen)}.</div>
    <div>App version ${APP_VERSION}</div></div>
    <a class="row" href="#/check"><div class="main"><div class="name">Sync check</div><div class="meta">${c.unbalanced ? `<span class="od">${c.unbalanced} vouchers didn't add up</span>` : "Every voucher added up"}. Vouchers by type.</div></div><span class="chev"></span></a></section>` : ""}
  <section class="page">
    <a class="row" href="#/settings"><div class="main"><div class="name">Settings</div><div class="meta">Change password, delete old data${S.companies.length > 1 ? ", companies" : ""}</div></div><span class="chev"></span></a>
    <div class="actions" style="padding-top:12px">
    <button class="btn" id="theme">Switch light/dark</button><button class="btn" id="logout">Log out</button></div></section>`;
  $("#logout").onclick = async () => { await fetch("/api/logout"); location.hash = "#/"; showLogin(); };
  $("#theme").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
  };
}

async function vGST() {
  setTitle(true);
  const d = await api(cpath("gst", periodParams()));
  const heads = ["IGST", "CGST", "SGST", "Cess"];
  const used = d.total ? heads.filter((k) => Math.abs(d.total.output[k]) > 0.005 || Math.abs(d.total.input[k]) > 0.005) : [];
  const mname = (m) => { const [y, mm] = m.split("-"); return `${MON[+mm - 1]} ${y}`; };
  const block = (title, x, open) => `<section class="page">
      <div class="block-title">${title}</div>
      <div class="gst-net"><div><div class="label">${x.net >= 0 ? "Net GST payable" : "Credit carried forward"}</div><div class="big ${x.net >= 0 ? "owe" : ""}">${rupees(x.net)}</div></div></div>
      <div class="gst-grid"><div></div><div class="label">Output</div><div class="label">Input</div>
        ${used.map((k) => `<div>${k}</div>${money(x.output[k])}${money(x.input[k])}`).join("")}
        <div><b>Total</b></div><b>${money(x.output_total)}</b><b>${money(x.input_total)}</b></div>
      ${x.sales !== undefined ? `<div class="note">Sales ${rupees(x.sales, false)}, purchases ${rupees(x.purchase, false)} before tax</div>` : ""}
    </section>`;
  view.innerHTML = `<h1 class="title">GST summary</h1>${periodBar(d.from, d.to)}
    ${!d.total ? '<div class="empty">No GST ledgers found under Duties &amp; Taxes.</div>' :
      block("Whole period", d.total) + d.months.map((m) => block(mname(m.month), m)).join("") +
      `<p class="note" style="border:0">Worked out from your vouchers, leaving out GST payments to the government and set-off entries. It's a quick check only. File your returns from Tally or the GST portal.<br>Counted: ${d.ledgers.map((l) => `${h(l.name)} (${l.side})`).join(", ")}.</p>`}`;
  wirePeriod(d.from, d.to);
}

function voucherRows(rows, narr) {
  let last = "";
  return rows.map((v) => {
    const head = v.date !== last ? `<div class="block-title" style="border-top:1px solid var(--rule)">${fdate(v.date)}</div>` : "";
    last = v.date;
    return head + `<a class="row" href="#/voucher/${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}</div>
      <div class="meta">${h(v.vtype)} ${h(v.number)}${narr && v.narration ? `, ${h(v.narration.replace(/\s+/g, " ").slice(0, 60))}` : ""}</div></div>
      <div class="end">${money(v.amount)}</div><span class="chev"></span></a>`;
  }).join("");
}

/* fills `el` with a voucher list from `what`, 200 at a time, with a Load more button */
async function pagedVouchers(el, what, params, first, emptyMsg) {
  let rows = first.vouchers.slice(), total = first.total;
  const draw = () => {
    el.innerHTML = (rows.length ? `<div class="count">${total === rows.length ? `${total} voucher${total === 1 ? "" : "s"}` : `Showing ${rows.length} of ${total} vouchers`}</div>` : "") +
      (voucherRows(rows, what === "vouchers") || `<div class="empty">${emptyMsg}</div>`) +
      (rows.length < total ? `<button class="row more" id="more">Load ${Math.min(200, total - rows.length)} more</button>` : "");
    const mb = $("#more", el);
    if (mb) mb.onclick = async () => {
      mb.disabled = true; mb.textContent = "Loading";
      try {
        const d = await api(cpath(what, { ...params, offset: rows.length }));
        rows = rows.concat(d.vouchers); total = d.total; draw();
      } catch (e) { mb.disabled = false; mb.textContent = "Couldn't load. Tap to try again"; }
    };
  };
  draw();
}

async function vDaybook(type) {
  setTitle(true);
  if (type !== undefined) S.dayType = type;
  const params = { ...periodParams(), type: S.dayType };
  const d = await api(cpath("daybook", params));
  view.innerHTML = `<h1 class="title">Day Book</h1>${periodBar(d.from, d.to)}
    <div class="toolbar"><button class="chip ${!S.dayType ? "on" : ""}" data-t="">All</button>${d.types.map((t) => `<button class="chip ${t === S.dayType ? "on" : ""}" data-t="${h(t)}">${h(t)}</button>`).join("")}</div>
    <section class="page" id="dblist"></section>`;
  pagedVouchers($("#dblist"), "daybook", params, d, "No vouchers in this period.");
  wirePeriod(d.from, d.to);
  view.querySelectorAll("[data-t]").forEach((b) => b.onclick = () => vDaybook(b.dataset.t).catch(fail));
}

let vSearchT;
async function vVouchers() {
  setTitle(false);
  if (S.vq === undefined) S.vq = "";
  const params = { q: S.vq, type: S.vtype || "", ...periodParams() };
  const d = await api(cpath("vouchers", params));
  if (!$("#vsearch")) {
    view.innerHTML = `<input class="search" id="vsearch" type="search" inputmode="search" placeholder="Party, voucher no., amount or narration" aria-label="Search vouchers" value="${h(S.vq)}">
      <div id="vperiod"></div><div class="toolbar" id="vtypes"></div><section class="page" id="vlist"></section>`;
    $("#vsearch").oninput = (e) => { clearTimeout(vSearchT); vSearchT = setTimeout(() => { S.vq = e.target.value; vVouchers().catch(fail); }, 250); };
  }
  $("#vperiod").innerHTML = periodBar(d.from, d.to);
  $("#vtypes").innerHTML = `<button class="chip ${!S.vtype ? "on" : ""}" data-t="">All</button>` + d.types.map((t) => `<button class="chip ${t === S.vtype ? "on" : ""}" data-t="${h(t)}">${h(t)}</button>`).join("");
  pagedVouchers($("#vlist"), "vouchers", params, d,
    S.vq ? "No voucher matches that search in this period. Try All dates." : "No vouchers in this period.");
  wirePeriod(d.from, d.to);
  $("#vtypes").querySelectorAll("[data-t]").forEach((b) => b.onclick = () => { S.vtype = b.dataset.t; vVouchers().catch(fail); });
}

async function vVoucher(id) {
  setTitle(true);
  const d = await api(`/api/c/${S.cid}/voucher/${id}`);
  const V = d.voucher, P = d.party;
  const order = { party: 0, sales: 1, other: 2, tax: 3 };
  const lines = d.lines.slice().sort((a, b) => order[a.kind] - order[b.kind]);
  const taxable = d.items.reduce((a, i) => a + i.amount, 0);
  const tax = d.lines.filter((l) => l.kind === "tax").reduce((a, l) => a + Math.abs(l.amount), 0);
  const gstin = V.party_gstin || P?.gstin;
  view.innerHTML = `
    <section class="page vhead">
      <div class="vtype">${h(V.vtype)}</div>
      <div class="vno">No. ${h(V.number)}</div>
      <div class="meta">${fdate(V.date)}${V.reference ? `, ref. ${h(V.reference)}` : ""}</div>
      ${V.party ? `<a class="vparty" href="#/ledger/${enc(V.party)}"><div class="name">${h(V.party)}</div>${gstin ? `<div class="meta">GSTIN ${h(gstin)}</div>` : ""}</a>` : ""}
      <div class="vtotal">${rupees(V.amount)}</div>
      <div class="actions" style="padding:12px 0 0"><button class="btn primary" id="vpdf">${ICON.share}Share PDF</button>
        <a class="btn" href="/api/c/${S.cid}/voucher_pdf/${id}" target="_blank" rel="noopener">${ICON.print}View PDF</a>
        ${V.party ? `<a class="btn" href="#/ledger/${enc(V.party)}">Party ledger</a>` : ""}</div>
    </section>
    ${d.items.length ? `<section class="page"><div class="block-title"><span>Items</span><span>Amount</span></div>
      ${d.items.map((i) => `<a class="row" href="#/item/${enc(i.item)}"><div class="main"><div class="name">${h(i.item)}</div>
        <div class="meta">${qty(Math.abs(i.qty), i.unit)}${i.rate ? ` at ₹${nf2.format(i.rate)}` : ""}</div></div><div class="end">${money(i.amount)}</div></a>`).join("")}
      ${tax > 0.005 ? `<div class="sumline"><span>Taxable value</span>${money(taxable)}</div><div class="sumline"><span>GST</span>${money(tax)}</div>` : ""}
      </section>` : ""}
    <section class="page"><div class="block-title"><span>Accounts</span><span>Dr / Cr</span></div>
      ${lines.map((l) => `<a class="row" href="#/ledger/${enc(l.ledger)}"><div class="main"><div class="name">${h(l.ledger)}</div>${l.kind === "tax" ? '<div class="meta">GST</div>' : ""}</div><div class="end">${drcr(l.amount)}</div></a>`).join("")}
    </section>
    ${d.bills.length ? `<section class="page"><div class="block-title">Bill references</div>
      ${d.bills.map((b) => { const inner = `<div class="main"><div class="name">${h(b.name || b.btype)}</div><div class="meta">${h(b.btype)}${b.days ? `, ${b.days} days credit` : ""}${b.vid ? ", tap to open the bill" : ""}</div></div><div class="end">${drcr(b.amount)}</div>${b.vid ? '<span class="chev"></span>' : ""}`;
        return b.vid ? `<a class="row" href="#/voucher/${b.vid}">${inner}</a>` : `<div class="row" style="cursor:default">${inner}</div>`; }).join("")}</section>` : ""}
    ${V.narration ? `<section class="page"><div class="block-title">Narration</div><div class="info" style="white-space:pre-line">${h(V.narration)}</div></section>` : ""}
    ${!V.balanced ? '<p class="note warn">This voucher\'s debits and credits did not match when it was synced.</p>' : ""}`;
  $("#vpdf").onclick = () => sharePdf(`/api/c/${S.cid}/voucher_pdf/${id}`, `${V.vtype} ${V.number}`);
}

async function vSales(kind) {
  setTitle(false);
  S.skind = kind || S.skind || "sales";
  const sales = S.skind === "sales";
  const d = await api(cpath("daily", { kind: S.skind, ...periodParams() }));
  const max = Math.max(1, ...d.days.map((x) => x.total));
  let month = "", body = "";
  const mtot = {};
  d.days.forEach((x) => { const m = x.date.slice(0, 7); mtot[m] = mtot[m] || { t: 0, n: 0 }; mtot[m].t += x.total; mtot[m].n += x.bills; });
  for (const x of d.days) {
    const m = x.date.slice(0, 7);
    if (m !== month) {
      month = m; const [yy, mm] = m.split("-");
      body += `<div class="block-title month-head"><span>${MON[+mm - 1]} ${yy}</span><span>${short(mtot[m].t)}, ${mtot[m].n} bills</span></div>`;
    }
    const dt = new Date(x.date + "T00:00:00");
    body += `<a class="row day" href="#/day/${S.skind}/${x.date}"><div class="main">
        <div class="name">${dt.toLocaleDateString("en-IN", { weekday: "short" })}, ${fdate(x.date)}</div>
        <div class="meta">${x.bills} bill${x.bills === 1 ? "" : "s"}${x.returns ? `, returns ${rupees(x.returns, false)}` : ""}</div>
        <div class="daybar"><span style="width:${Math.max(1, (x.total / max) * 100).toFixed(1)}%"></span></div></div>
      <div class="end">${money(x.total)}<div class="meta">${rupees(x.net, false)} before tax</div></div><span class="chev"></span></a>`;
  }
  view.innerHTML = `
    <div class="toolbar" role="group" aria-label="Sales or purchases">
      <a class="chip ${sales ? "on" : ""}" href="#/sales" aria-pressed="${sales}">Sales</a>
      <a class="chip ${!sales ? "on" : ""}" href="#/sales/purchase" aria-pressed="${!sales}">Purchases</a></div>
    ${periodBar(d.from, d.to)}
    <section class="page">
      <div class="hero"><div><div class="label">${sales ? "Sales" : "Purchases"} with tax</div><div class="big">${short(d.total)}</div></div>
        <div><div class="label">Before tax</div><div class="big" style="font-size:22px">${short(d.net)}</div></div></div>
      <div class="tiles">
        <div class="tile"><div class="label">Bills</div><div class="val">${nf0.format(d.bills)}</div></div>
        <div class="tile"><div class="label">Average a day</div><div class="val">${short(d.avg)}</div></div>
        <div class="tile"><div class="label">${sales ? "Returns" : "Returned"}</div><div class="val">${short(d.returns)}</div></div>
      </div>
      ${d.best && d.best.total ? `<div class="note">Best day: <a href="#/day/${S.skind}/${d.best.date}">${fdate(d.best.date)}</a>, ${rupees(d.best.total, false)}</div>` : ""}
    </section>
    <section class="page">${body || `<div class="empty">No ${sales ? "sales" : "purchases"} in this period.</div>`}</section>`;
  wirePeriod(d.from, d.to);
}

async function vDay(kind, day) {
  setTitle(true);
  const sales = kind !== "purchase";
  const base = sales ? "Sales" : "Purchase", ret = sales ? "Credit Note" : "Debit Note";
  const p = { from: day, to: day };
  const [a, r] = await Promise.all([api(cpath("vouchers", { ...p, type: base })), api(cpath("vouchers", { ...p, type: ret }))]);
  const dt = new Date(day + "T00:00:00");
  const tot = a.vouchers.reduce((s, v) => s + v.amount, 0);
  view.innerHTML = `<div class="crumbs"><a href="#/sales${sales ? "" : "/purchase"}">${sales ? "Sales" : "Purchases"} by day</a></div>
    <h1 class="title">${dt.toLocaleDateString("en-IN", { weekday: "long" })}, ${fdate(day)}</h1>
    <p class="subtitle">${a.total} bill${a.total === 1 ? "" : "s"}${a.total <= 200 ? `, ${rupees(tot)}` : ""}</p>
    <section class="page" id="dlist"></section>
    ${r.total ? `<h2 class="title" style="font-size:18px">${sales ? "Returns (credit notes)" : "Returns (debit notes)"}</h2><section class="page" id="rlist"></section>` : ""}`;
  pagedVouchers($("#dlist"), "vouchers", { ...p, type: base }, a, `No ${sales ? "sales" : "purchases"} on this day.`);
  if (r.total) pagedVouchers($("#rlist"), "vouchers", { ...p, type: ret }, r, "");
}

async function vCheck() {
  setTitle(true);
  const d = await api(cpath("check"));
  view.innerHTML = `<h1 class="title">Sync check</h1>
    <p class="subtitle">${d.unbalanced ? `${d.unbalanced} vouchers had debits and credits that didn't match when they were synced. Open one to compare it with Tally, and report the voucher types below if they look wrong.` : "Every synced voucher's debits and credits match."}</p>
    ${d.groups.map((g) => `<section class="page"><div class="block-title"><span>${h(g.vtype)}</span><span>${g.count} of ${g.of}</span></div>
      ${g.examples.map((v) => `<a class="row" href="#/voucher/${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}</div>
        <div class="meta">${fdate(v.date)}, No. ${h(v.number)}</div></div><div class="end"><span class="meta">off by</span> ${money(Math.abs(v.imbalance))}</div><span class="chev"></span></a>`).join("")}
      </section>`).join("")}
    <section class="page"><div class="block-title"><span>Vouchers synced by month</span><span>All / Sales</span></div>
      ${d.months.map((m) => { const [yy, mm] = m.m.split("-"); return `<a class="row" href="#/vouchers" data-month="${m.m}"><div class="main name">${MON[+mm - 1]} ${yy}</div><div class="end">${nf0.format(m.n)} / ${nf0.format(m.sales)}</div></a>`; }).join("") || '<div class="empty">No vouchers synced yet.</div>'}
    </section>
    <section class="page"><div class="block-title"><span>Vouchers synced by type</span><span>Count</span></div>
      ${d.types.map((t) => `<div class="row" style="cursor:default"><div class="main name">${h(t.vtype)}</div><div class="end">${nf0.format(t.n)}</div></div>`).join("")}
    </section>`;
}

async function vSettings() {
  setTitle(true);
  await loadCompanies();
  const range = (c) => c.first_vch ? `${fdate(c.first_vch)} to ${fdate(c.last_vch)}` : "no vouchers yet";
  view.innerHTML = `<h1 class="title">Settings</h1>
    <section class="page"><div class="block-title">Change app password</div>
      <form id="pwf" class="form">
        <label>Current password<input type="password" id="pw0" autocomplete="current-password" required></label>
        <label>New password<input type="password" id="pw1" autocomplete="new-password" minlength="8" required></label>
        <label>New password again<input type="password" id="pw2" autocomplete="new-password" minlength="8" required></label>
        <button class="btn primary" type="submit">Change password</button>
        <div class="msg" id="pwmsg" role="status"></div>
        <p class="hint">Other phones will need to log in again with the new password. If you ever forget it, delete <code>app_password.json</code> from the Bahi data folder on Unraid; the password from the container settings then works again.</p>
      </form></section>
    ${S.companies.map((c) => `<section class="page" data-cid="${c.id}">
      <div class="block-title"><span>${h(c.name)}</span>${c.id === S.cid ? "<span>showing now</span>" : `<button class="chip" data-use="${c.id}">Show this</button>`}</div>
      <div class="info"><div>Vouchers: ${nf0.format(c.vouchers)}, ${range(c)}</div>
        ${c.keep_from ? `<div>Keeping vouchers from ${fdate(c.keep_from)}</div>` : ""}</div>
      <form class="form" data-purge="${c.id}">
        <label>Delete vouchers before<input type="date" required value="${c.first_vch && c.first_vch > (c.keep_from || "") ? fyStart(c.last_vch) : ""}"></label>
        <button class="btn" type="submit">Delete older vouchers</button>
        <p class="hint">Removes them from Bahi only, never from Tally. Later syncs won't bring them back.</p>
      </form>
      <div class="actions"><button class="btn danger" data-del="${c.id}">Delete all of this company's data</button></div>
      <p class="hint" style="padding:0 14px 14px">If the company is still open in Tally, the next sync copies it again from scratch.</p>
    </section>`).join("")}`;
  $("#pwf").onsubmit = async (e) => {
    e.preventDefault();
    const msg = $("#pwmsg");
    if ($("#pw1").value !== $("#pw2").value) { msg.textContent = "The two new passwords don't match."; return; }
    const r = await fetch("/api/password", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current: $("#pw0").value, new: $("#pw1").value }) });
    const j = await r.json().catch(() => ({}));
    msg.textContent = r.ok ? "Password changed." : (j.error || "Couldn't change the password.");
    if (r.ok) $("#pwf").reset();
  };
  view.querySelectorAll("[data-use]").forEach((b) => b.onclick = () => {
    S.cid = Number(b.dataset.use); try { localStorage.setItem("cid", S.cid); } catch (e) {}
    renderCover(); vSettings().catch(fail);
  });
  view.querySelectorAll("[data-purge]").forEach((f) => f.onsubmit = async (e) => {
    e.preventDefault();
    const day = f.querySelector("input").value;
    if (!day || !confirm(`Delete every voucher before ${fdate(day)} from Bahi? Tally is not affected.`)) return;
    const r = await fetch(`/api/c/${f.dataset.purge}/purge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ before: day }) });
    const j = await r.json().catch(() => ({}));
    toast(r.ok ? `Deleted ${nf0.format(j.deleted)} vouchers.` : (j.error || "Couldn't delete."));
    vSettings().catch(fail);
  });
  view.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
    const c = S.companies.find((x) => x.id === Number(b.dataset.del));
    if (!confirm(`Delete everything Bahi has for ${c.name}? Tally is not affected.`)) return;
    await fetch(`/api/c/${c.id}/delete`, { method: "POST" });
    toast("Deleted."); S.cid = null; await loadCompanies(); location.hash = "#/reports";
  });
}

function fyStart(day) {
  const d = new Date((day || iso(new Date())) + "T00:00:00");
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${y}-04-01`;
}

async function vPL() {
  setTitle(true);
  const d = await api(cpath("pl", periodParams()));
  const s = d.sections;
  const sec = (key, label, sign) => {
    const x = s[key];
    if (!x.ledgers.length) return "";
    const id = "pl-" + key.replace(/\W/g, "");
    return `<button class="pl-line" aria-expanded="false" data-x="${id}"><span>${sign < 0 ? "Less: " : ""}${label}</span>${money(x.total)}</button>
      <div id="${id}" hidden>${x.ledgers.map((l) => `<a class="pl-line sub" style="cursor:pointer;text-decoration:none" href="#/ledger/${enc(l.name)}"><span>${h(l.name)}</span>${money(l.amount)}</a>`).join("")}</div>`;
  };
  const res = (label, n) => `<div class="pl-line result"><span>${n < 0 ? label.replace("profit", "loss") : label}</span><span class="amt ${n < 0 ? "loss" : ""}">${rupees(n)}</span></div>`;
  view.innerHTML = `<h1 class="title">Profit &amp; Loss</h1>${periodBar(d.from, d.to)}
    <section class="page">
      ${sec("Sales Accounts", "Sales", 1)}${sec("Direct Incomes", "Direct incomes", 1)}
      <div class="pl-line" style="cursor:default"><span>Closing stock</span>${money(d.closing_stock)}</div>
      <div class="pl-line" style="cursor:default"><span>Less: Opening stock</span>${money(d.opening_stock)}</div>
      ${sec("Purchase Accounts", "Purchases", -1)}${sec("Direct Expenses", "Direct expenses", -1)}
      ${res("Gross profit", d.gross_profit)}
      ${sec("Indirect Incomes", "Indirect incomes", 1)}${sec("Indirect Expenses", "Indirect expenses", -1)}
      ${res("Net profit", d.net_profit)}
      <div class="note">Tap a line to see its ledgers. Stock figures are Tally's current opening and closing stock, so profit matches Tally best when the period is the whole year.</div>
    </section>`;
  wirePeriod(d.from, d.to);
  view.querySelectorAll("[data-x]").forEach((b) => b.onclick = () => {
    const el = document.getElementById(b.dataset.x); el.hidden = !el.hidden; b.setAttribute("aria-expanded", String(!el.hidden));
  });
}

/* ---------------------------------------------------------------- login, errors, router */
function showLogin(msg = "") {
  $("#tabs").hidden = true; $("#status").innerHTML = ""; $("#company").textContent = "Bahi"; $("#back").hidden = true;
  view.innerHTML = `<div class="login"><form id="lf"><h1>Open your books</h1><p>Enter the app password you set on the server.</p>
    <input type="password" id="pw" autocomplete="current-password" aria-label="App password" placeholder="App password" required>
    <button class="btn primary" type="submit">Open</button><div class="err" role="alert">${h(msg)}</div></form></div>`;
  $("#pw").focus();
  $("#lf").onsubmit = async (e) => {
    e.preventDefault();
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("#pw").value }) });
    if (r.ok) { $("#tabs").hidden = false; start(); } else showLogin((await r.json().catch(() => ({}))).error || "Could not log in.");
  };
}
function fail(e) {
  if (e && e.login) return showLogin();
  view.innerHTML = `<div class="empty">${e && e.message === "offline" ? "Can't reach the server and nothing is saved on this phone for this screen yet. Check your internet connection." : h(e?.message || "Something went wrong.")}<br><br><button class="btn" onclick="route()">Try again</button></div>`;
}
let toastT;
function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.setAttribute("role", "status"); t.style.cssText = "position:fixed;left:50%;bottom:84px;transform:translateX(-50%);background:var(--ink);color:var(--paper);padding:10px 14px;border-radius:8px;font-size:14px;z-index:9;max-width:90vw"; document.body.appendChild(t); }
  t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 2800);
}

async function route() {
  offlineSeen = false;
  const [path, qs] = location.hash.slice(1).split("?");
  const parts = (path || "/").split("/").slice(1).map(decodeURIComponent);
  const params = new URLSearchParams(qs || "");
  if (!S.cid) {
    view.innerHTML = '<div class="empty">No data yet. Run Setup on the Tally PC to send your first sync.</div>';
    return;
  }
  loading();
  try {
    switch (parts[0]) {
      case "": case undefined: await vHome(); break;
      case "parties": await vParties(); break;
      case "ledger": await vLedger(parts[1]); break;
      case "group": await vGroup(parts[1]); break;
      case "groups": await vGroup(""); break;
      case "dues": await vDues(parts[1]); break;
      case "stock": await vStock(); break;
      case "item": await vItem(parts[1]); break;
      case "reports": vReports(); break;
      case "daybook": await vDaybook(params.get("type") ?? ""); break;
      case "voucher": await vVoucher(parts[1]); break;
      case "pl": await vPL(); break;
      case "gst": await vGST(); break;
      case "check": await vCheck(); break;
      case "settings": await vSettings(); break;
      case "sales": await vSales(parts[1] === "purchase" ? "purchase" : "sales"); break;
      case "day": await vDay(parts[1], parts[2]); break;
      case "vouchers": await vVouchers(); break;
      default: await vHome();
    }
    $("#offline").hidden = !offlineSeen;
    window.scrollTo(0, 0);
  } catch (e) { fail(e); }
}

function pickCompany() {
  if (S.companies.length < 2) return;
  const dlg = $("#sheet");
  dlg.innerHTML = `<h3>Choose company</h3>${S.companies.map((c) => `<button class="row" data-id="${c.id}"><div class="main name">${h(c.name)}</div>${c.id === S.cid ? "<span>✓</span>" : ""}</button>`).join("")}
    <div class="actions" style="padding-top:12px"><button class="btn" id="dclose">Close</button></div>`;
  dlg.querySelectorAll("[data-id]").forEach((b) => b.onclick = () => {
    S.cid = Number(b.dataset.id); try { localStorage.setItem("cid", S.cid); } catch (e) {}
    dlg.close(); renderCover(); route();
  });
  $("#dclose").onclick = () => dlg.close();
  dlg.showModal();
}

async function start() {
  try { await loadCompanies(); } catch (e) { return fail(e); }
  $("#tabs").hidden = false;
  route();
}

try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
window.addEventListener("hashchange", route);
$("#back").onclick = () => history.length > 1 ? history.back() : (location.hash = "#/");
$("#refresh").onclick = async () => { try { await loadCompanies(); } catch (e) {} route(); };
$("#company").onclick = pickCompany;
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadCompanies().then(renderCover).catch(() => {}); });
if ("serviceWorker" in navigator) {
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register("/sw.js").then((r) => r.update()).catch(() => {});
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (hadController && !reloaded) { reloaded = true; location.reload(); } // a new version took over
  });
}
start();
