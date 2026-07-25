"""In-place refreshing terminal dashboard for ``blueprince-train``.

Stable-Baselines3's default ``HumanOutputFormat`` re-prints its whole table
every rollout, so the window scrolls and every column reflows as digit counts
change. This module renders the same metrics into a fixed-size frame that is
redrawn in place with ANSI cursor moves.

Design notes (all deliberate, see the module tests):

* **Fixed geometry.** Every column has a constant width and every number a
  constant number of decimals, so nothing shifts between frames. Values are
  formatted with the ``" "`` sign flag, which reserves the minus column for
  positive numbers.
* **Equalizer bars.** Each non-monotonic metric gets a track showing the
  current value plus ``|`` markers at the min and max over the last
  :data:`HISTORY` samples. The axis is the padded window range snapped outward
  to a round number, so the markers sit inside the track and the endpoints do
  not twitch every frame.
* **Anchored fill.** A bar fills from its *anchor* to the current value. For
  near-zero-target metrics the anchor is 0.0, so the bar diverges left/right
  from wherever zero falls; for one-sided metrics the anchor is the axis low,
  giving an ordinary left-anchored fill. A metric whose axis never crosses
  zero degenerates to the left-anchored case automatically.
* **Event tail.** Trainer messages (checkpoints, resume, shutdown) go through
  :func:`emit` into a scrolling tail *inside* the frame; a stray ``print``
  would otherwise tear the display.

The rendering half is pure stdlib so it can be unit-tested without the ``rl``
extra installed; :func:`make_sb3_logger` is the only sb3-aware entry point.

Run ``python -m blueprince_sim.rl.dashboard`` for a synthetic demo.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

#: Number of recent samples the min/max markers summarise.
HISTORY = 1000

#: Frame geometry budget (the CLI contract is 240 columns x 40 rows).
MAX_WIDTH = 240
MAX_HEIGHT = 40
MIN_WIDTH = 96
#: Preferred width: wider than this wastes horizontal space on 10 metrics.
TARGET_WIDTH = 200

TRACK = "·"     # · empty track
FILL = "█"      # █ bar
MARKER = "│"          # │ min/max over the last HISTORY samples
MARKER_ON_FILL = "┃"  # ┃ same marker, drawn over a filled cell
ANCHOR = "┼"          # ┼ anchor (only drawn when the bar is empty)


# --------------------------------------------------------------------------
# metric table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricSpec:
    """How one sb3 logger key is displayed.

    ``goal`` is the human hint printed next to the value ("larger", "smaller",
    "~0", ...). ``zero_anchored`` selects the diverging bar; ``bar=False``
    suppresses the track entirely for monotonic counters.
    """

    key: str
    label: str
    panel: str
    fmt: str = "float"          # float | int | duration | sci
    decimals: int = 4
    goal: str = "-"
    bar: bool = True
    zero_anchored: bool = False


SPECS: tuple[MetricSpec, ...] = (
    # left column, top panel - monotonic counters, no bars
    MetricSpec("blueprince/episodes", "episodes", "PROGRESS", "int", bar=False),
    MetricSpec("time/iterations", "iterations", "PROGRESS", "int", bar=False),
    MetricSpec("time/total_timesteps", "timesteps", "PROGRESS", "int", bar=False),
    MetricSpec("time/time_elapsed", "elapsed", "PROGRESS", "duration", bar=False),
    MetricSpec("time/fps", "fps", "PROGRESS", "int", goal="larger"),
    # left column, bottom panel - what the agent actually achieves
    MetricSpec("blueprince/win_rate_1k", "win_rate_1k", "OUTCOMES", goal="larger"),
    MetricSpec("blueprince/win_rate_exploit_1k", "win_exploit", "OUTCOMES",
               goal="larger"),
    MetricSpec("blueprince/win_rate_explore_1k", "win_explore", "OUTCOMES",
               goal="larger"),
    MetricSpec("rollout/ep_rew_mean", "ep_rew_mean", "OUTCOMES", goal="larger"),
    MetricSpec("rollout/ep_len_mean", "ep_len_mean", "OUTCOMES", decimals=2),
    # right column - optimiser health
    MetricSpec("train/approx_kl", "approx_kl", "LEARNING", goal="smaller",
               zero_anchored=True),
    MetricSpec("train/clip_fraction", "clip_fraction", "LEARNING", goal="<0.3",
               zero_anchored=True),
    MetricSpec("train/clip_range", "clip_range", "LEARNING", decimals=3),
    MetricSpec("train/entropy_loss", "entropy_loss", "LEARNING", goal="rises~0",
               zero_anchored=True),
    MetricSpec("train/explained_variance", "explained_var", "LEARNING",
               goal="larger"),
    MetricSpec("train/learning_rate", "learning_rate", "LEARNING", "sci"),
    MetricSpec("train/loss", "loss", "LEARNING", goal="~0", zero_anchored=True),
    MetricSpec("train/n_updates", "n_updates", "LEARNING", "int", bar=False),
    MetricSpec("train/policy_gradient_loss", "pg_loss", "LEARNING", goal="~0",
               zero_anchored=True),
    MetricSpec("train/value_loss", "value_loss", "LEARNING", goal="smaller",
               zero_anchored=True),
)

PANEL_LAYOUT: dict[str, tuple[str, ...]] = {
    "left": ("PROGRESS", "OUTCOMES"),
    "right": ("LEARNING",),
}


# --------------------------------------------------------------------------
# number formatting - fixed width, sign column always reserved
# --------------------------------------------------------------------------

def format_value(spec: MetricSpec, value: float | None, width: int) -> str:
    """Right-align ``value`` in ``width`` columns with a reserved sign slot.

    Positive numbers get a leading space where the minus sign would go, so a
    value crossing zero never shifts the digits sideways.
    """
    if value is None:
        return "-".rjust(width)
    if spec.fmt == "int":
        text = f"{int(round(value)):,}"
        text = text if value < 0 else " " + text
    elif spec.fmt == "duration":
        text = " " + format_duration(value)
    elif spec.fmt == "sci":
        text = f"{value: .2e}"
    else:
        text = f"{value: .{spec.decimals}f}"
    return text[-width:].rjust(width) if len(text) > width else text.rjust(width)


def format_duration(seconds: float) -> str:
    """``H:MM:SS`` (no day rollover - a long run should read as 51:03:07)."""
    total = int(max(0.0, seconds))
    return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def format_axis(value: float, decimals: int) -> str:
    """Compact axis endpoint label.

    Trailing zeros are trimmed only after a decimal point - stripping them
    unconditionally would render an fps axis of 1200 as "12".
    """
    if value == 0:
        return "0"
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


# --------------------------------------------------------------------------
# axis scaling
# --------------------------------------------------------------------------

def nice_step(span: float, ticks: int = 4) -> float:
    """A round step (1/2/2.5/5 x 10^k) that divides ``span`` into ~``ticks``.

    Snapping the *step* rather than the endpoints keeps the axis tight: a
    19-26 window lands on 18-28, not on 10-50.
    """
    if span <= 0 or not math.isfinite(span):
        return 0.0
    raw = span / max(1, ticks)
    base = 10.0 ** math.floor(math.log10(raw))
    frac = raw / base
    pick = next((s for s in (1.0, 2.0, 2.5, 5.0) if frac <= s + 1e-12), 10.0)
    return pick * base


@dataclass(frozen=True)
class Axis:
    """Resolved bar scale. ``degenerate`` means every sample was identical."""

    lo: float
    hi: float
    step: float

    @property
    def degenerate(self) -> bool:
        return self.hi <= self.lo

    @property
    def decimals(self) -> int:
        if self.step <= 0:
            return 0
        return min(4, max(0, -math.floor(math.log10(self.step))))


def compute_axis(lo: float, hi: float, zero_anchored: bool,
                 pad: float = 0.15) -> Axis:
    """Padded, step-snapped axis covering ``[lo, hi]`` (and 0 when anchored).

    One-signed data never grows an axis of the opposite sign: a win rate that
    bottoms out at 0.000 gets an axis starting at 0, not at -0.0025. That also
    makes a zero-anchored metric whose samples never change sign degenerate
    into an ordinary left- (or right-) anchored fill.
    """
    if not math.isfinite(lo) or not math.isfinite(hi):
        return Axis(0.0, 0.0, 0.0)
    if zero_anchored:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    span = hi - lo
    if span <= 0:
        return Axis(lo, hi, 0.0)   # caller renders a flat "constant" track
    lo_p, hi_p = lo - span * pad, hi + span * pad
    if lo >= 0.0:
        lo_p = max(0.0, lo_p)
    if hi <= 0.0:
        hi_p = min(0.0, hi_p)
    step = nice_step(hi_p - lo_p)
    axis_lo = math.floor(lo_p / step) * step
    axis_hi = math.ceil(hi_p / step) * step
    if lo >= 0.0:
        axis_lo = max(0.0, axis_lo)
    if hi <= 0.0:
        axis_hi = min(0.0, axis_hi)
    return Axis(axis_lo, axis_hi, step)


# --------------------------------------------------------------------------
# bar rendering
# --------------------------------------------------------------------------

def render_bar(width: int, axis_lo: float, axis_hi: float, value: float,
               anchor: float, wmin: float, wmax: float) -> str:
    """Draw one equalizer track of exactly ``width`` characters.

    The fill spans anchor -> value (so a zero-anchored metric diverges from
    wherever 0 sits on the axis); ``|`` markers mark the window min and max.
    """
    if width <= 0:
        return ""
    if axis_hi <= axis_lo:
        return "constant".center(width, " ")[:width]

    def pos(x: float) -> float:
        frac = (x - axis_lo) / (axis_hi - axis_lo)
        return min(1.0, max(0.0, frac)) * width

    start, end = sorted((pos(anchor), pos(value)))
    cells = []
    for i in range(width):
        overlap = min(end, i + 1) - max(start, i)
        cells.append(FILL if overlap >= 0.5 else TRACK)
    # a nonzero deviation should always show at least one cell of fill
    if FILL not in cells and end - start > 0:
        cells[min(width - 1, int(start if value < anchor else max(0, end - 1)))] = FILL
    if end - start <= 0:
        cells[min(width - 1, int(start))] = ANCHOR
    for edge in (wmin, wmax):
        i = min(width - 1, int(pos(edge)))
        # a heavy bar keeps the fill readable underneath the marker, which
        # matters when the current value sits exactly at a window extreme
        cells[i] = MARKER_ON_FILL if cells[i] == FILL else MARKER
    return "".join(cells)


# --------------------------------------------------------------------------
# dashboard state + frame assembly
# --------------------------------------------------------------------------

@dataclass
class Series:
    """Rolling window of one metric's recent samples."""

    values: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))

    def push(self, value: float) -> None:
        if math.isfinite(value):
            self.values.append(float(value))

    @property
    def last(self) -> float | None:
        return self.values[-1] if self.values else None


