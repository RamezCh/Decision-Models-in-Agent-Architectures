// Shared helpers: header status, API calls, live stopwatches.

const MODEL_LABEL = { jev: "Jev", clm: "CLM-8B", llm: "BHT Medium (LLM)", clm_review: "CLM + Gemma review", random: "Random mover", oracle: "Perfect solver", keyword: "Keyword filter" };

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) n.append(c);
  return n;
}

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    throw new Error(`${r.status}: ${msg}`);
  }
  return r.json();
}

const pct = (p) => `${Math.round(p * 100)}%`;
const fmtMs = (ms) => (ms == null ? "–" : ms >= 10000 ? (ms / 1000).toFixed(1) + " s" : Math.round(ms) + " ms");

// A stopwatch that counts up live while a request is in flight, then freezes on the measured time.
class Stopwatch {
  constructor(root) { this.root = root; this.num = root.querySelector(".num"); this.unit = root.querySelector(".unit"); this.raf = null; }
  // scale < 1 = slow-motion replay: the watch still shows recorded milliseconds
  start(scale = 1) {
    this.stop();
    const t0 = performance.now();
    this.root.classList.add("running");
    const tick = () => { this.show((performance.now() - t0) * scale); this.raf = requestAnimationFrame(tick); };
    tick();
  }
  stop(ms) {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = null;
    this.root.classList.remove("running");
    if (ms !== undefined) {
      this.show(ms);
      // a 100 ms answer is over before anyone sees the counter move: flash the result instead
      if (ms != null) { this.root.classList.remove("flash"); void this.root.offsetWidth; this.root.classList.add("flash"); }
    }
  }
  show(ms) {
    if (ms == null) { this.num.textContent = "–"; this.unit.textContent = ""; return; }
    if (ms >= 10000) { this.num.textContent = (ms / 1000).toFixed(1); this.unit.textContent = "s"; }
    else { this.num.textContent = Math.round(ms); this.unit.textContent = "ms"; }
  }
}

function watchMarkup(label) {
  return el("div", {},
    el("div", { class: "watch" }, el("span", { class: "num", text: "–" }), el("span", { class: "unit" })),
    el("div", { class: "watch-label", text: label }));
}

async function loadStatus() {
  const box = document.querySelector(".status");
  if (!box) return {};
  try {
    const h = await api("/api/health");
    box.replaceChildren();
    for (const [name, info] of Object.entries(h)) {
      if (!info.configured) continue;          // only show what this setup actually uses
      let cls = "unknown", tip = "configured (reachability is checked on first call)";
      if (!info.configured) { cls = "down"; tip = name === "jev" ? "no TYPESAFE_API_KEY in .env" : "not configured"; }
      else if (info.reachable === true) { cls = "up"; tip = `reachable at ${info.base_url}`; }
      else if (info.reachable === false) { cls = "down"; tip = `cannot reach ${info.base_url}`; }
      box.append(el("span", { title: tip }, el("i", { class: `dot ${cls}` }),
        name === "llm" ? "BHT Medium" : (MODEL_LABEL[name] || name)));
    }
    return h;
  } catch (e) {
    box.textContent = "server offline";
    return {};
  }
}

// ── Speed panel ───────────────────────────────────────────────────────────
// Collects every model call on the page (live or replayed) and shows, per model:
// average, median, 95th percentile, fastest/slowest, how much of it is the model
// itself (CLM reports its own time) versus network + tunnel, and the recent calls.

const SPEED_COLOR = { jev: "var(--jev)", clm: "var(--clm)" };

class SpeedBoard {
  constructor(container, { unit = "call", perUnit = null } = {}) {
    this.box = typeof container === "string" ? document.getElementById(container) : container;
    this.unit = unit;          // what one sample is, e.g. "move", "listing check", "message"
    this.perUnit = perUnit;    // optional {n, label}: e.g. 10 questions per listing check
    this.samples = {};         // model -> [{ms, server}]
    this.render();
  }
  add(model, ms, serverMs = null) {
    if (ms == null || !(model in SPEED_COLOR)) return;
    (this.samples[model] = this.samples[model] || []).push({ ms, server: serverMs });
    this.render();
  }
  clear() { this.samples = {}; this.render(); }

  static pct(sorted, q) { return sorted[Math.min(sorted.length - 1, Math.round(q * (sorted.length - 1)))]; }

