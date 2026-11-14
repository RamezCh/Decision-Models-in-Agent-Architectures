// Scam check. Live: both models are asked now, in parallel. Recorded: each model's answers were
// recorded separately (scam-detector-demo/record.py) and appear after exactly the recorded time.

const DECISION_TEXT = { ok: "Looks OK", check: "Check manually", warn: "Likely scam" };
let examples = [], flags = [], current = null, verdictLanes = {}, mode = "live", catalog = null, busy = false;
let models = ["clm"];  // which models this demo asks; the server says (SCAM_MODELS in .env)
let speed = null;      // SpeedBoard: one sample per listing check (10 questions in one request)
let log = null;        // DecisionLog: one row per model per listing check

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

function mini(p, pushed = null) {
  if (p == null) return el("div", { class: "mini" }, el("span", { text: "–" }));
  const cell = el("div", { class: "mini" },
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${(p * 100).toFixed(1)}%` })),
    el("span", { text: pct(p) }));
  if (pushed == null) return cell;
  const dir = pushed > 0.3 ? "towards scam" : pushed < -0.3 ? "towards legit" : "little effect";
  return el("div", {}, cell, el("div", { class: `push ${pushed > 0.3 ? "up" : pushed < -0.3 ? "down" : ""}`,
    text: `${pushed > 0 ? "+" : ""}${pushed.toFixed(1)} ${dir}` }));
}

function renderFlagHead() {
  document.getElementById("flagHead").replaceChildren(el("th", { scope: "col", text: "Red flag" }),
    ...models.map(m => el("th", { scope: "col", style: `color:var(--${m})`, text: MODEL_LABEL[m] })));
}

// How much one answer pushed the calibrated risk (log-odds; + = towards scam)
function push(entry, id) {
  if (!entry || !entry.combined || !entry.combined.calibrated) return null;
  const c = entry.combined.contributions.find(x => x.id === id);
  return c ? c.push : null;
}

function renderFlags(res) {
  const answered = (m) => res.models[m] && res.models[m].ok ? res.models[m] : null;
  const rows = flags.map(f => {
    const ps = models.map(m => answered(m) ? answered(m).flags[f.id] : null);
    const known = ps.filter(p => p != null);
    const disagree = known.length > 1 && new Set(known.map(p => p >= 0.5)).size > 1;
    return el("tr", { class: disagree ? "disagree" : "", title: `${f.question}\nYes looks like: ${f.true}\nNo looks like: ${f.false}` },
      el("td", {}, f.label, disagree ? el("span", { class: "small muted", text: "  (models disagree)" }) : null),
      ...models.map((m, i) => el("td", { class: m }, mini(ps[i], push(answered(m), f.id)))));
  });
  rows.push(el("tr", { class: "overall", title: res.overall_question },
    el("td", {}, "One big question: “is this a scam?”", el("div", { class: "small muted", style: "font-weight:400", text: "also an input to the calibrated risk" })),
    ...models.map(m => el("td", { class: m }, mini(answered(m) ? answered(m).overall : null, push(answered(m), "overall"))))));
  document.querySelector("#flags tbody").replaceChildren(...rows);
  const a = res.agreement;
  document.getElementById("agree").textContent = a
    ? `The models agree on ${a.flags_agree} of ${a.flags_total} red flags and ${a.decision ? "reach the same decision" : "reach different decisions"}. Hover a row to see the exact question.`
    : `Hover a row to see the exact question ${models.length > 1 ? "each model was" : "the model was"} asked.`;
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
  v.risk.textContent = `risk ${pct(c.risk)}${c.calibrated ? "" : " (uncalibrated)"}`;
  const why = c.fired.length ? `Points to scam: ${c.fired.slice(0, 3).join(", ")}.` : "Nothing points clearly to a scam.";
  const against = c.against && c.against.length ? ` Points to legit: ${c.against.slice(0, 2).join(", ")}.` : "";
  v.reasons.replaceChildren(el("span", { text: why + against }),
    el("span", { class: "small muted", style: "display:block;margin-top:.3rem", text: `Risk ${c.calibration_note}.` }));
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


function logCheck(name, m) {
  const title = (current && current.title) || document.getElementById("title").value.trim() || "pasted listing";
  const who = el("span", { class: "who", style: `color:var(--${name})`, text: MODEL_LABEL[name] || name });
  if (!m || !m.ok) { log.add({ listing: title, who, decision: tag("error", "err"), why: m ? m.error : "not recorded", ms: fmtMs(m && m.latency_ms) }); return; }
  const c = m.combined;
  const top = (c.contributions || []).slice().sort((a, b) => Math.abs(b.push) - Math.abs(a.push)).slice(0, 3);
  const why = el("span", {});
  top.forEach((t, i) => { if (i) why.append(" · "); why.append(`${t.label} ${t.push >= 0 ? "+" : "−"}${Math.abs(t.push).toFixed(1)}`); });
  log.add({ listing: title, who, risk: pct(c.risk), decision: tag(DECISION_TEXT[c.decision] || c.decision, c.decision),
            why: c.calibrated ? why : "not calibrated", overall: pct(m.overall),
            truth: current && current.label ? tag(current.label, current.label === "scam" ? "warn" : "ok") : "–",
            ms: fmtMs(m.latency_ms) });
}

async function live(body, msg) {
  msg.textContent = "Asking both models…";
  Object.values(verdictLanes).forEach(v => v.watch.start());
  const res = await api("/api/scam/analyze", body);
  for (const [name, m] of Object.entries(res.models)) {
    verdictLanes[name].watch.stop(m.latency_ms); renderVerdict(name, m);
    if (m.ok) speed.add(name, m.latency_ms, m.server_ms);
    logCheck(name, m);
  }
  renderFlags(res);
  msg.textContent = "";
}

async function replay(id, msg) {
  msg.textContent = "";
  const res = await api(`/api/replay/scam/listing?id=${encodeURIComponent(id)}`);
  showRecordingNote("recNote", res.recorded, "Each verdict appears after exactly the time that model needed when recorded.");
  const pace = replaySpeed();
  // each lane runs on its own clock: the faster model's verdict appears first
  await Promise.all(models.map(async (name) => {
    const v = verdictLanes[name], m = res.models[name];
    if (!m) { renderVerdict(name, null); v.watch.stop(null); return; }
    v.watch.start(pace);
    await sleep((m.latency_ms || 0) / pace);
    v.watch.stop(m.latency_ms);
    renderVerdict(name, m);
    if (m.ok) speed.add(name, m.latency_ms, m.server_ms);
    logCheck(name, m);
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
    ...models.filter(p => s[p]).map(p => el("tr", {},
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
  document.querySelector("#flags tbody").replaceChildren(el("tr", {}, el("td", { colspan: String(models.length + 1), class: "muted", text: "Check a listing to see the answers." })));
  document.getElementById("agree").textContent = "";
  Object.values(verdictLanes).forEach(v => { resetLane(v); v.watch.stop(null); });
  renderExampleList();
  renderSummary();
}

document.addEventListener("DOMContentLoaded", async () => {
  speed = new SpeedBoard("speedBoard", { unit: "listing check", perUnit: { n: 10, label: "question" } });
  document.getElementById("speedClear").addEventListener("click", () => speed.clear());
  const lp = logPanel("decisionLog", "Decision log",
    "Every check, newest first: the calibrated risk, the decision, the answers that pushed it most, CLM's raw answer to the one big question, and (for the examples) the correct label.");
  document.getElementById("speedBoard").closest("section").after(lp.section);
  log = new DecisionLog(lp.box, [
    { key: "listing", label: "Listing", cls: "msgcol" }, { key: "who", label: "Model" }, { key: "risk", label: "Risk", cls: "num" },
    { key: "decision", label: "Decision" }, { key: "why", label: "Pushed it most", cls: "widecol" }, { key: "overall", label: "Raw “scam?”", cls: "num" },
    { key: "truth", label: "Correct label" }, { key: "ms", label: "Time", cls: "num" },
  ], { empty: "Check a listing to see every decision here." });
  lp.clear.addEventListener("click", () => log.clear());
  lp.dl.addEventListener("click", () => log.download("scam-decisions.csv"));
  const box = document.getElementById("verdicts");
  document.getElementById("form").addEventListener("submit", analyze);
  document.getElementById("text").addEventListener("input", () => { if (mode === "live") current = null; });
  try {
    const [data, cat] = await Promise.all([api("/api/scam/examples"), api("/api/replay/scam/catalog").catch(() => null)]);
    flags = data.flags;
    models = data.models && data.models.length ? data.models : models;
    catalog = cat || { listings: [], summary: {} };
    for (const name of models) { verdictLanes[name] = makeVerdictLane(name); box.append(verdictLanes[name].node); }
    box.classList.toggle("single", models.length === 1);
    renderFlagHead();
    // shuffle so scams and legit listings are mixed and the audience can guess first
    examples = data.examples.map(e => [Math.random(), e]).sort((a, b) => a[0] - b[0]).map(x => x[1]);
  } catch (e) { document.getElementById("formMsg").textContent = "Could not load examples: " + e.message; return; }
  applyMode(setupModeBar("scam", catalog.listings.length > 0, applyMode));
});
