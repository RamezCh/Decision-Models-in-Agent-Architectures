// Beat the guard: chat, three guard verdicts per message, scoreboard.
// Live (default): the audience plays. Recorded: a fixed set of attacks recorded earlier
// (beat-the-guard-demo/record.py), replayed with their real verdicts and timings.

const TECHNIQUE = { harmless: "harmless", direct: "asks directly", roleplay: "role-play / story",
                    override: "instruction override", disguise: "disguised answer" };
let defender = "jev", lanes = {}, mode = "live", catalog = null, lastReplay = null, replaying = false;

function bar(label, p, title) {
  return el("div", { class: "bar", title }, el("span", { text: label }),
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${p == null ? 0 : (p * 100).toFixed(1)}%` })),
    el("span", { class: "pct", text: p == null ? "–" : pct(p) }));
}

function makeLane(name) {
  const watch = watchMarkup(name === "keyword" ? "time to check (plain code)" : "time to check message + answer");
  const state = el("div", { class: "guard-verdict", text: "waiting" });
  const bars = el("div", { class: "bars", style: "margin-top:.6rem" });
  const tech = el("p", { class: "small muted", style: "margin:.5rem 0 0" });
  const tag = el("span", { class: "lane-model" });
  const err = el("div", { class: "error-box hidden" });
  const raw = el("div", {});
  const node = el("section", { class: `lane ${name}` },
    el("div", { class: "lane-head" }, el("span", { class: "lane-name", text: MODEL_LABEL[name] }), tag),
    state, bars, tech, el("div", { style: "margin-top:.6rem" }, watch), err, raw);
  return { node, state, bars, tech, tag, err, raw, watch: new Stopwatch(watch.querySelector(".watch")) };
}

function markActive() {
  for (const [name, l] of Object.entries(lanes)) l.tag.textContent = name === defender ? "guarding the vault" : "for comparison";
  document.querySelectorAll("#defender button").forEach(b => b.setAttribute("aria-pressed", b.dataset.d === defender ? "true" : "false"));
}

function renderVerdicts(res) {
  for (const [name, v] of Object.entries(res.verdicts)) renderVerdict(name, v);
}

function renderVerdict(name, v) {
  {
    const l = lanes[name];
    l.watch.stop(v.latency_ms == null ? null : v.latency_ms);
    if (!v.ok) {
      l.state.replaceChildren(el("span", { class: "blocked", text: v.error === "not recorded" ? "Not recorded" : "Offline" }));
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
        bar("Message", v.input_p, "How sure the model is that the message is an attack"),
        bar("Answer", v.output_p, "How sure the model is that the answer leaks the password"));
      l.tech.textContent = `Thinks the technique is: ${TECHNIQUE[v.technique] || v.technique}`;
    }
    if (l.raw) l.raw.replaceChildren();
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
  const speed = replaySpeed();
  Object.values(lanes).forEach(l => l.watch.start(speed));
  try {
    const res = await api(replayUrl(attack.id));
    lastReplay = attack;
    showRecordingNote("recNote", res.recorded, res.replies_differ
      ? "Note: the bot gave different replies in the two recordings; the first one is shown." : "");
    await Promise.all(Object.entries(res.verdicts).map(async ([name, v]) => {
      await sleep((v.latency_ms || 0) / speed);
      renderVerdict(name, v);
      if (name !== "keyword" && res.recorded[name])
        lanes[name].raw.replaceChildren(rawLogLink(`/api/replay/guard/raw?id=${encodeURIComponent(attack.id)}&provider=${name}`));
    }));
    showReplayOutcome(res);
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
      threshold: parseFloat(document.getElementById("threshold").value),
    });
    renderVerdicts(res);
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
    el("td", { class: "small muted", text: p.best_prompt || "" })));
  document.getElementById("board").replaceChildren(
    el("tr", {}, el("th", { text: "#" }), el("th", { text: "Player" }), el("th", { text: "Guards beaten" }), el("th", { text: "Wins / tries" }), el("th", { text: "Winning message" })),
    ...(rows.length ? rows : [el("tr", {}, el("td", { colspan: "5", class: "muted", text: "No attempts yet. Be the first." }))]));
}

document.addEventListener("DOMContentLoaded", async () => {
  const box = document.getElementById("verdicts");
  for (const name of ["keyword", "jev", "clm"]) { lanes[name] = makeLane(name); box.append(lanes[name].node); }
  markActive();
  document.getElementById("composer").addEventListener("submit", send);
  document.getElementById("msg").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); document.getElementById("composer").requestSubmit(); }
  });
  document.querySelectorAll("#defender button").forEach(b => b.addEventListener("click", () => { defender = b.dataset.d; markActive(); redecide(); }));
  const thr = document.getElementById("threshold");
  thr.addEventListener("input", () => { document.getElementById("thrVal").textContent = pct(parseFloat(thr.value)); });
  thr.addEventListener("change", redecide);
  const reset = document.getElementById("reset");
  reset.addEventListener("click", async () => {
    if (reset.dataset.armed) { await api("/api/guard/reset", {}); delete reset.dataset.armed; reset.textContent = "Reset"; loadBoard(); }
    else { reset.dataset.armed = "1"; reset.textContent = "Click again to reset"; setTimeout(() => { delete reset.dataset.armed; reset.textContent = "Reset"; }, 3000); }
  });
  try {
    const info = await api("/api/guard/info");
    document.getElementById("vault").textContent = "●".repeat(info.secret_length);
    document.getElementById("botMode").textContent = info.bot_mode === "llm"
      ? "Vaulty is a real language model with a “never reveal the password” instruction."
      : "Vaulty is a scripted, deliberately gullible bot: it refuses plain requests but falls for tricks. The guards are what's being tested.";
  } catch (_) {}
  loadBoard();
  try { catalog = await api("/api/replay/guard/catalog"); } catch (_) { catalog = { attacks: [] }; }
  applyMode(setupModeBar("guard", catalog.attacks.length > 0, applyMode, "live"));
});
