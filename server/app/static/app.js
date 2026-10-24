/* Bahi — phone app for Tally data synced to your server */
"use strict";
const APP_VERSION = "3.2.0";

const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const S = {
  companies: [], cid: null, period: null, // period: {key, from, to} or null = full synced year
  sync: { mode: "auto", every: 10 }, dueKind: "receivable", dayType: "", cache: {}, me: { owner: true, perms: [], name: "" }, approvals: 0,
};
const can = (p) => S.me.owner || S.me.perms.includes(p);
const canLedgers = () => can("ledgers") || can("parties");
const ENTRY = { receipt: ["Receipt", "e_receipt"], payment: ["Payment", "e_payment"], order: ["Sales order", "e_order"] };
const entryKinds = () => Object.keys(ENTRY).filter((k) => can(ENTRY[k][1]));
function applyTabs() {
  const show = { home: true, sales: can("sales"), parties: canLedgers(), vouchers: can("vouchers"), dues: can("dues"), reports: true };
  document.querySelectorAll("#tabs a[data-tab]").forEach((a) => a.hidden = !show[a.dataset.tab]);
  document.querySelectorAll("#tabs a[data-need]").forEach((a) => a.hidden = !a.dataset.need.split(" ").some((p) => p === "owner" ? S.me.owner : can(p)));
}
function entryBar() {
  const ks = entryKinds();
  if (!ks.length && !S.approvals) return "";
  return `<section class="page entrybar">
    ${S.me.owner && S.approvals ? `<a class="row" href="#/entries"><div class="main"><div class="name od">${S.approvals} ${S.approvals === 1 ? "entry waits" : "entries wait"} for your approval</div><div class="meta">Made by staff on their phones</div></div><span class="chev"></span></a>` : ""}
    ${ks.length ? `<div class="actions">${ks.map((k) => `<a class="btn" href="#/new/${k}">+ ${ENTRY[k][0]}</a>`).join("")}<a class="btn" href="#/entries">Entries</a></div>` : ""}</section>`;
}
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
const XL = '<svg viewBox="0 0 24 24"><path d="M5 3h10l4 4v14H5z M14 3v5h5 M8 12l5 6 M13 12l-5 6"/></svg>';
function excelBtn(what, params = {}) {
  const u = cpath("export", { what, ...params });
  return `<a class="btn" href="${u}" download>${XL}Excel</a>`;
}
function badge(st) { return st ? `<span class="badge">${st === "cancelled" ? "Cancelled" : "Optional"}</span>` : ""; }
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
/* ---------------------------------------------------------------- offline copy
   Everything the app shows, downloaded in bulk into the same saved copy the service worker serves offline. */
function dataKey(u) {
  const url = new URL(u, location.origin);
  const p = [...url.searchParams.entries()].filter(([, v]) => v !== "").sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  return url.origin + url.pathname + (p.length ? "?" + new URLSearchParams(p).toString() : "");
}
function pathFor(cid, what, params = {}, arg) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, v);
  const s = q.toString();
  return `/api/c/${cid}/${what}${arg ? "/" + arg : ""}${s ? "?" + s : ""}`;
}
const OFF = { running: false };
async function downloadOffline(onProgress = () => {}) {
  if (OFF.running || !("caches" in window)) return null;
  OFF.running = true;
  try {
    try { if (navigator.storage && navigator.storage.persist) await navigator.storage.persist(); } catch (e) {}
    const cache = await caches.open("bahi-data-v1");
    let done = 0, total = 0;
    const save = (path, data) => cache.put(dataKey(path), new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } }));
    const uniq = (list) => [...new Map(list.map((p) => [JSON.stringify(p), p])).values()];
    const periods = uniq([periodParams(), {}]);
    const run = async (cid, reqs) => {
      total += reqs.length; onProgress(done, total);
      const results = [];
      for (let i = 0; i < reqs.length; i += 60) {
        const part = reqs.slice(i, i + 60);
        const r = await fetch(pathFor(cid, "bulk"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ requests: part }) });
        if (!r.ok) throw new Error(r.status === 401 ? "login" : "Server error " + r.status);
        const j = await r.json();
        await Promise.all(part.map((q, k) => j.results[k] ? save(pathFor(cid, q.what, q.params, q.arg), j.results[k]) : null));
        part.forEach((q, k) => results.push(j.results[k]));
        done += part.length; onProgress(done, total);
      }
      return results;
    };
    await api("/api/me"); await api("/api/companies");
    for (const c of S.companies) {
      const core = [];
      const add = (what, list) => list.forEach((params) => core.push({ what, params }));
      add("dashboard", periods);
      add("ledgers", ["name", "balance", "recent"].map((sort) => ({ sort })));
      ["sales", "purchase"].forEach((kind) => add("daily", periods.map((p) => ({ kind, ...p }))));
      add("outstanding", [{ kind: "receivable" }, { kind: "payable" }]);
      add("stock", periods); add("godowns", [{}]); add("gst", periods); add("pl", periods); add("bs", [{}]);
      add("cashbank", periods); add("collections", [{}]); add("check", [{}]); add("group", [{}]);
      ["sales", "purchase"].forEach((kind) => add("a_parties", periods.map((p) => ({ kind, ...p }))));
      add("a_items", periods); add("a_years", [{}]); add("a_slow", [30, 60, 90, 180].map((days) => ({ days })));
      add("daybook", periods.map((p) => ({ type: "", ...p }))); add("vouchers", periods);
      const yearAgo = iso(new Date(Date.now() - 365 * 864e5));
      core.push({ what: "voucher_ids", params: { from: yearAgo, to: iso(new Date()) } });
      const res = await run(c.id, core);
      const ledgers = (res[1] && res[1].ledgers || []).map((l) => l.name);
      const items = (res.find((x, i) => core[i].what === "stock") || { items: [] }).items.map((x) => x.name);
      const ids = (res[res.length - 1] || { ids: [] }).ids;
      const groups = ((res.find((x, i) => core[i].what === "group") || {}).groups || []).map((g) => g.name);
      const more = [];
      const lper = uniq([ledgerParams(), {}]);
      ledgers.forEach((name) => lper.forEach((p) => more.push({ what: "ledger", params: { name, ...p } })));
      items.forEach((name) => periods.forEach((p) => more.push({ what: "stock_item", params: { name, ...p } })));
      groups.forEach((name) => more.push({ what: "group", params: { name } }));
      ids.forEach((id) => more.push({ what: "voucher", arg: id, params: {} }));
      await run(c.id, more);
    }
    const info = { at: Date.now(), items: done };
    try { localStorage.setItem("offline", JSON.stringify(info)); } catch (e) {}
    return info;
  } finally { OFF.running = false; }
}
function androidSection() {
  if (!window.BahiAndroid) return "";
  return `<section class="page"><div class="block-title">Android app <span>version ${h(BahiAndroid.version())}</span></div>
    <div class="info"><div>Server: ${h(BahiAndroid.server())}</div></div>
    <div class="actions"><button class="btn" onclick="BahiAndroid.changeServer()">Change server address</button><button class="btn" onclick="BahiAndroid.checkUpdate()">Check for app update</button></div></section>`;
}
function offlineSection() {
  const el = $("#offsec");
  if (!el) return;
  if (!("caches" in window)) { el.innerHTML = '<div class="block-title">Offline copy</div><div class="info">This browser can\'t keep an offline copy.</div>'; return; }
  const o = offlineInfo();
  el.innerHTML = `<div class="block-title">Offline copy <span>${o ? `saved ${ago(o.at / 1000)}` : "not saved yet"}</span></div>
    <div class="info"><div>Keeps everything on this phone to view without internet: every ledger (this month and this year), stock, dues, reports and the last 12 months' vouchers.${o ? ` ${nf0.format(o.items)} screens saved.` : ""}</div><div id="offsize"></div></div>
    <label style="display:flex;gap:8px;align-items:center;padding:0 0 8px"><input type="checkbox" id="offauto" ${offlineAuto() ? "checked" : ""}> Update it by itself every 6 hours while the app is open</label>
    <div class="actions"><button class="btn" id="offnow">${OFF.running ? "Saving" : "Save offline copy now"}</button></div><p class="meta" id="offmsg" role="status"></p>`;
  if (navigator.storage && navigator.storage.estimate) navigator.storage.estimate().then((e) => { const x = $("#offsize"); if (x && e.usage) x.textContent = `Space used on this phone: ${(e.usage / 1048576).toFixed(1)} MB`; }).catch(() => {});
  $("#offauto").onchange = (e) => { try { localStorage.setItem("offline_auto", e.target.checked ? "1" : "0"); } catch (err) {} };
  $("#offnow").onclick = async () => {
    const b = $("#offnow"); b.disabled = true; b.textContent = "Saving";
    try {
      await downloadOffline((d, t) => { const m = $("#offmsg"); if (m) m.textContent = `Saving ${nf0.format(d)} of ${nf0.format(t)}`; });
      toast("Offline copy saved."); offlineSection();
    } catch (e) { const m = $("#offmsg"); if (m) m.textContent = e.message === "login" ? "Log in again, then try." : "Couldn't finish: " + e.message; b.disabled = false; b.textContent = "Save offline copy now"; }
  };
}
function offlineInfo() { try { return JSON.parse(localStorage.getItem("offline") || "null"); } catch (e) { return null; } }
function offlineAuto() { try { return localStorage.getItem("offline_auto") !== "0"; } catch (e) { return true; } }
// keep the offline copy fresh: in the background, at most every 6 hours, when the server can be reached
async function autoOffline() {
  const o = offlineInfo();
  if (!offlineAuto() || !navigator.onLine || (o && Date.now() - o.at < 6 * 3600e3) || !S.companies.length) return;
  try { await downloadOffline(); } catch (e) { /* tried again next time */ }
}

function periodParams() { return S.period ? { from: S.period.from, to: S.period.to } : {}; }

