#!/usr/bin/env python3
"""Generate the training dashboard HTML from runs/metrics.jsonl.

Pure stdlib. Rerun any time; output overwrites runs/dashboard.html.
Usage: python tools/make_dashboard.py [--out runs/dashboard.html]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs"

SERIES = [  # (key, label, css var)  - fixed identity order, never re-colored
    ("win_rate_recent", "Overall", "--s-overall"),
    ("win_rate_exploit", "Exploit", "--s-exploit"),
    ("win_rate_explore", "Explore", "--s-explore"),
]

PLOT_W, PLOT_H, PAD_L, PAD_R, PAD_T, PAD_B = 860, 300, 52, 120, 16, 34


def load_samples() -> list[dict]:
    path = RUNS / "metrics.jsonl"
    if not path.exists():
        return []
    out = []
    seen = set()
    for line in path.read_text().splitlines():
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (m.get("episodes"), m.get("timesteps"))
        if key in seen:
            continue  # sampler re-reads the same checkpoint between saves
        seen.add(key)
        out.append(m)
    return out


def nice_ticks(vmax: float, n: int = 4) -> list[float]:
    if vmax <= 0:
        return [0.0, 1.0]
    raw = vmax / n
    mag = 10 ** (len(str(int(1 / raw))) if raw < 1 else -len(str(int(raw))) + 1)
    for step in (1, 2, 2.5, 5, 10):
        s = step / mag if raw < 1 else step * mag
        if s >= raw:
            break
    ticks, v = [], 0.0
    while v <= vmax * 1.001:
        ticks.append(round(v, 6))
        v += s
    return ticks


def build(out_path: Path) -> None:
    t0 = int((RUNS / "training_start_epoch").read_text().strip()) \
        if (RUNS / "training_start_epoch").exists() else int(time.time())
    samples = load_samples()
    latest = {}
    if (RUNS / "all-unlocks" / "latest.json").exists():
        latest = json.loads((RUNS / "all-unlocks" / "latest.json").read_text())

    hours_elapsed = (time.time() - t0) / 3600
    episodes = latest.get("episodes", 0)
    timesteps = latest.get("timesteps", 0)
    eps_per_hr = episodes / hours_elapsed if hours_elapsed > 0.05 else 0

    # --- series points: x hours since start, y win rate (percent) ---
    xs = [(m["sampled_at"] - t0) / 3600 for m in samples]
    xmax = max(xs + [hours_elapsed, 0.5]) * 1.02
    ymax_data = 0.0
    pts = {}
    for key, _, _ in SERIES:
        pts[key] = [(x, m.get(key)) for x, m in zip(xs, samples) if m.get(key) is not None]
        for _, y in pts[key]:
            ymax_data = max(ymax_data, y)
    ymax = max(ymax_data * 1.25, 0.02)  # min span 2% so early noise doesn't fill the chart
    yticks = nice_ticks(ymax * 100)
    ymax = max(yticks) / 100 if yticks else ymax

    iw = PLOT_W - PAD_L - PAD_R
    ih = PLOT_H - PAD_T - PAD_B

    def X(x):
        return PAD_L + x / xmax * iw

    def Y(y):
        return PAD_T + ih - (y / ymax) * ih

    def polyline(key):
        p = pts[key]
        return " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in p)

    grid = "".join(
        f'<line x1="{PAD_L}" y1="{Y(t/100):.1f}" x2="{PLOT_W - PAD_R}" y2="{Y(t/100):.1f}" class="grid"/>'
        f'<text x="{PAD_L - 8}" y="{Y(t/100) + 4:.1f}" class="tick" text-anchor="end">{t:g}%</text>'
        for t in yticks)
    xtick_step = max(1, round(xmax / 6))
    xgrid = "".join(
        f'<text x="{X(h):.1f}" y="{PLOT_H - 10}" class="tick" text-anchor="middle">{h:g}h</text>'
        for h in range(0, int(xmax) + 1, xtick_step))

    lines_svg, dots, ends = [], [], []
    for key, label, var in SERIES:
        p = pts[key]
        if not p:
            continue
        lines_svg.append(
            f'<polyline points="{polyline(key)}" fill="none" '
            f'stroke="var({var})" stroke-width="2" stroke-linejoin="round"/>')
        ex, ey = p[-1]
        dots.append(f'<circle cx="{X(ex):.1f}" cy="{Y(ey):.1f}" r="4" fill="var({var})" '
                    f'stroke="var(--surface)" stroke-width="2"/>')
        ends.append([X(ex), Y(ey), label, ey, var])
    # De-collide end labels: nudge any pair closer than 14px apart vertically.
    ends.sort(key=lambda e: e[1])
    for i in range(1, len(ends)):
        if ends[i][1] - ends[i - 1][1] < 14:
            ends[i][1] = ends[i - 1][1] + 14
    # Labels stay in ink; a small colored tick beside each carries identity
    # (matters once labels are nudged away from their line).
    endlabels = [
        f'<rect x="{ex + 8:.1f}" y="{ly - 1.5:.1f}" width="8" height="3" rx="1.5" '
        f'fill="var({var})"/>'
        f'<text x="{ex + 20:.1f}" y="{ly + 4:.1f}" class="endlabel">{label} {val:.2%}</text>'
        for ex, ly, label, val, var in ends]

    series_json = json.dumps({
        key: [[round(x, 3), y] for x, y in pts[key]] for key, _, _ in SERIES})
    labels_json = json.dumps({k: lbl for k, lbl, _ in SERIES})
    vars_json = json.dumps({k: v for k, _, v in SERIES})

    def fmt_pct(v):
        return f"{v:.2%}" if v is not None else "–"

    rows = "".join(
        f"<tr><td>{(m['sampled_at'] - t0) / 3600:.1f}h</td>"
        f"<td>{m.get('episodes', 0):,}</td><td>{m.get('timesteps', 0):,}</td>"
        f"<td>{fmt_pct(m.get('win_rate_recent'))}</td>"
        f"<td>{fmt_pct(m.get('win_rate_exploit'))}</td>"
        f"<td>{fmt_pct(m.get('win_rate_explore'))}</td></tr>"
        for m in samples[-12:][::-1])

    stat = lambda label, value, sub="": (
        f'<div class="tile"><div class="tlabel">{label}</div>'
        f'<div class="tval">{value}</div>'
        + (f'<div class="tsub">{sub}</div>' if sub else "") + "</div>")

    tiles = "".join([
        stat("Episodes", f"{episodes:,}"),
        stat("Timesteps", f"{timesteps:,}"),
        stat("Episodes / hour", f"{eps_per_hr:,.0f}"),
        stat("Hours running", f"{hours_elapsed:.1f}"),
        stat("Win rate (overall)", fmt_pct(latest.get("win_rate_recent")), "last 1,000 episodes"),
        stat("Win rate (exploit)", fmt_pct(latest.get("win_rate_exploit")), "best-known-policy mode"),
    ])

    updated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    html = f"""<title>Blue Prince RL Training</title>
