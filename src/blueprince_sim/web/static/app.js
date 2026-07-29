/* Blue Prince Training Observatory — vanilla JS, no build step. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const N = 1, E = 2, S = 4, W = 8;

const CAT_COLOR = {
  blueprint: "#4a7fd4", bedroom: "#b45cc0", hallway: "#e07b28",
  green: "#4caf50", shop: "#f2d024", red: "#d9534f",
  blackprint: "#5c6068", studio_addition: "#3ab5b0",
  outer: "#2a9d8f", objective: "#e8e8ee",
};
const catColor = (c) => CAT_COLOR[c] || "#7a7f88";

const state = {
  rooms: [],
  draftStats: null,
  draftCatsOff: new Set(),  // categories hidden in the draft-frequency bars
  tab: "dashboard",
  runsSort: "episode",
  runsList: [],
  selectedEp: null,
  run: null,          // {episode, frames, ...}
  frameIdx: 0,
  playing: false,
  speedIdx: 0,        // index into SPEEDS
  areaGraph: null,    // cached /api/areas response
  areaStats: null,    // cached /api/area_stats response
  areaMode: "replay", // "replay" or "agg"
  upgradeStats: null, // cached /api/upgrade_stats response
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
  if (tab === "runs") {
    refreshRuns();
    ensureAreaGraph().then(() => renderAreaPanel());
  } else {
    refreshDashboard();
  }
}
$("#tab-dashboard").onclick = () => setTab("dashboard");
$("#tab-runs").onclick = () => setTab("runs");

/* ----------------------------------------------------------- dashboard */

