// Beat the guard: chat, three guard verdicts per message, scoreboard.
// Live (default): the audience plays. Recorded: a fixed set of attacks recorded earlier
// (beat-the-guard-demo/record.py), replayed with their real verdicts and timings.

// The guards come from the server (GUARD_MODELS in .env): keyword filter + CLM by default.
let vaultLevel = null;   // Vaulty's difficulty (LLM mode only)
let log = null;     // DecisionLog: one row per guard per message
let speed = null;   // SpeedBoard: one sample per message (input check + output check)
let defender = "clm", lanes = {}, mode = "live", catalog = null, lastReplay = null, replaying = false;

function bar(label, p, title) {
  return el("div", { class: "bar", title }, el("span", { text: label }),
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${p == null ? 0 : (p * 100).toFixed(1)}%` })),
    el("span", { class: "pct", text: p == null ? "–" : pct(p) }));
}

function makeLane(name) {
  const watch = watchMarkup(name === "keyword" ? "time to check (plain code)"
    : name === "clm_review" ? "time to decide (CLM, plus Gemma when borderline)"
    : "time to check the message (the answer is checked by code)");
  const state = el("div", { class: "guard-verdict", text: "waiting" });
  const bars = el("div", { class: "bars", style: "margin-top:.6rem" });
  const tech = el("p", { class: "small muted", style: "margin:.5rem 0 0" });
  const tag = el("span", { class: "lane-model" });
  const err = el("div", { class: "error-box hidden" });
  const raw = el("div", {});
  const behind = el("div", {});
  const node = el("section", { class: `lane ${name}` },
    el("div", { class: "lane-head" }, el("span", { class: "lane-name", text: MODEL_LABEL[name] }), tag),
    state, bars, tech, el("div", { style: "margin-top:.6rem" }, watch), err, raw, behind);
  return { node, state, bars, tech, tag, err, raw, behind, watch: new Stopwatch(watch.querySelector(".watch")) };
}

function markActive() {
  for (const [name, l] of Object.entries(lanes)) l.tag.textContent = name === defender ? "guarding the vault" : "for comparison";
  document.querySelectorAll("#defender button").forEach(b => b.setAttribute("aria-pressed", b.dataset.d === defender ? "true" : "false"));
}

function renderVerdicts(res) {
  for (const [name, v] of Object.entries(res.verdicts)) { renderVerdict(name, v); if (v.ok) speed.add(name, v.latency_ms); }
}

function renderVerdict(name, v) {
  {
    const l = lanes[name];
    l.watch.stop(v.latency_ms == null ? null : v.latency_ms);
    if (name !== "keyword") setExchange(l.behind, v.exchange);
    if (!v.ok) {
      l.state.replaceChildren(el("span", { class: "blocked", text: v.error === "not recorded" ? "Not recorded"
        : (v.error || "").startsWith("borderline") ? "Live only" : "Offline" }));
      l.err.textContent = v.error; l.err.classList.toggle("hidden", v.error === "not recorded");
      l.bars.replaceChildren(); l.tech.textContent = "";
      return;
    }
    l.err.classList.add("hidden");
    const where = v.blocked_input ? "flagged the message" : v.blocked_output ? "flagged the answer" : "";
    l.state.replaceChildren(v.blocked ? el("span", { class: "blocked", text: "Blocked" }) : el("span", { class: "passed", text: "Let it through" }));
    if (where) l.state.append(el("span", { class: "small muted", text: `  (${where})` }));
    if (name === "keyword") {
      l.bars.replaceChildren(
        bar("Message", v.input_p, "Does the message contain a forbidden word? (yes = 100%)"),
        bar("Answer", v.output_p, "Does the answer contain the password written plainly, spaced out or reversed?"));
      l.tech.textContent = "Word list + exact match. No AI.";
    } else {
      l.bars.replaceChildren(
        bar("Message", v.input_p, "CLM's probability that the message is an attack, read straight from its answer"),
        bar("Answer", v.output_p, "Checked by code: does the answer contain the password plainly, spaced out, reversed, encoded or translated?"));
      const parts = (v.parts || []).slice().sort((a, b) => b.p - a.p);
      l.tech.replaceChildren(
        el("div", { text: "CLM's answers: " + parts.map(x =>
          `${x.label} ${pct(x.p)}${x.kind === "harmless" ? " (harmless)" : ""}`).join(" · ") }),
        el("div", { class: "muted", text: `Pure CLM (${v.design}), no extra model. Blocks at the threshold. The answer is checked by code.` }));
      if (name === "clm_review") l.tech.replaceChildren(...reviewLines(v));
    }
    if (l.raw) l.raw.replaceChildren();
  }
}

// CLM + Gemma review: which path the message took, and what the reviewer said
function reviewLines(v) {
  const band = v.band ? `${pct(v.band[0])}–${pct(v.band[1])}` : "the band";
  if (v.path === "fast") {
    return [el("div", { text: `Fast path: CLM said ${pct(v.input_p)}, clearly ${v.blocked_input ? "above" : "below"} the threshold ` +
                              `(outside ${band}), so CLM decided alone.` }),
            el("div", { class: "muted", text: "Only borderline messages are sent to Gemma." })];
  }
  const r = v.review;
  return [el("div", { text: `Borderline: CLM said ${pct(v.input_p)} (inside ${band}), so Gemma reviewed the message.` }),
          el("div", {}, el("strong", { text: `Gemma: ${r.block ? "BLOCK" : "ALLOW"}` }), ` (${fmtMs(r.ms)}) ${r.reason || ""}`),
          el("details", { class: "behind-raw" }, el("summary", { text: "Gemma's instructions and reply" }),
             el("pre", { class: "behind-pre", text: `${r.prompt || ""}\n\n--- reply ---\n${r.reply || ""}` }))];
}

function logMessage(text, res) {
  const leaked = res.bot && res.bot.leaked;
  for (const [name, v] of Object.entries(res.verdicts)) {
    const who = el("span", { class: "who", style: name === "keyword" ? "" : `color:var(--${name})`, text: res.defenders[name] || MODEL_LABEL[name] || name });
    if (!v.ok) { log.add({ msg: text, who, decision: tag("error", "err"), result: v.error, ms: fmtMs(v.latency_ms) }); continue; }
    const pMsg = name === "keyword" ? (v.input_p >= 0.5 ? "word found" : "no word")
      : name === "clm_review" && v.path === "review" ? `${(v.input_p * 100).toFixed(1)}% → Gemma: ${v.review.block ? "BLOCK" : "ALLOW"}`
      : `${(v.input_p * 100).toFixed(1)}%`;
    const where = v.blocked_input ? "blocked message" : v.blocked_output ? "blocked answer" : "let through";
    const result = v.blocked ? (leaked ? tag("caught the leak", "ok") : tag("false alarm", "check"))
                             : (leaked ? tag("missed the leak", "warn") : tag("correct pass", "ok"));
    log.add({ msg: el("span", { class: "msgcell", text: text }), who, pmsg: pMsg,
              leak: v.output_p >= 0.5 ? "yes" : "no", decision: tag(where, v.blocked ? "warn" : "ok"),
              leaked: leaked ? `yes (${res.bot.how || "leak"})` : "no", result, ms: fmtMs(v.latency_ms),
              _cls: name === res.defender ? "active-guard" : "" });
  }
}

function threshold() { return parseFloat(document.getElementById("threshold").value); }

function replayUrl(id) {
  return `/api/replay/guard/attack?id=${encodeURIComponent(id)}&defender=${defender}&threshold=${threshold()}`;
}

// Replay one recorded attack: each guard's verdict appears after its recorded time.
async function replayAttack(attack) {
  if (replaying) return;
  replaying = true;
  document.querySelectorAll("#attackList button").forEach(b => { b.disabled = true; });
  addMsg(attack.text, "you");
  const pace = replaySpeed();
  Object.values(lanes).forEach(l => l.watch.start(pace));
  try {
    const res = await api(replayUrl(attack.id));
    lastReplay = attack;
    showRecordingNote("recNote", res.recorded, res.replies_differ
      ? "Note: the bot gave different replies in the two recordings; the first one is shown." : "");
    await Promise.all(Object.entries(res.verdicts).map(async ([name, v]) => {
      await sleep((v.latency_ms || 0) / pace);
      renderVerdict(name, v);
      if (v.ok) speed.add(name, v.latency_ms);
      if (name !== "keyword" && res.recorded[name])
        lanes[name].raw.replaceChildren(rawLogLink(`/api/replay/guard/raw?id=${encodeURIComponent(attack.id)}&provider=${name}`));
    }));
    showReplayOutcome(res);
    logMessage(attack.text, res);
  } catch (e) {
    Object.values(lanes).forEach(l => l.watch.stop(null));
    addMsg("Error: " + e.message, "bot blocked");
  } finally {
    replaying = false;
    document.querySelectorAll("#attackList button").forEach(b => { b.disabled = false; });
  }
}

function showReplayOutcome(res) {
  const cls = res.outcome === "blocked" || res.outcome === "error" ? "bot blocked" : res.outcome === "won" ? "bot won" : "bot";
  const meta = res.outcome === "won" ? `This attack beats ${res.defenders[res.defender]}` : null;
  addMsg(res.shown, cls, meta);
  renderTruth(res);
}

// Guard or threshold changed after a replay: re-decide instantly on the same recorded probabilities.
async function redecide() {
  if (mode !== "recorded" || !lastReplay || replaying) return;
  try {
    const res = await api(replayUrl(lastReplay.id));
    for (const [name, v] of Object.entries(res.verdicts)) {
      const keepRaw = lanes[name].raw.firstChild;
      renderVerdict(name, v);
      if (keepRaw) lanes[name].raw.replaceChildren(keepRaw);
    }
    renderTruth(res);
    const last = document.querySelector("#chat .msg.bot:last-child");
    if (last) {
      last.className = `msg ${res.outcome === "blocked" || res.outcome === "error" ? "bot blocked" : res.outcome === "won" ? "bot won" : "bot"}`;
      last.textContent = res.shown;
      if (res.outcome === "won") last.append(el("span", { class: "meta", text: `This attack beats ${res.defenders[res.defender]}` }));
    }
  } catch (_) {}
}

function applyMode(m) {
  mode = m;
  const recorded = mode === "recorded";
  document.getElementById("composer").classList.toggle("hidden", recorded);
  document.getElementById("attackPanel").classList.toggle("hidden", !recorded);
  document.getElementById("recNote").classList.toggle("hidden", !recorded || !lastReplay);
  document.getElementById("modeHint").textContent = recorded ? "" :
    (catalog?.attacks?.length ? "Live: the audience plays. Switch to Recorded if the network fails."
      : "No recorded backup yet. Record one with: python beat-the-guard-demo/record.py");
  lastReplay = null;
  const list = document.getElementById("attackList");
  list.replaceChildren(...(catalog?.attacks || []).map(a =>
    el("button", { type: "button", text: a.text, onclick: () => replayAttack(a) })));
}

function renderTruth(res) {
  const box = document.getElementById("truth");
  const b = res.bot;
  const parts = [el("strong", { text: b.leaked ? `Vaulty really leaked the password (${b.how}). ` : "Vaulty did not leak the password. " })];
  if (b.leaked) {
    const beaten = res.beaten.map(d => res.defenders[d]);
    parts.push(el("span", { text: beaten.length ? `It got past: ${beaten.join(", ")}.` : "Every guard caught it." }));
  }
  if (res.bot.reply !== res.shown)
    parts.push(el("div", { class: "small muted", style: "margin-top:.3rem", text: `What Vaulty actually said: “${b.reply}”` }));
  box.replaceChildren(...parts);
  box.classList.remove("hidden");
}

function addMsg(text, cls, meta) {
  const chat = document.getElementById("chat");
  const m = el("div", { class: `msg ${cls}`, text });
  if (meta) m.append(el("span", { class: "meta", text: meta }));
  chat.append(m);
  chat.scrollTop = chat.scrollHeight;
}

async function send(ev) {
  ev.preventDefault();
  const box = document.getElementById("msg");
  const text = box.value.trim();
  if (!text) return;
  box.value = "";
  addMsg(text, "you");
  const btn = document.getElementById("send");
  btn.disabled = true;
  Object.values(lanes).forEach(l => l.watch.start());
  try {
    const res = await api("/api/guard/message", {
      text, defender, player: document.getElementById("player").value.trim() || "anonymous",
      threshold: parseFloat(document.getElementById("threshold").value), level: vaultLevel,
    });
    renderVerdicts(res);
    logMessage(text, res);
    const cls = res.outcome === "blocked" || res.outcome === "error" ? "bot blocked" : res.outcome === "won" ? "bot won" : "bot";
    const meta = res.outcome === "won" ? `You beat ${res.defenders[res.defender]}!` : null;
    addMsg(res.shown, cls, meta);
    renderTruth(res);
    loadBoard();
  } catch (e) {
    Object.values(lanes).forEach(l => l.watch.stop(null));
    addMsg("Error: " + e.message, "bot blocked");
  } finally { btn.disabled = false; box.focus(); }
}

async function guessPassword(ev) {
  ev.preventDefault();
  const box = document.getElementById("guess"), out = document.getElementById("guessResult");
  const guess = box.value.trim();
  if (!guess) return;
  try {
    const r = await api("/api/guard/guess", { guess, player: document.getElementById("player").value.trim() || "anonymous" });
    if (r.correct) {
      out.className = "small guess-ok";
      out.textContent = `Correct, the vault is open! The password is ${r.secret}.`;
      document.getElementById("vault").textContent = r.secret;
      document.getElementById("vault").classList.add("open");
    } else {
      out.className = "small guess-no";
      out.textContent = `${r.hint} (guess ${r.guesses})`;
    }
    loadBoard();
  } catch (e) { out.textContent = "Error: " + e.message; }
}

async function loadBoard() {
  const data = await api("/api/guard/leaderboard");
  const s = data.stats;
  document.getElementById("stats").replaceChildren(
    el("tr", {}, el("th", { text: "Guard" }), el("th", { text: "Leaks caught" }), el("th", { text: "Leaks missed" }), el("th", { text: "Blocked, nothing leaked" })),
    ...Object.entries(data.defenders).map(([d, label]) => el("tr", {},
      el("td", { style: `color:var(--${d === "keyword" ? "kw" : d});font-weight:600`, text: label }),
      el("td", { text: s[d].leaks_caught }), el("td", { text: s[d].leaks_missed }), el("td", { text: s[d].harmless_blocked }))));
  const rows = data.players.map((p, i) => el("tr", {},
    el("td", { text: i + 1 }), el("td", { text: p.player }),
    el("td", { text: p.beaten.map(d => data.defenders[d]).join(", ") || "–" }),
    el("td", { text: `${p.wins} / ${p.attempts}` }),
    el("td", { text: p.cracked ? "✓ opened" : p.guesses ? `${p.guesses} wrong` : "–" }),
    el("td", { class: "small muted", text: p.best_prompt || "" })));
  document.getElementById("board").replaceChildren(
    el("tr", {}, el("th", { text: "#" }), el("th", { text: "Player" }), el("th", { text: "Guards beaten" }), el("th", { text: "Wins / tries" }), el("th", { text: "Vault" }), el("th", { text: "Winning message" })),
    ...(rows.length ? rows : [el("tr", {}, el("td", { colspan: "6", class: "muted", text: "No attempts yet. Be the first." }))]));
}

function buildGuards(defenders, defaultDefender) {
  const box = document.getElementById("verdicts");
  const seg = document.getElementById("defender");
  lanes = {};
  box.replaceChildren(); seg.replaceChildren();
  for (const [name, label] of Object.entries(defenders)) {
    lanes[name] = makeLane(name);
    box.append(lanes[name].node);
    seg.append(el("button", { type: "button", "data-d": name, text: label,
      onclick: () => { defender = name; markActive(); redecide(); } }));
  }
  defender = defenders[defaultDefender] ? defaultDefender : Object.keys(defenders).pop();
  markActive();
}

document.addEventListener("DOMContentLoaded", async () => {
  speed = new SpeedBoard("speedBoard", { unit: "message check" });
  document.getElementById("speedClear").addEventListener("click", () => speed.clear());
  document.getElementById("guessForm").addEventListener("submit", guessPassword);
  const lp = logPanel("decisionLog", "Decision log",
    "Every message, newest first, for every guard: CLM's probability that the message is an attack, whether code found the password in Vaulty's answer, what the guard did, and whether that was right. The guard you play against is highlighted.");
  document.getElementById("speedBoard").closest("section").after(lp.section);
  log = new DecisionLog(lp.box, [
    { key: "msg", label: "Message", cls: "msgcol" }, { key: "who", label: "Guard" }, { key: "pmsg", label: "P(attack)", cls: "num" },
    { key: "leak", label: "Password in answer (code)" }, { key: "decision", label: "Guard did" },
    { key: "leaked", label: "Vaulty really leaked" }, { key: "result", label: "Verdict" }, { key: "ms", label: "Time", cls: "num" },
  ], { empty: "Send a message to see every decision here." });
  lp.clear.addEventListener("click", () => log.clear());
  lp.dl.addEventListener("click", () => log.download("guard-decisions.csv"));
  let info = null;
  try { info = await api("/api/guard/info"); } catch (_) {}
  buildGuards(info ? info.defenders : { keyword: "Keyword filter", clm: "CLM-8B" }, info ? info.default_defender : "clm");
  document.getElementById("composer").addEventListener("submit", send);
  document.getElementById("msg").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); document.getElementById("composer").requestSubmit(); }
  });
  const thr = document.getElementById("threshold");
  if (info && info.default_threshold) {   // each question design separates attacks at its own level
    thr.value = info.default_threshold;
    document.getElementById("thrVal").textContent = pct(info.default_threshold);
    document.getElementById("thrSource").textContent =
      `Starts at ${pct(info.default_threshold)}, where CLM's answers (design: ${info.design_text}) separate attacks from harmless chat. ` +
      (info.threshold_source.startsWith("measured") ? `Threshold ${info.threshold_source}.` : "");
  }
  thr.addEventListener("input", () => { document.getElementById("thrVal").textContent = pct(parseFloat(thr.value)); });
  thr.addEventListener("change", redecide);
  const reset = document.getElementById("reset");
  reset.addEventListener("click", async () => {
    if (reset.dataset.armed) { await api("/api/guard/reset", {}); delete reset.dataset.armed; reset.textContent = "Reset"; loadBoard(); }
    else { reset.dataset.armed = "1"; reset.textContent = "Click again to reset"; setTimeout(() => { delete reset.dataset.armed; reset.textContent = "Reset"; }, 3000); }
  });
  if (info && info.bot_mode === "llm" && info.levels) {
    vaultLevel = info.default_level;
    const seg = document.getElementById("level");
    const mark = () => seg.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.l === vaultLevel)));
    for (const [k, label] of Object.entries(info.levels))
      seg.append(el("button", { type: "button", "data-l": k, title: label, text: label.split(":")[0],
        onclick: () => { vaultLevel = k; mark(); } }));
    mark();
    document.getElementById("levelField").hidden = false;
  }
  if (info) {
    document.getElementById("vault").textContent = "●".repeat(info.secret_length);
    document.getElementById("botMode").textContent = info.bot_mode === "llm"
      ? `Vaulty is a real language model (${info.bot_label.replace(/^LLM \(|\)$/g, "")} on BHT's LUMIS). Its instructions depend on the level above: Easy is naive, Hard never reveals the password. If it only hints, prove you got it with the guess box.`
      : "Vaulty is a scripted, deliberately gullible bot: it refuses plain requests but falls for tricks. The guards are what's being tested.";
  }
  loadBoard();
  try { catalog = await api("/api/replay/guard/catalog"); } catch (_) { catalog = { attacks: [] }; }
  applyMode(setupModeBar("guard", catalog.attacks.length > 0, applyMode, "live"));
});