class Dashboard:
    """Accumulates metric samples and renders the frame.

    Pure: :meth:`render` returns a list of lines and touches no terminal
    state, so tests can assert on geometry. :class:`LiveDashboard` adds the
    ANSI redraw.
    """

    def __init__(self, title: str = "blueprince-train", subtitle: str = "",
                 width: int | None = None, event_lines: int = 4) -> None:
        self.title = title
        self.subtitle = subtitle
        self.width = _resolve_width(width)
        self.series: dict[str, Series] = {}
        self.events: deque[str] = deque(maxlen=event_lines)
        self.event_lines = event_lines
        self._specs = {s.key: s for s in SPECS}

    # -- data ------------------------------------------------------------
    def update(self, values: dict[str, object]) -> None:
        """Record one sb3 logger dump. Unknown/non-numeric keys are ignored.

        Coerces with ``float()`` rather than an isinstance check: sb3 records
        numpy scalars (``train/approx_kl`` is an ``np.float32``), and those
        are not instances of ``float``.
        """
        for key, raw in values.items():
            if key not in self._specs or isinstance(raw, (str, bool)) or raw is None:
                continue
            try:
                self.series.setdefault(key, Series()).push(float(raw))
            except (TypeError, ValueError):
                continue

    def note(self, message: str) -> None:
        """Add a line to the in-frame event tail."""
        for line in str(message).splitlines():
            self.events.append(line.rstrip())

    # -- rendering -------------------------------------------------------
    def render(self) -> list[str]:
        inner = self.width - 4                      # "| " ... " |"
        left_w = inner // 2 - 2
        right_w = inner - left_w - 3                # 3 = " | " column split
        left = self._panel_lines(PANEL_LAYOUT["left"], left_w)
        right = self._panel_lines(PANEL_LAYOUT["right"], right_w)
        rows = max(len(left), len(right))
        left += [" " * left_w] * (rows - len(left))
        right += [" " * right_w] * (rows - len(right))

        lines = [self._title_line()]
        lines += [f"│ {a} │ {b} │" for a, b in zip(left, right)]
        lines.append(self._rule("├", "┴", "┤", left_w, right_w))
        lines.append(self._boxed(self._legend(inner), inner))
        for text in self._event_block():
            lines.append(self._boxed(text, inner))
        lines.append("└" + "─" * (self.width - 2) + "┘")
        return lines

    # -- internals -------------------------------------------------------
    def _title_line(self) -> str:
        head = f"┌─ {self.title} "
        # a long --checkpoint-dir must not push the row past the frame width,
        # so the subtitle is what gets clipped, from the left (the tail of a
        # path is the informative end)
        room = self.width - len(head) - 4
        subtitle = self.subtitle if len(self.subtitle) <= room else (
            "…" + self.subtitle[-(room - 1):] if room > 1 else "")
        tail = f" {subtitle} ─┐" if subtitle else "─┐"
        return head + "─" * max(0, self.width - len(head) - len(tail)) + tail

    def _rule(self, left: str, mid: str, right: str,
              left_w: int, right_w: int) -> str:
        return (left + "─" * (left_w + 2) + mid
                + "─" * (right_w + 2) + right)

    def _boxed(self, text: str, inner: int) -> str:
        return "│ " + text[:inner].ljust(inner) + " │"

    def _legend(self, inner: int) -> str:
        return (f"goal = what healthy looks like · bar fills from 0 (or axis "
                f"low) to now · {MARKER} = min/max of last {HISTORY}")[:inner]

    def _event_block(self) -> list[str]:
        pad = [""] * (self.event_lines - len(self.events))
        return list(self.events) + pad

    def _panel_lines(self, panels: Iterable[str], width: int) -> list[str]:
        lines: list[str] = []
        for i, panel in enumerate(panels):
            if i:
                lines.append(" " * width)
            lines.append(panel.ljust(width)[:width])
            for spec in (s for s in SPECS if s.panel == panel):
                lines.append(self._metric_line(spec, width))
        return lines

    def _metric_line(self, spec: MetricSpec, width: int) -> str:
        label_w, value_w, goal_w = 14, 12, 8
        series = self.series.get(spec.key)
        value = series.last if series else None
        goal = "" if spec.goal == "-" else spec.goal
        head = ("  " + spec.label.ljust(label_w)[:label_w]
                + format_value(spec, value, value_w) + " "
                + goal.ljust(goal_w)[:goal_w])
        # the track absorbs all slack, so rows end flush with the panel edge
        track_w = width - len(head) - 2 - 2 * _AXIS_LABEL_W
        if not spec.bar or value is None or track_w < 8:
            return head.ljust(width)[:width]

        window = list(series.values) if series else []
        wmin, wmax = min(window), max(window)
        axis = compute_axis(wmin, wmax, spec.zero_anchored)
        if axis.degenerate:
            # No range to scale to - either a genuinely constant metric
            # (clip_range, learning_rate) or the first rollouts of a run. A
            # bar would imply movement that isn't there.
            body = ("warming up" if len(window) < 2 else "constant")
            return (head + " " * _AXIS_LABEL_W + body.center(track_w + 2)
                    + " " * _AXIS_LABEL_W).ljust(width)[:width]

        anchor = 0.0 if spec.zero_anchored else axis.lo
        bar = render_bar(track_w, axis.lo, axis.hi, value, anchor, wmin, wmax)
        dec = axis.decimals if spec.fmt != "int" else 0
        lo_lbl = format_axis(axis.lo, dec).rjust(_AXIS_LABEL_W - 1)[:_AXIS_LABEL_W - 1]
        hi_lbl = format_axis(axis.hi, dec).ljust(_AXIS_LABEL_W - 1)[:_AXIS_LABEL_W - 1]
        return (head + lo_lbl + " [" + bar + "] " + hi_lbl).ljust(width)[:width]


