/* Blue Prince Training Observatory — vanilla JS, no build step. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const N = 1, E = 2, S = 4, W = 8;

const CAT_COLOR = {
  blueprint: "#4a7fd4", bedroom: "#b45cc0", hallway: "#b99a3a",
  green: "#4caf50", shop: "#d9c04a", red: "#d9534f",
  blackprint: "#5c6068", studio_addition: "#3ab5b0",
  outer: "#2a9d8f", objective: "#e8e8ee",
};
const catColor = (c) => CAT_COLOR[c] || "#7a7f88";

const state = {
  rooms: [],
  tab: "dashboard",
  runsSort: "episode",
  runsList: [],
  selectedEp: null,
  run: null,          // {episode, frames, ...}
  frameIdx: 0,
  playing: false,
  speedIdx: 0,        // index into SPEEDS
};
const SPEEDS = [{ label: "1×", ms: 400 }, { label: "4×", ms: 110 }, { label: "16×", ms: 30 }];
let playTimer = null;

/* ------------------------------------------------------------- helpers */

const fmtInt = (n) => n == null ? "—" : Number(n).toLocaleString("en-US");
const fmtPct = (x, d = 1) => x == null ? "—" : (100 * x).toFixed(d) + "%";
function fmtBig(n) {
  if (n == null) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}
function fmtAge(sec) {
  if (sec == null) return "—";
  if (sec < 90) return Math.round(sec) + "s ago";
  if (sec < 5400) return Math.round(sec / 60) + "m ago";
  return (sec / 3600).toFixed(1) + "h ago";
}
const esc = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function roomAbbrev(name) {
  const words = name.replace(/'/g, "").split(/\s+/);
  return (words[0][0] + (words[1] ? words[1][0] : (words[0][1] || ""))).toUpperCase();
}
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

/* ---------------------------------------------------------------- tabs */

function setTab(tab) {
  state.tab = tab;
  $("#tab-dashboard").classList.toggle("active", tab === "dashboard");
  $("#tab-runs").classList.toggle("active", tab === "runs");
  $("#view-dashboard").classList.toggle("hidden", tab !== "dashboard");
  $("#view-runs").classList.toggle("hidden", tab !== "runs");
  if (tab === "runs") refreshRuns();
  else refreshDashboard();
}
$("#tab-dashboard").onclick = () => setTab("dashboard");
$("#tab-runs").onclick = () => setTab("runs");

/* ----------------------------------------------------------- dashboard */

async function refreshDashboard() {
  try {
    const [summary, metrics] = await Promise.all([
      getJSON("/api/summary"), getJSON("/api/metrics")]);
    renderTiles(summary, metrics);
    renderChart(metrics);
    renderCkptTable(metrics);
    $("#conn").textContent = `run: ${summary.run}`;
  } catch (err) {
    $("#conn").textContent = "server unreachable";
  }
}

function renderTiles(summary, metrics) {
  const latest = summary.latest || {};
  const train = metrics.train || [];
  let epsPerHr = null;
  if (train.length >= 2) {
    const a = train[0], b = train[train.length - 1];
    const hrs = (b.sampled_at - a.sampled_at) / 3600;
    if (hrs > 0.05) epsPerHr = (b.episodes - a.episodes) / hrs;
  }
  const age = summary.checkpoint_mtime == null ? null : summary.now - summary.checkpoint_mtime;
  const ev = summary.last_eval;
  const tiles = [
    ["Episodes", fmtInt(latest.episodes)],
    ["Timesteps", fmtBig(latest.timesteps)],
    ["Episodes / hr", epsPerHr == null ? "—" : fmtBig(Math.round(epsPerHr))],
    ["Last checkpoint", fmtAge(age)],
    ["Train win rate (1k)", fmtPct(latest.win_rate_recent)],
    ["Eval win rate", ev ? `${fmtPct(ev.p_antechamber)} <span class="dim">±ci</span>` : "—"],
    ["Replays stored", fmtInt(summary.n_replays)],
  ];
  $("#tiles").innerHTML = tiles.map(([k, v]) =>
    `<div class="tile"><div class="v">${v}</div><div class="k">${k}</div></div>`).join("");
}

function niceStep(raw) {
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * mag >= raw) return m * mag;
  return 10 * mag;
}

