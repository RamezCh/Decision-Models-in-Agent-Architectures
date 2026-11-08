// Scam check. Live: both models are asked now, in parallel. Recorded: each model's answers were
// recorded separately (scam-detector-demo/record.py) and appear after exactly the recorded time.

const DECISION_TEXT = { ok: "Looks OK", check: "Check manually", warn: "Likely scam" };
let examples = [], flags = [], current = null, verdictLanes = {}, mode = "live", catalog = null, busy = false;

function makeVerdictLane(name) {
  const watch = watchMarkup("time to answer all 10 questions");
  const big = el("span", { class: "big", text: "–" });
  const risk = el("span", { class: "muted", text: "" });
  const pin = el("div", { class: "pin", style: "left:0%" });
  const reasons = el("p", { class: "small", style: "margin:.6rem 0 0" });
  const err = el("div", { class: "error-box hidden" });
  const model = el("span", { class: "lane-model" });
  const raw = el("div", {});
  const node = el("section", { class: `lane ${name}` },
    el("div", { class: "lane-head" }, el("span", { class: "lane-name", text: MODEL_LABEL[name] }), model),
    el("div", { class: "verdict" }, big, risk),
    el("div", { class: "riskline", title: "green: below 30% risk, amber: 30–60%, red: above 60%" }, pin),
    el("div", { style: "margin-top:.8rem" }, watch), reasons, err, raw);
  return { node, big, risk, pin, reasons, err, model, raw, watch: new Stopwatch(watch.querySelector(".watch")) };
}

function resetLane(v) {
  v.big.textContent = "–"; v.big.className = "big"; v.risk.textContent = ""; v.reasons.textContent = "";
  v.err.classList.add("hidden"); v.raw.replaceChildren(); v.model.textContent = ""; v.pin.style.left = "0%";
}