async function refreshDashboard() {
  try {
    const [summary, metrics, draftStats, upgradeStats] = await Promise.all([
      getJSON("/api/summary"), getJSON("/api/metrics"),
      // Tolerate a server predating this endpoint (static files reload on
      // refresh, but routes need a server restart).
      getJSON("/api/draft_stats").catch(() => ({ train: [], eval: [] })),
      getJSON("/api/upgrade_stats").catch(() => ({ variants: [], economy: [], gates: {} }))]);
    state.draftStats = draftStats;
    state.upgradeStats = upgradeStats;
    renderTiles(summary, metrics);
    renderChart(metrics);
    renderDraftBars(draftStats);
    renderDraftTs(draftStats);
    renderCkptTable(metrics);
    renderUpgradeStats();
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

/* ------------------------------------------------------ draft frequency */

const DRAFT_PALETTE = ["#5b9dd9", "#e8c34a", "#57c46a", "#e0453a", "#b45cc0",
  "#3ab5b0", "#d98a3a", "#8fd94a", "#d94a8f", "#7a86e0", "#c0b45c", "#4ad9c0"];
const OTHER_COLOR = "#4a4f58";
const YIELD_GLYPHS = [["steps", "👣"], ["keys", "🔑"], ["gems", "💎"],
  ["coins", "🪙"], ["luck", "🍀"]];

function yieldBadges(yields) {
  // Expected per-draft resources from room data; zeros are omitted to keep
  // the common (empty) rooms quiet.
  if (!yields) return "";
  return YIELD_GLYPHS.map(([k, glyph]) => {
    const v = Math.round((yields[k] || 0) * 10) / 10;
    if (!v) return "";
    return `<span class="y${v < 0 ? " neg" : ""}">${v % 1 ? v.toFixed(1) : v}${glyph}</span>`;
  }).filter(Boolean).join(" ");
}

function renderDraftBars(ds) {
  const el = $("#draft-bars");
  const source = $("#draft-source").value, mode = $("#draft-mode").value;
  let seedsTotal = 0;
  const seedsWith = {};
  if (source === "eval") {
    const evals = ds.eval || [];
    const last = evals[evals.length - 1];
    if (!last) {
      el.innerHTML = '<p class="dim">no eval draft counts yet — they appear with the ' +
        "first eval of a checkpoint trained on the new code</p>";
      $("#draft-legend").innerHTML = "";
      return;
    }
    seedsTotal = last.eval_episodes || 0;
    Object.assign(seedsWith, last.seeds_with);
  } else {
    const w = $("#draft-window").value;
    const buckets = ds.train || [];
    const rows = w === "all" ? buckets : buckets.slice(-Number(w));
    if (!rows.length) {
      el.innerHTML = '<p class="dim">no draft stats yet — the first 10k-seed bucket ' +
        "lands after the trainer restarts on the new code</p>";
      $("#draft-legend").innerHTML = "";
      return;
    }
    for (const b of rows) {
      seedsTotal += b.seeds;
      for (const [n, v] of Object.entries(b.seeds_with))
        seedsWith[n] = (seedsWith[n] || 0) + v;
    }
  }
  const entries = Object.entries(seedsWith).sort((a, b) => b[1] - a[1]);
  if (!entries.length || !seedsTotal) {
    el.innerHTML = '<p class="dim">no drafts recorded in this window</p>';
    $("#draft-legend").innerHTML = "";
    return;
  }
  // Upgrade variants share a display name and category, so any id's match works.
  const metaByName = new Map();
  for (const r of state.rooms) if (r && !metaByName.has(r.name)) metaByName.set(r.name, r);
  const catOf = (name) => (metaByName.get(name) || {}).category;

  // Legend chips double as the category filter: click to toggle.
  const cats = [...new Set(entries.map(([n]) => catOf(n)).filter(Boolean))];
  $("#draft-legend").innerHTML = cats.map((c) =>
    `<span class="cat-chip${state.draftCatsOff.has(c) ? " off" : ""}" data-cat="${esc(c)}">
      <span class="sw" style="background:${catColor(c)}"></span>${esc(c).replace(/_/g, " ")}</span>`
  ).join("");
  for (const chip of document.querySelectorAll("#draft-legend .cat-chip")) {
    chip.onclick = () => {
      const c = chip.dataset.cat;
      if (state.draftCatsOff.has(c)) state.draftCatsOff.delete(c);
      else state.draftCatsOff.add(c);
      renderDraftBars(state.draftStats);
    };
  }

  const shown = entries.filter(([n]) => !state.draftCatsOff.has(catOf(n)));
  if (!shown.length) {
    el.innerHTML = '<p class="dim">every category is filtered out — click a chip above to re-enable</p>';
    return;
  }
  const maxV = shown[0][1];
  el.innerHTML = shown.map(([name, v]) => {
    const val = mode === "pct" ? fmtPct(v / seedsTotal) : fmtInt(v);
    const meta = metaByName.get(name) || {};
    const cat = meta.category;
    return `<div class="dbar">
      <span class="name" title="${esc(name)}${cat ? " · " + esc(cat) : ""}">${esc(name)}</span>
      <div class="track"><div class="fill" style="width:${(100 * v / maxV).toFixed(2)}%;
        background:${cat ? catColor(cat) : "var(--accent)"}"></div></div>
      <span class="val">${val}</span>
      <span class="yields" title="expected steps / keys / gems / coins / luck per draft (from room data)">${yieldBadges(meta.yields)}</span></div>`;
  }).join("") +
    `<div class="dbar total dim"><span class="name">seeds in window</span>` +
    `<div class="track"></div><span class="val">${fmtInt(seedsTotal)}</span><span class="yields"></span></div>`;
}

function renderDraftTs(ds) {
  const el = $("#draft-ts"), leg = $("#draft-ts-legend");
  const buckets = ds.train || [];
  if (!buckets.length) {
    el.innerHTML = '<p class="dim">no draft stats yet</p>';
    leg.innerHTML = "";
    return;
  }
  // Merge adjacent 10k buckets so the chart never exceeds ~60 columns.
  const group = Math.ceil(buckets.length / 60);
  const cols = [];
  for (let i = 0; i < buckets.length; i += group) {
    const chunk = buckets.slice(i, i + group);
    const drafts = {};
    for (const b of chunk)
      for (const [n, v] of Object.entries(b.drafts)) drafts[n] = (drafts[n] || 0) + v;
    cols.push({ start: chunk[0].bucket_start, end: chunk[chunk.length - 1].bucket_end, drafts });
  }
  const totals = {};
  for (const c of cols)
    for (const [n, v] of Object.entries(c.drafts)) totals[n] = (totals[n] || 0) + v;
  const top = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([n]) => n);
  const color = new Map(top.map((n, i) => [n, DRAFT_PALETTE[i]]));
  const colTotal = (c) => Object.values(c.drafts).reduce((a, b) => a + b, 0);
  const ymax = Math.max(...cols.map(colTotal)) * 1.05 || 1;

  const SW = 900, SH = 300, L = 56, R = 10, T = 12, B = 30;
  const bw = (SW - L - R) / cols.length;
  const Y = (v) => T + (1 - v / ymax) * (SH - T - B);
  let g = "";
  const ystep = niceStep(ymax / 4);
  for (let v = 0; v <= ymax; v += ystep) {
    g += `<line x1="${L}" y1="${Y(v)}" x2="${SW - R}" y2="${Y(v)}" class="grid"/>` +
         `<text x="${L - 7}" y="${Y(v) + 4}" class="tick" text-anchor="end">${fmtBig(v)}</text>`;
  }
  let s = "";
  cols.forEach((c, i) => {
    const x = L + i * bw;
    let acc = 0;
    const seg = (name, v, fill) => {
      if (!v) return;
      const y0 = Y(acc), y1 = Y(acc + v);
      s += `<rect x="${(x + bw * 0.08).toFixed(1)}" y="${y1.toFixed(1)}" width="${(bw * 0.84).toFixed(1)}"
        height="${Math.max(y0 - y1, 0.5).toFixed(1)}" fill="${fill}">
        <title>${esc(name)}: ${fmtInt(v)} drafts (seeds ${fmtBig(c.start)}–${fmtBig(c.end)})</title></rect>`;
      acc += v;
    };
    for (const n of top) seg(n, c.drafts[n] || 0, color.get(n));
    let other = 0;
    for (const [n, v] of Object.entries(c.drafts)) if (!color.has(n)) other += v;
    seg("other", other, OTHER_COLOR);
    if (cols.length <= 12 || i % Math.ceil(cols.length / 8) === 0) {
      g += `<text x="${x + bw / 2}" y="${SH - B + 16}" class="tick" text-anchor="middle">${fmtBig(c.start)}</text>`;
    }
  });
  el.innerHTML =
    `<svg viewBox="0 0 ${SW} ${SH}" xmlns="http://www.w3.org/2000/svg">
      <style>
        .grid { stroke: #2a2e35; stroke-width: 1; }
        .tick { fill: #8a919c; font-size: 11px; }
      </style>${g}${s}</svg>`;
  leg.innerHTML = top.map((n) =>
    `<span><span class="sw" style="background:${color.get(n)}"></span>${esc(n)}</span>`).join("") +
    `<span><span class="sw" style="background:${OTHER_COLOR}"></span>other</span>`;
}

for (const id of ["draft-source", "draft-mode", "draft-window"]) {
  $("#" + id).onchange = () => { if (state.draftStats) renderDraftBars(state.draftStats); };
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
  renderDivergenceBanner(state.run);
  refreshRuns();  // update selection highlight
  renderFrame();
}

function renderDivergenceBanner(run) {
  let banner = $("#divergence-banner");
  if (!banner) {
    // Insert the banner at the top of the house panel so it overlays the grid.
    banner = document.createElement("div");
    banner.id = "divergence-banner";
    banner.className = "divergence-banner hidden";
    $("#house-panel").prepend(banner);
  }
  const div = run ? run.divergence : null;
  if (!div) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  const total = run.frames ? run.frames.length - 1 : "?";
  // A legacy record has a known cause; anything else is an unexplained bug and
  // must not be misattributed to the old record format.
  const cause = div.legacy_record
    ? "Record predates day-config capture, so this day's starting state is unrecoverable."
    : "This record carries a day-config, so the divergence is unexplained — worth reporting.";
  banner.classList.remove("hidden");
  banner.textContent =
    `⚠ Replay diverged from the recorded run at action ${div.first_invalid_index} — ` +
    `${div.invalid_count} of ${total} actions could not be applied. ` +
    `This house is incomplete. ${cause}`;
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
      // Full room name in a foreignObject so CSS word-wrap keeps long names
      // legible without overflowing into neighboring tiles. The container is
      // inset 6px from each tile edge so door stubs aren't obscured.
      const fo = CELL - 12;
      svg += `<foreignObject x="${x + 6}" y="${y + 6}" width="${fo}" height="${fo}">` +
             `<div xmlns="http://www.w3.org/1999/xhtml" class="room-label${dark ? " dark" : ""}">` +
             `${esc(room.name)}</div></foreignObject>`;
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
        .room-label {
          display: flex; align-items: center; justify-content: center;
          width: 100%; height: 100%;
          color: #fff; font: 600 8.5px/1.2 -apple-system, sans-serif;
          text-align: center; word-break: break-word; overflow: hidden;
          opacity: .92; padding: 2px;
        }
        .room-label.dark { color: #222; }
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
  if (state.areaGraph) renderAreaPanel();

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
    $("#options-head").textContent = "Draft options";
    $("#options").innerHTML = '<div id="options-placeholder">— no draft in progress —</div>';
  }

  // Scepter color tint on the board area
  const housePanel = $("#house-panel");
  const SCEPTER_CLASSES = ["blueprint", "green", "red", "bedroom", "hallway", "shop"]
    .map((c) => `scepter-${c}`);
  for (const cls of SCEPTER_CLASSES) housePanel.classList.remove(cls);
  if (frame.scepter_color) housePanel.classList.add(`scepter-${frame.scepter_color}`);

  // Action log: full history, scroll-locked to newest unless user scrolled up.
  const logEl = $("#action-log");
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 4;
  let log = "";
  for (let i = 1; i <= idx; i++) {
    const a = run.frames[i].action;
    if (!a) continue;
    log += `<div class="log-row${a.explore ? " explore" : ""}${i === idx ? " current" : ""}" data-move="${i}">
      <span class="n">${i}</span>${esc(a.text)}</div>`;
  }
  logEl.innerHTML = log || '<div class="dim">—</div>';
  // The current row is always the LAST rendered row (log runs 1..idx), so
  // "keep the current move visible" reduces to "stay pinned to the bottom" —
  // but only when the user was already there. If they scrolled up to read
  // history, never yank them down mid-playback.
  if (atBottom) {
    logEl.scrollTop = logEl.scrollHeight;
  }

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

/* ============================================================ area graph */

// Band y-positions: surface on top, anchor in the middle, underground below.
// Values are normalised fractions of the chart height (0 = top, 1 = bottom).
const BAND_Y_CENTRE = { surface: 0.18, anchor: 0.50, underground: 0.82 };
// Area graph lives side-by-side with the house panel.  The house is portrait
// (5-wide × 9-tall), so it needs ~56% of its height as width; the graph gets
// the remaining horizontal space.  We design the viewBox at 600×520 so it
// renders comfortably in a ~45% share of a 700 px centre column without a
// scrollbar.  The taller viewBox (520 vs 420) gives the anchor band more
// vertical room to spread 8 nodes without overlap.
const AG_W = 600, AG_H = 520;
// Left padding is generous (72 px) so labels on depth-0 nodes can sit to the
// right of their node without being clipped by the SVG edge.  Right padding
// reserves 20 px; the null-depth strip takes an additional 40 px at the far
// right, so xUsable = 600 − 72 − 20 − 40 = 468.
const AG_PAD_L = 72, AG_PAD_R = 20, AG_PAD_T = 14, AG_PAD_B = 14;
const AG_NODE_R = 9;       // circle radius for modelled nodes
const AG_NODE_R_UNMOD = 7; // smaller radius for unmodelled nodes
// Maximum label characters before we elide with "…" and show full name as
// a tooltip title.  Each character at 8.5 px ≈ 6 px average-width → cap
// at 14 chars so labels stay within a ~84 px slot beside the node.
const AG_LABEL_MAX = 14;

// Shorten a node name for the SVG label: take only the text before the first
// '(' (the parenthetical is always context, not identity), then elide to
// AG_LABEL_MAX with "…".  The full name still lives in the SVG <title>.
function areaShortName(name) {
  const base = name.split("(")[0].trimEnd();
  return base.length <= AG_LABEL_MAX ? base : base.slice(0, AG_LABEL_MAX - 1) + "…";
}

// Derive pixel positions for every node from depth and band.  depth:null nodes
// go into a separate "unreachable" strip at the right edge of the chart.
function areaLayout(nodes) {
  // Group nodes by (depth, band) so we can spread them evenly.
  const byDepthBand = {};  // key: "depth:band" -> [node, ...]
  const nullDepth = [];
  for (const n of nodes) {
    if (n.depth == null) { nullDepth.push(n); continue; }
    const key = `${n.depth}:${n.band}`;
    (byDepthBand[key] = byDepthBand[key] || []).push(n);
  }

  // x from depth: map 0..maxDepth onto [AG_PAD_L, AG_W - AG_PAD_R - 40]
  // (subtract 40 to leave room for the null-depth strip).
  const maxDepth = Math.max(0, ...nodes.filter((n) => n.depth != null).map((n) => n.depth));
  const xUsable = AG_W - AG_PAD_L - AG_PAD_R - 40;
  const X = (d) => AG_PAD_L + (d / Math.max(maxDepth, 1)) * xUsable;

  // y from band, then spread within a (depth, band) group.
  const yUsable = AG_H - AG_PAD_T - AG_PAD_B;
  const Y_BAND = (band) => AG_PAD_T + (BAND_Y_CENTRE[band] || 0.5) * yUsable;
  // SPREAD: pixels between node centres when multiple share a (depth, band) slot.
  // The worst case is 9 anchor nodes at depth=3 (garage + 8 outer rooms):
  // at SPREAD=34 the group spans ±136 px around the band centre (y≈260).
  // The taller viewBox (AG_H=520) keeps them inside the anchor band's
  // ~43% zone (≈ 214 px) and clear of the surface (y≈103) and
  // underground (y≈417) band centres.
  const SPREAD = 34;

  const pos = {};
  for (const [key, group] of Object.entries(byDepthBand)) {
    const [depthStr, band] = key.split(":");
    const depth = Number(depthStr);
    const cx = X(depth);
    const cy = Y_BAND(band);
    // Centre the group around cy; odd n means middle node is at cy.
    // Alternate label side: even-index nodes get label on the right, odd on
    // the left (see label pass below).  Store side in pos so the label pass
    // can read it without recomputing group membership.
    group.forEach((n, i) => {
      const offset = (i - (group.length - 1) / 2) * SPREAD;
      pos[n.id] = { x: cx, y: cy + offset, labelSide: i % 2 === 0 ? "right" : "left" };
    });
  }
  // Null-depth nodes: park in the rightmost strip.
  nullDepth.forEach((n, i) => {
    pos[n.id] = {
      x: AG_W - AG_PAD_R - 20,
      y: AG_PAD_T + (i + 0.5) * (yUsable / Math.max(nullDepth.length, 1)),
      labelSide: "right",
    };
  });
  return pos;
}

// Colours for the three bands.
const BAND_COLOR = { surface: "#2a9d8f", anchor: "#8a919c", underground: "#7a50a0" };

function renderAreaSvg(graphData, visitTotals, visitedSet, currentAreaId, mode) {
  const { nodes, edges } = graphData;
  const pos = areaLayout(nodes);

  // --- edge pass ---
  let edgeSvg = "";
  for (const e of edges) {
    const p1 = pos[e.from], p2 = pos[e.to];
    if (!p1 || !p2) continue;
    // Small offset to give directed pairs a visible gap.
    const dx = p2.x - p1.x, dy = p2.y - p1.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const ox = (dy / len) * 2.5, oy = -(dx / len) * 2.5;
    const x1 = p1.x + ox, y1 = p1.y + oy;
    const x2 = p2.x + ox, y2 = p2.y + oy;
    const dash = e.stub ? "stroke-dasharray='5 3'" : "";
    edgeSvg += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}"
      x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
      class="ag-edge${e.stub ? " ag-stub" : ""}" ${dash}/>`;
  }

  // --- node pass ---
  let nodeSvg = "";
  // Compute aggregate visit scale for colour mapping.
  let maxVisits = 1;
  if (mode === "agg") {
    for (const v of Object.values(visitTotals)) if (v > maxVisits) maxVisits = v;
  }

  for (const n of nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const r = n.modelled ? AG_NODE_R : AG_NODE_R_UNMOD;

    let fill, stroke, opacity = 1;
    if (mode === "replay") {
      if (n.id === currentAreaId) {
        fill = "#e8c34a"; stroke = "#14161a"; // current — bright gold
      } else if (visitedSet.has(n.id)) {
        fill = BAND_COLOR[n.band] || "#8a919c"; stroke = "rgba(0,0,0,.4)"; // visited
      } else {
        fill = "#2a2e35"; stroke = "#44484f"; // not yet reached this episode
        opacity = 0.55;
      }
    } else {
      // Aggregate mode: use a single accent colour (#2a9d8f) for all nodes so
      // opacity alone encodes visit rate.  Using per-band colours here was the
      // root cause of defect 3: the anchor band's grey (#8a919c) looked dim
      // even at full opacity (house, ~32k visits) while the surface band's
      // vivid teal (#2a9d8f) looked brighter even at ~30% opacity (west_path,
      // ~10k visits), inverting the intended "more visits = more prominent"
      // encoding.  A uniform hue lets opacity carry the full signal.
      const frac = Math.min((visitTotals[n.id] || 0) / maxVisits, 1);
      fill = frac > 0 ? "#2a9d8f" : "#2a2e35";
      opacity = frac > 0 ? 0.25 + 0.75 * frac : 0.25;
      stroke = "#44484f";
    }

    // Unmodelled nodes get a dashed ring instead of a filled disc.
    if (!n.modelled) {
      nodeSvg += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r}"
        fill="none" stroke="${stroke}" stroke-width="1.5" stroke-dasharray="3 2"
        opacity="${opacity}">
        <title>${esc(n.name)} (unmodelled)</title></circle>`;
    } else {
      nodeSvg += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r}"
        fill="${fill}" stroke="${stroke}" stroke-width="${n.id === currentAreaId ? 2.5 : 1.5}"
        opacity="${opacity}">
        <title>${esc(n.name)}${mode === "agg" ? " — " + fmtInt(visitTotals[n.id] || 0) + " visits" : ""}</title></circle>`;
    }
    // Label — short name beside the node, full name in the SVG <title> tooltip.
    // Only drawn for modelled nodes (unmodelled already show a title on hover).
    // For nodes in a crowded column (anchor band at depth=3 has 9 modelled
    // nodes: garage + 8 outer rooms) labels alternate left/right so adjacent
    // labels don't collide.  For the depth-0 node (house) the label is anchored
    // "start" to the right so it does not extend left of the SVG edge.
    if (n.modelled) {
      const labelOpacity = opacity < 0.5 ? 0.5 : opacity;
      const short = areaShortName(n.name);
      const side = p.labelSide || "right";
      let lx, ly, anchor;
      if (n.depth === 0) {
        // Leftmost column: label to the right so it doesn't clip the SVG edge.
        lx = p.x + r + 4;
        ly = p.y + 3;  // vertically centred on node
        anchor = "start";
      } else if (side === "left") {
        lx = p.x - r - 4;
        ly = p.y + 3;
        anchor = "end";
      } else {
        lx = p.x + r + 4;
        ly = p.y + 3;
        anchor = "start";
      }
      nodeSvg += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}"
        class="ag-label" opacity="${labelOpacity}"
        text-anchor="${anchor}"><title>${esc(n.name)}</title>${esc(short)}</text>`;
    }
  }

  // Null-depth separator line (if any).
  const hasNull = nodes.some((n) => n.depth == null);
  const sepX = AG_W - AG_PAD_R - 40;
  const sepLine = hasNull
    ? `<line x1="${sepX}" y1="${AG_PAD_T}" x2="${sepX}" y2="${AG_H - AG_PAD_B}"
        stroke="#33373f" stroke-width="1" stroke-dasharray="4 4"/>
       <text x="${sepX + 4}" y="${AG_PAD_T + 8}" class="ag-label" fill="#44484f">unreachable</text>`
    : "";

  return `<svg viewBox="0 0 ${AG_W} ${AG_H}" xmlns="http://www.w3.org/2000/svg">
    <style>
      .ag-edge { stroke: #33373f; stroke-width: 1.2; }
      .ag-stub { stroke: #4a5060; stroke-width: 1.2; }
      .ag-label { fill: #c8ccd4; font-size: 8px; font-family: -apple-system, sans-serif; pointer-events: none; }
    </style>
    ${sepLine}${edgeSvg}${nodeSvg}
  </svg>`;
}