function renderChart(metrics) {
  const train = (metrics.train || []).filter((m) => m.win_rate_recent != null);
  const evals = (metrics.eval || []).filter((m) => m.p_antechamber != null);
  const el = $("#chart");
  if (!train.length && !evals.length) {
    el.innerHTML = '<p class="dim">no metrics yet — waiting for the first checkpoint sample</p>';
    $("#legend").innerHTML = "";
    return;
  }
  const t0 = Math.min(...train.map((m) => m.sampled_at), ...evals.map((m) => m.sampled_at));
  const hrs = (t) => (t - t0) / 3600;
  const SW = 900, SH = 320, L = 52, R = 16, T = 14, B = 34;
  const xmax = Math.max(...train.map((m) => hrs(m.sampled_at)),
                        ...evals.map((m) => hrs(m.sampled_at)), 0.1) * 1.03;
  let ymaxData = 0.001;
  for (const m of train) {
    for (const k of ["win_rate_recent", "win_rate_exploit", "win_rate_explore"])
      if (m[k] != null) ymaxData = Math.max(ymaxData, m[k]);
  }
  for (const m of evals) ymaxData = Math.max(ymaxData, (m.ci95 && m.ci95[1]) || m.p_antechamber);
  const ymax = ymaxData * 1.12;
  const X = (h) => L + (h / xmax) * (SW - L - R);
  const Y = (v) => T + (1 - v / ymax) * (SH - T - B);

  let g = "";
  const ystep = niceStep(ymax / 4), xstep = niceStep(xmax / 6);
  for (let v = 0; v <= ymax; v += ystep) {
    g += `<line x1="${L}" y1="${Y(v)}" x2="${SW - R}" y2="${Y(v)}" class="grid"/>` +
         `<text x="${L - 7}" y="${Y(v) + 4}" class="tick" text-anchor="end">${fmtPct(v, ystep < 0.01 ? 1 : 0)}</text>`;
  }
  for (let h = 0; h <= xmax; h += xstep) {
    g += `<line x1="${X(h)}" y1="${T}" x2="${X(h)}" y2="${SH - B}" class="grid"/>` +
         `<text x="${X(h)}" y="${SH - B + 16}" class="tick" text-anchor="middle">${h < 48 ? Math.round(h) + "h" : Math.round(h / 24) + "d"}</text>`;
  }

  const seriesLine = (key, cls) => {
    const pts = train.filter((m) => m[key] != null)
      .map((m) => `${X(hrs(m.sampled_at)).toFixed(1)},${Y(m[key]).toFixed(1)}`);
    return pts.length > 1 ? `<polyline points="${pts.join(" ")}" class="${cls}"/>` : "";
  };
  let s = seriesLine("win_rate_recent", "s-train");
  s += seriesLine("win_rate_exploit", "s-exploit");
  s += seriesLine("win_rate_explore", "s-explore");
  for (const m of evals) {
    const x = X(hrs(m.sampled_at)), y = Y(m.p_antechamber);
    if (m.ci95) s += `<line x1="${x}" y1="${Y(m.ci95[0])}" x2="${x}" y2="${Y(m.ci95[1])}" class="s-eval-ci"/>`;
    s += `<circle cx="${x}" cy="${y}" r="4" class="s-eval">` +
         `<title>eval @ ${fmtInt(m.episodes)} eps: ${fmtPct(m.p_antechamber)} (${m.eval_episodes} rollouts)</title></circle>`;
  }

  el.innerHTML =
    `<svg viewBox="0 0 ${SW} ${SH}" xmlns="http://www.w3.org/2000/svg">
      <style>
        .grid { stroke: #2a2e35; stroke-width: 1; }
        .tick { fill: #8a919c; font-size: 11px; }
        .s-train { fill: none; stroke: #5b9dd9; stroke-width: 2.2; }
        .s-exploit { fill: none; stroke: #57c46a; stroke-width: 1.6; }
        .s-explore { fill: none; stroke: #e0453a; stroke-width: 1.6; }
        .s-eval { fill: #e8c34a; stroke: #14161a; stroke-width: 1; }
        .s-eval-ci { stroke: #e8c34a; stroke-width: 1.4; opacity: .7; }
      </style>${g}${s}</svg>`;

  const legend = [
    ['<span class="sw" style="background:#5b9dd9"></span>training (1k rolling)', true],
    ['<span class="sw" style="background:#57c46a"></span>exploit episodes', train.some((m) => m.win_rate_exploit != null)],
    ['<span class="sw" style="background:#e0453a"></span>explore episodes', train.some((m) => m.win_rate_explore != null)],
    ['<span class="dot" style="background:#e8c34a"></span>deterministic eval ±95% CI', true],
  ];
  $("#legend").innerHTML = legend.filter(([, on]) => on).map(([html]) => `<span>${html}</span>`).join("");
}