function mini(p) {
  if (p == null) return el("div", { class: "mini" }, el("span", { text: "–" }));
  return el("div", { class: "mini" },
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${(p * 100).toFixed(1)}%` })),
    el("span", { text: pct(p) }));
}

function renderFlags(res) {
  const j = res.models.jev, c = res.models.clm;
  const rows = flags.map(f => {
    const pj = j?.ok ? j.flags[f.id] : null, pc = c?.ok ? c.flags[f.id] : null;
    const disagree = pj != null && pc != null && (pj >= 0.5) !== (pc >= 0.5);
    return el("tr", { class: disagree ? "disagree" : "", title: f.question },
      el("td", {}, f.label, disagree ? el("span", { class: "small muted", text: "  (models disagree)" }) : null),
      el("td", { class: "jev" }, mini(pj)), el("td", { class: "clm" }, mini(pc)));
  });
  rows.push(el("tr", { class: "overall", title: res.overall_question },
    el("td", {}, "One big question: “is this a scam?”", el("div", { class: "small muted", style: "font-weight:400", text: "asked separately, for comparison; not used in the risk score" })),
    el("td", { class: "jev" }, mini(j?.ok ? j.overall : null)), el("td", { class: "clm" }, mini(c?.ok ? c.overall : null))));
  document.querySelector("#flags tbody").replaceChildren(...rows);
  const a = res.agreement;
  document.getElementById("agree").textContent = a
    ? `The models agree on ${a.flags_agree} of ${a.flags_total} red flags and ${a.decision ? "reach the same decision" : "reach different decisions"}. Hover a row to see the exact question.`
    : "Hover a row to see the exact question each model was asked.";
}

function renderVerdict(name, m) {
  const v = verdictLanes[name];
  if (!m) {
    v.big.textContent = "Not recorded"; v.big.className = "big"; v.risk.textContent = ""; v.reasons.textContent = "";
    return;
  }
  v.model.textContent = m.model || "";
  if (!m.ok) {
    v.big.textContent = "No answer"; v.big.className = "big"; v.risk.textContent = "";
    v.err.textContent = m.error; v.err.classList.remove("hidden"); v.reasons.textContent = "";
    return;
  }
  v.err.classList.add("hidden");
  const c = m.combined;
  v.big.textContent = DECISION_TEXT[c.decision];
  v.big.className = `big ${c.decision}`;
  v.risk.textContent = `risk ${pct(c.risk)}`;
  v.pin.style.left = `${(c.risk * 100).toFixed(1)}%`;
  const why = c.fired.length ? `Main reasons: ${c.fired.slice(0, 3).join(", ")}.` : "No red flag above 50%.";
  const unsure = c.unsure.length ? ` Unsure about: ${c.unsure.join(", ")}, so a person should look.` : "";
  v.reasons.textContent = why + unsure;
}

function readForm() {
  return {
    text: document.getElementById("text").value.trim(),
    title: document.getElementById("title").value.trim() || null,
    district: document.getElementById("district").value.trim() || null,
    rent_eur: parseFloat(document.getElementById("rent").value) || null,
    size_m2: parseFloat(document.getElementById("size").value) || null,
  };
}

async function analyze(ev) {
  ev?.preventDefault();
  if (busy) return;
  const msg = document.getElementById("formMsg");
  const body = readForm();
  if (body.text.length < 10) { msg.textContent = "Paste at least a sentence of listing text."; return; }
  if (mode === "recorded" && !current) { msg.textContent = "Pick a recorded example, or switch to Live to check your own text."; return; }
  busy = true;
  const go = document.getElementById("go");
  go.disabled = true;
  document.getElementById("truth").classList.add("hidden");
  Object.values(verdictLanes).forEach(resetLane);
  try {
    if (mode === "recorded") await replay(current.id, msg);
    else await live(body, msg);
    showTruthButton();
  } catch (e) {
    Object.values(verdictLanes).forEach(v => v.watch.stop(null));
    msg.textContent = "Error: " + e.message;
  } finally { busy = false; go.disabled = false; }
}

async function live(body, msg) {
  msg.textContent = "Asking both models…";
  Object.values(verdictLanes).forEach(v => v.watch.start());
  const res = await api("/api/scam/analyze", body);
  for (const [name, m] of Object.entries(res.models)) { verdictLanes[name].watch.stop(m.latency_ms); renderVerdict(name, m); }
  renderFlags(res);
  msg.textContent = "";
}

async function replay(id, msg) {
  msg.textContent = "";
  const res = await api(`/api/replay/scam/listing?id=${encodeURIComponent(id)}`);
  showRecordingNote("recNote", res.recorded, "Each verdict appears after exactly the time that model needed when recorded.");
  const speed = replaySpeed();
  // each lane runs on its own clock: the faster model's verdict appears first
  await Promise.all(["jev", "clm"].map(async (name) => {
    const v = verdictLanes[name], m = res.models[name];
    if (!m) { renderVerdict(name, null); v.watch.stop(null); return; }
    v.watch.start(speed);
    await sleep((m.latency_ms || 0) / speed);
    v.watch.stop(m.latency_ms);
    renderVerdict(name, m);
    v.raw.replaceChildren(rawLogLink(`/api/replay/scam/raw?id=${encodeURIComponent(id)}&provider=${name}`));
  }));
  renderFlags(res);
}

function showTruthButton() {
  const box = document.getElementById("truth");
  if (!current) return;
  const ex = current;
  box.replaceChildren(el("button", { class: "btn ghost", text: "Reveal the correct answer", onclick: () => {
    box.replaceChildren(el("strong", { text: ex.label === "scam" ? "This example is a scam. " : "This example is legitimate. " }),
      el("span", { text: ex.why }));
  } }));
  box.classList.remove("hidden");
}

function pick(ex, btn) {
  current = ex;
  document.querySelectorAll("#examples button").forEach(b => b.setAttribute("aria-pressed", b === btn ? "true" : "false"));
  document.getElementById("title").value = ex.title || "";
  document.getElementById("district").value = ex.district || "";
  document.getElementById("rent").value = ex.rent_eur ?? "";
  document.getElementById("size").value = ex.size_m2 ?? "";
  document.getElementById("text").value = ex.text;
  document.getElementById("truth").classList.add("hidden");
}

function renderExampleList() {
  const list = document.getElementById("examples");
  const recordedIds = new Set((catalog?.listings || []).map(l => l.id));
  const shown = mode === "recorded" ? examples.filter(e => recordedIds.has(e.id)) : examples;
  list.replaceChildren();
  for (const ex of shown) {
    const b = el("button", { type: "button", "aria-pressed": "false" },
      el("strong", { text: ex.title }), el("span", { class: "small muted", text: `  ${ex.district}, €${ex.rent_eur}, ${ex.size_m2} m²` }));
    b.addEventListener("click", () => pick(ex, b));
    list.append(b);
  }
  if (shown.length) pick(shown[0], list.firstChild);
}

function renderSummary() {
  const panel = document.getElementById("recSummaryPanel");
  const s = catalog?.summary || {};
  if (mode !== "recorded" || !Object.keys(s).length) { panel.classList.add("hidden"); return; }
  const n = catalog.listings.length;
  document.getElementById("recSummaryTitle").textContent = `All ${n} recorded listings`;
  document.getElementById("recSummary").replaceChildren(
    el("tr", {}, ...["Model", "Answered", "Correct decisions", "Median time", "95th percentile"].map(t => el("th", { text: t }))),
    ...["jev", "clm"].filter(p => s[p]).map(p => el("tr", {},
      el("td", { style: `color:var(--${p});font-weight:600`, text: MODEL_LABEL[p] }),
      el("td", { text: `${s[p].answered} of ${s[p].listings}` }),
      el("td", { text: s[p].answered ? `${s[p].correct} of ${s[p].answered} (${pct(s[p].correct / s[p].answered)})` : "–" }),
      el("td", { text: fmtMs(s[p].median_ms) }), el("td", { text: fmtMs(s[p].p95_ms) }))));
  panel.classList.remove("hidden");
}

function applyMode(m) {
  mode = m;
  const recorded = mode === "recorded";
  ["title", "district", "rent", "size", "text"].forEach(id => { document.getElementById(id).readOnly = recorded; });
  document.getElementById("listingHint").textContent = recorded
    ? "Pick a recorded example. To check your own text, switch to Live."
    : "Pick an example (made up for this demo) or paste your own.";
  document.getElementById("go").textContent = recorded ? "Replay check" : "Check listing";
  document.getElementById("recNote").classList.toggle("hidden", !recorded);
  document.getElementById("modeHint").textContent = recorded ? "" :
    (catalog?.listings?.length ? "Live: both models are asked right now."
      : "Nothing recorded yet, so this runs live. Record with: python scam-detector-demo/record.py");
  document.querySelector("#flags tbody").replaceChildren(el("tr", {}, el("td", { colspan: "3", class: "muted", text: "Check a listing to see the answers." })));
  document.getElementById("agree").textContent = "";
  Object.values(verdictLanes).forEach(v => { resetLane(v); v.watch.stop(null); });
  renderExampleList();
  renderSummary();
}

document.addEventListener("DOMContentLoaded", async () => {
  const box = document.getElementById("verdicts");
  for (const name of ["jev", "clm"]) { verdictLanes[name] = makeVerdictLane(name); box.append(verdictLanes[name].node); }
  document.getElementById("form").addEventListener("submit", analyze);
  document.getElementById("text").addEventListener("input", () => { if (mode === "live") current = null; });
  try {
    const [data, cat] = await Promise.all([api("/api/scam/examples"), api("/api/replay/scam/catalog").catch(() => null)]);
    flags = data.flags;
    catalog = cat || { listings: [], summary: {} };
    // shuffle so scams and legit listings are mixed and the audience can guess first
    examples = data.examples.map(e => [Math.random(), e]).sort((a, b) => a[0] - b[0]).map(x => x[1]);
  } catch (e) { document.getElementById("formMsg").textContent = "Could not load examples: " + e.message; return; }
  applyMode(setupModeBar("scam", catalog.listings.length > 0, applyMode));
});