function renderAreaLegend(mode, hasData) {
  const parts = [
    // Modelled vs unmodelled is always visible.
    `<span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;
      background:#2a9d8f;vertical-align:middle;margin-right:4px"></span>modelled area</span>`,
    `<span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;
      border:1.5px dashed #8a919c;background:none;vertical-align:middle;margin-right:4px"></span>unmodelled (no engine contents)</span>`,
    `<span><svg width="22" height="4" style="vertical-align:middle;margin-right:4px">
      <line x1="0" y1="2" x2="22" y2="2" stroke="#4a5060" stroke-width="1.5" stroke-dasharray="4 3"/></svg>stub gate (passes unconditionally — upper bound)</span>`,
  ];
  if (mode === "replay") {
    parts.push(
      `<span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;
        background:#e8c34a;vertical-align:middle;margin-right:4px"></span>current</span>`,
      `<span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;
        background:#2a9d8f;vertical-align:middle;margin-right:4px"></span>visited this episode</span>`,
    );
  } else if (!hasData) {
    parts.push(`<span style="color:var(--dim)">no off-grid travel recorded yet</span>`);
  } else {
    parts.push(
      `<span>opacity = relative visit rate (all seeds, all areas on one scale)</span>`,
    );
  }
  $("#area-legend").innerHTML = parts.join("");
}