async function loadCompanies() {
  const d = await api("/api/companies");
  S.companies = d.companies;
  S.approvals = d.approvals || 0;
  S.sync = d.sync || { mode: "auto", every: 10 };
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
  if (c.paused || S.sync.mode === "manual") {
    st.innerHTML = `<span class="dot off"></span>${c.paused ? "Sync paused" : "Manual sync"}. Figures as of ${new Date(c.last_sync * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}`;
    return;
  }
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
function periodBar(from, to, slot = "period") {
  const P = slot === "period" ? S.period : ledgerPeriod();
  const key = P ? P.key : "year";
  return `<div class="toolbar" role="group" aria-label="Period">${PERIODS.map(([k, l]) =>
    `<button class="chip ${k === key ? "on" : ""}" data-period="${k}" aria-pressed="${k === key}">${l}</button>`).join("")}</div>
    ${key === "custom" ? `<div class="dates"><input type="date" id="pf" value="${from}" aria-label="From date"> to <input type="date" id="pt" value="${to}" aria-label="To date"> <button class="chip" id="papply">Show</button></div>` :
      `<p class="subtitle">${key === "all" ? "All synced dates" : `${fdate(from)} to ${fdate(to)}`}</p>`}`;
}
function wirePeriod(from, to, slot = "period") {
  const set = (v) => {
    if (slot === "period") { S.period = v; try { localStorage.setItem("period", JSON.stringify(S.period)); } catch (e) {} }
    else S.lperiod = v || { key: "year" };     // a ledger's period lasts until the app is closed
  };
  view.querySelectorAll("[data-period]").forEach((b) => b.onclick = () => {
    const k = b.dataset.period;
    set(k === "year" ? null : k === "custom" ? { key: "custom", from: from < "2001" ? iso(new Date(Date.now() - 30 * 864e5)) : from, to: to > "2098" ? iso(new Date()) : to } : periodFor(k));
    route();
  });
  const ap = $("#papply");
  if (ap) ap.onclick = () => { set({ key: "custom", from: $("#pf").value, to: $("#pt").value }); route(); };
}
/* Ledgers open on this month unless another period was picked on a ledger */
function ledgerPeriod() {
  const p = S.lperiod || periodFor("month");
  return p.key === "year" ? null : p;
}
function ledgerParams() { const p = ledgerPeriod(); return p ? { from: p.from, to: p.to } : {}; }

function loading() { view.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>'; }
function setTitle(back) {
  $("#back").hidden = !back;
  const tab = (location.hash.split("/")[1] || "home").split("?")[0];
  const map = { "": "home", ledger: "parties", group: "parties", item: "reports", daybook: "reports", voucher: "vouchers", pl: "reports", gst: "reports", check: "reports", settings: "reports", analysis: "reports", bs: "reports", cashbook: "reports", collect: "dues", entries: "reports", new: "home", day: "sales", stock: "reports", groups: "reports", godowns: "reports", brs: "reports" };
  const on = map[tab] || tab;
  document.querySelectorAll("#tabs a[data-tab]").forEach((a) => a.classList.toggle("on", a.dataset.tab === on));
  document.querySelectorAll("#tabs a[data-route]").forEach((a) => a.classList.toggle("on", a.dataset.route === tab));
  if (document.querySelector(`#tabs a[data-route="${tab}"]`)) document.querySelectorAll("#tabs a[data-tab]").forEach((a) => a.classList.remove("on"));
}

/* ---------------------------------------------------------------- views */
async function vHome() {
  setTitle(false);
  if (!can("accounts")) return vStaffHome();
  const d = await api(cpath("dashboard", periodParams()));
  const thisMonth = new Date().toISOString().slice(0, 7);
  view.innerHTML = `${entryBar()}
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
  return `<a class="row${v.status ? " void" : ""}" href="#/voucher/${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}${badge(v.status)}</div>
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
  if (window.BahiAndroid) {      // the Android app downloads it and opens the phone's share sheet (WhatsApp, email...)
    BahiAndroid.share(new URL(url, location.origin).href, name.replace(/[^\w .-]+/g, "").slice(0, 80) + ".pdf");
    return;
  }
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
    const od = b.overdue > 0 ? `<span class="od">${b.overdue} days overdue${b.interest > 0.5 ? `, interest ${rupees(b.interest, false)}` : ""}</span>` :
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
  const d = await api(cpath("ledger", { name, ...ledgerParams() }));
  const L = d.ledger, phone = digits(L.mobile || L.phone);
  const co = S.companies.find((c) => c.id === S.cid)?.name || "";
  const isDebtor = d.closing > 0.5 && d.bill_kind === "receivable";
  const overdue = (d.bills || []).filter((b) => b.overdue > 0 && b.amount > 0);
  const waText = isDebtor ? reminderText(L.name, co, d.closing, overdue, d.interest, d.interest_rate) : `Dear ${L.name}, greetings from ${co}.`;
  const pdfUrl = cpath("ledger_pdf", { name, ...ledgerParams() });
  const pending = (d.bills || []).filter((b) => Math.abs(b.amount) > 0.5);
  view.innerHTML = `
    <div class="crumbs"><a href="#/group/${enc(L.parent)}">${h(L.parent)}</a></div>
    <h1 class="title">${h(L.name)}</h1>
    ${periodBar(d.from, d.to, "ledger")}
    ${(d.mismatch || []).filter((i) => i.to >= d.from).length ? `<p class="note od" style="border:0">Some entries in this ledger don't match Tally yet (${d.mismatch.filter((i) => i.to >= d.from).map((i) => `${fdate(i.from)} to ${fdate(i.to)}, ${nf2.format(Math.abs(i.amount))}`).join("; ")}), so the opening shown here is off by that much. Bahi is fetching them again. <a href="#/check">Sync check</a></p>` : ""}
    <section class="page">
      ${L.gstin || L.mobile || L.phone || L.email ? `<div class="info" style="padding-top:12px">${L.gstin ? `<div>GSTIN ${h(L.gstin)}</div>` : ""}${L.mobile || L.phone ? `<div>${h(L.mobile || L.phone)}</div>` : ""}${L.email ? `<div>${h(L.email)}</div>` : ""}</div>` : ""}
      <div class="actions" style="${L.gstin || L.mobile || L.phone || L.email ? "" : "padding-top:12px"}">
        <button class="btn primary" id="sharepdf">${ICON.share}Share PDF</button>
        <a class="btn" href="${pdfUrl}" target="_blank" rel="noopener">${ICON.print}View PDF</a>
        ${excelBtn("ledger", { name, ...ledgerParams() })}
        ${phone ? `<a class="btn wa" href="https://wa.me/${phone}?text=${enc(waText)}" target="_blank" rel="noopener">${ICON.wa}${isDebtor ? "Remind" : "WhatsApp"}</a><a class="btn" href="tel:+${phone}">${ICON.call}Call</a>` : ""}
      </div>
      <div class="totals">
        <div><div class="label">Opening</div>${drcr(d.opening)}</div>
        <div><div class="label">Closing</div>${drcr(d.closing)}</div>
        <div><div class="label">Debits</div>${money(d.debit, "dr")}</div>
        <div><div class="label">Credits</div>${money(d.credit, "cr")}</div>
      </div>
    </section>
    ${d.entries.length > 1 ? sortChips("esorts", [["old", "Oldest first"], ["new", "Newest first"], ["amount", "Largest amount"]], S.esort) : ""}
    <section class="page ruled stmt">
      <div class="carry"><span>Opening balance</span>${drcr(d.opening)}</div>
      ${sortEntries(d.entries).map((e) => `<a class="entry" href="#/voucher/${e.id}">
          <span class="d">${fdate(e.date)}</span>
          <span class="p">${h(e.against || e.vtype)}</span>${drcr(e.amount)}
          <span class="v">${h(e.vtype)} ${h(e.number)}</span><span class="bal">Bal ${drcr(e.balance)}</span>
        </a>`).join("") || '<div class="empty">No entries in this period.</div>'}
      <div class="closing"><span>Closing balance</span>${drcr(d.closing)}</div>
    </section>
    ${pending.length ? `<section class="page billsec"><div class="block-title">Pending bills <span>${overdue.length ? `${overdue.length} overdue` : ""}${d.interest > 0.5 ? `, interest ${rupees(d.interest, false)}` : ""}</span></div>${billRows(pending.slice(0, 5))}
      ${pending.length > 5 ? `<div id="morebills" hidden>${billRows(pending.slice(5))}</div><button class="row" id="showbills" style="justify-content:center;color:var(--ink-2);font-weight:500">Show all ${pending.length} bills</button>` : ""}</section>` : ""}`;
  wirePeriod(d.from, d.to, "ledger");
  $("#sharepdf").onclick = () => sharePdf(pdfUrl, `${L.name} statement`);
  view.querySelectorAll("#esorts [data-sort]").forEach((b) => b.onclick = () => {
    const y = window.scrollY; savePref("esort", b.dataset.sort); vLedger(name).then(() => window.scrollTo(0, y)).catch(fail);
  });
  const sb = $("#showbills");
  if (sb) sb.onclick = () => { $("#morebills").hidden = false; sb.remove(); };
}

function reminderText(name, co, total, overdue, interest = 0, rate = 0) {
  let t = `Dear ${name}, your balance with ${co} is ${rupees(total)}.`;
  if (overdue && overdue.length) {
    const top = overdue.slice().sort((a, b) => b.overdue - a.overdue).slice(0, 5);
    t += ` Overdue bills: ` + top.map((b) => `${b.ref} dated ${fdate(b.date)} for ${rupees(b.amount)} (${b.overdue} days overdue)`).join("; ") +
      (overdue.length > 5 ? ` and ${overdue.length - 5} more` : "") + ".";
  }
  if (interest > 0.5 && rate) t += ` Interest at ${rate}% p.a. on the overdue bills comes to ${rupees(interest)} up to today.`;
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
      <a class="chip" href="#/collect">Follow-up list</a>
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
            <div class="meta">${p.overdue_amount > 0.5 ? `<span class="od">${rupees(p.overdue_amount, false)} overdue</span>, ` : ""}${p.oldest_days !== null ? `oldest bill ${p.oldest_days} days` : "no bill dates"}${p.interest > 0.5 ? `, interest ${rupees(p.interest, false)}` : ""}</div></div>
            <div class="end">${money(p.amount)}</div><span class="chev down"></span></button>
          <div class="bills" id="pb${i}" hidden>${billRows(p.bills)}
            <div class="actions" style="padding-top:10px"><a class="btn" href="#/ledger/${enc(p.name)}">Open ledger</a>
            ${rec && ph ? `<a class="btn wa" href="https://wa.me/${ph}?text=${enc(reminderText(p.name, co, p.amount, od, p.interest, d.interest_rate))}" target="_blank" rel="noopener">${ICON.wa}Remind</a>` : ""}</div></div>
        </div>`;
      }).join("") || `<div class="empty">${rec ? "Nobody owes you money right now." : "You don't owe anyone right now."}</div>`}
    </section>
    <div class="actions" style="padding:0 0 4px">${excelBtn("outstanding", { kind: S.dueKind })}</div>
    <p class="note" style="border:0">${d.source === "tally" ? "Bills as calculated by Tally's outstanding report." : "Bills worked out from the bill references in your vouchers."} Ages count from the bill date.</p>`;
  view.querySelectorAll("[data-p]").forEach((b) => b.onclick = () => {
    const el = document.getElementById("pb" + b.dataset.p); el.hidden = !el.hidden;
    b.setAttribute("aria-expanded", String(!el.hidden)); b.querySelector(".chev").classList.toggle("up", !el.hidden);
  });
}

async function vStock(q = "") {
  setTitle(false);
  S.sq = q;
  const d = await api(cpath("stock", { q, ...periodParams() }));
  if (!$("#ssearch")) {
    view.innerHTML = `<div id="speriod"></div><input class="search" id="ssearch" type="search" placeholder="Search items" aria-label="Search stock items" value="${h(q)}"><div id="slist"></div>`;
    $("#ssearch").oninput = (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => vStock(e.target.value).catch(fail), 200); };
  }
  $("#speriod").innerHTML = periodBar(d.from, d.to);
  wirePeriod(d.from, d.to);
  const flagged = d.items.filter((i) => i.flag);
  const shown = S.sflag ? flagged : d.items;
  $("#slist").innerHTML = `<section class="page"><div class="hero">
      <div><div class="label">Opening, ${fdate(d.from)}</div><div class="big" style="font-size:24px">${d.open_exact ? "" : "≈ "}${short(d.open_total)}</div></div>
      <div><div class="label">Closing, ${fdate(d.to < iso(new Date()) ? d.to : iso(new Date()))}</div><div class="big">${d.close_exact ? "" : "≈ "}${short(d.total)}</div></div>
      <div class="label" style="grid-column:1/-1">${d.items.length} items${flagged.length ? `, <button class="linkbtn od" id="sflag">${S.sflag ? "show all" : `${flagged.length} need attention`}</button>` : ""}</div></div></section>
    <section class="page">
      <div class="stock-head"><span>Item</span><span>Opening</span><span>In / Out</span><span>Closing</span></div>
      ${shown.map((i) => `<a class="row stock-row" href="#/item/${enc(i.name)}">
        <div class="main"><div class="name">${h(i.name)}${i.flag ? ` <span class="badge ${i.flag}">${i.flag === "negative" ? "negative" : "below minimum"}</span>` : ""}</div><div class="meta">${i.rate ? `₹${nf2.format(i.rate)} / ${h(i.unit)}` : ""}</div></div>
        <div class="sc"><span class="lbl">Opening</span><b>${qty(i.open_qty, i.unit)}</b><span class="meta">${i.open_exact ? "" : "≈ "}${money(i.open_value)}</span></div>
        <div class="sc"><span class="lbl">In / Out</span><b class="up">+${nfq.format(i.in_qty)}</b><b class="down">−${nfq.format(i.out_qty)}</b></div>
        <div class="sc"><span class="lbl">Closing</span><b>${qty(i.close_qty, i.unit)}</b><span class="meta">${i.close_exact ? "" : "≈ "}${money(i.close_value)}</span></div></a>`).join("")
      || '<div class="empty">No stock item matches that name.</div>'}</section>
    <div class="actions" style="padding:0 0 4px"><a class="btn" href="#/godowns">Stock by godown</a>${excelBtn("stock", periodParams())}</div>
    <p class="note" style="border:0">Set a minimum on an item's page to be told on Telegram when it runs low. Negative stock (all godowns together) is flagged too.</p>
    <p class="note" style="border:0;margin-top:0">Opening and closing are Tally's own figures for whole months, quarters and years, across all godowns. For other dates Bahi works them out from the nearest month-end and marks them ≈.</p>`;
  const sf = $("#sflag"); if (sf) sf.onclick = (e) => { e.preventDefault(); S.sflag = !S.sflag; vStock(S.sq || "").catch(fail); };
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
      <div><div class="label">Opening, ${fdate(d.from)}</div><span class="amt">${qty(d.period.open_qty, I.unit)}</span><div class="meta">${d.period.open_exact ? "" : "≈ "}${money(d.period.open_value)}</div></div>
      <div><div class="label">Closing${d.period.close_exact ? " (in hand now)" : `, ${fdate(d.to)}`}</div><span class="amt">${qty(d.period.close_qty, I.unit)}</span><div class="meta">${d.period.close_exact ? "" : "≈ "}${money(d.period.close_value)}</div></div>
      <div><div class="label">Came in</div><span class="amt">${qty(d.inward, I.unit)}</span></div>
      <div><div class="label">Went out</div><span class="amt">${qty(d.outward, I.unit)}</span></div>
    </div></section>
    ${can("stock") ? `<section class="page"><form class="form" id="minf" style="padding-top:12px">
      <label>Alert me on Telegram when stock falls below<span style="display:flex;gap:8px;align-items:center"><input type="number" name="min" min="0" step="any" value="${d.period.min ?? ""}" placeholder="no minimum" style="flex:1"> ${h(I.unit || "")}</span></label>
      <button class="btn" type="submit">Save minimum</button></form></section>` : ""}
    ${d.godowns && d.godowns.length ? `<section class="page"><div class="block-title">In each godown now</div>
      ${d.godowns.map((g) => `<div class="row"><div class="main"><div class="name">${h(g.godown)}</div></div>
        <div class="end"><span class="amt${g.qty < 0 ? " down" : ""}">${qty(g.qty, I.unit)}</span></div></div>`).join("")}
      <div class="row"><div class="main"><div class="name"><b>All godowns</b></div></div><div class="end"><b class="amt">${qty(I.closing_qty, I.unit)}</b></div></div>
    </section>` : ""}
    <section class="page"><div class="block-title">Movements</div>
      ${d.moves.map((m) => `<a class="row" href="#/voucher/${m.id}"><div class="main"><div class="name">${h(m.party || m.vtype)}</div>
        <div class="meta">${fdate(m.date)}, ${h(m.vtype)} ${h(m.number)}${m.rate ? `, ₹${nf2.format(m.rate)}` : ""}</div></div>
        <div class="end">${m.transfer ? `<span class="meta">moved between godowns</span>` : m.tracked ? `<span class="meta">${qty(Math.abs(m.qty), I.unit)}, counted on the delivery note</span>` :
          `<span class="amt ${m.qty < 0 ? "down" : "up"}">${m.qty > 0 ? "+" : "−"}${qty(Math.abs(m.qty), I.unit)}</span>`}</div></a>`).join("")
        || '<div class="empty">No movement in this period.</div>'}
    </section>`;
  wirePeriod(d.from, d.to);
  const mf = $("#minf");
  if (mf) mf.onsubmit = async (e) => {
    e.preventDefault();
    const r = await fetch(cpath("stockmin"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item: name, min: mf.min.value }) });
    toast(r.ok ? (mf.min.value ? `You'll get a Telegram message when ${name} falls below ${mf.min.value}.` : "Minimum removed.") : "Couldn't save.");
  };
}

