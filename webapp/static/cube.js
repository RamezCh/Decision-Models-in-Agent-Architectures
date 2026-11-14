// Cube race. Live: every selected player asks its model now, all lanes at the same time.
// Recorded: each player's moves were recorded separately (runner/record.py); the lanes replay
// them side by side, each move taking exactly as long as it took when recorded.

const FACE_POS = { 0: [3, 0], 1: [6, 3], 2: [3, 3], 3: [3, 6], 4: [0, 3], 5: [9, 3] }; // U R F D L B -> [col,row]
const FACE_OF_MOVE = { U: 0, R: 1, F: 2, D: 3, L: 4, B: 5 };
const LANE_COLOR = { jev: "var(--jev)", clm: "var(--clm)", random: "var(--rnd)", oracle: "var(--orc)" };
// pause after each move so an audience can follow (the "Pause after each move" setting)
const pauseMs = () => parseInt(document.getElementById("pace").value, 10);
let log = null;
let speed = null;   // SpeedBoard: response time per move, per model

let level = 3, cube = null, running = false, lanes = {}, mode = "live", catalog = null;

function renderNet(container, state, turnedFace = null) {
  const cells = Array.from({ length: 108 }, () => el("div", { class: "gap" }));
  for (let f = 0; f < 6; f++) {
    const [c0, r0] = FACE_POS[f];
    for (let i = 0; i < 9; i++) {
      const col = c0 + (i % 3), row = r0 + Math.floor(i / 3);
      const cls = `s c${state[f * 9 + i]}` + (f === turnedFace ? " turned" : "");
      cells[row * 12 + col] = el("div", { class: cls });
    }
  }
  container.replaceChildren(...cells);
}

function makeLane(player) {
  const net = el("div", { class: "net", role: "img", "aria-label": "Unfolded cube" });
  const watch = watchMarkup("thinking time for the last move");
  const dist = el("div", { class: "v", text: level });
  const made = el("div", { class: "v", text: "0" });
  const opt = el("div", { class: "v", text: "–" });
  const bars = el("div", { class: "bars" });
  const history = el("div", { class: "history" });
  const err = el("div", { class: "error-box hidden" });
  const banner = el("div", { class: "solved-banner hidden", text: "Solved" });
  const model = el("span", { class: "lane-model" });
  const rec = cube.recorded ? cube.recorded.players[player] : null;
  const raw = rec && (player === "jev" || player === "clm")
    ? rawLogLink(`/api/replay/cube/raw?level=${cube.level}&seed=${cube.seed}&player=${player}`) : null;
  const node = el("section", { class: `lane ${player}` },
    el("div", { class: "lane-head" }, el("span", { class: "lane-name", text: MODEL_LABEL[player] }), model),
    net, banner, el("div", { style: "margin-top:.6rem" }, watch),
    el("div", { class: "stats" },
      el("div", { class: "stat" }, dist, el("div", { class: "k", text: "moves left" })),
      el("div", { class: "stat" }, made, el("div", { class: "k", text: "moves made" })),
      el("div", { class: "stat" }, opt, el("div", { class: "k", text: "optimal moves" }))),
    el("h3", { class: "small muted", text: "Top choices for the last move" }), bars,
    el("h3", { class: "small muted", style: "margin-top:.6rem", text: "Move history" }), history, err, raw);
  if (rec && rec.steps[0] && rec.steps[0].model) model.textContent = rec.steps[0].model;
  const lane = { player, node, net, watch: new Stopwatch(watch.querySelector(".watch")), dist, made, opt, bars, history,
                 err, banner, model, rec, state: cube.state.slice(), last: null, steps: 0, optimal: 0, movesMade: [],
                 series: [level], solved: false };
  renderNet(net, lane.state);
  return lane;
}

function playerBoxes() { return [...document.querySelectorAll('.controls input[type=checkbox][value]')]; }

function selectedPlayers() {
  return playerBoxes().filter(c => c.checked && !c.disabled).map(c => c.value);
}

function whoNode(p) { return el("span", { class: "who", style: `color:var(--${p}, inherit)`, text: MODEL_LABEL[p] || p }); }
function cubeLabel() { return cube ? `L${level} · seed ${cube.seed ?? "?"}` : "–"; }

function buildLanes() {
  const box = document.getElementById("lanes");
  lanes = {};
  for (const p of selectedPlayers()) lanes[p] = makeLane(p);
  box.replaceChildren(...Object.values(lanes).map(l => l.node));
  drawChart();
}

function setInfo(msg) { document.getElementById("scrambleInfo").textContent = msg; }

// ── loading cubes ───────────────────────────────────────────────────────────