function renderCkptTable(metrics) {
  const rows = (metrics.train || []).slice(-12).reverse();
  if (!rows.length) { $("#ckpt-table").innerHTML = '<p class="dim">none yet</p>'; return; }
  $("#ckpt-table").innerHTML = `<table>
    <tr><th>sampled</th><th>episodes</th><th>timesteps</th><th>win rate (1k)</th></tr>
    ${rows.map((m) => `<tr>
      <td>${new Date(m.sampled_at * 1000).toLocaleString()}</td>
      <td>${fmtInt(m.episodes)}</td><td>${fmtBig(m.timesteps)}</td>
      <td>${fmtPct(m.win_rate_recent)}</td></tr>`).join("")}
  </table>`;
}

/* ---------------------------------------------------------------- runs */

$("#runs-sort").onchange = (e) => { state.runsSort = e.target.value; refreshRuns(); };

async function refreshRuns() {
  try {
    state.runsList = await getJSON(`/api/runs?sort=${state.runsSort}`);
  } catch (err) { return; }
  const rows = state.runsList.map((r) => {
    const badge = r.win ? '<span class="badge win">WIN</span>'
                        : `<span class="badge rank">r${r.deepest_rank}</span>`;
    const star = r.top ? '<span class="star" title="best of its 1000-episode window">★</span> ' : "";
    const sel = r.episode === state.selectedEp ? " selected" : "";
    return `<div class="run-row${sel}" data-ep="${r.episode}">
      <span class="ep">${star}#${fmtInt(r.episode)}</span>${badge}</div>`;
  });
  $("#runs-list").innerHTML = rows.join("") || '<div class="run-row dim">no replays recorded yet</div>';
  for (const el of document.querySelectorAll(".run-row[data-ep]")) {
    el.onclick = () => loadRun(Number(el.dataset.ep));
  }
}

async function loadRun(episode) {
  stopPlayback();
  state.selectedEp = episode;
  $("#run-title").textContent = `loading run #${fmtInt(episode)}…`;
  try {
    state.run = await getJSON(`/api/run/${episode}`);
  } catch (err) {
    $("#run-title").textContent = `failed to load run #${fmtInt(episode)}`;
    return;
  }
  state.frameIdx = 0;
  $("#controls").classList.remove("hidden");
  const slider = $("#pb-slider");
  slider.max = state.run.frames.length - 1;
  slider.value = 0;
  refreshRuns();  // update selection highlight
  renderFrame();
}

/* ------------------------------------------------------ house rendering */

const CELL = 100, MARG = 10;
function cellXY(cell) {
  const rank = Math.floor(cell / 5) + 1, col = cell % 5;
  return [MARG + col * CELL, MARG + (9 - rank) * CELL];
}

function doorStubs(x, y, mask, fill) {
  let s = "";
  const t = 12, w = 18, c = CELL / 2 - w / 2;
  if (mask & N) s += `<rect x="${x + c}" y="${y}" width="${w}" height="${t}" fill="${fill}"/>`;
  if (mask & S) s += `<rect x="${x + c}" y="${y + CELL - t}" width="${w}" height="${t}" fill="${fill}"/>`;
  if (mask & E) s += `<rect x="${x + CELL - t}" y="${y + c}" width="${t}" height="${w}" fill="${fill}"/>`;
  if (mask & W) s += `<rect x="${x}" y="${y + c}" width="${t}" height="${w}" fill="${fill}"/>`;
  return s;
}

const FACING_ANGLE = { N: 0, E: 90, S: 180, W: 270 };