_AXIS_LABEL_W = 8


def _resolve_width(width: int | None) -> int:
    if width is None:
        width = min(TARGET_WIDTH, shutil.get_terminal_size((TARGET_WIDTH, 40)).columns - 1)
    return max(MIN_WIDTH, min(MAX_WIDTH, width))


# --------------------------------------------------------------------------
# live terminal rendering
# --------------------------------------------------------------------------

class LiveDashboard(Dashboard):
    """:class:`Dashboard` that redraws itself in place on an ANSI terminal."""

    def __init__(self, *args, stream=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stream = stream if stream is not None else sys.stdout
        self._height = 0
        self._started = False

    def refresh(self) -> None:
        lines = self.render()
        out = []
        if not self._started:
            out.append("\x1b[?25l")           # hide cursor
            self._started = True
        elif self._height:
            out.append(f"\x1b[{self._height}A\r")
        for line in lines:
            out.append("\x1b[2K" + line + "\n")
        out.append("\x1b[J")                  # clear anything below a shrunk frame
        self._height = len(lines)
        self.stream.write("".join(out))
        self.stream.flush()

    def update(self, values: dict[str, object]) -> None:
        super().update(values)
        self.refresh()

    def note(self, message: str) -> None:
        super().note(message)
        self.refresh()

    def close(self) -> None:
        if self._started:
            self.refresh()
            self.stream.write("\x1b[?25h")    # restore cursor
            self.stream.flush()
            self._started = False


# --------------------------------------------------------------------------
# process-wide hookup
# --------------------------------------------------------------------------

_ACTIVE: LiveDashboard | None = None


def supported(stream=None) -> bool:
    """True when stdout is an ANSI-capable TTY (not a pipe, not TERM=dumb)."""
    stream = stream if stream is not None else sys.stdout
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    return os.environ.get("TERM", "") not in ("", "dumb")


def activate(title: str, subtitle: str = "") -> LiveDashboard:
    """Install the process-wide dashboard that :func:`emit` writes into.

    Draws an empty frame immediately: the first rollout takes
    ``n_envs * n_steps`` env steps, and a blank terminal for that long reads
    as a hung process.
    """
    global _ACTIVE
    _ACTIVE = LiveDashboard(title=title, subtitle=subtitle, event_lines=6)
    _ACTIVE.refresh()
    return _ACTIVE


def deactivate() -> None:
    global _ACTIVE
    if _ACTIVE is not None:
        _ACTIVE.close()
    _ACTIVE = None


def emit(message: str) -> None:
    """Trainer log line: into the dashboard's event tail, else plain stdout.

    Trainer messages must not go through ``print`` while the dashboard owns
    the screen - the frame is redrawn relative to the cursor, so an
    interleaved write tears it.
    """
    if _ACTIVE is not None:
        _ACTIVE.note(message)
    else:
        print(message, flush=True)


def make_sb3_logger(dashboard: Dashboard, tensorboard_dir: str | None = None):
    """An sb3 ``Logger`` that renders into ``dashboard`` instead of scrolling.

    Pass the result to ``model.set_logger``; sb3 then skips its own
    ``configure_logger`` (it honours ``_custom_logger``) and the default
    ``HumanOutputFormat`` table never gets installed.
    """
    from stable_baselines3.common.logger import (  # local: sb3 is an extra
        KVWriter,
        Logger,
        TensorBoardOutputFormat,
    )

    class _DashboardWriter(KVWriter):
        def write(self, key_values, key_excluded, step: int = 0) -> None:
            dashboard.update(key_values)

        def close(self) -> None:
            pass

    formats = [_DashboardWriter()]
    if tensorboard_dir:
        formats.append(TensorBoardOutputFormat(tensorboard_dir))
    return Logger(folder=None, output_formats=formats)


# --------------------------------------------------------------------------
# demo
# --------------------------------------------------------------------------

def _demo(frames: int = 60, live: bool = True) -> None:
    """Render synthetic frames so the layout can be eyeballed without torch."""
    import random
    import time

    dash: Dashboard = (LiveDashboard(title="blueprince-train",
                                     subtitle="runs/new-reward · reward=phased")
                       if live and supported() else
                       Dashboard(title="blueprince-train",
                                 subtitle="runs/new-reward · reward=phased"))
    rng = random.Random(0)
    for i in range(frames):
        t = i / max(1, frames)
        dash.update({
            "blueprince/episodes": 1_200_000 + i * 4096,
            "time/iterations": 2100 + i,
            "time/total_timesteps": 45_000_000 + i * 4096,
            "time/time_elapsed": 11564 + i * 3.1,
            "time/fps": 1400 + rng.gauss(0, 60),
            "blueprince/win_rate_1k": max(0.0, 0.012 + t * 0.01 + rng.gauss(0, 0.003)),
            "blueprince/win_rate_exploit_1k": max(0.0, 0.018 + t * 0.01
                                                  + rng.gauss(0, 0.004)),
            "blueprince/win_rate_explore_1k": max(0.0, 0.004 + rng.gauss(0, 0.002)),
            "rollout/ep_rew_mean": -1.2 + t * 2.0 + rng.gauss(0, 0.3),
            "rollout/ep_len_mean": 22.4 + rng.gauss(0, 1.5),
            "train/approx_kl": abs(0.012 + rng.gauss(0, 0.004)),
            "train/clip_fraction": abs(0.18 + rng.gauss(0, 0.03)),
            "train/clip_range": 0.2,
            "train/entropy_loss": -1.9 + t * 0.4 + rng.gauss(0, 0.05),
            "train/explained_variance": 0.42 + t * 0.2 + rng.gauss(0, 0.05),
            "train/learning_rate": 3e-4,
            "train/loss": rng.gauss(0, 0.02),
            "train/n_updates": 21_030 + i * 10,
            "train/policy_gradient_loss": -0.009 + rng.gauss(0, 0.003),
            "train/value_loss": abs(0.034 + rng.gauss(0, 0.008)),
        })
        if i % 20 == 0:
            dash.note(f"[train] checkpoint latest.zip: {1_200_000 + i * 4096} "
                      f"episodes, win_rate(1k)=0.021")
        if live and isinstance(dash, LiveDashboard):
            time.sleep(0.05)
    if isinstance(dash, LiveDashboard):
        dash.close()
    else:
        print("\n".join(dash.render()))


if __name__ == "__main__":       # pragma: no cover - manual inspection aid
    _demo(live="--static" not in sys.argv)
