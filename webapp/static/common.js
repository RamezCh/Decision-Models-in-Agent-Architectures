// Shared helpers: header status, API calls, live stopwatches.

const MODEL_LABEL = { jev: "Jev", clm: "CLM-8B", random: "Random mover", oracle: "Perfect solver", keyword: "Keyword filter" };

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
    if (ms !== undefined) this.show(ms);
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
      let cls = "unknown", tip = "configured (reachability is checked on first call)";
      if (!info.configured) { cls = "down"; tip = name === "jev" ? "no TYPESAFE_API_KEY in .env" : "not configured"; }
      else if (info.reachable === true) { cls = "up"; tip = `reachable at ${info.base_url}`; }
      else if (info.reachable === false) { cls = "down"; tip = `cannot reach ${info.base_url}`; }
      box.append(el("span", { title: tip }, el("i", { class: `dot ${cls}` }), MODEL_LABEL[name] || name));
    }
    return h;
  } catch (e) {
    box.textContent = "server offline";
    return {};
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

document.addEventListener("DOMContentLoaded", loadStatus);