async function vGodowns(g) {
  setTitle(true);
  const d = await api(cpath("godowns"));
  if (!d.split) {
    view.innerHTML = `<h1 class="title">Stock by godown</h1><div class="empty">Your stock isn't split into godowns in Tally, or the Tally PC hasn't sent godown details yet (they come with the next full sync).</div>`;
    return;
  }
  const rows = g ? d.rows.filter((r) => r.godown === g) : [];
  view.innerHTML = `<h1 class="title">${g ? h(g) : "Stock by godown"}</h1>
    ${g ? `<section class="page">${rows.map((r) => `<a class="row" href="#/item/${enc(r.item)}"><div class="main"><div class="name">${h(r.item)}${r.qty < 0 ? ' <span class="badge negative">negative here</span>' : ""}</div><div class="meta">${h(r.parent || "")}</div></div>
        <div class="end"><span class="amt${r.qty < 0 ? " down" : ""}">${qty(r.qty, r.unit)}</span><div class="meta">${money(r.value)}</div></div></a>`).join("") || '<div class="empty">Nothing here.</div>'}</section>`
    : `<section class="page">${d.godowns.map((x) => `<a class="row" href="#/godowns/${enc(x.godown)}"><div class="main"><div class="name">${h(x.godown)}</div>
        <div class="meta">${x.items} item${x.items === 1 ? "" : "s"}${x.negative ? `, <span class="down">${x.negative} negative</span>` : ""}</div></div><div class="end"><span class="amt">${money(x.value)}</span></div></a>`).join("")}</section>`}
    <p class="note" style="border:0">Godown figures are each item's opening in that godown plus the vouchers Bahi has. A godown can show negative when a transfer was entered late; the total of all godowns is always Tally's closing, and that is what the Stock page and alerts use.${d.godowns.some((x) => x.godown === "Not split by godown") ? " “Not split by godown” is stock Tally counts in the total but Bahi couldn't place, for example from vouchers older than the sync start." : ""}</p>`;
}