// Sum visit counts across all buckets for each area.
function areaVisitTotals(areaStats) {
  const totals = {};
  for (const b of (areaStats && areaStats.train) || []) {
    for (const [id, n] of Object.entries(b.visits || {})) {
      totals[id] = (totals[id] || 0) + n;
    }
  }
  return totals;
}

// Collect the set of area ids visited up to frameIdx.
function visitedAreasUpTo(frames, upTo) {
  const visited = new Set();
  for (let i = 0; i <= upTo; i++) {
    const area = frames[i] && frames[i].area;
    if (area) visited.add(area);
  }
  return visited;
}

async function ensureAreaGraph() {
  if (!state.areaGraph) {
    state.areaGraph = await getJSON("/api/areas").catch(() => null);
  }
  if (!state.areaStats) {
    state.areaStats = await getJSON("/api/area_stats").catch(() => ({ train: [] }));
  }
}

function renderAreaPanel() {
  const graphData = state.areaGraph;
  if (!graphData) {
    $("#area-graph").innerHTML = '<p class="dim" style="padding:4px 0">area graph unavailable</p>';
    $("#area-legend").innerHTML = "";
    return;
  }

  const mode = state.areaMode;
  const visitTotals = areaVisitTotals(state.areaStats);
  const hasAggData = Object.keys(visitTotals).length > 0;

  let currentAreaId = "house"; // default when player is on the grid
  let visitedSet = new Set(["house"]);

  if (mode === "replay" && state.run && state.run.frames) {
    const frame = state.run.frames[state.frameIdx];
    currentAreaId = frame.area || "house";
    visitedSet = visitedAreasUpTo(state.run.frames, state.frameIdx);
    visitedSet.add("house"); // house is always considered visited
  }

  $("#area-graph").innerHTML = renderAreaSvg(graphData, visitTotals, visitedSet, currentAreaId, mode);
  renderAreaLegend(mode, hasAggData);
}