function renderHouse(frame) {
  const rooms = state.rooms;
  let svg = "";
  for (let cell = 0; cell < 45; cell++) {
    const [x, y] = cellXY(cell);
    svg += `<rect x="${x}" y="${y}" width="${CELL}" height="${CELL}" class="cell-bg"/>`;
    const idx = frame.grid[cell];
    if (idx >= 0 && rooms[idx]) {
      const room = rooms[idx];
      const color = catColor(room.category);
      const dark = room.category === "objective";
      svg += `<rect x="${x + 4}" y="${y + 4}" width="${CELL - 8}" height="${CELL - 8}" rx="9"
               fill="${color}" class="room"><title>${esc(room.name)}</title></rect>`;
      svg += doorStubs(x, y, frame.doors[cell], color);
      svg += `<text x="${x + CELL / 2}" y="${y + CELL / 2 + 7}" class="room-label${dark ? " dark" : ""}"
               text-anchor="middle">${esc(roomAbbrev(room.name))}</text>`;
    } else if (cell === 2 || cell === 42) {
      svg += `<text x="${x + CELL / 2}" y="${y + CELL / 2 + 4}" class="cell-hint"
               text-anchor="middle">${cell === 2 ? "ENTRANCE" : "ANTECHAMBER"}</text>`;
    }
  }
  // Drafting target highlight
  const pend = frame.pending;
  if (pend && pend.target_cell >= 0) {
    const [tx, ty] = cellXY(pend.target_cell);
    svg += `<rect x="${tx + 4}" y="${ty + 4}" width="${CELL - 8}" height="${CELL - 8}" rx="9" class="draft-target"/>`;
  }
  // Player marker with facing arrow
  const [px, py] = cellXY(frame.pos);
  const cx = px + CELL / 2, cy = py + CELL / 2;
  const ang = FACING_ANGLE[frame.facing] ?? 0;
  svg += `<g transform="translate(${cx},${cy})">
    <circle r="15" class="player"/>
    <polygon points="0,-26 -8,-13 8,-13" class="player-arrow" transform="rotate(${ang})"/>
  </g>`;

  $("#house").innerHTML =
    `<svg viewBox="0 0 ${2 * MARG + 5 * CELL} ${2 * MARG + 9 * CELL}"
          preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
      <style>
        .cell-bg { fill: #191c21; stroke: #262a31; stroke-width: 1; }
        .room { stroke: rgba(0,0,0,.35); stroke-width: 1.5; }
        .room-label { fill: #fff; font: 700 26px -apple-system, sans-serif; opacity: .92; }
        .room-label.dark { fill: #222; }
        .cell-hint { fill: #3c414a; font: 600 11px -apple-system, sans-serif; letter-spacing: .06em; }
        .draft-target { fill: none; stroke: #e8c34a; stroke-width: 3; stroke-dasharray: 8 6; }
        .player { fill: #fff; stroke: #14161a; stroke-width: 3; }
        .player-arrow { fill: #fff; stroke: #14161a; stroke-width: 2; }
      </style>${svg}</svg>`;
}

/* -------------------------------------------------------- detail panel */

function miniGlyph(mask) {
  const sz = 34, t = 7, w = 12, c = sz / 2 - w / 2;
  let s = `<rect x="4" y="4" width="${sz - 8}" height="${sz - 8}" rx="5" fill="#3a3f48"/>`;
  if (mask & N) s += `<rect x="${c}" y="0" width="${w}" height="${t}" fill="#c8ccd4"/>`;
  if (mask & S) s += `<rect x="${c}" y="${sz - t}" width="${w}" height="${t}" fill="#c8ccd4"/>`;
  if (mask & E) s += `<rect x="${sz - t}" y="${c}" width="${t}" height="${w}" fill="#c8ccd4"/>`;
  if (mask & W) s += `<rect x="0" y="${c}" width="${t}" height="${w}" fill="#c8ccd4"/>`;
  return `<svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}">${s}</svg>`;
}