async function vBRS(ledger) {
  setTitle(true);
  if (S.brsLed !== ledger) { S.brsLed = ledger; S.brsFrom = S.brsTo = ""; S.brsTab = "tally"; }
  const d = await api(cpath("brs", { ledger: ledger || "", from: S.brsFrom || "", to: S.brsTo || "" }));
  if (!ledger) {
    if (d.ledgers.length === 1) { location.replace("#/brs/" + enc(d.ledgers[0].name)); return; }
    view.innerHTML = `<h1 class="title">Bank reconciliation</h1><section class="page">${d.ledgers.map((l) => `<a class="row" href="#/brs/${enc(l.name)}"><div class="main"><div class="name">${h(l.name)}</div><div class="meta">${l.saved ? "Statement uploaded" : "No statement yet"}</div></div><span class="chev"></span></a>`).join("") || '<div class="empty">No bank ledgers found in Tally (ledgers under Bank Accounts or Bank OD A/c).</div>'}</section>`;
    return;
  }
  const amt = (a) => `<span class="amt ${a < 0 ? "down" : "up"}">${a < 0 ? "−" : "+"}${nf2.format(Math.abs(a))}</span>`;
  const vrow = (v) => `<a class="row" href="#/voucher/${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}</div><div class="meta">${fdate(v.date)}, ${h(v.vtype)} ${h(v.number)}${v.narration ? ", " + h(v.narration.slice(0, 80)) : ""}</div></div><div class="end">${amt(v.amount)}</div></a>`;
  const brow = (b, extra = "") => `<div class="row"><div class="main"><div class="name">${h(b.desc || "(no description)")}</div><div class="meta">${fdate(b.date)}${b.ref ? ", ref " + h(b.ref) : ""}</div>${extra}</div><div class="end">${amt(b.amount)}</div></div>`;
  const upload = `<form class="form" id="brsf"><label>${d.matched ? "Add another statement" : "Bank statement"}<input type="file" id="brsfile" accept=".xlsx,.xls,.csv,.txt,.htm,.html" required></label>
      <button class="btn" type="submit">Upload and match</button><p class="meta" id="brsmsg" role="status"></p></form>`;
  if (!d.matched) {
    view.innerHTML = `<h1 class="title">${h(ledger)}</h1><section class="page"><div class="info">
      <div><b>1.</b> In net banking, download the account statement for the period as Excel (or CSV).</div>
      <div><b>2.</b> Choose that file here. Bahi matches every line with the entries on this ledger in Tally.</div></div>${upload}</section>`;
  } else {
    const s = d.summary, tab = S.brsTab || "tally";
    const notBank = [...d.pending, ...d.tally_only];
    const list = tab === "tally" ? (notBank.map(vrow).join("") || '<div class="empty">Everything in Tally shows in the bank.</div>')
      : tab === "bank" ? (d.bank_only.map((b) => brow(b, (d.candidates[b.n] || []).length ? `<button class="linkbtn" data-pair="${b.n}">Pair with a Tally entry</button>` : "")).join("") || '<div class="empty">Every bank entry is in Tally.</div>')
      : d.matched.map((m) => `<a class="row" href="#/voucher/${m.tally.id}"><div class="main"><div class="name">${h(m.tally.party || m.tally.vtype)}</div><div class="meta">Tally ${fdate(m.tally.date)} ${h(m.tally.vtype)} ${h(m.tally.number)} · Bank ${fdate(m.bank.date)}${m.days ? ` (${m.days > 0 ? "+" : ""}${m.days} days)` : ""}${m.manual ? " · paired by you" : ""}</div><div class="meta">${h(m.bank.desc)}</div></div><div class="end">${amt(m.bank.amount)}</div></a>`).join("");
    const line = (l, v, cls = "") => `<div class="row"><div class="main">${l}</div><div class="end"><span class="amt ${cls}">${v === null || v === undefined ? "–" : nf2.format(v)}</span></div></div>`;
    view.innerHTML = `<h1 class="title">${h(ledger)}</h1>
      <div class="dates" style="margin:6px 0 10px"><input type="date" id="bf" value="${d.from}" min="${d.first}" max="${d.last}" aria-label="From date"> to <input type="date" id="bt" value="${d.to}" min="${d.first}" max="${d.last}" aria-label="To date"> <button class="chip" id="bapply">Show</button></div>
      <section class="page"><div class="block-title">Reconciliation on ${fdate(d.to)}</div>
        ${line("Balance as per Tally", s.tally)}
        ${line("Add: cheques issued, not yet in the bank", s.unpresented)}
        ${line("Less: deposits not yet credited by the bank", s.uncleared)}
        ${line("Add: credits in the bank, not in Tally", s.bank_cr)}
        ${line("Less: debits in the bank, not in Tally", s.bank_dr)}
        ${line("<b>Balance as per bank (worked out)</b>", s.expected)}
        ${s.statement !== null ? line("Balance shown on the statement", s.statement) : ""}
        ${s.diff !== null ? (Math.abs(s.diff) < 0.5 ? `<p class="note" style="border:0">The statement balance agrees.</p>` : `<p class="note od" style="border:0">Differs from the statement by ${nf2.format(s.diff)}. Usually an entry dated before ${fdate(d.from)} is still pending, or the statement doesn't start where the Tally balance does.</p>`) : ""}
      </section>
      <div class="toolbar" role="group" aria-label="Show">
        <button class="chip ${tab === "tally" ? "on" : ""}" data-tab="tally">Not in bank yet <span class="cnt">${notBank.length}</span></button>
        <button class="chip ${tab === "bank" ? "on" : ""}" data-tab="bank">Not in Tally <span class="cnt">${d.bank_only.length}</span></button>
        <button class="chip ${tab === "matched" ? "on" : ""}" data-tab="matched">Matched <span class="cnt">${d.matched.length}</span></button></div>
      <section class="page">${list}</section>
      ${tab === "bank" && d.bank_only.length ? '<p class="note" style="border:0">Bank charges, interest and direct transfers usually show here. Enter them in Tally; after the next sync they move to Matched.</p>' : ""}
      <section class="page">${upload}</section>
      <p class="note" style="border:0">Statement ${fdate(d.first)} to ${fdate(d.last)}${d.file ? `, last file ${h(d.file)}` : ""}. Uploading the next month's statement adds to this one. <button class="linkbtn" id="brsclear">Remove statement</button></p>`;
    view.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { S.brsTab = b.dataset.tab; vBRS(ledger).catch(fail); });
    $("#bapply").onclick = () => { S.brsFrom = $("#bf").value; S.brsTo = $("#bt").value; vBRS(ledger).catch(fail); };
    $("#brsclear").onclick = async () => {
      if (!confirm("Remove the uploaded statement for " + ledger + "?")) return;
      await fetch(cpath("brs", { ledger, action: "clear" }), { method: "POST" }); S.brsFrom = S.brsTo = ""; vBRS(ledger).catch(fail);
    };
    view.querySelectorAll("[data-pair]").forEach((b) => b.onclick = () => {
      const n = +b.dataset.pair, bl = d.bank_only.find((x) => x.n === n);
      const ids = d.candidates[n] || [], all = [...d.pending, ...d.tally_only];
      const opts = ids.map((id) => all.find((v) => v.id === id)).filter(Boolean);
      const dlg = $("#sheet");
      dlg.innerHTML = `<h3>Pair ${nf2.format(Math.abs(bl.amount))} on ${fdate(bl.date)}</h3>${opts.map((v) => `<button class="row" data-v="${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}</div><div class="meta">${fdate(v.date)}, ${h(v.vtype)} ${h(v.number)}</div></div></button>`).join("") || '<div class="empty">No Tally entry with this amount is left unmatched.</div>'}
        <div class="actions" style="padding-top:12px"><button class="btn" id="dclose">Close</button></div>`;
      dlg.querySelectorAll("[data-v]").forEach((x) => x.onclick = async () => {
        await fetch(cpath("brs", { ledger, action: "pair" }), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ n, vid: +x.dataset.v }) });
        dlg.close(); vBRS(ledger).catch(fail);
      });
      $("#dclose").onclick = () => dlg.close();
      dlg.showModal();
    });
  }
  $("#brsf").onsubmit = async (e) => {
    e.preventDefault();
    const file = $("#brsfile").files[0]; if (!file) return;
    $("#brsmsg").textContent = "Reading the statement";
    const r = await fetch(cpath("brs", { ledger }), { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { $("#brsmsg").textContent = j.error || "Couldn't read that file."; return; }
    S.brsFrom = j.from; S.brsTo = j.to; S.brsTab = "tally";
    toast(`${j.added} new bank entries read. ${j.matched.length} matched with Tally.`);
    vBRS(ledger).catch(fail);
  };
}

let syncPoll = null;
async function syncNow() {
  const r = await fetch("/api/sync/now", { method: "POST" });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(j.error || "Couldn't ask for a sync."); return; }
  const c0 = S.companies.find((x) => x.id === S.cid), before = c0 ? c0.last_sync : 0, t0 = Date.now();
  toast("Asked the Tally PC to sync. It starts within 2 minutes.");
  clearInterval(syncPoll);
  syncPoll = setInterval(async () => {
    try { await loadCompanies(); } catch (e) { return; }
    const c = S.companies.find((x) => x.id === S.cid);
    const picked = S.sync.last_run * 1000 >= t0 - 1000;
    if ((c && c.last_sync > before) || (picked && c && c.last_seen * 1000 > t0)) {
      clearInterval(syncPoll); toast(c && c.last_sync > before ? "Sync finished. Showing the latest figures." : "Synced. Nothing had changed in Tally."); route();
    } else if (Date.now() - t0 > 5 * 60000) {
      clearInterval(syncPoll); toast("The Tally PC didn't respond. Is it on, with Tally open?");
    }
  }, 10000);
}

function vReports() {
  setTitle(false);
  const c = S.companies.find((x) => x.id === S.cid);
  const R = [
    ["#/entries", "Entries from phone", "Receipts, payments and orders made in the app, and their status", entryKinds().length || S.me.owner],
    ["#/vouchers", "Vouchers", "Search and open any voucher", can("vouchers")],
    ["#/daybook", "Day Book", "Every voucher by date", can("vouchers")],
    ["#/analysis", "Sales analysis", "Top customers and items, margins, this year against last, slow stock", can("accounts")],
    ["#/pl", "Profit &amp; Loss", "Sales, purchases, expenses and profit", can("accounts")],
    ["#/bs", "Balance Sheet", "What the business owns and owes, as on today", can("accounts")],
    ["#/cashbook", "Cash and bank book", "Money in and out each day, with opening and closing balances", can("accounts")],
    ["#/brs", "Bank reconciliation", "Match your bank statement with the bank ledger in Tally", can("accounts")],
    ["#/collect", "Follow-up list", "Who should pay you: overdue, due this week, promises", can("dues")],
    ["#/gst", "GST summary", "Output tax, input credit and net payable by month", can("accounts")],
    ["#/groups", "Group summary", "Balances by Tally group", can("accounts")],
    ["#/dues/receivable", "Outstanding", "Bill-wise dues with ageing", can("dues")],
    ["#/stock", "Stock summary", "Quantity and value of every item", can("stock")],
  ].filter((r) => r[3] && S.cid);
  view.innerHTML = `${S.me.owner ? "" : `<p class="subtitle" style="margin-top:4px">Logged in as ${h(S.me.name)}</p>`}
  ${S.sync.mode !== "paused" ? `<section class="page"><button class="row" id="syncrow"><div class="main"><div class="name">Sync now</div><div class="meta">${S.sync.mode === "manual" ? "Sync is manual. " : ""}Get the latest from Tally (the Tally PC must be on with Tally open)</div></div></button></section>` : ""}
  ${S.cid ? "" : '<section class="page"><div class="empty">No Tally data yet. Reports appear after the first sync from the Tally PC. Settings below work already.</div></section>'}
  ${R.length ? `<section class="page">` : "<div hidden>"}
    ${R.map(([href, name, meta]) => `<a class="row" href="${href}"><div class="main"><div class="name">${name}${href === "#/entries" && S.me.owner && S.approvals ? ` <span class="badge">${S.approvals} to approve</span>` : ""}</div><div class="meta">${meta}</div></div><span class="chev"></span></a>`).join("")}
  ${R.length ? "</section>" : "</div>"}
  ${c && S.me.owner ? `<section class="page"><div class="block-title">Sync</div><div class="info">
    <div>Data from ${fdate(c.from_date)} to ${fdate(c.to_date)}</div><div>${c.ledgers} ledgers, ${c.vouchers} vouchers</div>
    <div>Last change synced ${ago(c.last_sync)}. Tally last checked ${ago(c.last_seen)}.</div>
    <div>App version ${APP_VERSION}</div></div>
    <a class="row" href="#/check"><div class="main"><div class="name">Sync check</div><div class="meta">${c.unbalanced ? `<span class="od">${c.unbalanced} vouchers didn't add up</span>` : "Every voucher added up"}. Vouchers by type.</div></div><span class="chev"></span></a></section>` : ""}
  <section class="page">
    <a class="row" href="#/settings"><div class="main"><div class="name">Settings</div><div class="meta">${S.me.owner ? `Staff logins, Telegram summaries, backups, change password, delete old data${S.companies.length > 1 ? ", companies" : ""}` : "Change your password"}</div></div><span class="chev"></span></a>
    <div class="actions" style="padding-top:12px">
    <button class="btn" id="theme">Switch light/dark</button><button class="btn" id="logout">Log out</button></div></section>`;
  if ($("#syncrow")) $("#syncrow").onclick = () => syncNow();
  $("#logout").onclick = async () => { await fetch("/api/logout"); location.hash = "#/"; showLogin(); };
  $("#theme").onclick = () => {
    const cur = document.documentElement.dataset.theme || "light";
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
    return head + `<a class="row${v.status ? " void" : ""}" href="#/voucher/${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}${badge(v.status)}</div>
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

/* Main voucher types (Sales, Receipt...) combine all of the company's own types under them.
   Pick a main type, then optionally one of its own types (e.g. GST Sales) from the second row. */
function typeChips(types, base, sub) {
  const top = `<div class="toolbar" role="group" aria-label="Voucher type"><button class="chip ${!base ? "on" : ""}" data-t="">All</button>${types.map((t) =>
    `<button class="chip ${t.base === base ? "on" : ""}" data-t="${h(t.base)}">${h(t.base)}${t.subs.length > 1 ? ` <span class="cnt">${t.subs.length} types</span>` : ""}</button>`).join("")}</div>`;
  const cur = types.find((t) => t.base === base);
  const subs = cur && cur.subs.length ? `<div class="toolbar subtypes" role="group" aria-label="${h(base)} types"><span class="sublbl">${h(base)} types:</span>
    <button class="chip ${!sub ? "on" : ""}" data-st="">All combined</button>${cur.subs.map((x) =>
      `<button class="chip ${x.name === sub ? "on" : ""}" data-st="${h(x.name)}">${h(x.name)} <span class="cnt">${nf0.format(x.n)}</span></button>`).join("")}</div>` : "";
  return top + subs;
}
function wireTypeChips(el, onBase, onSub) {
  el.querySelectorAll("[data-t]").forEach((b) => b.onclick = () => onBase(b.dataset.t));
  el.querySelectorAll("[data-st]").forEach((b) => b.onclick = () => onSub(b.dataset.st));
}

async function vDaybook(type) {
  setTitle(true);
  if (type !== undefined && type !== S.dayType) { S.dayType = type; S.daySub = ""; }
  const params = { ...periodParams(), type: S.dayType, sub: S.daySub || "" };
  const d = await api(cpath("daybook", params));
  view.innerHTML = `<h1 class="title">Day Book</h1>${periodBar(d.from, d.to)}
    <div id="dbtypes">${typeChips(d.types, S.dayType, S.daySub)}</div>
    <section class="page" id="dblist"></section>`;
  pagedVouchers($("#dblist"), "daybook", params, d, "No vouchers in this period.");
  wirePeriod(d.from, d.to);
  wireTypeChips($("#dbtypes"), (t) => vDaybook(t).catch(fail), (st) => { S.daySub = st; vDaybook().catch(fail); });
}

let vSearchT;
async function vVouchers() {
  setTitle(false);
  if (S.vq === undefined) S.vq = "";
  const params = { q: S.vq, type: S.vtype || "", sub: S.vsub || "", ...periodParams() };
  const d = await api(cpath("vouchers", params));
  if (!$("#vsearch")) {
    view.innerHTML = `<input class="search" id="vsearch" type="search" inputmode="search" placeholder="Party, voucher no., amount or narration" aria-label="Search vouchers" value="${h(S.vq)}">
      <div id="vperiod"></div><div id="vtypes"></div><section class="page" id="vlist"></section><div class="actions" id="vxl" style="padding:0 0 12px"></div>`;
    $("#vsearch").oninput = (e) => { clearTimeout(vSearchT); vSearchT = setTimeout(() => { S.vq = e.target.value; vVouchers().catch(fail); }, 250); };
  }
  $("#vperiod").innerHTML = periodBar(d.from, d.to);
  $("#vtypes").innerHTML = typeChips(d.types, S.vtype || "", S.vsub || "");
  $("#vxl").innerHTML = excelBtn("vouchers", params);
  pagedVouchers($("#vlist"), "vouchers", params, d,
    S.vq ? "No voucher matches that search in this period. Try All dates." : "No vouchers in this period.");
  wirePeriod(d.from, d.to);
  wireTypeChips($("#vtypes"), (t) => { S.vtype = t; S.vsub = ""; vVouchers().catch(fail); }, (st) => { S.vsub = st; vVouchers().catch(fail); });
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
    ${V.status ? `<p class="note warn" style="border:0;padding:0 4px 10px">This voucher is ${V.status === "cancelled" ? "cancelled" : "optional"} in Tally, so it doesn't count in balances, stock or reports.</p>` : ""}
    <section class="page vhead">
      <div class="vtype">${h(V.vtype)}${badge(V.status)}</div>
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
    ${(() => { const E = V.extra || {};
      const rows = [["IRN", E.irn], ["Ack No.", E.ack_no], ["Ack Date", E.ack_date && fdate(E.ack_date)], ["e-Way Bill No.", E.ewb_no],
        ["e-Way Bill date", E.ewb_date && fdate(E.ewb_date)], ["Valid up to", E.ewb_valid], ["Vehicle", E.ewb_vehicle],
        ["Mode", E.ewb_mode], ["Distance", E.ewb_distance && E.ewb_distance + " km"], ["Transporter", E.ewb_transporter]].filter((r) => r[1]);
      return rows.length ? `<section class="page"><div class="block-title">${E.irn ? "e-Invoice" : ""}${E.irn && E.ewb_no ? " and " : ""}${E.ewb_no ? "e-Way Bill" : ""}</div>
        <div class="info">${rows.map(([k, v]) => `<div><span style="color:var(--ink-3)">${k}:</span> <b style="overflow-wrap:anywhere">${h(v)}</b></div>`).join("")}
        <div style="color:var(--ink-3)">${E.ewb_no ? "The PDF has the e-Way Bill as page 2." : ""}${E.qr ? " The PDF prints the signed QR code." : ""}</div></div></section>` : ""; })()}
    ${V.narration ? `<section class="page"><div class="block-title">Narration</div><div class="info" style="white-space:pre-line">${h(V.narration)}</div></section>` : ""}
    ${!V.balanced ? '<p class="note warn">This voucher\'s debits and credits did not match when it was synced.</p>' : ""}`;
  $("#vpdf").onclick = () => sharePdf(`/api/c/${S.cid}/voucher_pdf/${id}`, `${V.vtype} ${V.number}`);
}

async function vSales(kind) {
  setTitle(false);
  if ((kind || S.skind || "sales") !== S.skind) S.ssub = "";
  S.skind = kind || S.skind || "sales";
  const sales = S.skind === "sales";
  const sp = { kind: S.skind, sub: S.ssub || "", ...periodParams() };
  const d = await api(cpath("daily", sp));
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
    ${d.subs.length ? `<div class="toolbar subtypes" role="group" aria-label="Voucher types"><span class="sublbl">${sales ? "Sales" : "Purchase"} types:</span>
      <button class="chip ${!S.ssub ? "on" : ""}" data-ss="">All combined</button>${d.subs.map((x) => `<button class="chip ${x === S.ssub ? "on" : ""}" data-ss="${h(x)}">${h(x)}</button>`).join("")}</div>` : ""}
    <section class="page">
      <div class="hero"><div><div class="label">${S.ssub ? h(S.ssub) : sales ? "Sales" : "Purchases"} with tax</div><div class="big">${short(d.total)}</div></div>
        <div><div class="label">Before tax</div><div class="big" style="font-size:22px">${short(d.net)}</div></div></div>
      <div class="tiles">
        <div class="tile"><div class="label">Bills</div><div class="val">${nf0.format(d.bills)}</div></div>
        <div class="tile"><div class="label">Average a day</div><div class="val">${short(d.avg)}</div></div>
        <div class="tile"><div class="label">${sales ? "Returns" : "Returned"}</div><div class="val">${short(d.returns)}</div></div>
      </div>
      ${d.best && d.best.total ? `<div class="note">Best day: <a href="#/day/${S.skind}/${d.best.date}">${fdate(d.best.date)}</a>, ${rupees(d.best.total, false)}</div>` : ""}
    </section>
    <section class="page">${body || `<div class="empty">No ${sales ? "sales" : "purchases"} in this period.</div>`}</section>
    ${S.ssub ? `<p class="note" style="border:0">Showing only ${h(S.ssub)}. Returns are counted under All combined.</p>` : ""}
    <div class="actions" style="padding:0 0 12px">${excelBtn("daily", sp)}<a class="btn" href="#/analysis">Sales analysis</a></div>`;
  wirePeriod(d.from, d.to);
  view.querySelectorAll("[data-ss]").forEach((b) => b.onclick = () => { S.ssub = b.dataset.ss; vSales().catch(fail); });
}

async function vDay(kind, day) {
  setTitle(true);
  const sales = kind !== "purchase";
  const base = sales ? "Sales" : "Purchase", ret = sales ? "Credit Note" : "Debit Note";
  const p = { from: day, to: day };
  const sub = S.skind === kind ? (S.ssub || "") : "";
  const [a, r] = await Promise.all([api(cpath("vouchers", { ...p, type: base, sub })), sub ? Promise.resolve({ vouchers: [] }) : api(cpath("vouchers", { ...p, type: ret }))]);
  const dt = new Date(day + "T00:00:00");
  const tot = a.vouchers.filter((v) => !v.status).reduce((s, v) => s + v.amount, 0);   // cancelled/optional don't count
  view.innerHTML = `<div class="crumbs"><a href="#/sales${sales ? "" : "/purchase"}">${sales ? "Sales" : "Purchases"} by day</a></div>
    <h1 class="title">${dt.toLocaleDateString("en-IN", { weekday: "long" })}, ${fdate(day)}</h1>
    <p class="subtitle">${a.total} bill${a.total === 1 ? "" : "s"}${a.total <= 200 ? `, ${rupees(tot)}` : ""}</p>
    <section class="page" id="dlist"></section>
    ${r.total ? `<h2 class="title" style="font-size:18px">${sales ? "Returns (credit notes)" : "Returns (debit notes)"}</h2><section class="page" id="rlist"></section>` : ""}`;
  pagedVouchers($("#dlist"), "vouchers", { ...p, type: base }, a, `No ${sales ? "sales" : "purchases"} on this day.`);
  if (r.total) pagedVouchers($("#rlist"), "vouchers", { ...p, type: ret }, r, "");
}

const ATABS = [["parties", "Customers"], ["items", "Items"], ["years", "This year vs last"], ["slow", "Slow stock"]];
async function vAnalysis(tab) {
  setTitle(true);
  S.atab = tab || S.atab || "parties";
  S.akind = S.akind || "sales";
  const t = S.atab;
  const tabs = `<div class="toolbar" role="tablist">${ATABS.map(([k, l]) => `<a class="chip ${k === t ? "on" : ""}" href="#/analysis/${k}" role="tab" aria-selected="${k === t}">${l}</a>`).join("")}</div>`;
  let html = "";
  if (t === "parties") {
    const d = await api(cpath("a_parties", { kind: S.akind, ...periodParams() }));
    const sales = S.akind === "sales";
    const chg = (r) => r.change === null ? (r.prev ? "" : (d.has_prev ? '<span class="up">new</span>' : "")) :
      `<span class="${r.change >= 0 ? "up" : "down"}">${r.change >= 0 ? "▲" : "▼"} ${Math.abs(r.change)}%</span>`;
    html = `<div class="toolbar"><button class="chip ${sales ? "on" : ""}" data-k="sales">Customers</button><button class="chip ${!sales ? "on" : ""}" data-k="purchase">Suppliers</button></div>
      ${periodBar(d.from, d.to)}
      <section class="page"><div class="hero"><div><div class="label">${sales ? "Sales" : "Purchases"} with tax</div><div class="big">${short(d.total)}</div></div>
        <div><div class="label">Same period last year</div><div class="big" style="font-size:22px">${d.has_prev ? short(d.prev_total) : "no data"}</div></div></div></section>
      <section class="page"><div class="block-title"><span>${sales ? "Customer" : "Supplier"}</span><span>Value, share, vs last year</span></div>
      ${d.parties.slice(0, 200).map((r) => `<a class="row" href="#/ledger/${enc(r.party)}"><div class="main"><div class="name">${h(r.party)}</div>
        <div class="meta">${r.bills} bills, ${r.share}%${r.last ? `, last ${fdate(r.last)}` : ""}${!r.total && r.prev ? `, <span class="down">nothing this period (${short(r.prev)} last year)</span>` : ""}</div>
        <div class="daybar"><span style="width:${Math.max(1, r.share)}%"></span></div></div>
        <div class="end">${money(r.total)}<div class="meta">${chg(r)}</div></div><span class="chev"></span></a>`).join("") || '<div class="empty">Nothing in this period.</div>'}
      </section><div class="actions" style="padding:0 0 12px">${excelBtn("a_parties", { kind: S.akind, ...periodParams() })}</div>`;
    view.innerHTML = tabs + html;
    view.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => { S.akind = b.dataset.k; vAnalysis().catch(fail); });
    wirePeriod(d.from, d.to);
  } else if (t === "items") {
    const d = await api(cpath("a_items", periodParams()));
    html = `${periodBar(d.from, d.to)}
      <section class="page"><div class="hero" style="grid-template-columns:1fr"><div class="label">Item sales before tax</div><div class="big">${short(d.total)}</div></div></section>
      <section class="page"><div class="block-title"><span>Item</span><span>Value, margin</span></div>
      ${d.items.map((r) => `<a class="row" href="#/item/${enc(r.item)}"><div class="main"><div class="name">${h(r.item)}</div>
        <div class="meta">${qty(r.qty, r.unit)} at ₹${nf2.format(r.rate)}${r.in_hand !== null ? `, ${qty(r.in_hand, r.unit)} in hand` : ""}</div>
        <div class="daybar"><span style="width:${Math.max(1, r.share)}%"></span></div></div>
        <div class="end">${money(r.value)}<div class="meta">${r.margin === null ? "margin n/a" : `<span class="${r.margin >= 0 ? "up" : "down"}">${r.margin}% margin</span>`}</div></div><span class="chev"></span></a>`).join("") || '<div class="empty">No item sales in this period.</div>'}
      </section>
      <p class="note" style="border:0">Margin compares the average selling rate with the average purchase rate of the item (or its stock rate when there were no purchases). It's an estimate, not Tally's exact gross profit.</p>
      <div class="actions" style="padding:0 0 12px">${excelBtn("a_items", periodParams())}</div>`;
    view.innerHTML = tabs + html; wirePeriod(d.from, d.to);
  } else if (t === "years") {
    const d = await api(cpath("a_years"));
    const mon = (m) => MON[+m - 1];
    const ch = d.last_total ? Math.round((d.this_total - d.last_total) / d.last_total * 1000) / 10 : null;
    html = `<section class="page"><div class="hero"><div><div class="label">Sales ${d.this_label}</div><div class="big">${short(d.this_total)}</div></div>
        <div><div class="label">${d.last_label}</div><div class="big" style="font-size:22px">${d.has_prev ? short(d.last_total) : "not synced"}</div></div></div>
        ${ch !== null ? `<div class="note">${ch >= 0 ? "Up" : "Down"} ${Math.abs(ch)}% on last year so far (last year's figure is the full year).</div>` : ""}
        <div class="chart" id="ychart"></div>
        <div class="legend"><span><i style="background:var(--bar)"></i>${d.this_label}</span><span><i style="background:var(--bar2)"></i>${d.last_label}</span></div></section>
      <section class="page"><div class="block-title"><span>Month</span><span>${d.this_label} / ${d.last_label}</span></div>
      ${d.months.map((m) => { const c = m.last ? Math.round((m.this - m.last) / m.last * 100) : null;
        return `<div class="row" style="cursor:default"><div class="main name">${mon(m.month)}</div><div class="end">${money(m.this)}<div class="meta">${d.has_prev ? money(m.last) : ""}${c !== null && m.this ? ` <span class="${c >= 0 ? "up" : "down"}">${c >= 0 ? "▲" : "▼"}${Math.abs(c)}%</span>` : ""}</div></div></div>`; }).join("")}
      </section>
      ${d.has_prev ? "" : '<p class="note" style="border:0">Last year isn\'t synced. To compare, run Setup on the Tally PC with an earlier from-date.</p>'}`;
    view.innerHTML = tabs + html;
    drawYears($("#ychart"), d.months);
  } else {
    S.slowDays = S.slowDays || 60;
    const d = await api(cpath("a_slow", { days: S.slowDays }));
    html = `<div class="toolbar">${[30, 60, 90, 180].map((n) => `<button class="chip ${n === S.slowDays ? "on" : ""}" data-days="${n}">${n}+ days</button>`).join("")}</div>
      <section class="page"><div class="hero" style="grid-template-columns:1fr"><div class="label">Stock not sold for ${d.days}+ days</div><div class="big owe">${short(d.value)}</div>
        <div class="label">${d.items.length} items</div></div></section>
      <section class="page">${d.items.map((i) => `<a class="row" href="#/item/${enc(i.name)}"><div class="main"><div class="name">${h(i.name)}</div>
        <div class="meta">${qty(i.closing_qty, i.unit)} in hand, ${i.last_out ? `last sold ${fdate(i.last_out)} (${i.idle} days)` : "no sale in synced data"}</div></div>
        <div class="end">${money(i.closing_value)}</div><span class="chev"></span></a>`).join("") || '<div class="empty">Every item in stock has sold recently.</div>'}</section>
      <div class="actions" style="padding:0 0 12px">${excelBtn("a_slow", { days: S.slowDays })}</div>`;
    view.innerHTML = tabs + html;
    view.querySelectorAll("[data-days]").forEach((b) => b.onclick = () => { S.slowDays = +b.dataset.days; vAnalysis().catch(fail); });
  }
}

/* two series, grouped bars: this year (brand red) beside last year (light) */
function drawYears(el, rows) {
  const W = Math.max(280, el.clientWidth - 16), H = 160, padB = 22, padT = 10;
  const max = Math.max(1, ...rows.map((r) => Math.max(r.this, r.last)));
  const slot = W / rows.length, bw = Math.max(3, (slot - 6) / 2);
  const bars = rows.map((r, i) => {
    const x0 = i * slot + (slot - bw * 2 - 2) / 2;
    const one = (v, x, fill, label) => { const hh = Math.max(v > 0 ? 2 : 0, (v / max) * (H - padB - padT)); const y = H - padB - hh, rad = Math.min(3, bw / 2, hh);
      return hh ? `<path d="M${x},${H - padB} V${y + rad} Q${x},${y} ${x + rad},${y} H${x + bw - rad} Q${x + bw},${y} ${x + bw},${y + rad} V${H - padB} Z" fill="${fill}"><title>${label}: ${rupees(v, false)}</title></path>` : ""; };
    return one(r.last, x0, "var(--bar2)", MON[+r.month - 1] + " last year") + one(r.this, x0 + bw + 2, "var(--bar)", MON[+r.month - 1] + " this year") +
      `<text x="${i * slot + slot / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${MON[+r.month - 1][0]}</text>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" aria-label="Monthly sales, this year against last year"><line x1="0" x2="${W}" y1="${H - padB}" y2="${H - padB}" stroke="var(--rule)"/>${bars}</svg>`;
}

async function vCheck() {
  setTitle(true);
  const d = await api(cpath("check"));
  const B = d.balances || { checked: 0, issues: [] };
  const mon = (m) => { const [yy, mm] = m.split("-"); return `${MON[+mm - 1]} ${yy}`; };
  view.innerHTML = `<h1 class="title">Sync check</h1>
    <section class="page"><div class="block-title"><span>Ledger balances against Tally</span><span>${B.checked ? `${B.checked} month-ends` : ""}</span></div>
      ${!B.checked ? '<div class="info">Not checked yet. The Tally PC sends Tally\'s balances at each month-end with the next sync after updating.</div>'
        : !B.issues.length ? `<div class="info">Every ledger's balance matches Tally at every month-end (${B.ledgers} ledgers). No entries are missing.</div>`
        : `<div class="info od">${B.issues.length} difference${B.issues.length > 1 ? "s" : ""} from Tally. Bahi fetches those months again by itself; if a line stays here after the next sync, entries in that month can't be read from Tally. Please report it.</div>
          ${B.issues.map((i) => `<a class="row" href="#/ledger/${enc(i.ledger)}"><div class="main"><div class="name">${h(i.ledger)}</div>
            <div class="meta">${i.months.length > 1 ? `${fdate(i.from)} to ${fdate(i.to)}` : mon(i.months[0])}: Bahi's entries differ from Tally's by this amount${i.refetched ? `. Still different after fetching that month again ${ago(i.refetched)}` : ". Fetching that month again"}</div></div>
            <div class="end">${money(Math.abs(i.amount))}</div><span class="chev"></span></a>`).join("")}`}
    </section>
    <p class="subtitle">${d.unbalanced ? `${d.unbalanced} vouchers had debits and credits that didn't match when they were synced. Open one to compare it with Tally, and report the voucher types below if they look wrong.` : "Every synced voucher's debits and credits match."}</p>
    ${d.groups.map((g) => `<section class="page"><div class="block-title"><span>${h(g.vtype)}</span><span>${g.count} of ${g.of}</span></div>
      ${g.examples.map((v) => `<a class="row" href="#/voucher/${v.id}"><div class="main"><div class="name">${h(v.party || v.vtype)}</div>
        <div class="meta">${fdate(v.date)}, No. ${h(v.number)}</div></div><div class="end"><span class="meta">off by</span> ${money(Math.abs(v.imbalance))}</div><span class="chev"></span></a>`).join("")}
      </section>`).join("")}
    <section class="page"><div class="block-title"><span>Vouchers synced by month</span><span>All / Sales</span></div>
      ${d.months.map((m) => { const [yy, mm] = m.m.split("-"); return `<a class="row" href="#/vouchers" data-month="${m.m}"><div class="main name">${MON[+mm - 1]} ${yy}</div><div class="end">${nf0.format(m.n)} / ${nf0.format(m.sales)}${m.cancelled ? `<div class="meta">${m.cancelled} cancelled</div>` : ""}</div></a>`; }).join("") || '<div class="empty">No vouchers synced yet.</div>'}
    </section>
    <section class="page"><div class="block-title"><span>Vouchers synced by type</span><span>Count</span></div>
      ${d.types.map((t) => `<div class="row" style="cursor:default"><div class="main"><div class="name">${h(t.vtype)}</div>${t.base && t.base !== t.vtype ? `<div class="meta">counted as ${h(t.base)}</div>` : ""}</div><div class="end">${nf0.format(t.n)}</div></div>`).join("")}
    </section>`;
}

async function vSettings() {
  setTitle(true);
  await loadCompanies();
  if (!S.me.owner) return vMySettings();
  const range = (c) => c.first_vch ? `${fdate(c.first_vch)} to ${fdate(c.last_vch)}` : "no vouchers yet";
  let tg = {};
  try { tg = await api("/api/telegram"); } catch (e) {}
  view.innerHTML = `<h1 class="title">Settings</h1>
    <section class="page" id="syncsec"><div class="block-title">Syncing from Tally <span>${{ auto: `every ${S.sync.every} min`, manual: "manual", paused: '<span class="od">paused</span>' }[S.sync.mode]}</span></div>
      <form class="form" id="syncf" style="padding-top:4px">
        <label><span><input type="radio" name="mode" value="auto" ${S.sync.mode === "auto" ? "checked" : ""}> Automatic, every
          <select name="every" style="padding:4px 8px">${[2, 5, 10, 15, 30, 60].map((n) => `<option value="${n}" ${n === S.sync.every ? "selected" : ""}>${n} minutes</option>`).join("")}</select></span></label>
        <label><span><input type="radio" name="mode" value="manual" ${S.sync.mode === "manual" ? "checked" : ""}> Manual: only when I tap Sync now</span></label>
        <label><span><input type="radio" name="mode" value="paused" ${S.sync.mode === "paused" ? "checked" : ""}> Paused: send nothing from Tally</span></label>
        <div class="actions" style="padding:0"><button class="btn primary" type="submit">Save</button>${S.sync.mode !== "paused" ? '<button class="btn" type="button" id="syncnow">Sync now</button>' : ""}</div>
        <p class="hint">${S.sync.mode === "paused" ? "The app shows the figures from the last sync. Entries made on the phone wait until you resume." :
          "The Tally PC checks with the app every 2 minutes while it's on and Tally is open, so Sync now takes up to 2 minutes to start."}</p></form>
      <div class="info" style="padding-top:0"><div>Tally PC files: ${S.sync.agent_version ? `version ${h(S.sync.agent_version)}` : "version not reported yet"}${S.sync.agent_latest && S.sync.agent_version && S.sync.agent_latest !== S.sync.agent_version ? `. Version ${h(S.sync.agent_latest)} is ready${S.sync.agent_auto !== false ? " and installs itself at the PC's next check" : ""}.` : S.sync.agent_latest ? " (up to date)" : ""}</div>
        <label style="display:flex;gap:8px;align-items:center;margin-top:6px"><input type="checkbox" id="agentauto" ${S.sync.agent_auto !== false ? "checked" : ""}> Update the Tally PC files automatically when the server is updated</label></div></section>
    <section class="page" id="tgsec"><div class="block-title">Telegram summary and alerts <span>${tg.configured ? "on" : "off"}</span></div>
      ${tg.configured ? `<form class="form" id="tgf">
        <label><span><input type="checkbox" id="tgdaily" ${tg.daily ? "checked" : ""}> Daily summary at</span><input type="time" id="tgtime" value="${h(tg.time || "09:00")}"></label>
        <label><span><input type="checkbox" id="tgalerts" ${tg.alerts ? "checked" : ""}> Alert me when a payment of at least</span><input type="number" id="tgmin" min="0" step="1000" value="${tg.alert_min}"></label>
        <label><span><input type="checkbox" id="tgstock" ${tg.stock_alerts !== false ? "checked" : ""}> Alert me when stock falls below its minimum or goes negative</span></label>
        <div class="actions" style="padding:0"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" id="tgtest">Send summary now</button><button class="btn danger" type="button" id="tgoff">Turn off</button></div>
        <div class="msg" id="tgmsg" role="status"></div></form>` : `<div class="info" style="padding-top:2px">
        <div>Get yesterday's sales, collections, cash and bank and overdue dues every morning, and a message when a big payment comes in.</div></div>
        <ol class="steps">
          <li>In Telegram, open <b>@BotFather</b>, send <code>/newbot</code>, pick any name. It replies with a <b>token</b>.</li>
          <li>Paste the token below.</li>
          <li>Open your new bot (BotFather gives a link), tap <b>Start</b>, then tap <b>Connect</b> here.</li>
        </ol>
        <form class="form" id="tgc"><label>Bot token<input type="text" id="tgtoken" autocomplete="off" placeholder="123456789:AA..." required></label>
        <button class="btn primary" type="submit">Connect</button><div class="msg" id="tgmsg" role="status"></div></form>`}
    </section>
    <section class="page" id="intsec"></section>
    <section class="page" id="stsec"></section>
    <section class="page" id="bksec"></section>
    <section class="page" id="offsec"></section>
    ${androidSection()}
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
      <div class="actions">${S.sync.mode === "paused" ? "" : `<button class="btn" data-pause="${h(c.name)}" data-on="${c.paused ? "" : "1"}">${c.paused ? "Resume syncing this company" : "Pause syncing this company"}</button>`}
        <button class="btn danger" data-del="${c.id}">Delete all of this company's data</button></div>
      ${c.paused && S.sync.mode !== "paused" ? '<p class="hint" style="padding:0 14px"><span class="od">Syncing is paused for this company.</span></p>' : ""}
      <p class="hint" style="padding:0 14px 14px">If the company is still open in Tally, the next sync copies it again from scratch.</p>
    </section>`).join("")}`;
  const post = async (url, body) => {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || "Failed"); return j;
  };
  if ($("#tgc")) $("#tgc").onsubmit = async (e) => {
    e.preventDefault(); $("#tgmsg").textContent = "Connecting";
    try { const j = await post("/api/telegram/find", { token: $("#tgtoken").value.trim() });
      await post("/api/telegram/test", {}); toast(`Connected to ${j.chat_name || "your chat"}.`); vSettings().catch(fail);
    } catch (err) { $("#tgmsg").textContent = err.message; }
  };
  if ($("#tgf")) {
    $("#tgf").onsubmit = async (e) => {
      e.preventDefault();
      try { await post("/api/telegram", { daily: $("#tgdaily").checked, time: $("#tgtime").value, alerts: $("#tgalerts").checked, alert_min: $("#tgmin").value, stock_alerts: $("#tgstock").checked });
        $("#tgmsg").textContent = "Saved."; } catch (err) { $("#tgmsg").textContent = err.message; }
    };
    $("#tgtest").onclick = async () => { $("#tgmsg").textContent = "Sending";
      try { await post("/api/telegram/test", { cid: S.cid }); $("#tgmsg").textContent = "Sent. Check Telegram."; } catch (err) { $("#tgmsg").textContent = err.message; } };
    $("#tgoff").onclick = async () => { if (!confirm("Stop Telegram messages?")) return; await post("/api/telegram", { off: true }); vSettings().catch(fail); };
  }
  const showBackups = async (b) => {
    b = b || await api("/api/backups").catch(() => null);
    if (!b) return;
    const last = b.backups[0];
    $("#bksec").innerHTML = `<div class="block-title">Backups <span>${b.backups.length} kept</span></div>
      <div class="info"><div>${last ? `Last backup ${ago(last.time)}.` : "No backup yet."} A copy is made every night at ${h(b.at)}, and the last ${b.keep} are kept in the <code>backups</code> folder next to your data on the server.</div>
      <div>Your books are always safe in Tally. The backup saves the synced copy, phone entries, follow-up notes, staff logins and settings, so nothing is lost if the server's disk fails. Download one now and then to keep a copy off the server.</div></div>
      ${b.backups.map((x) => `<div class="row"><div class="main"><div class="name">${new Date(x.time * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}</div><div class="meta">${x.name.includes("before-restore") ? "Saved just before a restore" : "Backup"}, ${(x.size / 1048576).toFixed(1)} MB</div></div>
        <div class="end" style="display:flex;gap:6px"><a class="chip" href="/api/backups/${enc(x.name)}" download>Download</a><button class="chip" data-restore="${h(x.name)}">Restore</button></div></div>`).join("")}
      <div class="actions"><button class="btn" id="bknow">Back up now</button></div>
      <form class="form" id="rsf"><label>Restore from a backup file<input type="file" id="rsfile" accept=".zip" required></label>
        <button class="btn" type="submit">Restore this file</button><p class="meta" id="rsmsg" role="status"></p></form>
      <p class="note" style="border:0">Restoring puts back the synced data, phone entries, follow-up notes, staff logins, settings and the app password as they were in that backup. Bahi first saves a copy of everything as it is now, so a restore can be undone. Nothing in Tally changes, and the next sync brings in anything entered in Tally since the backup.</p>`;
    $("#bknow").onclick = async () => { $("#bknow").textContent = "Backing up"; $("#bknow").disabled = true;
      try { showBackups(await post("/api/backups", {})); toast("Backup made."); } catch (err) { toast(err.message); showBackups(); } };
    const doRestore = async (url, body, label) => {
      if (!confirm(`Restore ${label}?\n\nEverything in Bahi goes back to how it was in that backup. A copy of how things are now is saved first. If the backup has an older app password, you'll log in with that one.`)) return false;
      const r = await fetch(url, { method: "POST", body });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { toast(j.error || "Couldn't restore."); return false; }
      alert(`Restored. The way things were just before is saved as ${j.safety}.`);
      location.hash = "#/"; location.reload();
      return true;
    };
    $("#bksec").querySelectorAll("[data-restore]").forEach((btn) => btn.onclick = () =>
      doRestore(`/api/backups/restore?name=${enc(btn.dataset.restore)}`, null, btn.dataset.restore));
    $("#rsf").onsubmit = async (e) => {
      e.preventDefault();
      const f = $("#rsfile").files[0]; if (!f) return;
      $("#rsmsg").textContent = "Checking the file";
      if (!(await doRestore("/api/backups/restore", f, f.name))) $("#rsmsg").textContent = "";
    };
  };
  showBackups();
  offlineSection();
  showStaff().catch(() => {});
  (async () => {
    const it = await api("/api/interest").catch(() => null);
    if (!it || !$("#intsec")) return;
    $("#intsec").innerHTML = `<div class="block-title">Interest on overdue bills <span>${it.on ? `${it.rate}% p.a.` : "off"}</span></div>
      <form class="form" id="intf">
        <label><span><input type="checkbox" name="on" ${it.on ? "checked" : ""}> Work out interest on overdue customer bills</span></label>
        <label>Rate, % a year<input type="number" name="rate" min="0" max="60" step="0.5" value="${it.rate}"></label>
        <label>Grace days after the due date<input type="number" name="grace" min="0" max="365" step="1" value="${it.grace}"></label>
        <button class="btn primary" type="submit">Save</button>
        <p class="hint">Simple interest from each bill's due date (or its bill date when it has no credit period). It shows on Dues, ledgers and the follow-up list, goes into WhatsApp reminders, and the ledger PDF gets an interest table at the end. Nothing is posted in Tally.</p></form>`;
    $("#intf").onsubmit = async (e) => {
      e.preventDefault(); const f = e.target;
      try { await post("/api/interest", { on: f.on.checked, rate: f.rate.value, grace: f.grace.value }); toast("Saved."); vSettings().catch(fail); } catch (err) { toast(err.message); }
    };
  })();
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
  $("#syncf").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target, mode = f.querySelector("[name=mode]:checked").value;
    try { await post("/api/sync", { mode, every: +f.every.value }); } catch (err) { toast(err.message); return; }
    toast({ auto: `Syncing every ${f.every.value} minutes.`, manual: "Manual sync: tap Sync now when you want fresh figures.", paused: "Syncing paused. Nothing more is sent from Tally until you resume." }[mode]);
    await loadCompanies(); renderCover(); vSettings().catch(fail);
  };
  if ($("#syncnow")) $("#syncnow").onclick = () => syncNow();
  $("#agentauto").onchange = async (e) => { await post("/api/sync", { agent_auto: e.target.checked }); toast(e.target.checked ? "The Tally PC will update itself." : "Automatic updates of the Tally PC are off."); };
  view.querySelectorAll("[data-pause]").forEach((b) => b.onclick = async () => {
    await post("/api/sync", { company: b.dataset.pause, paused: !!b.dataset.on });
    toast(b.dataset.on ? "Syncing paused for this company." : "Syncing resumed for this company.");
    await loadCompanies(); renderCover(); vSettings().catch(fail);
  });
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

function vMySettings() {
  view.innerHTML = `<h1 class="title">Settings</h1><p class="subtitle">Logged in as ${h(S.me.name)}</p>
    <section class="page"><div class="block-title">Change your password</div>
      <form id="pwf" class="form">
        <label>Current password<input type="password" id="pw0" autocomplete="current-password" required></label>
        <label>New password<input type="password" id="pw1" autocomplete="new-password" minlength="6" required></label>
        <label>New password again<input type="password" id="pw2" autocomplete="new-password" minlength="6" required></label>
        <button class="btn primary" type="submit">Change password</button><div class="msg" id="pwmsg" role="status"></div>
        <p class="hint">Forgot it? Ask the owner to set a new one.</p></form></section>
    <section class="page" id="offsec"></section>${androidSection()}`;
  offlineSection();
  $("#pwf").onsubmit = async (e) => {
    e.preventDefault();
    const msg = $("#pwmsg");
    if ($("#pw1").value !== $("#pw2").value) { msg.textContent = "The two new passwords don't match."; return; }
    const r = await fetch("/api/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current: $("#pw0").value, new: $("#pw1").value }) });
    const j = await r.json().catch(() => ({}));
    msg.textContent = r.ok ? "Password changed." : (j.error || "Couldn't change the password.");
    if (r.ok) $("#pwf").reset();
  };
}

/* ---------------------------------------------------------------- staff logins (owner) */
const PRESETS = { Salesman: ["parties", "dues", "stock", "e_receipt", "e_order"], Accountant: ["accounts", "sales", "ledgers", "vouchers", "dues", "stock", "e_receipt", "e_payment", "e_order"] };
async function showStaff() {
  const d = await api("/api/users");
  const sec = $("#stsec");
  if (!sec) return;
  const label = Object.fromEntries(d.perms);
  const permBoxes = (sel, id) => d.perms.map(([k, l]) => `<label><span><input type="checkbox" name="perm" value="${k}" ${sel.includes(k) ? "checked" : ""}> ${h(l)}</span></label>`).join("");
  const coBoxes = (sel) => S.companies.length > 1 ? `<div class="block-title" style="padding:6px 0 0">Companies</div>
      <label><span><input type="checkbox" name="allco" ${!sel.length ? "checked" : ""}> All companies</span></label>
      ${S.companies.map((c) => `<label><span><input type="checkbox" name="co" value="${h(c.name)}" ${sel.includes(c.name) ? "checked" : ""}> ${h(c.name)}</span></label>`).join("")}` : "";
  const summary = (u) => u.perms.filter((p) => !p.startsWith("e_")).map((p) => ({ accounts: "money figures", sales: "sales", ledgers: "all ledgers", parties: "party ledgers", vouchers: "vouchers", dues: "dues", stock: "stock" }[p])).join(", ") +
    (u.perms.some((p) => p.startsWith("e_") && p !== "e_direct") ? `; enters ${u.perms.filter((p) => ["e_receipt", "e_payment", "e_order"].includes(p)).map((p) => ({ e_receipt: "receipts", e_payment: "payments", e_order: "orders" }[p])).join(", ")}${u.perms.includes("e_direct") ? " (no approval)" : ""}` : "");
  sec.innerHTML = `<div class="block-title">Staff logins <span>${d.users.length}</span></div>
    <div class="info"><div>Staff log in with their name and their own password, and see only what you tick. You always log in with the app password and see everything.</div></div>
    ${d.users.map((u, i) => `<div class="party"><button class="row" aria-expanded="false" data-su="${i}"><div class="main"><div class="name">${h(u.name)}${u.active ? "" : ' <span class="badge">switched off</span>'}</div>
        <div class="meta">${h(summary(u) || "nothing ticked yet")}</div><div class="meta">${u.last_login ? `Last logged in ${ago(u.last_login)}` : "Hasn't logged in yet"}</div></div><span class="chev down"></span></button>
      <div class="bills" id="su${i}" hidden><form class="form staff" data-name="${h(u.name)}" style="padding:12px 14px 14px">
        ${permBoxes(u.perms)}${coBoxes(u.companies)}
        <label>New password (leave empty to keep)<input type="text" name="password" autocomplete="off" minlength="6"></label>
        <div class="actions" style="padding:0"><button class="btn primary" type="submit">Save</button>
          <button class="btn" type="button" data-toggle>${u.active ? "Switch off" : "Switch on"}</button><button class="btn danger" type="button" data-remove>Remove</button></div>
      </form></div></div>`).join("")}
    <div class="party"><button class="row" aria-expanded="false" data-su="new"><div class="main"><div class="name">+ Add a staff member</div></div><span class="chev down"></span></button>
      <div class="bills" id="sunew" hidden><form class="form staff" data-new="1" style="padding:12px 14px 14px">
        <label>Name they log in with<input type="text" name="name" required maxlength="40" autocomplete="off"></label>
        <label>Password<input type="text" name="password" required minlength="6" autocomplete="off"></label>
        <div class="actions" style="padding:0">Quick pick: ${Object.keys(PRESETS).map((k) => `<button class="chip" type="button" data-preset="${k}">${k}</button>`).join("")}</div>
        ${permBoxes([])}${coBoxes([])}
        <button class="btn primary" type="submit">Add</button></form></div></div>
    <p class="hint" style="padding:0 14px 14px">Staff entries wait for your approval in <b>Entries from phone</b> unless you tick the last box. Switching someone off or giving a new password logs them out at once.</p>`;
  sec.querySelectorAll("[data-su]").forEach((b) => b.onclick = () => {
    const el = document.getElementById("su" + b.dataset.su); el.hidden = !el.hidden;
    b.setAttribute("aria-expanded", String(!el.hidden)); b.querySelector(".chev").classList.toggle("up", !el.hidden);
  });
  const send = async (body) => {
    const r = await fetch("/api/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { toast(j.error || "Couldn't save."); return false; }
    showStaff(); return true;
  };
  const read = (f) => {
    const perms = [...f.querySelectorAll("[name=perm]:checked")].map((x) => x.value);
    const all = f.querySelector("[name=allco]");
    const companies = !all || all.checked ? [] : [...f.querySelectorAll("[name=co]:checked")].map((x) => x.value);
    return { perms, companies };
  };
  sec.querySelectorAll("form.staff").forEach((f) => {
    f.querySelectorAll("[data-preset]").forEach((b) => b.onclick = () => {
      const set = PRESETS[b.dataset.preset]; f.querySelectorAll("[name=perm]").forEach((x) => x.checked = set.includes(x.value)); });
    f.onsubmit = async (e) => {
      e.preventDefault();
      const body = { ...read(f), password: f.password.value || undefined };
      if (f.dataset.new) Object.assign(body, { name: f.name.value, new: true }); else body.name = f.dataset.name;
      if (await send(body)) toast(f.dataset.new ? `${body.name} added. Tell them their name and password.` : "Saved.");
    };
    const tg = f.querySelector("[data-toggle]");
    if (tg) tg.onclick = () => send({ name: f.dataset.name, active: tg.textContent === "Switch on" });
    const rm = f.querySelector("[data-remove]");
    if (rm) rm.onclick = () => confirm(`Remove ${f.dataset.name}? Their entries stay.`) && send({ name: f.dataset.name, remove: true });
  });
}

/* ---------------------------------------------------------------- staff home */
async function vStaffHome() {
  const tiles = [["#/dues", "Dues", "Who owes what, with bills", can("dues")], ["#/collect", "Follow-up list", "Overdue and due this week", can("dues")],
    ["#/parties", "Ledgers", can("ledgers") ? "All ledgers" : "Customers and suppliers", canLedgers()], ["#/stock", "Stock", "Items in hand", can("stock")],
    ["#/sales", "Sales by day", "Daily sales", can("sales")], ["#/vouchers", "Vouchers", "Search any voucher", can("vouchers")]].filter((t) => t[3]);
  view.innerHTML = `<h1 class="title">Hello, ${h(S.me.name)}</h1>${entryBar()}
    <section class="page">${tiles.map(([href, n, m]) => `<a class="row" href="${href}"><div class="main"><div class="name">${n}</div><div class="meta">${m}</div></div><span class="chev"></span></a>`).join("")
      || '<div class="empty">The owner hasn\'t given you access to anything yet.</div>'}</section>`;
}

/* ---------------------------------------------------------------- entries from the phone */
const EST = { approval: ["Waiting for owner's approval", ""], queued: ["Waiting for the Tally PC", ""], sending: ["Being added to Tally", ""],
  done: ["In Tally", "ok"], failed: ["Tally didn't accept it", "bad"], rejected: ["Rejected by owner", "bad"], cancelled: ["Cancelled", ""] };
async function vEntries() {
  setTitle(true);
  const d = await api(cpath("entries"));
  const me = S.me.owner ? "Owner" : S.me.name;
  view.innerHTML = `<h1 class="title">Entries from phone</h1>${entryBar()}
    <section class="page">${d.entries.map((e) => {
      const x = e.data, [st, cls] = EST[e.status] || [e.status, ""];
      const detail = e.kind === "order" ? x.items.map((i) => `${h(i.item)}: ${nfq.format(i.qty)} ${h(i.unit)} at ₹${nf2.format(i.rate)}`).join("<br>")
        : `${e.kind === "receipt" ? "Into" : "From"} ${h(x.account)}${x.bills.length ? `, against ${x.bills.map((b) => h(b.ref)).join(", ")}` : ""}`;
      const btn = [];
      if (S.me.owner && e.status === "approval") btn.push(`<button class="btn primary" data-act="approve" data-id="${e.id}">Approve</button><button class="btn" data-act="reject" data-id="${e.id}">Reject</button>`);
      if (e.status === "failed" && (S.me.owner || e.by === me)) btn.push(`<button class="btn" data-act="retry" data-id="${e.id}">Try again</button>`);
      if (["approval", "queued", "failed"].includes(e.status) && (S.me.owner || e.by === me)) btn.push(`<button class="btn" data-act="cancel" data-id="${e.id}">Cancel</button>`);
      return `<div class="entry"><div class="row" style="cursor:default"><div class="main"><div class="name">${h(x.vtype)}: ${h(x.party)}</div>
          <div class="meta">${fdate(x.date)}, by ${h(e.by)}${e.approved_by && e.approved_by !== e.by ? `, approved by ${h(e.approved_by)}` : ""}</div>
          <div class="meta">${detail}${x.narration ? `<br><i>${h(x.narration)}</i>` : ""}</div>
          <div class="meta"><span class="est ${cls}">${st}</span>${e.status === "done" && e.done ? ` ${ago(e.done)}` : ""}</div>
          ${e.error ? `<div class="meta od">${h(e.error)}</div>` : ""}</div>
        <div class="end">${money(x.amount)}</div></div>${btn.length ? `<div class="actions" style="padding:0 14px 12px">${btn.join("")}</div>` : ""}</div>`;
    }).join("") || '<div class="empty">No entries made in the app yet.</div>'}</section>
    <p class="note" style="border:0">Entries go into Tally the next time the Tally PC syncs (every 10 minutes while Tally is open), then show up in the app like any other voucher. Each has "entered on phone by …" in its narration.</p>`;
  view.querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    if (b.dataset.act === "reject" && !confirm("Reject this entry? It won't go into Tally.")) return;
    b.disabled = true;
    const r = await fetch(cpath(`entry/${b.dataset.id}/${b.dataset.act}`), { method: "POST" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) toast(j.error || "Couldn't do that.");
    await loadCompanies().catch(() => {}); vEntries().catch(fail);
  });
}

async function vNewEntry(kind) {
  setTitle(true);
  if (!ENTRY[kind] || !can(ENTRY[kind][1])) { view.innerHTML = '<div class="empty">You can\'t make this kind of entry.</div>'; return; }
  const f = await api(cpath("entry_form", { kind }));
  const order = kind === "order", rec = kind === "receipt";
  const list = (id, arr) => `<datalist id="${id}">${arr.map((x) => `<option value="${h(x)}">`).join("")}</datalist>`;
  const sel = (name, arr) => `<select name="${name}">${arr.map((x) => `<option>${h(x)}</option>`).join("")}</select>`;
  view.innerHTML = `<h1 class="title">New ${ENTRY[kind][0].toLowerCase()}</h1>
    <section class="page"><form class="form" id="ef" style="padding-top:14px" autocomplete="off">
      ${f.vtypes.length > 1 ? `<label>Voucher type${sel("vtype", f.vtypes)}</label>` : ""}
      <label>Date<input type="date" name="date" value="${f.today}" required></label>
      <label>${order ? "Customer" : rec ? "Received from" : "Paid to"}<input name="party" list="plist" required placeholder="Start typing a name">${list("plist", f.parties)}</label>
      ${order ? `
        <div id="items"></div><button class="btn" type="button" id="additem">+ Add item</button>${list("ilist", f.items.map((i) => i.name))}
        <div class="total">Total before tax <b id="otot">₹0</b></div>
        <label>Deliver by (optional)<input type="date" name="due"></label>
        ${f.sales_ledgers.length > 1 ? `<label>Sales ledger${sel("sales_ledger", f.sales_ledgers)}</label>` : ""}
        <p class="hint">GST is added when the order is turned into an invoice in Tally.</p>`
      : `<label>${rec ? "Into" : "From"}${sel("account", f.accounts)}</label>
        <div id="bills"></div>
        <label>Amount (₹)<input type="number" name="amount" min="0.01" step="0.01" inputmode="decimal" required></label>`}
      <label>Narration (optional)<input name="narration" maxlength="500" placeholder="${order ? "e.g. Deliver to shop" : "e.g. Cheque no. 12345"}"></label>
      <button class="btn primary" type="submit">Save</button><div class="msg" id="emsg" role="status"></div>
      <p class="hint">${S.me.owner || can("e_direct") ? "It goes into Tally the next time the Tally PC syncs." : "The owner approves it first, then it goes into Tally at the next sync."}</p>
    </form></section>`;
  const form = $("#ef");
  if (order) {
    const items = Object.fromEntries(f.items.map((i) => [i.name, i]));
    const add = () => {
      const row = document.createElement("div"); row.className = "irow";
      row.innerHTML = `<label>Item<input name="item" list="ilist" placeholder="Start typing an item"></label>
        <div class="two"><label>Qty<input name="qty" type="number" min="0" step="any" inputmode="decimal"></label><label>Rate<input name="rate" type="number" min="0" step="0.01" inputmode="decimal"></label></div>
        <div class="meta" data-info></div>`;
      $("#items").appendChild(row);
      row.querySelector("[name=item]").onchange = (e) => {
        const it = items[e.target.value]; const r = row.querySelector("[name=rate]");
        row.querySelector("[data-info]").textContent = it ? `${nfq.format(it.in_hand || 0)} ${it.unit} in hand` : "Pick an item from the list";
        if (it && !r.value) r.value = it.rate || "";
        tot();
      };
      row.oninput = tot;
    };
    const tot = () => {
      let t = 0;
      $("#items").querySelectorAll(".irow").forEach((r) => { t += (+r.querySelector("[name=qty]").value || 0) * (+r.querySelector("[name=rate]").value || 0); });
      $("#otot").textContent = rupees(t);
    };
    $("#additem").onclick = add; add();
  } else {
    let typed = false;
    form.amount.oninput = () => { typed = true; };
    form.party.onchange = async () => {
      $("#bills").innerHTML = "";
      if (!f.parties.includes(form.party.value)) return;
      const b = await api(cpath("party_bills", { name: form.party.value })).catch(() => ({ bills: [] }));
      if (!b.bills.length) return;
      $("#bills").innerHTML = `<div class="block-title" style="padding:4px 0 0">Against bills (optional)</div>
        ${b.bills.map((x, i) => `<div class="pbill"><label><span><input type="checkbox" data-b="${i}"> ${h(x.ref)} <span class="meta">${x.date ? fdate(x.date) : ""}${x.overdue ? `, ${x.overdue} days overdue` : ""}</span></span></label>
          <input type="number" step="0.01" min="0" data-ba="${i}" value="${x.amount}" aria-label="Amount against ${h(x.ref)}"></div>`).join("")}
        <p class="hint">Tick the bills this ${rec ? "receipt" : "payment"} settles. Anything left over goes "on account".</p>`;
      const sum = () => {
        if (typed) return;
        let t = 0; $("#bills").querySelectorAll("[data-b]:checked").forEach((c) => { t += +$("#bills").querySelector(`[data-ba="${c.dataset.b}"]`).value || 0; });
        form.amount.value = t ? t.toFixed(2) : "";
      };
      $("#bills").oninput = sum; $("#bills").onchange = sum;
      $("#bills")._bills = b.bills;
    };
  }
  form.onsubmit = async (e) => {
    e.preventDefault();
    const body = { kind, date: form.date.value, party: form.party.value, narration: form.narration.value, vtype: form.vtype ? form.vtype.value : undefined };
    if (order) {
      body.items = [...$("#items").querySelectorAll(".irow")].map((r) => ({ item: r.querySelector("[name=item]").value, qty: r.querySelector("[name=qty]").value, rate: r.querySelector("[name=rate]").value })).filter((i) => i.item);
      body.due = form.due.value; body.sales_ledger = form.sales_ledger ? form.sales_ledger.value : undefined;
    } else {
      body.account = form.account.value; body.amount = form.amount.value;
      const bl = $("#bills")._bills || [];
      body.bills = [...$("#bills").querySelectorAll("[data-b]:checked")].map((c) => ({ ref: bl[c.dataset.b].ref, amount: $("#bills").querySelector(`[data-ba="${c.dataset.b}"]`).value }));
    }
    const btn = form.querySelector("button[type=submit]"); btn.disabled = true; $("#emsg").textContent = "Saving";
    const r = await fetch(cpath("entry"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    btn.disabled = false;
    if (!r.ok) { $("#emsg").textContent = j.error || "Couldn't save."; return; }
    toast(j.entry.status === "approval" ? "Saved. It goes to the owner for approval." : "Saved. It goes into Tally at the next sync.");
    location.hash = "#/entries";
  };
}

function fyStart(day) {
  const d = new Date((day || iso(new Date())) + "T00:00:00");
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${y}-04-01`;
}

/* ---------------------------------------------------------------- Tally-style P&L and Balance Sheet
   Two sides like Tally: each heading with its total on the right, details (italic) in an inner column.
   Side by side on a computer, one under the other on a phone. Tap a heading to open its details. */
function tamt(n) { return n < 0 ? `(-)${nf2.format(-n)}` : nf2.format(n); }
function tallySide(title, sub, rows, total, key) {
  const body = rows.map((g, i) => {
    const id = `${key}${i}`;
    const lines = (g.lines || []).map((l) => {
      const href = l.stock ? "#/stock" : g.pl ? "" : l.group ? `#/group/${enc(l.name)}` : `#/ledger/${enc(l.name)}`;
      const inner = `<span class="tn">${h(l.name)}</span><span class="ti">${tamt(l.amount)}</span><span class="to"></span>`;
      return href ? `<a class="tl sub" href="${href}">${inner}</a>` : `<div class="tl sub">${inner}</div>`;
    }).join("");
    const label = `${h(g.name)}${g.approx ? ' <span class="approx" title="Worked out at average rates">≈</span>' : ""}`;
    if (g.result) return `<div class="tl res"><span class="tn">${label}</span><span class="ti"></span><span class="to">${tamt(g.amount)}</span></div>`;
    if (g.stock) return `<a class="tl grp" href="#/stock"><span class="tn">${label}</span><span class="ti"></span><span class="to">${tamt(g.amount)}</span></a>`;
    if (g.ledger) return `<a class="tl grp" href="#/ledger/${enc(g.name)}"><span class="tn">${label}</span><span class="ti"></span><span class="to">${tamt(g.amount)}</span></a>`;
    return `<button class="tl grp" aria-expanded="${S.tdetail ? "true" : "false"}" data-tx="${id}"><span class="tn">${label}</span><span class="ti"></span><span class="to">${tamt(g.amount)}</span></button>
      <div class="tdet" id="${id}" ${S.tdetail ? "" : "hidden"}>${lines}</div>`;
  }).join("");
  return `<div class="tside"><div class="thead"><span>${title}</span><span>${sub}</span></div><div class="tbody">${body}</div>
    <div class="ttot"><span class="tn">Total</span><span class="ti"></span><span class="to">${tamt(total)}</span></div></div>`;
}
function wireTally() {
  view.querySelectorAll("[data-tx]").forEach((b) => b.onclick = () => {
    const el = document.getElementById(b.dataset.tx); el.hidden = !el.hidden; b.setAttribute("aria-expanded", String(!el.hidden));
  });
  const t = $("#tdetail");
  if (t) t.onclick = () => { S.tdetail = !S.tdetail; route(); };
}
const tdate = (iso) => { const [y, m, d] = iso.split("-"); return `${+d}-${MON[+m - 1]}-${y}`; };

async function vPL() {
  setTitle(true);
  const d = await api(cpath("pl", periodParams()));
  const co = S.companies.find((c) => c.id === S.cid)?.name || "";
  const per = `${tdate(d.from)} to ${tdate(d.to)}`;
  view.innerHTML = `<div class="treport-head"><div class="tco">${h(co)}</div><div class="ttitle">Profit &amp; Loss A/c</div><div class="tper">${per}</div></div>
    ${periodBar(d.from, d.to)}
    <div class="actions" style="padding:0 0 10px"><button class="chip ${S.tdetail ? "on" : ""}" id="tdetail">${S.tdetail ? "Detailed" : "Condensed"}: tap to switch</button></div>
    <div class="treport">
      <div class="tblock">${tallySide("Particulars", per, d.trading.dr, d.trading.total, "td")}${tallySide("Particulars", per, d.trading.cr, d.trading.total, "tc")}</div>
      <div class="tblock">${tallySide("Particulars", "", d.pl.dr, d.pl.total, "pd")}${tallySide("Particulars", "", d.pl.cr, d.pl.total, "pc")}</div>
    </div>
    <p class="note" style="border:0">Laid out like Tally: expenses on the left, incomes on the right, Gross Profit carried down to the Nett Profit. Groups go where Tally puts them, including groups you made.${d.stock_exact ? "" : " Stock marked ≈ is valued at average rates for the dates chosen, so it can differ a little from Tally."}</p>`;
  wirePeriod(d.from, d.to); wireTally();
}

async function vBS() {
  setTitle(true);
  const d = await api(cpath("bs"));
  const co = S.companies.find((c) => c.id === S.cid)?.name || "";
  const at = `as at ${tdate(d.as_at)}`;
  view.innerHTML = `<div class="treport-head"><div class="tco">${h(co)}</div><div class="ttitle">Balance Sheet</div><div class="tper">${at}</div></div>
    <div class="actions" style="padding:0 0 10px"><button class="chip ${S.tdetail ? "on" : ""}" id="tdetail">${S.tdetail ? "Detailed" : "Condensed"}: tap to switch</button></div>
    <div class="treport"><div class="tblock">${tallySide("Liabilities", at, d.liabilities, d.total, "bl")}${tallySide("Assets", at, d.assets, d.total, "ba")}</div></div>
    <p class="note" style="border:0">From Tally's closing balances at the last sync. Profit &amp; Loss A/c shows this year's profit (Current Period, from ${tdate(d.period_from)}) and everything before it (Opening Balance).${d.unbalanced ? ` ${d.unbalanced} vouchers didn't add up at the last sync (see Sync check), which can make these figures a little off.` : ""}${d.stock_in_ledgers ? " Closing stock is taken from your stock ledgers." : ""}</p>`;
  wireTally();
}

/* ---------------------------------------------------------------- cash and bank book */
async function vCashbook() {
  setTitle(true);
  const d = await api(cpath("cashbank", periodParams()));
  view.innerHTML = `<h1 class="title">Cash and bank book</h1>${periodBar(d.from, d.to)}
    <section class="page"><div class="hero"><div><div class="label">Opening, ${fdate(d.from)}</div><div class="big" style="font-size:22px">${short(d.opening)}</div></div>
      <div><div class="label">Closing, ${fdate(d.to)}</div><div class="big">${short(d.closing)}</div></div>
      <div><div class="label">Money in</div><div class="big" style="font-size:20px;color:var(--good)">${short(d.in)}</div></div>
      <div><div class="label">Money out</div><div class="big owe" style="font-size:20px">${short(d.out)}</div></div></div>
      <div class="note">Money in and out of each account includes transfers between your own cash and bank accounts.</div></section>
    <section class="page"><div class="block-title"><span>Account</span><span>Closing</span></div>
      ${d.ledgers.map((l) => `<a class="row" href="#/ledger/${enc(l.name)}"><div class="main"><div class="name">${h(l.name)}</div>
        <div class="meta">${l.kind}. Opening ${short(l.opening)}, in ${short(l.in)}, out ${short(l.out)}</div></div><div class="end">${drcr(l.closing)}</div><span class="chev"></span></a>`).join("") || '<div class="empty">No cash or bank ledgers found.</div>'}</section>
    <section class="page"><div class="block-title"><span>Day</span><span>In / out, closing</span></div>
      ${d.days.map((x, i) => `<div class="party"><button class="row" aria-expanded="false" data-cd="${i}"><div class="main"><div class="name">${fdate(x.date)}</div>
          <div class="meta">${x.in ? `<span class="up">+${money(x.in)}</span> ` : ""}${x.out ? `<span class="down">−${money(x.out)}</span>` : ""}${!x.in && !x.out ? "transfers only" : ""}</div></div>
          <div class="end">${money(x.closing)}<div class="meta">opening ${money(x.opening)}</div></div><span class="chev down"></span></button>
        <div class="bills" id="cd${i}" hidden></div></div>`).join("")
        || '<div class="empty">No cash or bank entries in this period.</div>'}</section>`;
  const entries = (x) => x.entries.map((e) => `<a class="row" href="#/voucher/${e.id}"><div class="main"><div class="name">${h(e.party || e.vtype)}</div>
          <div class="meta">${h(e.vtype)} ${h(e.number)}, ${e.transfer ? "transfer between " + e.ledgers.map(h).join(" and ") : h(e.ledgers.join(", "))}</div></div>
          <div class="end ${e.amount < 0 ? "down" : e.transfer ? "" : "up"}">${e.transfer ? "transfer" : (e.amount < 0 ? "−" : "+") + money(Math.abs(e.amount))}</div></a>`).join("");
  wirePeriod(d.from, d.to);
  view.querySelectorAll("[data-cd]").forEach((b) => b.onclick = () => {
    const el = document.getElementById("cd" + b.dataset.cd);
    if (!el.innerHTML) el.innerHTML = entries(d.days[+b.dataset.cd]);
    el.hidden = !el.hidden;
    b.setAttribute("aria-expanded", String(!el.hidden)); b.querySelector(".chev").classList.toggle("up", !el.hidden);
  });
}

/* ---------------------------------------------------------------- collection follow-up */
async function vCollect() {
  setTitle(true);
  S.cf = S.cf || "all";
  const d = await api(cpath("collections"));
  try { const it = await api("/api/interest"); S.irate = it.on ? it.rate : 0; } catch (e) { S.irate = 0; }
  const co = S.companies.find((c) => c.id === S.cid)?.name || "";
  const F = { all: ["Everyone", () => true], overdue: ["Overdue", (p) => p.overdue > 0.5], week: ["Due this week", (p) => p.due_soon > 0.5],
    promised: ["Promised", (p) => p.promise] };
  const list = d.parties.filter(F[S.cf][1]);
  const bill = (b, txt, late) => {
    const inner = `<div><div class="ref">${h(b.ref)}</div><div class="meta">${b.date ? fdate(b.date) : ""}${b.due ? `, due ${fdate(b.due)}` : ""}</div></div>
      <div class="end">${money(b.amount)}<div class="meta">${late ? `<span class="od">${txt}</span>` : txt}</div></div>${b.vid ? '<span class="chev"></span>' : ""}`;
    return b.vid ? `<a class="bill" href="#/voucher/${b.vid}">${inner}</a>` : `<div class="bill">${inner}</div>`;
  };
  view.innerHTML = `<h1 class="title">Follow-up list</h1>
    <div class="toolbar" role="group" aria-label="Show">${Object.entries(F).map(([k, [l]]) => `<button class="chip ${k === S.cf ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}</div>
    <section class="page"><div class="hero"><div><div class="label">Overdue</div><div class="big owe">${short(d.overdue)}</div></div>
      <div><div class="label">Falling due in ${d.days} days</div><div class="big">${short(d.due_soon)}</div></div></div>
      ${d.promised_today.length ? `<div class="note">Promised to pay today: <b>${d.promised_today.map(h).join(", ")}</b></div>` : ""}</section>
    <section class="page">${list.map((p, i) => {
      const ph = digits(p.mobile || p.phone);
      const od = p.overdue_bills.map((b) => ({ ...b, overdue: b.late }));
      const status = p.promise_missed ? `<span class="od">promised ${fdate(p.promise)}, not paid</span>` :
        p.promise ? `promised ${fdate(p.promise)}` : "";
      return `<div class="party"><button class="row" aria-expanded="false" data-c="${i}"><div class="main"><div class="name">${h(p.name)}</div>
          <div class="meta">${p.overdue > 0.5 ? `<span class="od">${rupees(p.overdue, false)} overdue</span>, up to ${p.late} days late` : `${rupees(p.due_soon, false)} due this week`}${p.interest > 0.5 ? `, interest ${rupees(p.interest, false)}` : ""}${status ? `, ${status}` : ""}</div>
          ${p.note ? `<div class="meta notep">${h(p.note)}</div>` : ""}</div>
          <div class="end">${money(p.balance)}<div class="meta">balance</div></div><span class="chev down"></span></button>
        <div class="bills" id="cb${i}" hidden>
          <div class="actions" style="padding:12px 14px 4px">
              ${ph ? `<a class="btn wa" href="https://wa.me/${ph}?text=${enc(reminderText(p.name, co, p.balance, od, p.interest, S.irate || 0))}" target="_blank" rel="noopener">${ICON.wa}Remind</a><a class="btn" href="tel:+${ph}">${ICON.call}Call</a>` : ""}
              <a class="btn" href="#/ledger/${enc(p.name)}">Ledger</a></div>
          <form class="form fu" data-party="${h(p.name)}" style="padding:8px 14px 14px">
            <div class="block-title" style="padding:0">Note and promised date</div>
            <label>Note<input type="text" name="note" maxlength="300" value="${h(p.note)}" placeholder="e.g. Will pay half after Diwali"></label>
            <label>Promised to pay on<input type="date" name="promise" value="${h(p.promise)}"></label>
            <div class="actions" style="padding:0"><button class="btn primary" type="submit">Save note</button>${p.note || p.promise ? '<button class="btn" type="button" data-clear>Clear</button>' : ""}</div></form>
          ${(() => {
            const all = [...p.overdue_bills.map((b) => bill(b, `${b.late} days late`, true)), ...p.soon_bills.map((b) => bill(b, b.in_days ? `due in ${b.in_days} days` : "due today"))];
            return `<div style="border-top:1px solid var(--rule)">${all.slice(0, 5).join("")}${all.length > 5 ? `<div hidden data-more>${all.slice(5).join("")}</div><button class="btn" style="margin:10px 14px 12px" data-showmore>Show ${all.length - 5} more bills</button>` : ""}</div>`;
          })()}
        </div></div>`;
    }).join("") || `<div class="empty">${S.cf === "all" ? "Nobody is overdue or due this week." : "Nobody in this list."}</div>`}</section>
    <p class="note" style="border:0">Bills without a credit period count as due on the bill date. Notes are kept on your server, not in Tally.</p>`;
  view.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => { S.cf = b.dataset.f; vCollect().catch(fail); });
  view.querySelectorAll("[data-c]").forEach((b) => b.onclick = () => {
    const el = document.getElementById("cb" + b.dataset.c); el.hidden = !el.hidden;
    b.setAttribute("aria-expanded", String(!el.hidden)); b.querySelector(".chev").classList.toggle("up", !el.hidden);
  });
  const save = async (form, note, promise) => {
    const r = await fetch(cpath("followup"), { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ party: form.dataset.party, note, promise }) });
    if (!r.ok) { toast((await r.json().catch(() => ({}))).error || "Couldn't save."); return; }
    toast(note || promise ? "Note saved." : "Note cleared."); vCollect().catch(fail);
  };
  view.querySelectorAll("[data-showmore]").forEach((b) => b.onclick = () => { b.previousElementSibling.hidden = false; b.remove(); });
  view.querySelectorAll("form.fu").forEach((f) => {
    f.onsubmit = (e) => { e.preventDefault(); save(f, f.note.value.trim(), f.promise.value); };
    const c = f.querySelector("[data-clear]"); if (c) c.onclick = () => save(f, "", "");
  });
}

/* ---------------------------------------------------------------- login, errors, router */
function showLogin(msg = "") {
  $("#tabs").hidden = true; $("#status").innerHTML = ""; $("#company").textContent = "Bahi"; $("#back").hidden = true;
  view.innerHTML = `<div class="login"><form id="lf"><h1>Open your books</h1><p>Enter the app password you set on the server.</p>
    <input type="text" id="lname" autocomplete="username" aria-label="Your name" placeholder="Your name (staff only)">
    <input type="password" id="pw" autocomplete="current-password" aria-label="Password" placeholder="Password" required>
    <p style="font-size:13px;margin:0">Owner: leave the name empty and use the app password.</p>
    <button class="btn primary" type="submit">Open</button><div class="err" role="alert">${h(msg)}</div></form></div>`;
  $("#pw").focus();
  $("#lf").onsubmit = async (e) => {
    e.preventDefault();
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: $("#lname").value.trim(), password: $("#pw").value }) });
    if (r.ok) { $("#tabs").hidden = false; start(); } else showLogin((await r.json().catch(() => ({}))).error || "Could not log in.");
  };
}
function fail(e) {
  if (e && e.login) return showLogin();
  view.innerHTML = `<div class="empty">${e && e.message === "offline" ? `Can't reach the server, and this screen isn't saved on this phone.${offlineInfo() ? ` The offline copy (saved ${ago(offlineInfo().at / 1000)}) has every ledger for this month and this year, stock, dues, reports and the last 12 months' vouchers, for the periods shown when it was saved.` : " Download the offline copy in Settings when you're connected."}` : h(e?.message || "Something went wrong.")}<br><br><button class="btn" onclick="route()">Try again</button></div>`;
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
  // pages that don't need Tally data work before the first sync too
  if (!S.cid && !["reports", "settings"].includes(parts[0])) {
    setTitle(false);
    view.dataset.view = parts[0] || "home";
    view.innerHTML = `<section class="page"><div class="empty">No Tally data yet. Run Setup on the Tally PC to send your first sync.</div>
      ${S.me.owner ? `<a class="row" href="#/settings"><div class="main"><div class="name">Settings</div><div class="meta">Sync, staff logins, Telegram, backups</div></div><span class="chev"></span></a>` : ""}
      <a class="row" href="#/reports"><div class="main"><div class="name">Reports</div><div class="meta">Everything else in the app</div></div><span class="chev"></span></a></section>`;
    return;
  }
  view.dataset.view = parts[0] || "home";
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
      case "godowns": await vGodowns(parts[1]); break;
      case "brs": await vBRS(parts[1]); break;
      case "reports": vReports(); break;
      case "daybook": await vDaybook(params.get("type") ?? ""); break;
      case "voucher": await vVoucher(parts[1]); break;
      case "pl": await vPL(); break;
      case "bs": await vBS(); break;
      case "cashbook": await vCashbook(); break;
      case "collect": await vCollect(); break;
      case "entries": await vEntries(); break;
      case "new": await vNewEntry(parts[1]); break;
      case "gst": await vGST(); break;
      case "check": await vCheck(); break;
      case "analysis": await vAnalysis(parts[1]); break;
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
  try { S.me = await api("/api/me"); await loadCompanies(); } catch (e) { return fail(e); }
  applyTabs();
  $("#tabs").hidden = false;
  route();
  setTimeout(autoOffline, 4000);
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