  render() {
    const models = Object.keys(this.samples);
    if (!models.length) {
      this.box.replaceChildren(el("p", { class: "muted small", style: "margin:0", text: `Each ${this.unit} adds a bar here, with running averages.` }));
      return;
    }
    const all = models.flatMap(m => this.samples[m].map(s => s.ms));
    const top = Math.max(250, ...all) * 1.25;
    const rows = models.map(m => {
      const xs = this.samples[m], ms = xs.map(s => s.ms), sorted = [...ms].sort((a, b) => a - b);
      const avg = ms.reduce((a, b) => a + b, 0) / ms.length;
      const srv = xs.filter(s => s.server != null).map(s => s.server);
      const avgSrv = srv.length ? srv.reduce((a, b) => a + b, 0) / srv.length : null;
      const stat = (k, v) => el("div", { class: "speed-stat" }, el("div", { class: "v", text: v }), el("div", { class: "k", text: k }));
      const stats = [
        stat(`calls`, String(ms.length)),
        stat("median", fmtMs(SpeedBoard.pct(sorted, 0.5))),
        stat("95% faster than", fmtMs(SpeedBoard.pct(sorted, 0.95))),
        stat("fastest / slowest", `${fmtMs(sorted[0])} / ${fmtMs(sorted[sorted.length - 1])}`),
      ];
      if (this.perUnit) stats.push(stat(`per ${this.perUnit.label}`, fmtMs(avg / this.perUnit.n)));
      const split = avgSrv != null
        ? el("div", { class: "speed-split", title: "CLM reports how long the model itself took; the rest is network, VPN and tunnel" },
            el("div", { class: "seg-model", style: `width:${Math.min(100, avgSrv / avg * 100).toFixed(1)}%` }),
            el("span", { class: "small", text: `model ${fmtMs(avgSrv)}, network + tunnel ${fmtMs(Math.max(0, avg - avgSrv))}` }))
        : null;
      return el("div", { class: "speed-row", style: `--c:${SPEED_COLOR[m]}` },
        el("div", { class: "speed-head" },
          el("span", { class: "lane-name", style: `color:${SPEED_COLOR[m]}`, text: MODEL_LABEL[m] }),
          el("span", { class: "speed-avg" }, el("span", { class: "num", text: Math.round(avg) }), el("span", { class: "unit", text: " ms average" }))),
        el("div", { class: "speed-stats" }, ...stats), split,
        this.sparkline(ms.slice(-60), avg, top));
    });
    this.box.replaceChildren(...rows);
  }

  sparkline(ms, avg, top) {
    const W = 1200, H = 90, bw = W / 60;   // wide and short: stays compact on a big screen
    const y = (v) => H - (v / top) * H;
    const bars = ms.map((v, i) => `<rect x="${(i * bw + 1).toFixed(1)}" y="${y(v).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${(H - y(v)).toFixed(1)}" rx="1.5" fill="var(--c)" opacity="0.85"><title>${Math.round(v)} ms</title></rect>`).join("");
    const grid = [100, 250, 500, 1000, 2000, 5000].filter(g => g < top * 0.85).map(g =>
      `<line x1="0" x2="${W}" y1="${y(g)}" y2="${y(g)}" stroke="var(--line)"/><text x="${W - 2}" y="${y(g) - 3}" text-anchor="end" font-size="15" fill="var(--muted)">${g >= 1000 ? g / 1000 + " s" : g + " ms"}</text>`).join("");
    const avgLine = `<line x1="0" x2="${W}" y1="${y(avg)}" y2="${y(avg)}" stroke="var(--ink)" stroke-dasharray="4 4"/>`;
    const wrap = el("div", { class: "speed-spark" });
    wrap.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Bar chart of the most recent response times, average ${Math.round(avg)} ms">${grid}${bars}${avgLine}</svg>`;
    wrap.append(el("div", { class: "small muted", text: `last ${ms.length} ${this.unit}${ms.length === 1 ? "" : "s"}; dashed line = average` }));
    return wrap;
  }
}

// ── Recorded / Live ───────────────────────────────────────────────────────

const sleep = (ms) => new Promise(r => setTimeout(r, Math.max(0, ms)));

function storedMode(page) {
  try { return localStorage.getItem(`mode:${page}`); } catch (_) { return null; }
}
function storeMode(page, mode) {
  try { localStorage.setItem(`mode:${page}`, mode); } catch (_) {}
}