function renderFrame() {
  const run = state.run;
  if (!run) return;
  const idx = state.frameIdx;
  const frame = run.frames[idx];
  renderHouse(frame);

  const outcome = run.win ? "WIN" : `r${run.deepest_rank} (${run.reason || "?"})`;
  $("#run-title").innerHTML =
    `run <b>#${fmtInt(run.episode)}</b> · seed ${run.seed} · ${outcome}` +
    (run.top ? ' <span class="star">★</span>' : "");
  const phase = frame.phase === "TERMINAL"
    ? `<span class="phase terminal">${run.win ? "WON" : "OVER"}</span>`
    : `<span class="phase">${frame.phase}</span>`;
  $("#move-line").innerHTML = `Move ${idx} / ${run.frames.length - 1} ${phase}`;

  const r = frame.resources;
  $("#resources").innerHTML =
    [["Steps", r.steps], ["Gems", r.gems], ["Keys", r.keys],
     ["Coins", r.coins], ["Dice", r.dice], ["Luck", r.luck]]
    .map(([k, v]) => `<div class="res"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  const act = frame.action;
  $("#mode-line").innerHTML = act == null ? '<span class="exploit">mode: —</span>'
    : act.explore ? '<span class="explore">● EXPLORE</span>'
                  : '<span class="exploit">○ exploit</span>';

  // Draft options: while DRAFTING show the live hand; on the frame after a
  // choose, look back at the hand it was picked from.
  let pend = frame.pending, chosenSlot = null;
  if (!pend && act && idx > 0 && /^choose #(\d)/.test(act.text)) {
    pend = run.frames[idx - 1].pending;
    chosenSlot = Number(act.text.match(/^choose #(\d)/)[1]) - 1;
  }
  if (pend) {
    $("#options-head").classList.remove("hidden");
    $("#options-head").textContent =
      `Draft options — facing ${pend.direction || "?"}` + (chosenSlot != null ? " (picked)" : "");
    $("#options").innerHTML = pend.options.map((o) => {
      const cls = ["opt", o.affordable ? "" : "unaffordable",
                   o.slot === chosenSlot ? "chosen" : ""].join(" ");
      const tags = [o.rarity || "", o.layout || "", o.forced ? "forced" : "", o.hidden ? "mystery" : ""]
        .filter(Boolean).join(" · ");
      return `<div class="${cls}">${miniGlyph(o.orientation)}
        <div><div class="name" style="color:${o.hidden ? "#8a919c" : catColor(o.category)}">${esc(o.name)}</div>
        <div class="sub">${esc(tags)}</div></div>
        <div class="cost">${o.cost > 0 ? o.cost + " 💎" : "free"}</div></div>`;
    }).join("");
  } else {
    $("#options-head").classList.add("hidden");
    $("#options").innerHTML = "";
  }

  const lo = Math.max(1, idx - 9);
  let log = "";
  for (let i = lo; i <= idx; i++) {
    const a = run.frames[i].action;
    if (!a) continue;
    log += `<div class="log-row${a.explore ? " explore" : ""}${i === idx ? " current" : ""}">
      <span class="n">${i}</span>${esc(a.text)}</div>`;
  }
  $("#action-log").innerHTML = log || '<div class="dim">—</div>';

  const slider = $("#pb-slider");
  slider.value = idx;
  $("#pb-pos").textContent = `move ${idx} / ${run.frames.length - 1}`;
}

/* ------------------------------------------------------------ playback */

function seek(idx) {
  if (!state.run) return;
  state.frameIdx = Math.max(0, Math.min(state.run.frames.length - 1, idx));
  renderFrame();
}
function stopPlayback() {
  state.playing = false;
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  $("#pb-play").textContent = "▶";
}
function startPlayback() {
  if (!state.run) return;
  if (state.frameIdx >= state.run.frames.length - 1) state.frameIdx = 0;
  state.playing = true;
  $("#pb-play").textContent = "⏸";
  playTimer = setInterval(() => {
    if (state.frameIdx >= state.run.frames.length - 1) { stopPlayback(); return; }
    seek(state.frameIdx + 1);
  }, SPEEDS[state.speedIdx].ms);
}
$("#pb-start").onclick = () => { stopPlayback(); seek(0); };
$("#pb-back").onclick = () => { stopPlayback(); seek(state.frameIdx - 1); };
$("#pb-end").onclick = () => { stopPlayback(); seek(state.run ? state.run.frames.length - 1 : 0); };
$("#pb-play").onclick = () => state.playing ? stopPlayback() : startPlayback();
$("#pb-speed").onclick = () => {
  state.speedIdx = (state.speedIdx + 1) % SPEEDS.length;
  $("#pb-speed").textContent = SPEEDS[state.speedIdx].label;
  if (state.playing) { stopPlayback(); startPlayback(); }
};
$("#pb-slider").oninput = (e) => { stopPlayback(); seek(Number(e.target.value)); };
document.addEventListener("keydown", (e) => {
  if (state.tab !== "runs" || !state.run) return;
  if (e.key === "ArrowLeft") { stopPlayback(); seek(state.frameIdx - 1); }
  else if (e.key === "ArrowRight") { stopPlayback(); seek(state.frameIdx + 1); }
  else if (e.key === " ") { e.preventDefault(); state.playing ? stopPlayback() : startPlayback(); }
});

/* ---------------------------------------------------------------- init */

async function init() {
  try { state.rooms = await getJSON("/api/rooms"); } catch (err) { /* retried below */ }
  refreshDashboard();
  setInterval(() => {
    if (document.hidden) return;
    if (!state.rooms.length) getJSON("/api/rooms").then((r) => { state.rooms = r; }).catch(() => {});
    if (state.tab === "dashboard") refreshDashboard();
  }, 10_000);
  setInterval(() => {
    if (document.hidden || state.tab !== "runs") return;
    refreshRuns();
  }, 30_000);
}
init();