<style>
:root {{
  --surface: #f7f8fa; --panel: #ffffff; --ink: #16202c; --ink-2: #5a6675;
  --ink-3: #8a94a3; --line: #dde3ea; --accent: #2a78d6;
  --s-overall: #2a78d6; --s-exploit: #008300; --s-explore: #e87ba4;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    --surface: #14181e; --panel: #1b2129; --ink: #e8ecf1; --ink-2: #a7b0bc;
    --ink-3: #6d7683; --line: #2a323d; --accent: #3987e5;
    --s-overall: #3987e5; --s-exploit: #00a000; --s-explore: #d55181;
  }}
}}
:root[data-theme="dark"] {{
  --surface: #14181e; --panel: #1b2129; --ink: #e8ecf1; --ink-2: #a7b0bc;
  --ink-3: #6d7683; --line: #2a323d; --accent: #3987e5;
  --s-overall: #3987e5; --s-exploit: #00a000; --s-explore: #d55181;
}}
body {{ background: var(--surface); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  margin: 0; padding: 28px 20px 48px; }}
main {{ max-width: 940px; margin: 0 auto; display: grid; gap: 20px; }}
header h1 {{ font-size: 21px; margin: 0; letter-spacing: -0.01em; }}
header p {{ margin: 4px 0 0; color: var(--ink-2); font-size: 13.5px; }}
.mono, .tval, td {{ font-variant-numeric: tabular-nums;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
.tile {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  padding: 12px 14px; }}
.tlabel {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--ink-3); }}
.tval {{ font-size: 22px; font-weight: 600; margin-top: 2px; }}
.tsub {{ font-size: 12px; color: var(--ink-2); }}
.panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  padding: 16px; }}
.panel h2 {{ font-size: 13px; margin: 0 0 10px; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--ink-2); font-weight: 600; }}
.chartwrap {{ overflow-x: auto; }}
svg .grid {{ stroke: var(--line); stroke-width: 1; }}
svg .tick {{ fill: var(--ink-3); font-size: 12px;
  font-family: ui-monospace, Menlo, monospace; }}
svg .endlabel {{ fill: var(--ink-2); font-size: 12px; font-weight: 600; }}
.legend {{ display: flex; gap: 18px; margin: 4px 0 8px; font-size: 13px; color: var(--ink-2); }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.sw {{ width: 14px; height: 3px; border-radius: 2px; display: inline-block; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th {{ text-align: right; color: var(--ink-3); font-weight: 600; font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.05em; padding: 6px 10px;
  border-bottom: 1px solid var(--line); }}
td {{ text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--line);
  color: var(--ink-2); }}
th:first-child, td:first-child {{ text-align: left; }}
#tip {{ position: fixed; pointer-events: none; background: var(--panel);
  border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px;
  font-size: 12.5px; display: none; box-shadow: 0 4px 14px rgba(0,0,0,0.15); z-index: 5; }}