async function newCube() {
  if (mode === "recorded") return loadRecordedCube(randomRecordedSeed());
  try {
    const c = await api(`/api/cube/new?level=${level}`);
    cube = { state: c.state, scramble: c.scramble, seed: c.seed, level, recorded: null };
  } catch (e) { setInfo("Error: " + e.message); return; }
  playerBoxes().forEach(b => { b.disabled = false; b.closest("label").title = ""; });
  setInfo(`Scramble: ${cube.scramble.join(" ")}  (seed ${cube.seed}; ${level} perfect move${level > 1 ? "s" : ""} solve it)`);
  buildLanes();
}

function randomRecordedSeed() {
  const seeds = catalog.levels[level].seeds;
  const others = seeds.filter(s => !cube || s !== cube.seed || seeds.length === 1);
  return others[Math.floor(Math.random() * others.length)];
}

async function loadRecordedCube(seed) {
  let game;
  try { game = await api(`/api/replay/cube/game?level=${level}&seed=${seed}`); }
  catch (e) { setInfo("Error: " + e.message); return; }
  cube = { state: game.initial_state, scramble: game.scramble, seed, level, recorded: game };
  document.getElementById("recCube").value = String(seed);
  for (const b of playerBoxes()) {
    const has = !!game.players[b.value];
    b.disabled = !has;
    b.closest("label").title = has ? "" : "not recorded for this cube";
    if (has && !b.dataset.touched) b.checked = true;
  }
  setInfo(`Recorded cube ${seed}: scramble ${cube.scramble.join(" ")} (${level} perfect move${level > 1 ? "s" : ""} solve it)`);
  const metas = {};
  for (const [p, r] of Object.entries(game.players)) if (p === "jev" || p === "clm") metas[p] = r.recorded;
  showRecordingNote("recNote", metas, "The lanes start together here, but each model's moves come from its own separate recording.");
  buildLanes();
}

// ── one move ────────────────────────────────────────────────────────────────

async function liveStep(lane, constrain) {
  try {
    return await api("/api/cube/step", { player: lane.player, state: lane.state, last_move: lane.last, constrain,
      start_state: cube.state, history: lane.movesMade, no_repeat: document.getElementById("noRepeat").checked });
  } catch (e) { return { ok: false, error: e.message, latency_ms: null }; }
}

async function recordedStep(lane) {
  const s = lane.rec.steps[lane.steps];
  if (!s) return null;   // the recording ended (solved, out of moves, or stopped on an error)
  await sleep((s.latency_ms || 0) / replaySpeed());
  return s;
}

// Moves allowed: a recording's own limit, or the "Moves allowed" setting (Infinity = no limit)
function moveLimit() {
  if (cube && cube.recorded) return cube.recorded.max_steps;
  const v = document.getElementById("moveLimit").value;
  return v === "auto" ? level * 3 + 4 : (parseInt(v, 10) || Infinity);
}

async function playLane(lane, maxSteps) {
  const constrain = document.getElementById("constrain").checked;
  while (running && !lane.solved && lane.steps < maxSteps) {
    lane.watch.start(mode === "recorded" ? replaySpeed() : 1);
    const t0 = performance.now();
    const res = mode === "recorded" ? await recordedStep(lane) : await liveStep(lane, constrain);
    if (!res) { lane.watch.stop(); return; }
    lane.watch.stop(res.latency_ms);
    if (res.ok) speed.add(lane.player, res.latency_ms, res.server_ms);
    if (res.model) lane.model.textContent = res.model;
    if (!res.ok) {
      log.add({ cube: cubeLabel(), who: whoNode(lane.player), step: lane.steps + 1, move: "–", verdict: tag("error", "err"),
                opts: res.error, ms: fmtMs(res.latency_ms) });
      lane.err.textContent = "Stopped: " + res.error;
      lane.err.classList.remove("hidden");
      return;
    }
    lane.steps++; lane.last = res.move; lane.state = res.state_after; lane.movesMade.push(res.move);
    if (res.verdict === "optimal") lane.optimal++;
    lane.series.push(res.distance_after);
    renderNet(lane.net, lane.state, FACE_OF_MOVE[res.move[0]]);
    lane.dist.textContent = res.distance_after == null ? "7+" : res.distance_after;
    lane.made.textContent = lane.steps;
    lane.opt.textContent = pct(lane.optimal / lane.steps);
    lane.history.append(el("span", { class: `chip ${res.verdict}`, title: `${res.verdict}; best was ${(res.optimal_moves || []).join(", ") || "–"}`, text: res.move }));
    showBars(lane, res.probabilities, res.move);
    const pChosen = res.probabilities && res.probabilities[res.move];
    log.add({ cube: cubeLabel(), who: whoNode(lane.player), step: lane.steps, move: el("strong", { text: res.move }),
              p: pChosen == null ? "–" : pct(pChosen),
              opts: res.probabilities && Object.keys(res.probabilities).length ? topOptions(res.probabilities, res.move)
                    : lane.player === "oracle" ? "looks up the best move" : lane.player === "random" ? "uniform random" : "–",
              verdict: tag(res.verdict, res.verdict), left: res.distance_after == null ? "7+" : res.distance_after,
              ms: fmtMs(res.latency_ms) });
    if (res.solved) { lane.solved = true; lane.banner.textContent = `Solved in ${lane.steps} moves`; lane.banner.classList.remove("hidden"); }
    drawChart();
    const wait = pauseMs() - (performance.now() - t0);
    if (wait > 0) await sleep(wait);
  }
}