// Builds the "Recorded | Live" switch + replay speed. Calls onChange(mode).
function setupModeBar(page, hasRecordings, onChange, defaultMode = "recorded") {
  const seg = document.getElementById("mode");
  const speed = document.getElementById("speed");
  let mode = storedMode(page) || defaultMode;
  if (!hasRecordings) mode = "live";
  const paint = () => {
    seg.querySelectorAll("button").forEach(b => {
      b.setAttribute("aria-pressed", b.dataset.mode === mode ? "true" : "false");
      if (b.dataset.mode === "recorded") {
        b.disabled = !hasRecordings;
        b.title = hasRecordings ? "Replay calls recorded earlier, at their real speed" : "Nothing recorded yet (see the README)";
      }
    });
    if (speed) speed.closest("label").classList.toggle("hidden", mode !== "recorded");
  };
  seg.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    if (b.disabled || b.dataset.mode === mode) return;
    mode = b.dataset.mode; storeMode(page, mode); paint(); onChange(mode);
  }));
  paint();
  return mode;
}

// Replay speed: 1 = real time, 0.25 = four times slower
function replaySpeed() {
  const s = document.getElementById("speed");
  return s ? parseFloat(s.value) : 1;
}

function fmtDate(iso) {
  if (!iso) return "unknown date";
  try {
    return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch (_) { return iso; }
}

// "Jev: recorded 8 Nov 2026, 18:53 on Laptop, Berlin (network ping 162 ms), model jev-1.13.0"
function recordingLine(name, meta) {
  if (!meta) return null;
  const bits = [`recorded ${fmtDate(meta.recorded_at)}`];
  if (meta.where) bits.push(`on ${meta.where}`);
  let s = `${MODEL_LABEL[name] || name}: ${bits.join(" ")}`;
  if (meta.ping_ms != null) s += ` (network ping ${Math.round(meta.ping_ms)} ms)`;
  if (meta.models && meta.models.length) s += `, model ${meta.models.join(", ")}`;
  return s;
}

function showRecordingNote(target, metas, extra) {
  const box = typeof target === "string" ? document.getElementById(target) : target;
  const lines = Object.entries(metas || {}).map(([n, m]) => recordingLine(n, m)).filter(Boolean);
  box.replaceChildren(
    el("strong", { text: "Replaying recorded calls at their real speed. " }),
    el("span", { text: "Each model was recorded on its own, one call at a time. " + (extra || "") }),
    ...lines.map(l => el("div", { class: "small", text: l })));
  box.classList.remove("hidden");
}

function rawLogLink(url) {
  return el("a", { href: url, target: "_blank", rel: "noopener", class: "small raw-link", text: "Raw log" });
}

let healthReady = Promise.resolve({});   // pages can await the model status
document.addEventListener("DOMContentLoaded", () => { healthReady = loadStatus(); });

// ── Decision log ──────────────────────────────────────────────────────────
// Every decision on the page, newest first: who decided, what, with which
// probabilities, how it turned out and how long it took. Download as CSV for
// your own analysis.

class DecisionLog {
  // columns: [{ key, label, cls? }]; a row value may be text, a number or a DOM node (with .dataset.csv)
  constructor(container, columns, { max = 300, empty = "Nothing yet." } = {}) {
    this.root = typeof container === "string" ? document.getElementById(container) : container;
    this.columns = [{ key: "_n", label: "#", cls: "num" }, ...columns];
    this.rows = [];
    this.max = max;
    this.empty = empty;
    this.tbody = el("tbody");
    this.root.replaceChildren(
      el("div", { class: "log-scroll" },
        el("table", { class: "log-table" },
          el("thead", {}, el("tr", {}, ...this.columns.map(c => el("th", { scope: "col", class: c.cls || "", text: c.label })))),
          this.tbody)));
    this.render();
  }
  add(row) {
    this.rows.push({ _n: this.rows.length + 1, ...row });
    if (this.rows.length > this.max) this.rows.shift();
    const tr = this.rowNode(this.rows[this.rows.length - 1]);
    if (this.rows.length === 1) this.tbody.replaceChildren();
    this.tbody.prepend(tr);
    tr.classList.add("log-new");
    setTimeout(() => tr.classList.remove("log-new"), 1300);   // don't replay when its tab is opened later
    if (this.tbody.children.length > this.max) this.tbody.lastChild.remove();
  }
  rowNode(r) {
    return el("tr", { class: r._cls || "" }, ...this.columns.map(c => {
      const v = r[c.key];
      return el("td", { class: c.cls || "" }, v == null ? "–" : v instanceof Node ? v.cloneNode(true) : String(v));
    }));
  }
  render() {
    this.tbody.replaceChildren(...(this.rows.length ? this.rows.slice().reverse().map(r => this.rowNode(r))
      : [el("tr", {}, el("td", { colspan: String(this.columns.length), class: "muted", text: this.empty }))]));
  }
  clear() { this.rows = []; this.render(); }
  csv() {
    const cell = (v) => {
      const s = v == null ? "" : v instanceof Node ? (v.dataset && v.dataset.csv) || v.textContent : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    return [this.columns.map(c => cell(c.label)).join(","),
      ...this.rows.map(r => this.columns.map(c => cell(r[c.key])).join(","))].join("\n");
  }
  download(name) {
    const a = el("a", { href: URL.createObjectURL(new Blob([this.csv()], { type: "text/csv" })), download: name });
    document.body.append(a); a.click(); a.remove();
  }
}

// A compact "A 62% · B 21% · C 9%" list of the top options, the chosen one in bold.
function topOptions(probs, chosen, n = 3) {
  const top = Object.entries(probs || {}).sort((a, b) => b[1] - a[1]).slice(0, n);
  const node = el("span", { class: "opts" });
  top.forEach(([k, p], i) => {
    if (i) node.append(" · ");
    node.append(el(k === chosen ? "strong" : "span", { text: `${k} ${pct(p)}` }));
  });
  node.dataset.csv = top.map(([k, p]) => `${k}=${p.toFixed(3)}`).join(" ");
  return node;
}

function tag(text, cls) { return el("span", { class: `chip ${cls || ""}`, text }); }

function logPanel(id, title, hint) {
  // <section> with a heading, a hint, Clear + CSV buttons and the table container
  const box = el("div", { id });
  const clear = el("button", { class: "btn ghost small", type: "button", text: "Clear" });
  const dl = el("button", { class: "btn ghost small", type: "button", text: "Download CSV" });
  const section = el("section", { class: "panel", style: "margin-top:1rem" },
    el("div", { style: "display:flex;justify-content:space-between;align-items:baseline;gap:1rem;flex-wrap:wrap" },
      el("h2", { text: title }), el("div", { style: "display:flex;gap:.5rem" }, dl, clear)),
    hint ? el("p", { class: "small muted", style: "margin:.2rem 0 .6rem", text: hint }) : null, box);
  return { section, box, clear, dl };
}

// ── Behind the scenes ─────────────────────────────────────────────────────
// One model call, opened up: the state and questions we sent, the exact texts CLM compared
// (state as prose + question, one text per possible answer) and the probability of each answer.
// `container` keeps the panel open across updates if the user opened it.

function setExchange(container, ex) {
  const wasOpen = !!container.querySelector("details.behind[open]");
  container.replaceChildren(ex ? exchangePanel(ex, wasOpen) : "");
}

function exchangePanel(ex, open = false) {
  const label = MODEL_LABEL[ex.provider] || ex.provider;
  const answers = (ex.response && ex.response.answers) || {};
  const qs = (ex.request && ex.request.questions) || {};
  const reads = ex.reads;
  const body = [];
  if (ex.response && ex.response.error) body.push(el("div", { class: "error-box", text: `No answer: ${ex.response.error}` }));
  body.push(el("p", { class: "small muted", text: reads
    ? `${label} never sees the JSON. It turns the state into the text below, adds each question after a blank line, ` +
      "and compares that with one text per possible answer. The closer an answer's text, the higher its probability."
    : `The request ${label} received and what it answered.` }));
  if (reads) {
    body.push(el("div", { class: "behind-h", text: "What it reads first (the state as text)" }),
              el("pre", { class: "behind-pre", text: reads.context || "(empty)" }));
  }
  body.push(el("div", { class: "behind-h", text: `${Object.keys(qs).length} question${Object.keys(qs).length === 1 ? "" : "s"}, ` +
    "each answered against that same text" }));
  for (const [qid, q] of Object.entries(qs)) {
    const a = answers[qid] || {};
    const probs = a.probabilities || {};
    const cands = reads ? reads.questions[qid].candidates : Object.fromEntries(Object.keys(probs).map(k => [k, k]));
    const rows = Object.entries(cands).map(([k, text]) => ({ k, text, p: probs[k] }))
      .sort((x, y) => (y.p ?? -1) - (x.p ?? -1));
    const chosen = a.label ?? a.value;
    body.push(el("div", { class: "behind-q" },
      el("div", { class: "behind-qtitle" }, el("code", { text: qid }), ` ${q.instructions || ""} `,
        el("span", { class: "muted", text: `(${q.type})` })),
      el("table", { class: "behind-table" }, el("tbody", {}, ...rows.map(r => el("tr", { class: String(r.k) === String(chosen) ? "chosen" : "" },
        el("td", { class: "behind-cand", text: r.text }),
        el("td", { class: "behind-p" }, r.p == null ? "–" : el("span", {},
          el("span", { class: "behind-bar" }, el("span", { style: `width:${(r.p * 100).toFixed(1)}%` })),
          ` ${(r.p * 100).toFixed(1)}%`))))))));
  }
  const pretty = (o) => JSON.stringify(o, null, 2);
  body.push(el("details", { class: "behind-raw" }, el("summary", { text: "Request as sent (JSON)" }),
                el("pre", { class: "behind-pre", text: pretty(ex.request) })),
            el("details", { class: "behind-raw" }, el("summary", { text: "Response (answers as received, with timing)" }),
                el("pre", { class: "behind-pre", text: pretty(ex.response) })));
  const d = el("details", { class: "behind" }, el("summary", { text: `Behind the scenes: what ${label} got and answered` }), ...body);
  d.open = open;
  return d;
}

// ── Tabs for the detail panels ────────────────────────────────────────────
// <section class="panel tabbed" id="details"> holds children with data-tab="Label".
// Pages add more with addTab(). The chosen tab is remembered per page.

function tabbedHost(host) {
  host = typeof host === "string" ? document.getElementById(host) : host;
  if (!host._tabs) {
    const bar = el("div", { class: "tabbar", role: "tablist" });
    const panes = el("div", { class: "tabpanes" });
    const initial = [...host.querySelectorAll(":scope > [data-tab]")];
    host.prepend(bar, panes);
    host._tabs = { bar, panes, items: [] };
    initial.forEach(n => addTab(host, n.dataset.tab, n));
  }
  return host;
}

function addTab(host, label, node, { first = false } = {}) {
  host = tabbedHost(host);
  const t = host._tabs;
  const key = `tab:${location.pathname}`;
  const btn = el("button", { type: "button", role: "tab", text: label, onclick: () => selectTab(host, label) });
  node.classList.add("tabpane");
  if (first) { t.bar.prepend(btn); t.panes.prepend(node); t.items.unshift({ label, btn, node }); }
  else { t.bar.append(btn); t.panes.append(node); t.items.push({ label, btn, node }); }
  let saved = null;
  try { saved = localStorage.getItem(key); } catch (_) {}
  selectTab(host, t.items.some(i => i.label === saved) ? saved : t.items[0].label, false);
}

function selectTab(host, label, remember = true) {
  for (const i of host._tabs.items) {
    const on = i.label === label;
    i.btn.setAttribute("aria-selected", String(on));
    i.node.hidden = !on;
  }
  if (remember) try { localStorage.setItem(`tab:${location.pathname}`, label); } catch (_) {}
}

document.addEventListener("DOMContentLoaded", () => document.querySelectorAll(".tabbed").forEach(tabbedHost));

// ── Overview page: each model card shows whether this setup uses it ───────
document.addEventListener("DOMContentLoaded", async () => {
  const box = document.getElementById("models");
  if (!box) return;
  const h = await healthReady;
  for (const card of box.querySelectorAll("[data-model]")) {
    const info = h[card.dataset.model];
    const out = card.querySelector(".model-status");
    if (!info) { out.textContent = ""; continue; }
    card.classList.toggle("off", !info.configured);
    out.textContent = !info.configured
      ? (card.dataset.model === "jev" ? "Not set up here (no TYPESAFE_API_KEY)" : "Not set up here (no BHT_LLM_INF_API_KEY in your environment)")
      : info.reachable === false ? `Set up, but not reachable at ${info.base_url}`
      : `Ready · ${info.model || info.label || ""}`;
  }
});