footer {{ color: var(--ink-3); font-size: 12.5px; }}
</style>
<main>
<header>
  <h1>Blue Prince drafting policy &mdash; training telemetry</h1>
  <p>MaskablePPO &middot; all unlocks, no room upgrades &middot; 70% exploit / 30% explore
     &middot; checkpoint every 10,000 episodes &middot; updated {updated}</p>
</header>
<div class="tiles">{tiles}</div>
<div class="panel">
  <h2>Win rate &mdash; rolling last 1,000 episodes</h2>
  <div class="legend">
    <span><i class="sw" style="background:var(--s-overall)"></i>Overall</span>
    <span><i class="sw" style="background:var(--s-exploit)"></i>Exploit (best-known policy)</span>
    <span><i class="sw" style="background:var(--s-explore)"></i>Explore (high-temp sampling)</span>
  </div>
  <div class="chartwrap">
  <svg id="chart" viewBox="0 0 {PLOT_W} {PLOT_H}" width="100%"
       style="min-width:560px; touch-action:pan-y">
    {grid}{xgrid}
    <line x1="{PAD_L}" y1="{PAD_T + ih}" x2="{PLOT_W - PAD_R}" y2="{PAD_T + ih}" class="grid"/>
    {''.join(lines_svg)}
    {''.join(dots)}
    {''.join(endlabels)}
    <line id="xhair" x1="0" y1="{PAD_T}" x2="0" y2="{PAD_T + ih}"
          stroke="var(--ink-3)" stroke-dasharray="3,3" style="display:none"/>
  </svg>
  </div>
</div>
<div class="panel">
  <h2>Recent checkpoints</h2>
  <table>
    <thead><tr><th>Elapsed</th><th>Episodes</th><th>Timesteps</th>
      <th>Overall</th><th>Exploit</th><th>Explore</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="6">Waiting for the first checkpoint&hellip;</td></tr>'}</tbody>
  </table>
</div>
<footer>Win rate = P(reach the Antechamber) over the rolling last 1,000 training
episodes per mode. Exploit episodes sample the policy sharply (temp 0.5); explore
episodes sample flat (temp 1.5, 5% legal-action floor). Simulator probabilities:
TFMurphy decompiled v1.3 tables.</footer>
</main>
<div id="tip"></div>
<script>
const SERIES = {series_json};
const LABELS = {labels_json};
const VARS = {vars_json};
const XMAX = {xmax:.4f}, YMAX = {ymax:.6f};
const PL = {PAD_L}, PR = {PAD_R}, PT = {PAD_T}, PB = {PAD_B}, W = {PLOT_W}, H = {PLOT_H};
const svg = document.getElementById('chart'), tip = document.getElementById('tip'),
      xhair = document.getElementById('xhair');
const showTip = ev => {{
  const r = svg.getBoundingClientRect();
  const sx = (ev.clientX - r.left) * (W / r.width);
  if (sx < PL || sx > W - PR) {{ tip.style.display = 'none'; xhair.style.display = 'none'; return; }}
  const hx = (sx - PL) / (W - PL - PR) * XMAX;
  let html = '', shown = false, nearest = null;
  for (const k in SERIES) {{
    const pts = SERIES[k];
    if (!pts.length) continue;
    let best = pts[0];
    for (const p of pts) if (Math.abs(p[0] - hx) < Math.abs(best[0] - hx)) best = p;
    if (nearest === null || Math.abs(best[0] - hx) < Math.abs(nearest - hx)) nearest = best[0];
  }}
  if (nearest === null) return;
  html = '<b>' + nearest.toFixed(1) + 'h</b><br>';
  for (const k in SERIES) {{
    const pts = SERIES[k].filter(p => Math.abs(p[0] - nearest) < 1e-6);
    if (pts.length) {{
      html += '<span style="color:var(' + VARS[k] + ')">&#9632;</span> ' + LABELS[k] +
              ': ' + (pts[0][1] * 100).toFixed(2) + '%<br>';
      shown = true;
    }}
  }}
  if (!shown) {{ tip.style.display = 'none'; xhair.style.display = 'none'; return; }}
  const cx = PL + nearest / XMAX * (W - PL - PR);
  xhair.setAttribute('x1', cx); xhair.setAttribute('x2', cx);
  xhair.style.display = '';
  tip.innerHTML = html;
  tip.style.display = 'block';
  tip.style.left = Math.min(Math.max(8, ev.clientX - 75), window.innerWidth - 170) + 'px';
  tip.style.top = Math.max(8, ev.clientY - 84) + 'px';
}};
// pointer events cover mouse AND touch: tap or drag on the chart pins the
// crosshair to the nearest sample.
svg.addEventListener('pointermove', showTip);
svg.addEventListener('pointerdown', showTip);
svg.addEventListener('pointerleave', () => {{
  tip.style.display = 'none'; xhair.style.display = 'none';
}});
</script>
"""
    out_path.write_text(html)
    print(f"wrote {out_path} ({len(samples)} samples, {episodes} episodes)")


if __name__ == "__main__":
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else RUNS / "dashboard.html"
    build(out)