function showBars(lane, probs, chosen) {
  const top = Object.entries(probs || {}).sort((a, b) => b[1] - a[1]).slice(0, 3);
  lane.bars.replaceChildren(...top.map(([m, p]) =>
    el("div", { class: "bar" }, el("span", { text: m + (m === chosen ? "  (chosen)" : "") }),
      el("div", { class: "track" }, el("div", { class: "fill", style: `width:${(p * 100).toFixed(1)}%` })),
      el("span", { class: "pct", text: pct(p) }))));
}

async function startRace() {
  const btn = document.getElementById("start");
  if (running) { running = false; btn.textContent = "Start race"; return; }
  if (!cube) await newCube();
  if (!cube) return;
  buildLanes();   // reset every lane to the same starting cube
  running = true;
  btn.textContent = "Stop";
  document.getElementById("newCube").disabled = true;
  const maxSteps = moveLimit();
  await Promise.all(Object.values(lanes).map(l => playLane(l, maxSteps)));
  running = false;
  btn.textContent = mode === "recorded" ? "Replay again" : "Race again";
  document.getElementById("newCube").disabled = false;
}

// ── chart + summary ─────────────────────────────────────────────────────────

function drawChart() {
  const svg = document.getElementById("chart");
  const W = 900, H = 240, L = 40, R = 16, T = 12, B = 30;
  const limit = cube ? moveLimit() : level * 3 + 4, yMax = 8;
  const longest = Math.max(0, ...Object.values(lanes).map(l => l.series.length - 1));
  // finite limit: fixed axis; no limit: the axis grows with the longest game
  const maxSteps = Number.isFinite(limit) ? limit : Math.max(12, Math.ceil((longest + 4) / 10) * 10);
  const x = (i) => L + (i / maxSteps) * (W - L - R);
  const y = (d) => T + (1 - (d == null ? yMax : d) / yMax) * (H - T - B);
  const parts = [];
  for (let d = 0; d <= 7; d++) {
    parts.push(`<line x1="${L}" x2="${W - R}" y1="${y(d)}" y2="${y(d)}" stroke="var(--line)" stroke-width="1"/>`);
    parts.push(`<text x="${L - 8}" y="${y(d) + 4}" text-anchor="end" font-size="12" fill="var(--muted)">${d}</text>`);
  }
  parts.push(`<text x="${L - 8}" y="${y(null) + 4}" text-anchor="end" font-size="12" fill="var(--muted)">7+</text>`);
  for (let i = 0; i <= maxSteps; i += Math.max(1, Math.round(maxSteps / 10)))
    parts.push(`<text x="${x(i)}" y="${H - 8}" text-anchor="middle" font-size="12" fill="var(--muted)">${i}</text>`);
  const order = Object.keys(lanes);
  for (const lane of Object.values(lanes)) {
    // small vertical offset per player so identical paths stay visible
    const off = (order.indexOf(lane.player) - (order.length - 1) / 2) * 3;
    const pts = lane.series.map((d, i) => `${x(i).toFixed(1)},${(y(d) + off).toFixed(1)}`).join(" ");
    const dash = lane.player === "random" ? ' stroke-dasharray="6 5"' : lane.player === "oracle" ? ' stroke-dasharray="2 4"' : "";
    parts.push(`<polyline points="${pts}" fill="none" stroke="${LANE_COLOR[lane.player]}" stroke-width="3" stroke-linejoin="round"${dash}/>`);
    const last = lane.series.length - 1;
    parts.push(`<circle cx="${x(last)}" cy="${y(lane.series[last]) + off}" r="4.5" fill="${LANE_COLOR[lane.player]}"/>`);
  }
  svg.innerHTML = parts.join("");
  document.getElementById("legend").replaceChildren(...Object.values(lanes).map(l =>
    el("span", {}, el("i", { style: `background:${LANE_COLOR[l.player]}` }), MODEL_LABEL[l.player])));
}