// Wire up the mode toggle buttons.
$("#area-mode-replay").onclick = () => {
  state.areaMode = "replay";
  $("#area-mode-replay").classList.add("active");
  $("#area-mode-agg").classList.remove("active");
  renderAreaPanel();
};
$("#area-mode-agg").onclick = () => {
  state.areaMode = "agg";
  $("#area-mode-agg").classList.add("active");
  $("#area-mode-replay").classList.remove("active");
  renderAreaPanel();
};

/* ========================================================= upgrade stats */

function renderUpgradeStats() {
  const el = $("#upgrade-stats");
  const us = state.upgradeStats || { variants: [], economy: [], gates: {} };

  let html = "";

  // --- block 1: chosen vs offered per variant ---
  html += `<div class="panel-head" style="margin-top:0">Upgrade variants</div>`;
  const variants = us.variants || [];
  if (!variants.length) {
    html += `<p class="dim">no upgrade decisions recorded yet</p>`;
  } else {
    const maxOffered = variants[0].offered;  // already sorted descending by offered
    html += `<div id="upgrade-variants">`;
    for (const v of variants) {
      const pct = fmtPct(v.selection_rate);
      const chosenW = (v.offered > 0 ? v.chosen / maxOffered * 100 : 0).toFixed(2);
      const offeredW = (v.offered / maxOffered * 100).toFixed(2);
      html += `<div class="ubar">
        <span class="uname" title="${esc(v.variant)}">${esc(v.variant)}</span>
        <div class="utrack">
          <div class="ufill-offered" style="width:${offeredW}%"></div>
          <div class="ufill-chosen" style="width:${chosenW}%"></div>
        </div>
        <span class="upct" title="${fmtInt(v.chosen)} chosen / ${fmtInt(v.offered)} offered">${pct}</span>
      </div>`;
    }
    html += `</div>`;
    html += `<div style="font-size:11px;color:var(--dim);margin-top:2px;margin-bottom:10px">
      dark = offered, bright = chosen; percentage = selection rate</div>`;
  }

  // --- block 2: disk economy over time (dual y-axis) ---
  // mean_disks_held (~0–3) and mean_slots_upgraded (~0–14) differ by ~10×,
  // so a shared axis squashes the disks-held line to invisibility.  Each
  // series gets its own scale: left axis (blue) for disks_held, right axis
  // (gold) for slots_upgraded.  Decision-count bars sit behind both lines.
  const economy = us.economy || [];
  const axis = us.economy_axis || "day";
  html += `<div class="panel-head">Disk economy over time</div>`;
  html += `<div id="upgrade-econ-legend">
    <span><span class="sw" style="background:#5b9dd9"></span>mean disks held <span class="dim">(left axis)</span></span>
    <span><span class="sw" style="background:#e8c34a"></span>mean slots upgraded <span class="dim">(right axis)</span></span>
    <span class="dim">x-axis: ${axis}</span>
  </div>`;
  if (!economy.length) {
    html += `<p class="dim">no economy data yet</p>`;
  } else {
    // Left = 44 to fit y-axis tick labels; Right = 44 for the right-axis ticks.
    const SW = 900, SH = 160, L = 44, R = 44, T = 10, B = 24;
    const xs = economy.map((b) => b.bucket_start);
    const xmin = xs[0], xmax = xs[xs.length - 1] || xs[0];
    const xrange = xmax - xmin || 1;
    const X = (v) => L + ((v - xmin) / xrange) * (SW - L - R);

    // Left axis: mean_disks_held
    const ymaxL = Math.max(...economy.map((b) => b.mean_disks_held || 0), 0.1) * 1.2;
    const YL = (v) => T + (1 - v / ymaxL) * (SH - T - B);
    // Right axis: mean_slots_upgraded
    const ymaxR = Math.max(...economy.map((b) => b.mean_slots_upgraded || 0), 0.1) * 1.2;
    const YR = (v) => T + (1 - v / ymaxR) * (SH - T - B);

    let g = "", s = "";
    // Grid lines from left axis.
    const ystepL = niceStep(ymaxL / 3);
    for (let v = 0; v <= ymaxL; v += ystepL) {
      g += `<line x1="${L}" y1="${YL(v).toFixed(1)}" x2="${SW - R}" y2="${YL(v).toFixed(1)}" class="grid"/>` +
           `<text x="${L - 5}" y="${(YL(v) + 4).toFixed(1)}" class="tick ec-tick-l" text-anchor="end">${v % 1 ? v.toFixed(1) : v}</text>`;
    }
    // Right-axis ticks (no grid line to avoid double-gridding).
    const ystepR = niceStep(ymaxR / 3);
    for (let v = 0; v <= ymaxR; v += ystepR) {
      g += `<text x="${SW - R + 5}" y="${(YR(v) + 4).toFixed(1)}" class="tick ec-tick-r" text-anchor="start">${v % 1 ? v.toFixed(1) : v}</text>`;
    }
    // x-axis labels — up to 8 ticks.
    const xstep = niceStep(xrange / 6);
    for (let v = xmin; v <= xmax + 1; v += xstep) {
      g += `<text x="${X(v).toFixed(1)}" y="${SH - B + 14}" class="tick" text-anchor="middle">${Math.round(v)}</text>`;
    }

    // Decision-count bars (background, 25% height) — drawn first so lines sit above.
    const maxDec = Math.max(...economy.map((b) => b.decisions), 1);
    const bw = Math.max(2, (SW - L - R) / economy.length - 1);
    for (const b of economy) {
      const bh = ((b.decisions / maxDec) * (SH - T - B) * 0.25).toFixed(1);
      const bx = (X(b.bucket_start) - bw / 2).toFixed(1);
      s += `<rect x="${bx}" y="${(SH - B - Number(bh)).toFixed(1)}" width="${bw.toFixed(1)}"
        height="${bh}" fill="#33373f">
        <title>${fmtInt(b.decisions)} decisions @ ${axis} ${b.bucket_start}</title></rect>`;
    }

    // Line: mean_disks_held on the LEFT scale.
    const diskPts = economy.filter((b) => b.mean_disks_held != null)
      .map((b) => `${X(b.bucket_start).toFixed(1)},${YL(b.mean_disks_held).toFixed(1)}`);
    if (diskPts.length > 1)
      s += `<polyline points="${diskPts.join(" ")}" fill="none" stroke="#5b9dd9" stroke-width="2"/>`;
    // Line: mean_slots_upgraded on the RIGHT scale.
    const slotPts = economy.filter((b) => b.mean_slots_upgraded != null)
      .map((b) => `${X(b.bucket_start).toFixed(1)},${YR(b.mean_slots_upgraded).toFixed(1)}`);
    if (slotPts.length > 1)
      s += `<polyline points="${slotPts.join(" ")}" fill="none" stroke="#e8c34a" stroke-width="2"/>`;

    html += `<div class="chart"><svg viewBox="0 0 ${SW} ${SH}" xmlns="http://www.w3.org/2000/svg">
      <style>
        .grid { stroke: #2a2e35; stroke-width: 1; }
        .tick { fill: #8a919c; font-size: 10px; }
        .ec-tick-l { fill: #5b9dd9; }
        .ec-tick-r { fill: #e8c34a; }
      </style>${g}${s}</svg></div>`;
  }

  // --- block 3: gate context ---
  const gates = us.gates || {};
  html += `<div class="panel-head">Gate context</div>`;
  if (!gates.decisions) {
    html += `<p class="dim">no gate data yet</p>`;
  } else {
    const { decisions, catacombs_unlocked, slot_draft_count_zero } = gates;
    const d = decisions || 1;  // guard against zero division
    const tiles = [
      ["Upgrade decisions", fmtInt(decisions), null],
      ["Catacombs unlocked", fmtInt(catacombs_unlocked),
        fmtPct(catacombs_unlocked / d) + " of decisions"],
      ["Zero-draft decisions", fmtInt(slot_draft_count_zero),
        fmtPct(slot_draft_count_zero / d) + " of decisions"],
    ];
    html += `<div id="upgrade-gates">`;
    for (const [k, v, sub] of tiles) {
      html += `<div class="upgrade-gate-tile">
        <div class="gv">${v}</div>
        <div class="gk">${esc(k)}</div>
        ${sub ? `<div style="font-size:10px;color:var(--dim)">${esc(sub)}</div>` : ""}
      </div>`;
    }
    html += `</div>`;
  }

  el.innerHTML = html;
}

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
