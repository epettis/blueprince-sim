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
  $("#tab-progress").classList.toggle("active", tab === "progress");
  $("#tab-runs").classList.toggle("active", tab === "runs");
  $("#tab-play").classList.toggle("active", tab === "play");
  $("#view-dashboard").classList.toggle("hidden", tab !== "dashboard");
  $("#view-progress").classList.toggle("hidden", tab !== "progress");
  $("#view-runs").classList.toggle("hidden", tab !== "runs");
  $("#view-play").classList.toggle("hidden", tab !== "play");
  if (tab === "runs") {
    refreshRuns();
    ensureAreaGraph().then(() => renderAreaPanel());
  } else if (tab === "play") {
    ensureAreaGraph().then(() => { if (state.playState) renderPlayArea(); });
  } else if (tab === "progress") {
    refreshProgress();
  } else {
    refreshDashboard();
  }
}
$("#tab-dashboard").onclick = () => setTab("dashboard");
$("#tab-progress").onclick = () => setTab("progress");
$("#tab-runs").onclick = () => setTab("runs");
$("#tab-play").onclick = () => setTab("play");

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

/* -------------------------------------------------------------- progress */
/* Parallels rl/dashboard.py's SPECS tuple: same 20 metrics, same three
 * panels, same labels/goals, so the browser reads like the CLI's in-place
 * terminal dashboard. Keys are the literal sb3 logger keys (e.g.
 * "train/approx_kl") that rl/train.py's checkpoint metadata carries when
 * present -- see _logger_snapshot there and Observatory.metrics() in
 * web/server.py, which is what makes them show up in metrics.train rows. */
const METRIC_SPECS = [
  // PROGRESS -- monotonic counters (bar:false, no trend line, matching the
  // CLI's "left column, top panel" comment).
  { key: "blueprince/episodes", label: "episodes", panel: "PROGRESS", fmt: "int", bar: false },
  { key: "time/iterations", label: "iterations", panel: "PROGRESS", fmt: "int", bar: false },
  { key: "time/total_timesteps", label: "timesteps", panel: "PROGRESS", fmt: "int", bar: false },
  { key: "time/time_elapsed", label: "elapsed", panel: "PROGRESS", fmt: "duration", bar: false },
  { key: "time/fps", label: "fps", panel: "PROGRESS", fmt: "int", goal: "larger" },
  // OUTCOMES -- what the agent actually achieves.
  { key: "blueprince/win_rate_1k", label: "win_rate_1k", panel: "OUTCOMES", goal: "larger" },
  { key: "blueprince/win_rate_exploit_1k", label: "win_exploit", panel: "OUTCOMES", goal: "larger" },
  { key: "blueprince/win_rate_explore_1k", label: "win_explore", panel: "OUTCOMES", goal: "larger" },
  { key: "rollout/ep_rew_mean", label: "ep_rew_mean", panel: "OUTCOMES", goal: "larger" },
  { key: "rollout/ep_len_mean", label: "ep_len_mean", panel: "OUTCOMES", decimals: 2 },
  // LEARNING -- optimiser health.
  { key: "train/approx_kl", label: "approx_kl", panel: "LEARNING", goal: "smaller" },
  { key: "train/clip_fraction", label: "clip_fraction", panel: "LEARNING", goal: "<0.3" },
  { key: "train/clip_range", label: "clip_range", panel: "LEARNING", decimals: 3 },
  { key: "train/entropy_loss", label: "entropy_loss", panel: "LEARNING", goal: "rises~0" },
  { key: "train/explained_variance", label: "explained_var", panel: "LEARNING", goal: "larger" },
  { key: "train/learning_rate", label: "learning_rate", panel: "LEARNING", fmt: "sci" },
  { key: "train/loss", label: "loss", panel: "LEARNING", goal: "~0" },
  { key: "train/n_updates", label: "n_updates", panel: "LEARNING", fmt: "int", bar: false },
  { key: "train/policy_gradient_loss", label: "pg_loss", panel: "LEARNING", goal: "~0" },
  { key: "train/value_loss", label: "value_loss", panel: "LEARNING", goal: "smaller" },
];
const PROGRESS_PANELS = ["PROGRESS", "OUTCOMES", "LEARNING"];