function renderSummary() {
  const panel = document.getElementById("recSummaryPanel");
  const lv = catalog && catalog.levels[level];
  if (mode !== "recorded" || !lv) { panel.classList.add("hidden"); return; }
  document.getElementById("recSummaryTitle").textContent = `All ${lv.seeds.length} recorded cubes at difficulty ${level}`;
  const order = ["jev", "clm", "random", "oracle"].filter(p => lv.summary[p]);
  document.getElementById("recSummary").replaceChildren(
    el("tr", {}, ...["Player", "Cubes", "Solved", "Optimal moves", "Median time per move", "Stopped on error"].map(t => el("th", { text: t }))),
    ...order.map(p => {
      const s = lv.summary[p];
      return el("tr", {},
        el("td", { style: `color:${LANE_COLOR[p]};font-weight:600`, text: MODEL_LABEL[p] }),
        el("td", { text: s.games }), el("td", { text: `${s.solved} of ${s.games}` }),
        el("td", { text: s.optimal_rate == null ? "–" : `${pct(s.optimal_rate)} of ${s.moves}` }),
        el("td", { text: fmtMs(s.median_ms) }), el("td", { text: s.errors }));
    }));
  panel.classList.remove("hidden");
}

// ── mode handling ───────────────────────────────────────────────────────────

function paintLevels() {
  document.querySelectorAll("#level button").forEach(b => {
    const lv = parseInt(b.textContent, 10);
    const available = mode === "live" || (catalog && catalog.levels[lv]);
    b.disabled = !available;
    b.title = available ? "" : "nothing recorded at this difficulty";
    b.setAttribute("aria-pressed", lv === level ? "true" : "false");
  });
}

function fillCubePicker() {
  const sel = document.getElementById("recCube");
  const lv = catalog && catalog.levels[level];
  sel.replaceChildren(...(lv ? lv.seeds.map(s => el("option", { value: s, text: `Cube ${s}` })) : []));
}

function applyMode(m) {
  mode = m;
  running = false;
  const recorded = mode === "recorded";
  document.getElementById("recCubeField").classList.toggle("hidden", !recorded);
  // in recorded mode the recording's own rules apply, so the live-only settings are greyed out
  ["constrain", "noRepeat", "moveLimit"].forEach(id => { document.getElementById(id).disabled = recorded; });
  document.getElementById("recNote").classList.toggle("hidden", !recorded);
  document.getElementById("start").textContent = recorded ? "Start replay" : "Start race";
  document.getElementById("modeHint").textContent = recorded ? "" :
    (Object.keys(catalog.levels).length ? "Live: every move asks the models right now."
      : "Nothing recorded yet, so this runs live. Record with: python -m runner.record (see the README).");
  if (recorded && !catalog.levels[level]) level = parseInt(Object.keys(catalog.levels)[0], 10);
  paintLevels();
  fillCubePicker();
  renderSummary();
  cube = null;
  newCube();
}

document.addEventListener("DOMContentLoaded", async () => {
  speed = new SpeedBoard("speedBoard", { unit: "move" });
  document.getElementById("speedClear").addEventListener("click", () => speed.clear());
  const lp = logPanel("decisionLog", "Decision log",
    "Every move, newest first: who chose it, the top options with the model's probabilities, what the perfect solver says about it, and how long it took.");
  document.getElementById("speedBoard").closest("section").after(lp.section);
  log = new DecisionLog(lp.box, [
    { key: "cube", label: "Cube" }, { key: "who", label: "Player" }, { key: "step", label: "Move #", cls: "num" },
    { key: "move", label: "Chose" }, { key: "p", label: "P(chosen)", cls: "num" }, { key: "opts", label: "Top options", cls: "widecol" },
    { key: "verdict", label: "Solver says" }, { key: "left", label: "Moves left", cls: "num" }, { key: "ms", label: "Time", cls: "num" },
  ], { empty: "Start a race to see every decision here." });
  lp.clear.addEventListener("click", () => log.clear());
  lp.dl.addEventListener("click", () => log.download("cube-decisions.csv"));
  const seg = document.getElementById("level");
  for (let i = 1; i <= 7; i++) {
    seg.append(el("button", { text: i, onclick: () => {
      if (running) return;
      level = i;
      paintLevels(); fillCubePicker(); renderSummary();
      cube = null;
      newCube();
    } }));
  }
  document.getElementById("newCube").addEventListener("click", () => { if (!running) newCube(); });
  document.getElementById("start").addEventListener("click", startRace);
  document.getElementById("recCube").addEventListener("change", (e) => { if (!running) loadRecordedCube(parseInt(e.target.value, 10)); });
  playerBoxes().forEach(c => c.addEventListener("change", () => { c.dataset.touched = "1"; if (!running && cube) buildLanes(); }));
  try { catalog = await api("/api/replay/cube/catalog"); } catch (_) { catalog = { levels: {} }; }
  const has = Object.keys(catalog.levels).length > 0;
  applyMode(setupModeBar("cube", has, applyMode));
});