// H:MM:SS, matching rl/dashboard.py::format_duration exactly (no day rollover).
function fmtDuration(sec) {
  const total = Math.max(0, Math.floor(sec));
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
// Matches Python's f"{value:.2e}" exponent width (JS's toExponential omits
// the leading zero on single-digit exponents, e.g. "3.00e-4" vs "3.00e-04").
function fmtSci(v) {
  return v.toExponential(2).replace(/e([+-])(\d)$/, "e$10$2");
}
// Mirrors rl/dashboard.py::format_value's fmt dispatch (int/duration/sci/float).
function formatMetric(spec, v) {
  if (v == null) return "—";
  switch (spec.fmt) {
    case "int": return Math.round(v).toLocaleString("en-US");
    case "duration": return fmtDuration(v);
    case "sci": return fmtSci(v);
    default: return v.toFixed(spec.decimals ?? 4);
  }
}

// One metric's trend line across this run's full recorded history. Reuses
// niceStep-adjacent thinking (min/max axis labels) but at sparkline scale;
// the CLI's "warming up" (fewer than 2 samples) / "constant" (no spread)
// bar states are echoed here as text so degrading gracefully reads the same
// way in both places.
function renderMetricSpark(rows, spec) {
  const pts = rows.filter((m) => m[spec.key] != null).map((m) => ({ t: m.sampled_at, v: m[spec.key] }));
  if (!pts.length) return '<div class="spark-empty">no data</div>';
  if (pts.length < 2) return '<div class="spark-empty">warming up</div>';
  const vs = pts.map((p) => p.v);
  const vmin = Math.min(...vs), vmax = Math.max(...vs);
  if (vmin === vmax) return `<div class="spark-empty">constant (${formatMetric(spec, vmin)})</div>`;
  const SW = 100, SH = 36, PAD = 2;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
  const X = (t) => PAD + (t1 > t0 ? (t - t0) / (t1 - t0) : 0) * (SW - 2 * PAD);
  const Y = (v) => SH - PAD - ((v - vmin) / (vmax - vmin)) * (SH - 2 * PAD);
  const pointsAttr = pts.map((p) => `${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${SW} ${SH}" class="spark" preserveAspectRatio="none">
      <polyline points="${pointsAttr}" class="spark-line"/>
    </svg>
    <div class="spark-range"><span>${formatMetric(spec, vmin)}</span><span>${formatMetric(spec, vmax)}</span></div>`;
}

function metricCardHtml(rows, spec) {
  let last = null;
  for (let i = rows.length - 1; i >= 0; i--) {
    if (rows[i][spec.key] != null) { last = rows[i][spec.key]; break; }
  }
  const goal = spec.goal ? `<span class="metric-goal">${esc(spec.goal)}</span>` : "";
  const trend = spec.bar === false ? "" : renderMetricSpark(rows, spec);
  return `<div class="metric-card">
    <div class="metric-head"><span class="metric-label">${esc(spec.label)}</span>${goal}</div>
    <div class="metric-value">${formatMetric(spec, last)}</div>
    ${trend}
  </div>`;
}

function renderProgressTab(metrics) {
  const train = metrics.train || [];
  const banner = $("#progress-banner");
  const hasAnyNewKeys = train.some((m) => METRIC_SPECS.some((s) => m[s.key] != null));
  if (!train.length) {
    banner.textContent = "no metrics yet — waiting for the first checkpoint sample";
    banner.classList.remove("hidden");
  } else if (!hasAnyNewKeys) {
    banner.textContent = "this run's metrics.jsonl predates the train/*, rollout/* and time/* " +
      "metrics (only episodes/timesteps/win-rate were recorded before) — every card below will " +
      "read “no data” until the trainer checkpoints again on the current code.";
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
  for (const panel of PROGRESS_PANELS) {
    $(`#progress-panel-${panel}`).innerHTML =
      METRIC_SPECS.filter((s) => s.panel === panel).map((s) => metricCardHtml(train, s)).join("");
  }
}

async function refreshProgress() {
  try {
    const [summary, metrics] = await Promise.all([getJSON("/api/summary"), getJSON("/api/metrics")]);
    renderProgressTab(metrics);
    $("#conn").textContent = `run: ${summary.run}`;
  } catch (err) {
    $("#conn").textContent = "server unreachable";
  }
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
  // Reset zoom on both SVGs when a different run is loaded.
  resetPanZoom("house-svg");
  resetPanZoom("area-graph-svg");
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

function renderHouse(frame, targetId = "house", svgKey = "house-svg") {
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
      // Drafting and entering are distinct: a placed room is not one the
      // player has stepped into (see GameState.entered). `frame.entered` is
      // only present on Play tab frames (web/play.py); Runs tab replay
      // frames have no such field and simply never show the overlay. A
      // diagonal fade over the whole tile marks an unvisited room -- the
      // category color still shows through the near corner so the room is
      // identifiable, just visibly unvisited.
      if (frame.entered && frame.entered[cell] === false) {
        svg += `<rect x="${x + 4}" y="${y + 4}" width="${CELL - 8}" height="${CELL - 8}" rx="9"
                 fill="url(#unvisited-fade)" class="room-unvisited"><title>drafted, not yet entered</title></rect>`;
      }
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

  const houseEl = $("#" + targetId);
  houseEl.innerHTML =
    `<svg viewBox="0 0 ${2 * MARG + 5 * CELL} ${2 * MARG + 9 * CELL}"
          preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="unvisited-fade" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#0a0b0d" stop-opacity="0"/>
          <stop offset="100%" stop-color="#0a0b0d" stop-opacity=".62"/>
        </linearGradient>
      </defs>
      <style>
        .cell-bg { fill: #191c21; stroke: #262a31; stroke-width: 1; }
        .room { stroke: rgba(0,0,0,.35); stroke-width: 1.5; }
        .room-unvisited { pointer-events: none; }
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
  // Attach pan/zoom to the freshly rendered house SVG.
  const houseSvgEl = houseEl.querySelector("svg");
  if (houseSvgEl) attachPanZoom(houseSvgEl, svgKey);
}

/* -------------------------------------------------------- detail panel */

// Held special items as a row of chips: "{name} ×{count}" (count omitted at 1).
// Shared by the Runs (replay) detail panel and the Play tab -- both frames carry
// the same `inventory` field (see web/replay.py::_inventory_list).
function inventoryChipsHtml(items) {
  if (!items || !items.length) return '<p class="dim" style="margin:2px 0">— none —</p>';
  return items.map((it) =>
    `<span class="inv-chip">${esc(it.name)}${it.count > 1 ? ` <span class="n">×${it.count}</span>` : ""}</span>`
  ).join("");
}

function miniGlyph(mask) {
  const sz = 34, t = 7, w = 12, c = sz / 2 - w / 2;
  let s = `<rect x="4" y="4" width="${sz - 8}" height="${sz - 8}" rx="5" fill="#3a3f48"/>`;
  if (mask & N) s += `<rect x="${c}" y="0" width="${w}" height="${t}" fill="#c8ccd4"/>`;
  if (mask & S) s += `<rect x="${c}" y="${sz - t}" width="${w}" height="${t}" fill="#c8ccd4"/>`;
  if (mask & E) s += `<rect x="${sz - t}" y="${c}" width="${t}" height="${w}" fill="#c8ccd4"/>`;
  if (mask & W) s += `<rect x="0" y="${c}" width="${t}" height="${w}" fill="#c8ccd4"/>`;
  return `<svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}">${s}</svg>`;
}

// One draft-option card, shared by the Runs (replay) detail panel and the
// Play tab so both present orientation/rarity/layout/cost in identical visual
// language (the owner's ask was specifically to stop the Play tab reinventing
// this as plain buttons). `extra` lets a caller add interaction affordances:
//   chosen     - true when this is frame N+1's look-back at the picked slot
//   clickable  - true when the caller wired a click handler onto the card
//   dataAttrs  - raw ` key="val"` string(s) for the click handler to read
// `o.legal_orientations` (from web/replay.py::_option_legal_orientations) is
// every door mask this room could legally take at this doorway; when it has
// more than the one it was dealt in, the extra masks are shown as small dim
// glyphs so "orientation is hugely important" is visible even though nothing
// today lets a slot pick between them directly -- see the "also legal" note.
// Draft-panel header text: names the room the draft was opened from, not just
// its grid coordinate (the coordinate stays too, parenthetically, since room
// names can repeat across a house -- see env/actions.py::_room_name_at, the
// server-side counterpart this mirrors). The outer-room draft has no source
// cell at all (`from_cell === -1`, opened from the West Path doorstep off-grid)
// and so has no "facing" either; that case gets its own sentence instead of
// showing "facing ?".
function draftHeaderText(pend) {
  if (pend.from_cell === -1) return "Draft options — outer draft (West Path)";
  const loc = `r${Math.floor(pend.from_cell / 5) + 1}c${pend.from_cell % 5}`;
  const src = pend.from_room ? `${pend.from_room} (${loc})` : loc;
  return `Draft options — from ${src}, facing ${pend.direction || "?"}`;
}

function optionCardHtml(o, extra = {}) {
  const cls = ["opt", o.affordable ? "" : "unaffordable", extra.chosen ? "chosen" : "",
               extra.clickable ? "clickable" : ""].filter(Boolean).join(" ");
  const tags = [o.rarity || "", o.layout || "", o.forced ? "forced" : "", o.hidden ? "mystery" : ""]
    .filter(Boolean).join(" · ");
  const others = (o.legal_orientations || []).filter((m) => m !== o.orientation);
  const altHtml = others.length
    ? `<div class="opt-alt" title="This room's layout also legally fits the other highlighted orientation(s) at this doorway. Nothing lets you choose it directly for this option -- only Rotate options (when available) cycles the whole hand's orientations together.">
        <span class="opt-alt-label">also legal:</span>${others.map((m) => miniGlyph(m)).join("")}
      </div>`
    : "";
  return `<div class="${cls}"${extra.dataAttrs || ""}>${miniGlyph(o.orientation)}
    <div class="opt-body"><div class="name" style="color:${o.hidden ? "#8a919c" : catColor(o.category)}">${esc(o.name)}</div>
    <div class="sub">${esc(tags)}</div>${altHtml}</div>
    <div class="cost">${o.cost > 0 ? o.cost + " 💎" : "free"}</div></div>`;
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
  $("#inventory").innerHTML = inventoryChipsHtml(frame.inventory);

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
      draftHeaderText(pend) + (chosenSlot != null ? " (picked)" : "");
    $("#options").innerHTML = pend.options.map((o) =>
      optionCardHtml(o, { chosen: o.slot === chosenSlot })).join("");
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

/* =========================================================== pan / zoom */

// Pan/zoom state keyed by a stable string id.  Zoom state survives re-renders
// (frame changes) but is reset when a different run is selected (see loadRun).
const PZ_STATE = {};    // { x, y, w, h } — current viewBox window
const PZ_ORIGIN = {};   // { ox, oy, ow, oh } — original design viewBox
const PZ_MIN_SCALE = 1, PZ_MAX_SCALE = 8;

// Attach wheel-to-zoom and drag-to-pan behaviour to an SVG element.
// stateKey is a stable string so the zoom level persists across innerHTML
// replacements that create a new SVG element.
//
// IMPORTANT: the wheel handler is registered with { passive: false } so that
// calling preventDefault() actually suppresses the page scroll.  Omitting
// that option (or using addEventListener without it) causes browsers to ignore
// preventDefault on wheel events, and the page scrolls behind the zoom.
//
// The implementation manipulates the SVG viewBox, not CSS transforms, so
// strokes, text, and dashed patterns scale correctly and stay crisp.
function attachPanZoom(svgEl, stateKey) {
  // Parse the original (design) viewBox.  We always read it fresh from the
  // element attribute so that a reset-then-reattach correctly picks up the
  // design dimensions rather than whatever the zoomed state left behind.
  // The origin is stored separately (PZ_ORIGIN) so reset can restore it
  // even after a re-render replaces the SVG element.
  const vbAttr = svgEl.getAttribute("viewBox") || "0 0 100 100";
  const [ox, oy, ow, oh] = vbAttr.split(" ").map(Number);

  // On first attach (or after a reset) store the design dimensions.
  if (!PZ_ORIGIN[stateKey]) {
    PZ_ORIGIN[stateKey] = { ox, oy, ow, oh };
  }
  // Use the stored origin (not the potentially-modified attribute) so that
  // re-attaching after a reset sees the correct design bounds.
  const { ox: origX, oy: origY, ow: origW, oh: origH } = PZ_ORIGIN[stateKey];

  // Initialise pan/zoom state on first call for this key; preserve on
  // subsequent calls (frame changes must not reset the zoom level).
  if (!PZ_STATE[stateKey]) {
    PZ_STATE[stateKey] = { x: origX, y: origY, w: origW, h: origH };
  }

  // Apply the current (possibly pre-existing) zoom state to the new element.
  function applyViewBox() {
    const s = PZ_STATE[stateKey];
    svgEl.setAttribute("viewBox", `${s.x} ${s.y} ${s.w} ${s.h}`);
  }
  applyViewBox();

  // Convert a mouse event's client-space position to SVG viewBox coordinates.
  function clientToSVG(e) {
    const rect = svgEl.getBoundingClientRect();
    const s = PZ_STATE[stateKey];
    return {
      svgX: s.x + (e.clientX - rect.left) / rect.width  * s.w,
      svgY: s.y + (e.clientY - rect.top)  / rect.height * s.h,
    };
  }

  // Clamp pan so the content can't be dragged entirely out of view.
  // We require at least 20% of each dimension to remain visible.
  function clampPan(s) {
    const margin = 0.20;
    s.x = Math.min(s.x, origX + origW - s.w * margin);
    s.x = Math.max(s.x, origX + origW * margin - s.w);
    s.y = Math.min(s.y, origY + origH - s.h * margin);
    s.y = Math.max(s.y, origY + origH * margin - s.h);
  }

  // --- wheel: zoom about the cursor ---
  svgEl.addEventListener("wheel", (e) => {
    e.preventDefault();  // must prevent page scroll; requires {passive:false}
    const s = PZ_STATE[stateKey];
    const { svgX, svgY } = clientToSVG(e);
    // Normalise delta: positive = zoom in (reduce viewBox size).
    const delta = e.deltaMode === 1 ? e.deltaY * 20 : e.deltaY;  // line vs pixel mode
    const factor = Math.pow(1.0015, delta);  // ~1.0015^100 ≈ 1.16 per typical notch
    const newW = Math.max(origW / PZ_MAX_SCALE, Math.min(origW / PZ_MIN_SCALE, s.w * factor));
    const newH = Math.max(origH / PZ_MAX_SCALE, Math.min(origH / PZ_MIN_SCALE, s.h * factor));
    // Keep the point under the cursor stationary.
    s.x = svgX - (svgX - s.x) * (newW / s.w);
    s.y = svgY - (svgY - s.y) * (newH / s.h);
    s.w = newW;
    s.h = newH;
    clampPan(s);
    applyViewBox();
  }, { passive: false });

  // --- drag: pan while zoomed ---
  // Track in screen pixels to avoid the drift that occurs when converting to
  // SVG space using an origin (s.x/s.y) that changes with each mousemove.
  let drag = null;
  svgEl.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    const s = PZ_STATE[stateKey];
    drag = {
      startClientX: e.clientX, startClientY: e.clientY,
      startVbX: s.x, startVbY: s.y,
      vbW: s.w, vbH: s.h,   // snapshot so wheel during drag doesn't corrupt
    };
    svgEl.style.cursor = "grabbing";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const s = PZ_STATE[stateKey];
    const rect = svgEl.getBoundingClientRect();
    // Pixel delta → SVG-space delta (using the snapshot viewBox dims).
    const dsvgX = (e.clientX - drag.startClientX) / rect.width  * drag.vbW;
    const dsvgY = (e.clientY - drag.startClientY) / rect.height * drag.vbH;
    s.x = drag.startVbX - dsvgX;
    s.y = drag.startVbY - dsvgY;
    clampPan(s);
    applyViewBox();
  });
  const endDrag = () => { drag = null; svgEl.style.cursor = ""; };
  window.addEventListener("mouseup", endDrag);
  svgEl.addEventListener("mouseleave", () => { if (drag) { drag = null; svgEl.style.cursor = ""; } });

  // --- double-click: reset view ---
  svgEl.addEventListener("dblclick", () => {
    PZ_STATE[stateKey] = { x: origX, y: origY, w: origW, h: origH };
    applyViewBox();
  });
}

// Reset zoom state for a given key (called when a new run is selected so the
// new run starts at 1× zoom).  Clears both the current window and the origin
// record so the next attachPanZoom call re-reads the design viewBox.
function resetPanZoom(stateKey) {
  delete PZ_STATE[stateKey];
  delete PZ_ORIGIN[stateKey];
}

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

// The synthetic node id used to represent the collapsed outer-room slot.
const OUTER_NODE_ID = "__outer_room__";

// Shorten a node name for the SVG label: take only the text before the first
// '(' (the parenthetical is always context, not identity), then elide to
// AG_LABEL_MAX with "…".  The full name still lives in the SVG <title>.
function areaShortName(name) {
  const base = name.split("(")[0].trimEnd();
  return base.length <= AG_LABEL_MAX ? base : base.slice(0, AG_LABEL_MAX - 1) + "…";
}

// Return the set of outer-room node ids: exactly the 'to' targets of edges
// whose 'from' is 'west_path' AND whose 'requires' list contains
// 'outer_room_drawn'.  This is the canonical way to find them without
// hardcoding names — garage has a bidirectional edge with west_path but does
// not carry the 'outer_room_drawn' requirement, so it is correctly excluded.
function deriveOuterRoomIds(edges) {
  const ids = new Set();
  for (const e of edges) {
    if (e.from === "west_path" && Array.isArray(e.requires) && e.requires.includes("outer_room_drawn")) {
      ids.add(e.to);
    }
  }
  return ids;
}

// Build a transformed view of {nodes, edges} where the eight outer-room nodes
// are collapsed into a single synthetic OUTER_NODE_ID node.  The caller
// provides:
//   outerRoomIds  — Set of ids to collapse
//   drafteId      — the id of the drafted outer room (or null)
//   mode          — "replay" or "agg"
// Returns { nodes, edges, outerPos } where outerPos is the position object
// for the synthetic node (same depth/band as the real ones so toggling modes
// does not reflow the graph).
function collapseOuterRooms(graphData, outerRoomIds, mode) {
  const { nodes, edges } = graphData;

  // A representative outer room node (for depth/band — they all share them).
  const sampleOuter = nodes.find((n) => outerRoomIds.has(n.id));
  if (!sampleOuter) return { nodes, edges };  // nothing to collapse

  // Build the synthetic node.
  const synNode = {
    id: OUTER_NODE_ID,
    name: "outer room",       // overwritten by the caller for labels
    kind: "anchor",
    modelled: true,
    depth: sampleOuter.depth,
    band: sampleOuter.band,
    _isOuterSlot: true,       // flag for rendering logic
  };

  // Filter out the eight individual outer-room nodes; keep everything else.
  const newNodes = nodes.filter((n) => !outerRoomIds.has(n.id)).concat([synNode]);

  // Rewrite edges: any edge whose 'from' or 'to' is an outer-room id becomes
  // an edge from/to OUTER_NODE_ID instead, then deduplicate.
  // In replay mode we only keep edges originating FROM the drafted room (or
  // the west_path → synthetic edge).  In agg mode we keep the union of all
  // onward edges from all outer rooms.
  const seenEdges = new Set();
  const newEdges = [];

  for (const e of edges) {
    const fromIsOuter = outerRoomIds.has(e.from);
    const toIsOuter   = outerRoomIds.has(e.to);

    if (!fromIsOuter && !toIsOuter) {
      // Unrelated edge — pass through unchanged.
      newEdges.push(e);
      continue;
    }

    // In replay mode: only include onward edges from the drafted room.
    // "Onward" means from an outer room to somewhere that is NOT west_path
    // (the west_path → outer edges are implicit; keep the synthetic inbound
    // edge only).
    if (mode === "replay") {
      // west_path → outer_room: rewrite as west_path → OUTER_NODE_ID.
      if (e.from === "west_path" && toIsOuter) {
        const key = `west_path->${OUTER_NODE_ID}`;
        if (!seenEdges.has(key)) { seenEdges.add(key); newEdges.push({ ...e, to: OUTER_NODE_ID }); }
        continue;
      }
      // outer_room → west_path: skip (the return edge is implied by the inbound one).
      if (fromIsOuter && e.to === "west_path") continue;
      // outer_room → elsewhere: only if this room is the drafted outer room.
      if (fromIsOuter && e.to !== "west_path") {
        // We leave 'from' as the real id so the caller can filter by draftedId.
        // The caller replaces this with OUTER_NODE_ID only if fromIsOuter AND
        // the room matches.  Handled by the _outerFrom flag below.
        newEdges.push({ ...e, _outerFrom: true });
        continue;
      }
      // Fallthrough (e.g. something → outer_room other than west_path): drop.
      continue;
    }

    // Aggregate mode: keep all edges, rewriting outer ids.
    const rewrittenFrom = fromIsOuter ? OUTER_NODE_ID : e.from;
    const rewrittenTo   = toIsOuter   ? OUTER_NODE_ID : e.to;
    if (rewrittenFrom === rewrittenTo) continue;  // self-loop after collapse
    // Skip outer→west_path return edges — they would duplicate west_path→outer.
    if (rewrittenFrom === OUTER_NODE_ID && rewrittenTo === "west_path") continue;
    const key = `${rewrittenFrom}->${rewrittenTo}`;
    if (!seenEdges.has(key)) {
      seenEdges.add(key);
      newEdges.push({ ...e, from: rewrittenFrom, to: rewrittenTo, _aggOuter: fromIsOuter });
    }
  }

  return { nodes: newNodes, edges: newEdges };
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
  // With the outer rooms collapsed to one node the worst-case anchor column at
  // depth=3 is now just: garage + outer_room_slot = 2 nodes, so SPREAD only
  // matters for other columns.  Keep 34 px so any future expansion is safe.
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

function renderAreaSvg(graphData, visitTotals, visitedSet, currentAreaId, mode, outerRoomIds, draftedOuterRoomId) {
  // Collapse the eight outer-room nodes into one synthetic slot before layout.
  const { nodes: collNodes, edges: collEdges } = collapseOuterRooms(graphData, outerRoomIds, mode);
  const pos = areaLayout(collNodes);

  // In replay mode, determine which onward edges to show based on the drafted room.
  // The draftedOuterRoomId is the actual outer room id (e.g. "tomb"), or null.
  // _outerFrom edges have 'from' == the real outer-room id; we rewrite to OUTER_NODE_ID
  // only for the drafted room, and drop the rest.
  const finalEdges = collEdges.map((e) => {
    if (!e._outerFrom) return e;
    if (mode === "replay") {
      // Only show onward edges for the drafted room; drop edges from other outer rooms.
      if (e.from !== draftedOuterRoomId) return null;
      return { ...e, from: OUTER_NODE_ID };
    }
    // Aggregate: _outerFrom edges were already rewritten by collapseOuterRooms.
    return e;
  }).filter(Boolean);

  // --- edge pass ---
  let edgeSvg = "";
  for (const e of finalEdges) {
    const p1 = pos[e.from], p2 = pos[e.to];
    if (!p1 || !p2) continue;
    // Small offset to give directed pairs a visible gap.
    const dx = p2.x - p1.x, dy = p2.y - p1.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const ox = (dy / len) * 2.5, oy = -(dx / len) * 2.5;
    const x1 = p1.x + ox, y1 = p1.y + oy;
    const x2 = p2.x + ox, y2 = p2.y + oy;
    const dash = e.stub ? "stroke-dasharray='5 3'" : "";
    // In aggregate mode, onward edges that originate from the outer-room slot
    // are rendered faintly (the union of all rooms' possibilities, not one day's
    // specific topology).
    const faint = mode === "agg" && e._aggOuter ? " ag-edge-faint" : "";
    edgeSvg += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}"
      x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
      class="ag-edge${e.stub ? " ag-stub" : ""}${faint}" ${dash}/>`;
  }

  // --- node pass ---
  let nodeSvg = "";
  // Compute aggregate visit scale for colour mapping.
  // For the synthetic outer-room slot, the visit total is the SUM across all 8 rooms.
  let maxVisits = 1;
  const effectiveVisits = { ...visitTotals };
  if (outerRoomIds.size > 0) {
    let outerTotal = 0;
    for (const id of outerRoomIds) outerTotal += (visitTotals[id] || 0);
    effectiveVisits[OUTER_NODE_ID] = outerTotal;
  }
  if (mode === "agg") {
    for (const v of Object.values(effectiveVisits)) if (v > maxVisits) maxVisits = v;
  }

  // Build hover tooltip for the outer-room slot in aggregate mode:
  // per-room breakdown, descending by visit count, omitting zeros.
  function outerAggTooltip() {
    const breakdown = [];
    for (const id of outerRoomIds) {
      const n = graphData.nodes.find((x) => x.id === id);
      const cnt = visitTotals[id] || 0;
      if (cnt > 0 && n) breakdown.push([areaShortName(n.name), cnt]);
    }
    breakdown.sort((a, b) => b[1] - a[1]);
    if (!breakdown.length) return "outer room slot — 0 visits";
    const total = breakdown.reduce((s, [, c]) => s + c, 0);
    return `outer room slot — ${fmtInt(total)} visits total\n` +
      breakdown.map(([name, cnt]) => `  ${name}: ${fmtInt(cnt)}`).join("\n");
  }

  for (const n of collNodes) {
    const p = pos[n.id];
    if (!p) continue;
    const r = n.modelled ? AG_NODE_R : AG_NODE_R_UNMOD;

    let fill, stroke, opacity = 1;

    if (n.id === OUTER_NODE_ID) {
      // --- synthetic outer-room slot ---
      if (mode === "replay") {
        const isDrafted = draftedOuterRoomId != null;
        const isCurrentOuter = isDrafted && (currentAreaId === draftedOuterRoomId);
        if (isCurrentOuter) {
          fill = "#e8c34a"; stroke = "#14161a"; // current — bright gold
        } else if (isDrafted) {
          fill = BAND_COLOR[n.band] || "#8a919c"; stroke = "rgba(0,0,0,.4)";
        } else {
          // Not yet drafted this day.
          fill = "#2a2e35"; stroke = "#44484f";
          opacity = 0.55;
        }
        // The label is the drafted room's short name, or a placeholder.
        const labelText = isDrafted
          ? (() => {
              const rNode = graphData.nodes.find((x) => x.id === draftedOuterRoomId);
              return rNode ? areaShortName(rNode.name) : draftedOuterRoomId;
            })()
          : "outer room";
        const titleText = isDrafted
          ? (() => {
              const rNode = graphData.nodes.find((x) => x.id === draftedOuterRoomId);
              return rNode ? rNode.name : draftedOuterRoomId;
            })()
          : "outer room (not drafted yet)";
        const strokeW = isCurrentOuter ? 2.5 : 1.5;
        nodeSvg += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r}"
          fill="${fill}" stroke="${stroke}" stroke-width="${strokeW}" opacity="${opacity}">
          <title>${esc(titleText)}</title></circle>`;
        // Label
        const labelOpacity = isDrafted ? Math.max(opacity, 0.5) : 0.5;
        const short = isDrafted ? labelText : "outer room\n(not drafted)";
        const lx = (p.labelSide || "right") === "left" ? p.x - r - 4 : p.x + r + 4;
        const anchor = (p.labelSide || "right") === "left" ? "end" : "start";
        nodeSvg += `<text x="${lx.toFixed(1)}" y="${(p.y + 3).toFixed(1)}"
          class="ag-label${isDrafted ? "" : " ag-label-dim"}" opacity="${labelOpacity}"
          text-anchor="${anchor}"><title>${esc(titleText)}</title>${esc(short)}</text>`;
      } else {
        // Aggregate mode: shade by sum of all outer-room visits.
        const frac = Math.min((effectiveVisits[OUTER_NODE_ID] || 0) / maxVisits, 1);
        fill = frac > 0 ? "#2a9d8f" : "#2a2e35";
        opacity = frac > 0 ? 0.25 + 0.75 * frac : 0.25;
        stroke = "#44484f";
        const tooltip = outerAggTooltip();
        nodeSvg += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r}"
          fill="${fill}" stroke="${stroke}" stroke-width="1.5" opacity="${opacity}">
          <title>${esc(tooltip)}</title></circle>`;
        // Label
        const lx = (p.labelSide || "right") === "left" ? p.x - r - 4 : p.x + r + 4;
        const anchor = (p.labelSide || "right") === "left" ? "end" : "start";
        nodeSvg += `<text x="${lx.toFixed(1)}" y="${(p.y + 3).toFixed(1)}"
          class="ag-label" opacity="${Math.max(opacity, 0.5)}"
          text-anchor="${anchor}"><title>${esc(tooltip)}</title>${esc("outer room")}</text>`;
      }
      continue;
    }

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
      const frac = Math.min((effectiveVisits[n.id] || 0) / maxVisits, 1);
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
        <title>${esc(n.name)}${mode === "agg" ? " — " + fmtInt(effectiveVisits[n.id] || 0) + " visits" : ""}</title></circle>`;
    }
    // Label — short name beside the node, full name in the SVG <title> tooltip.
    // Only drawn for modelled nodes (unmodelled already show a title on hover).
    // The alternating-side label logic is preserved for other columns even
    // though the outer-room collapse makes the depth-3 anchor column much less
    // crowded.  For the depth-0 node (house) the label is anchored "start" to
    // the right so it does not extend left of the SVG edge.
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
  const hasNull = collNodes.some((n) => n.depth == null);
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
      .ag-edge-faint { stroke: #2a2e35; stroke-width: 1; opacity: 0.45; }
      .ag-label { fill: #c8ccd4; font-size: 8px; font-family: -apple-system, sans-serif; pointer-events: none; }
      .ag-label-dim { fill: #6a7180; }
    </style>
    ${sepLine}${edgeSvg}${nodeSvg}
  </svg>`;
}

function renderAreaLegend(mode, hasData, legendElId = "area-legend") {
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
  $("#" + legendElId).innerHTML = parts.join("");
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

  // Derive the outer-room id set once from the live graph data.
  const outerRoomIds = deriveOuterRoomIds(graphData.edges);

  let currentAreaId = "house"; // default when player is on the grid
  let visitedSet = new Set(["house"]);
  let draftedOuterRoomId = null;  // frame.outer_room (or null before the draft)

  if (mode === "replay" && state.run && state.run.frames) {
    const frame = state.run.frames[state.frameIdx];
    currentAreaId = frame.area || "house";
    visitedSet = visitedAreasUpTo(state.run.frames, state.frameIdx);
    visitedSet.add("house"); // house is always considered visited
    draftedOuterRoomId = frame.outer_room || null;
  }

  const svgHtml = renderAreaSvg(
    graphData, visitTotals, visitedSet, currentAreaId, mode,
    outerRoomIds, draftedOuterRoomId,
  );
  const graphEl = $("#area-graph");
  graphEl.innerHTML = svgHtml;
  // Attach pan/zoom to the freshly rendered SVG (zoom state persists across
  // frame changes because attachPanZoom is idempotent on the same element id).
  const svgEl = graphEl.querySelector("svg");
  if (svgEl) attachPanZoom(svgEl, "area-graph-svg");
  renderAreaLegend(mode, hasAggData);
}

// Reset-view buttons: restore the stored origin viewBox without deleting the
// origin record (so subsequent interactions still use the correct design dims).
$("#house-reset-zoom").onclick = () => {
  const orig = PZ_ORIGIN["house-svg"];
  if (orig) PZ_STATE["house-svg"] = { x: orig.ox, y: orig.oy, w: orig.ow, h: orig.oh };
  else delete PZ_STATE["house-svg"];  // no origin yet — force re-init on next attach
  const svgEl = $("#house svg");
  if (svgEl) attachPanZoom(svgEl, "house-svg");
};
$("#area-reset-zoom").onclick = () => {
  const orig = PZ_ORIGIN["area-graph-svg"];
  if (orig) PZ_STATE["area-graph-svg"] = { x: orig.ox, y: orig.oy, w: orig.ow, h: orig.oh };
  else delete PZ_STATE["area-graph-svg"];
  const svgEl = $("#area-graph svg");
  if (svgEl) attachPanZoom(svgEl, "area-graph-svg");
};

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

/* ===================================================================== play */
/* The "Play" tab drives a server-side PlaySession (web/play.py) through
   /api/play/*. It reuses renderHouse() and renderAreaSvg()/renderAreaLegend()
   unchanged (both already take a frame/target-id rather than reading global
   `state.run`), so the house grid and the area graph look and behave exactly
   like the Runs tab's replay view. */

state.playState = null;              // last /api/play/{new,state,act,undo} response
state.playVisited = new Set(["house"]);  // area ids seen so far (client-side, best-effort)
state.playDebug = false;             // debug-overlay toggle; OFF by default (observation parity)
state.playLog = [];                  // running per-day action log (client-side only)
// Which of the tabbed map panels is showing. Auto-followed to match
// the player's on-grid/off-grid status on every real transition (see
// updatePlayMapTab); a manual tab click holds until the next transition, so
// looking at the other map never traps the player out of sync permanently.
state.playMapTab = "house";
state.playMapLastOffGrid = undefined;  // previous frame's off-grid status; undefined = force a sync

async function playApiGet(url) {
  const r = await fetch(url);
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.error) || `${url}: ${r.status}`);
  return data;
}
async function playApiPost(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.error) || `${url}: ${r.status}`);
  return data;
}

function applyPlayState(s) {
  state.playState = s;
  if (s.frame && s.frame.area) state.playVisited.add(s.frame.area);
  pushPlayLog(s);
  renderPlayAll();
}

async function startPlaySession() {
  const seedRaw = $("#play-seed").value.trim();
  const body = {
    seed: seedRaw === "" ? null : Number(seedRaw),
    n_days: Number($("#play-ndays").value) || 1,
    reward: $("#play-reward").value,
    unlocks: $("#play-unlocks").value,
  };
  $("#play-save-status").textContent = "starting…";
  state.playVisited = new Set(["house"]);
  state.playLog = [];
  state.playMapTab = "house";
  state.playMapLastOffGrid = undefined;
  try {
    const s = await playApiPost("/api/play/new", body);
    $("#play-status").classList.remove("hidden");
    $("#play-save-status").textContent = "";
    applyPlayState(s);
  } catch (err) {
    $("#play-save-status").textContent = `failed to start: ${err.message}`;
  }
}
$("#play-start-btn").onclick = startPlaySession;

async function playAct(actionId) {
  try {
    const s = await playApiPost("/api/play/act", { action: actionId });
    applyPlayState(s);
  } catch (err) {
    $("#play-save-status").textContent = `rejected: ${err.message}`;
  }
}

async function playUndo() {
  try {
    const s = await playApiPost("/api/play/undo", {});
    $("#play-save-status").textContent = s.undone ? "" : (s.message || "nothing to undo");
    applyPlayState(s);
  } catch (err) {
    $("#play-save-status").textContent = `undo failed: ${err.message}`;
  }
}
$("#play-undo-btn").onclick = playUndo;

async function playSave() {
  try {
    const s = await playApiPost("/api/play/save", {});
    $("#play-save-status").textContent = `saved ${s.written} record${s.written === 1 ? "" : "s"} → ${s.path}`;
  } catch (err) {
    $("#play-save-status").textContent = `save failed: ${err.message}`;
  }
}
$("#play-save-btn").onclick = playSave;

$("#play-debug").onchange = (e) => {
  state.playDebug = e.target.checked;
  $("#play-debug-marker").classList.toggle("hidden", !state.playDebug);
  renderPlayAll();
};

// Group display order for the legal-action list; any group not listed here
// (there shouldn't be one — see test_action_group_covers_full_action_space)
// still renders, just after these.
const PLAY_GROUP_LABELS = {
  draft: "Draft", choose: "Choose", move: "Move", travel: "Travel",
  buy: "Buy", trade: "Trade", fabricate: "Fabricate", use: "Use", control: "Control",
};
const PLAY_GROUP_ORDER = ["draft", "choose", "move", "travel", "buy", "trade", "fabricate", "use", "control"];

// One shop-stock row (frame.shop_stock, from web/play.py::_shop_stock_view)
// for an entry the action mask did NOT legalize -- sold out, unaffordable, or
// blocked (a required held item missing). Rendered dim and unclickable
// rather than omitted, so a shop keeps showing what it carries even when the
// player cannot yet buy it (the owner: "I may eventually have the money and
// want to return"). Entries the mask DID legalize are skipped here; those
// already render as ordinary clickable buttons from legal_actions.
function shopStockRowHtml(entry) {
  const reason = entry.sold_out ? "sold out" : entry.blocked ? "locked" : "can't afford";
  return `<div class="play-action-btn shop-row-unaffordable" title="${esc(reason)}">` +
    `<span class="log-text">${esc(entry.id)}</span>` +
    `<span class="shop-row-price">${entry.price}g · ${esc(reason)}</span></div>`;
}

function renderPlayActions() {
  const el = $("#play-actions");
  const s = state.playState;
  if (!s) { el.innerHTML = ""; return; }
  if (s.attempt_over) {
    el.innerHTML = '<p class="dim">attempt over — start a new session to continue</p>';
    return;
  }
  // While a draft hand is open (frame.pending truthy), env/actions.py's
  // action_mask legalizes ONLY the "choose" and "control" groups (choose a
  // slot, redraw, rotate — see action_mask's Phase.DRAFTING branch), and
  // renderPlayDraft() already renders all three richly (option cards with
  // orientation glyphs, a labelled redraw button, a labelled rotate button).
  // Skipping those two groups here avoids showing the same actions twice as
  // both a rich card and a bare "choose #2 Parlor" button.
  const pending = s.frame.pending;
  // Same idea while an Upgrade Disk choice is open (frame.pending_upgrade):
  // the three CHOOSE_UPGRADE actions are already rendered readably by
  // renderPlayUpgrade() (name + effect_text), so drop them here
  // rather than also showing "choose upgrade #0 (parlor__ix108)" verbatim.
  const pendingUpgrade = s.frame.pending_upgrade;
  const upgradeRe = /^choose upgrade #\d+ \(/;
  const byGroup = {};
  for (const a of s.legal_actions || []) {
    if (pending && (a.group === "choose" || a.group === "control")) continue;
    if (pendingUpgrade && a.group === "choose" && upgradeRe.test(a.label)) continue;
    (byGroup[a.group] = byGroup[a.group] || []).push(a);
  }
  const groups = [...PLAY_GROUP_ORDER, ...Object.keys(byGroup).filter((g) => !PLAY_GROUP_ORDER.includes(g))];
  // Stock rows the mask left unlegalized (sold out / unaffordable / locked)
  // for the shop the player currently stands in, if any -- see
  // web/play.py::_shop_stock_view. Only ever populated in the "buy" group.
  const unaffordableStock = (s.frame.shop_stock || []).filter((e) => e.action_id == null);
  let html = "";
  for (const g of groups) {
    const acts = byGroup[g];
    const extraRows = g === "buy" ? unaffordableStock : [];
    if ((!acts || !acts.length) && !extraRows.length) continue;
    html += `<div class="play-group-head">${esc(PLAY_GROUP_LABELS[g] || g)}</div>`;
    for (const a of acts || []) {
      html += `<button class="play-action-btn" data-id="${a.id}">${esc(a.label)}</button>`;
    }
    for (const entry of extraRows) {
      html += shopStockRowHtml(entry);
    }
  }
  // An empty list here has two very different meanings: mid-draft (or
  // mid-upgrade-choice), every legal action moved into the panel above
  // (nothing is actually wrong); otherwise an empty list means the day truly
  // has nowhere left to go. The cases must stay distinguished below.
  const emptyMsg = pending
    ? '<p class="dim">all legal actions are in the Draft options panel above</p>'
    : pendingUpgrade
    ? '<p class="dim">all legal actions are in the Upgrade Disk panel above</p>'
    : '<p class="dim">no legal actions — day is over</p>';
  el.innerHTML = html || emptyMsg;
  // [data-id] excludes shop-row-unaffordable rows (see shopStockRowHtml),
  // which share the .play-action-btn layout but carry no action to wire up.
  for (const btn of el.querySelectorAll(".play-action-btn[data-id]")) {
    btn.onclick = () => playAct(Number(btn.dataset.id));
  }
}

// Find the legal "choose"-group action for a given draft slot by matching
// describe_action's label format ("choose #{n} {name}", n = slot+1 — see
// env/actions.py::describe_action and the same regex trick renderFrame()
// already uses to recover a replayed pick's slot). Matching on the label
// rather than hardcoding CHOOSE_BASE offsets means this keeps working if the
// action space is ever renumbered. Per-option orientation choice is not a
// real game mechanic (each dealt option carries a rolled orientation;
// rotation is a separate, whole-hand effect — see ROTATE_ACTION), so there
// is only ever one choose action per slot.
function findChooseAction(legalActions, slot) {
  const re = new RegExp(`^choose #${slot + 1} `);
  return legalActions.find((a) => a.group === "choose" && re.test(a.label)) || null;
}

function renderPlayDraft() {
  const el = $("#play-draft");
  const s = state.playState;
  if (!el) return;
  const pend = s && !s.attempt_over ? s.frame.pending : null;
  if (!pend) { el.innerHTML = ""; return; }

  const legal = s.legal_actions || [];
  const optsHtml = pend.options.map((o) => {
    const action = findChooseAction(legal, o.slot);
    const dataAttrs = action ? ` data-choose-id="${action.id}"` : "";
    return optionCardHtml(o, { clickable: !!action, dataAttrs });
  }).join("");

  const rd = pend.redraw || {};
  const redrawHtml = rd.available
    ? `<button id="play-redraw-btn" class="play-draft-btn">Redraw — costs ${esc(
        rd.kind === "free" ? `free (${rd.free_left} left)`
        : rd.kind === "die" ? "1 die 🎲"
        : rd.kind === "study" ? `1 gem 💎 (Study ${rd.study_used}/${rd.study_cap} used)`
        : rd.kind)}</button>`
    : `<div class="play-draft-unavailable">Redraw unavailable — ${esc(rd.reason || "no source")}</div>`;

  const rotateLegal = legal.some((a) => a.group === "control" && a.label === "rotate options");
  const rotateHtml = rotateLegal
    ? `<button id="play-rotate-btn" class="play-draft-btn">Rotate all options' orientation
        <span class="dim">(${pend.rotations_used} used this hand)</span></button>`
    : "";

  el.innerHTML = `<div class="panel-head" style="margin-top:0">${esc(draftHeaderText(pend))}</div>
    <div id="play-draft-opts">${optsHtml}</div>
    <div class="play-draft-controls">${redrawHtml}${rotateHtml}</div>`;

  for (const card of el.querySelectorAll(".opt.clickable[data-choose-id]")) {
    card.onclick = () => playAct(Number(card.dataset.chooseId));
  }
  const redrawBtn = $("#play-redraw-btn");
  if (redrawBtn) {
    const redrawAction = legal.find((a) => a.group === "control" && a.label === "redraw");
    if (redrawAction) redrawBtn.onclick = () => playAct(redrawAction.id);
  }
  const rotateBtn = $("#play-rotate-btn");
  if (rotateBtn) {
    const rotateAction = legal.find((a) => a.group === "control" && a.label === "rotate options");
    if (rotateAction) rotateBtn.onclick = () => playAct(rotateAction.id);
  }
}

// Find the legal CHOOSE_UPGRADE action for a given offered-variant index by
// matching describe_action's label format ("choose upgrade #{i} (...)",
// i 0-based -- see env/actions.py::describe_action). Same label-matching
// trick as findChooseAction, so this keeps working if the action space is
// ever renumbered.
function findChooseUpgradeAction(legalActions, index) {
  const re = new RegExp(`^choose upgrade #${index} \\(`);
  return legalActions.find((a) => a.group === "choose" && re.test(a.label)) || null;
}

// The disk-upgrade menu: web/play.py's pending_upgrade resolves
// each offered variant id to a readable name plus the sheet's effect_text --
// e.g. "Parlor" / "3 Prize" vs "Parlor" / "2 Wind-up Keys" -- since the raw
// ids (parlor__ix108 / parlor__ix109) are indistinguishable on their own.
// Reuses .opt's card styling rather than inventing new markup.
function renderPlayUpgrade() {
  const el = $("#play-upgrade");
  const s = state.playState;
  if (!el) return;
  const pu = s && !s.attempt_over ? s.frame.pending_upgrade : null;
  if (!pu) { el.innerHTML = ""; return; }

  const legal = s.legal_actions || [];
  const optsHtml = pu.options.map((o) => {
    const action = findChooseUpgradeAction(legal, o.index);
    const dataAttrs = action ? ` data-choose-id="${action.id}"` : "";
    const cls = ["opt", action ? "clickable" : ""].filter(Boolean).join(" ");
    return `<div class="${cls}"${dataAttrs}>
      <div class="opt-body"><div class="name">${esc(o.name)}</div>
      <div class="sub">${esc(o.effect_text || "no effect text on record")}</div></div>
    </div>`;
  }).join("");

  el.innerHTML = `<div class="panel-head" style="margin-top:0">Upgrade Disk — choose a variant for ${esc(pu.slot_name || pu.slot)}</div>
    <div id="play-upgrade-opts">${optsHtml}</div>`;

  for (const card of el.querySelectorAll(".opt.clickable[data-choose-id]")) {
    card.onclick = () => playAct(Number(card.dataset.chooseId));
  }
}

function renderPlayStatus() {
  const s = state.playState;
  if (!s) return;
  const status = s.attempt_over ? "ATTEMPT OVER"
    : s.day_over ? "day over (advancing…)" : s.frame.phase;
  $("#play-progress").innerHTML =
    `day <b>${s.day}</b> / ${s.n_days} &nbsp;·&nbsp; steps <b>${s.frame.resources.steps}</b>
     &nbsp;·&nbsp; ${esc(status)} &nbsp;·&nbsp; seed ${s.seed}`;
}

function renderPlayResources() {
  const s = state.playState;
  if (!s) return;
  const r = s.frame.resources;
  $("#play-resources").innerHTML =
    [["Steps", r.steps], ["Gems", r.gems], ["Keys", r.keys],
     ["Coins", r.coins], ["Dice", r.dice], ["Luck", r.luck]]
    .map(([k, v]) => `<div class="res"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
}

function renderPlayInventory() {
  const s = state.playState;
  $("#play-inventory").innerHTML = s ? inventoryChipsHtml(s.frame.inventory) : "";
}

// The server only returns the most recently applied action, so the running
// per-day log is accumulated client-side. `n_actions_today` is the source of
// truth for "how many entries the log should have" — it resets to 0 on a new
// day/session and shrinks by one on undo, so the log is trimmed/cleared to
// match rather than guessed at from the action stream alone.
function pushPlayLog(s) {
  if (s.n_actions_today === 0) { state.playLog = []; return; }
  const a = s.frame.action;
  if (a && (!state.playLog.length || state.playLog[state.playLog.length - 1].index !== a.index)) {
    state.playLog.push(a);
  }
  if (state.playLog.length > s.n_actions_today) {
    state.playLog = state.playLog.slice(0, s.n_actions_today);
  }
}

// Resource ids that get an icon instead of a spelled-out name in the log;
// same glyph set the dashboard's draft-frequency badges use. Held special
// items (the "container opens" case) fall through to their name.
const PAYOUT_ICON = { steps: "👣", gems: "💎", keys: "🔑", coins: "🪙", dice: "🎲", luck: "🍀" };

// What a step paid out, diffed server-side across the whole action (see
// web/play.py::_payout_diff) -- one reporting point regardless of whether the
// gain came from a record's items, a grant effect, a room_hook, or a
// container open. Costs render alongside gains (signed) rather than being
// hidden, since a room's grant can be masked by the same move's step cost.
function payoutHtml(payout) {
  if (!payout || !payout.length) return "";
  const items = payout.map((p) => {
    const icon = PAYOUT_ICON[p.id];
    const label = icon || ` ${esc(p.name)}`;
    const sign = p.delta > 0 ? "+" : "";
    const cls = p.delta > 0 ? "pos" : "neg";
    return `<span class="log-payout-item ${cls}">${sign}${p.delta}${label}</span>`;
  });
  return `<span class="log-payout">${items.join(" ")}</span>`;
}

function renderPlayLog() {
  // A dedicated row class (not the Runs tab's .log-row) so the payout badge
  // gets its own non-shrinking flex slot instead of being swallowed by the
  // row's ellipsis truncation on long entries (draft/travel labels are
  // exactly the long ones, and exactly where the payout matters most).
  //
  // Rendered newest-first so the most recent action and its payout are
  // visible without scrolling; the "n" label keeps each row's chronological
  // action number (state.playLog stays oldest-first internally) so reversal
  // never reorders the numbering itself.
  $("#play-action-log").innerHTML = state.playLog.length
    ? state.playLog.map((a, i) =>
        `<div class="play-log-row"><span class="n">${i + 1}</span>` +
        `<span class="log-text">${esc(a.text)}</span>${payoutHtml(a.payout)}</div>`
      ).reverse().join("")
    : '<div class="dim">—</div>';
}

function renderPlayDebug() {
  const el = $("#play-debug-panel");
  const s = state.playState;
  if (!state.playDebug || !s || !s.debug) { el.classList.add("hidden"); el.innerHTML = ""; return; }
  el.classList.remove("hidden");
  const d = s.debug;
  const lockRows = Object.entries(d.door_locks || {})
    .map(([cell, segs]) => `r${Math.floor(cell / 5) + 1}c${cell % 5}: ` +
      Object.entries(segs).map(([dir, st]) => `${dir}=${st}`).join(" ")).join("<br>") || "—";
  el.innerHTML = `<div class="panel-head" style="margin-top:0">Debug overlay</div>
    <div>open frontier doors: <b>${fmtInt(d.open_path_count)}</b></div>
    <div style="margin-top:8px">door lock states:<br>${lockRows}</div>
    <div style="margin-top:8px" class="dim">optimistic distances to the Antechamber are on the house grid</div>`;
}

function renderPlayHouse() {
  const s = state.playState;
  if (!s) { $("#play-house").innerHTML = ""; return; }
  renderHouse(s.frame, "play-house", "play-house-svg");
  if (state.playDebug && s.debug && s.debug.optimistic_distances) {
    // Overlay the optimistic per-cell distance-to-Antechamber on top of the
    // freshly rendered SVG (debug-only signal: env/obs.py never encodes it).
    const svg = $("#play-house svg");
    if (svg) {
      let ov = "";
      s.debug.optimistic_distances.forEach((dv, cell) => {
        if (dv < 0) return;
        const [x, y] = cellXY(cell);
        ov += `<text x="${x + 8}" y="${y + 16}" class="debug-dist">${dv}</text>`;
      });
      svg.insertAdjacentHTML("beforeend", ov);
    }
  }
}

function renderPlayArea() {
  const s = state.playState;
  const graphEl = $("#play-area-graph"), legendEl = $("#play-area-legend");
  if (!s || !state.areaGraph) {
    graphEl.innerHTML = '<p class="dim" style="padding:4px 0">area graph unavailable</p>';
    legendEl.innerHTML = "";
    return;
  }
  const outerRoomIds = deriveOuterRoomIds(state.areaGraph.edges);
  const currentAreaId = s.frame.area || "house";
  const draftedOuterRoomId = s.frame.outer_room || null;
  // "replay" mode colours by current-position + visited-so-far, which is
  // exactly the semantics a live session wants (no aggregate/replay toggle
  // needed here — this IS the live position). visitTotals is only consulted
  // by aggregate-mode rendering, so an empty object is safe to pass.
  graphEl.innerHTML = renderAreaSvg(
    state.areaGraph, {}, state.playVisited, currentAreaId, "replay",
    outerRoomIds, draftedOuterRoomId,
  );
  const svgEl = graphEl.querySelector("svg");
  if (svgEl) attachPanZoom(svgEl, "play-area-graph-svg");
  renderAreaLegend("replay", true, "play-area-legend");
}

// The map tabs' load-bearing half: auto-switch whenever the player's
// on-grid/off-grid status actually changes (frame.area null <-> non-null),
// so the view follows without being told to. A manual tab click (see the
// button handlers below) is left alone between transitions -- it only gets
// overridden the next time a real crossing happens, which is what keeps
// auto-follow from trapping the player on the wrong map indefinitely.
function updatePlayMapTab(frame) {
  const offGrid = frame.area != null;
  if (state.playMapLastOffGrid === undefined || offGrid !== state.playMapLastOffGrid) {
    state.playMapTab = offGrid ? "area" : "house";
  }
  state.playMapLastOffGrid = offGrid;
}

function renderPlayMapTabs() {
  const onHouse = state.playMapTab !== "area";
  $("#play-map-tab-house").classList.toggle("active", onHouse);
  $("#play-map-tab-area").classList.toggle("active", !onHouse);
  $("#play-house-panel").classList.toggle("hidden", !onHouse);
  $("#play-area-panel").classList.toggle("hidden", onHouse);
}

$("#play-map-tab-house").onclick = () => { state.playMapTab = "house"; renderPlayMapTabs(); };
$("#play-map-tab-area").onclick = () => { state.playMapTab = "area"; renderPlayMapTabs(); };

function renderPlayAll() {
  renderPlayStatus();
  renderPlayResources();
  renderPlayInventory();
  renderPlayDraft();
  renderPlayUpgrade();
  renderPlayActions();
  renderPlayLog();
  if (state.playState) updatePlayMapTab(state.playState.frame);
  renderPlayMapTabs();
  renderPlayHouse();
  renderPlayArea();
  renderPlayDebug();
}

/* ---------------------------------------------------------------- init */

async function init() {
  try { state.rooms = await getJSON("/api/rooms"); } catch (err) { /* retried below */ }
  refreshDashboard();
  setInterval(() => {
    if (document.hidden) return;
    if (!state.rooms.length) getJSON("/api/rooms").then((r) => { state.rooms = r; }).catch(() => {});
    if (state.tab === "dashboard") refreshDashboard();
    if (state.tab === "progress") refreshProgress();
  }, 10_000);
  setInterval(() => {
    if (document.hidden || state.tab !== "runs") return;
    refreshRuns();
  }, 30_000);
}
init();
