"""Tests for the in-place training dashboard.

These assert the properties the display is *for* - fixed geometry, no
sideways drift when a value changes sign or grows a digit, bars anchored
where the metric's "good" is - rather than mirroring the metric table back.
"""

from __future__ import annotations

import io

import pytest

from blueprince_sim.rl.dashboard import (
    ANCHOR,
    FILL,
    MARKER,
    MARKER_ON_FILL,
    MAX_HEIGHT,
    MAX_WIDTH,
    SPECS,
    Dashboard,
    LiveDashboard,
    MetricSpec,
    compute_axis,
    format_axis,
    format_duration,
    format_value,
    nice_step,
    render_bar,
)

FLOAT = MetricSpec("x", "x", "P", decimals=4)
INT = MetricSpec("n", "n", "P", "int")


def sample(**over) -> dict[str, float]:
    """One plausible sb3 logger dump; ``over`` replaces individual keys."""
    values = {
        "blueprince/episodes": 1_441_664,
        "time/iterations": 2159,
        "time/total_timesteps": 45_241_664,
        "time/time_elapsed": 11_746.0,
        "time/fps": 1469.0,
        "blueprince/win_rate_1k": 0.0207,
        "blueprince/win_rate_exploit_1k": 0.0284,
        "blueprince/win_rate_explore_1k": 0.0010,
        "rollout/ep_rew_mean": 0.9896,
        "rollout/ep_len_mean": 22.6,
        "train/approx_kl": 0.0110,
        "train/clip_fraction": 0.1947,
        "train/clip_range": 0.2,
        "train/entropy_loss": -1.4541,
        "train/explained_variance": 0.6868,
        "train/learning_rate": 3e-4,
        "train/loss": 0.0292,
        "train/n_updates": 21_620,
        "train/policy_gradient_loss": -0.0066,
        "train/value_loss": 0.0312,
    }
    values.update(over)
    return values


# -- number formatting -----------------------------------------------------

def test_sign_change_does_not_shift_digits():
    """The minus column is reserved, so +0.5 and -0.5 align digit for digit."""
    pos = format_value(FLOAT, 0.5, 12)
    neg = format_value(FLOAT, -0.5, 12)
    assert len(pos) == len(neg) == 12
    assert pos.replace(" ", "", 1) == neg.replace("-", "", 1)
    assert pos.index("0") == neg.index("0")


def test_decimals_are_capped_not_full_precision():
    """approx_kl-style values render at 4 decimals, not sb3's 9+."""
    assert format_value(FLOAT, 0.008123456789, 12).strip() == "0.0081"


@pytest.mark.parametrize("value", [0.0, -1.0, 1e-9, 12345.6789, -0.00004])
def test_value_width_is_constant(value):
    assert len(format_value(FLOAT, value, 12)) == 12
    assert len(format_value(INT, value, 12)) == 12


def test_missing_metric_renders_a_placeholder_not_a_crash():
    assert format_value(FLOAT, None, 12).strip() == "-"


def test_large_counters_stay_inside_their_column():
    assert len(format_value(INT, 45_241_664, 12)) == 12
    assert "45,241,664" in format_value(INT, 45_241_664, 12)


def test_duration_is_hms():
    assert format_duration(11_746) == "3:15:46"
    assert format_duration(0) == "0:00:00"


def test_axis_label_keeps_integer_zeros():
    """1200 must not render as '12' (trailing zeros trim only after a '.')."""
    assert format_axis(1200.0, 0) == "1200"
    assert format_axis(0.0500, 3) == "0.05"


# -- axis scaling ----------------------------------------------------------

def test_axis_hugs_the_window_instead_of_snapping_wide():
    """A 19-26 window gets a tight axis, not a 10-50 one."""
    axis = compute_axis(19.0, 26.0, zero_anchored=False)
    assert axis.lo >= 10.0 and axis.hi <= 35.0
    assert axis.lo <= 19.0 and axis.hi >= 26.0


def test_axis_pads_so_markers_sit_inside_the_track():
    axis = compute_axis(0.010, 0.020, zero_anchored=False)
    assert axis.lo < 0.010 and axis.hi > 0.020


def test_one_signed_data_never_grows_an_opposite_sign_axis():
    """A win rate that touches 0.0 keeps an axis starting at 0, not -0.0025."""
    assert compute_axis(0.0, 0.008, zero_anchored=False).lo == 0.0
    assert compute_axis(-2.0, 0.0, zero_anchored=True).hi == 0.0


def test_zero_anchored_axis_always_contains_zero():
    axis = compute_axis(0.5, 0.9, zero_anchored=True)
    assert axis.lo <= 0.0 <= axis.hi


def test_constant_metric_is_degenerate():
    """learning_rate/clip_range never move; the axis reports that."""
    assert compute_axis(0.2, 0.2, zero_anchored=False).degenerate


def test_nice_step_is_a_round_number():
    for span in (0.007, 1.0, 7.0, 12_000.0):
        step = nice_step(span)
        mantissa = step / 10 ** __import__("math").floor(__import__("math").log10(step))
        assert round(mantissa, 6) in (1.0, 2.0, 2.5, 5.0)


# -- bars ------------------------------------------------------------------

def test_bar_width_is_exact():
    for value in (-1.0, 0.0, 0.35, 1.0):
        bar = render_bar(20, -1.0, 1.0, value, 0.0, -1.0, 1.0)
        assert len(bar) == 20


def test_zero_anchored_bar_diverges_from_the_middle():
    """Positive fills right of centre, negative fills left of it."""
    pos = render_bar(20, -1.0, 1.0, 0.6, 0.0, -0.8, 0.8)
    neg = render_bar(20, -1.0, 1.0, -0.6, 0.0, -0.8, 0.8)
    assert pos.index(FILL) >= 9        # fill starts at/after the centre
    assert neg.index(FILL) < 9         # fill starts left of the centre
    assert pos[:8].count(FILL) == 0
    assert neg[12:].count(FILL) == 0


def test_left_anchored_bar_fills_from_the_left_edge():
    bar = render_bar(20, 0.0, 1.0, 0.5, 0.0, 0.1, 0.9)
    assert bar[0] in (FILL, MARKER_ON_FILL)
    assert bar[-1] not in (FILL, MARKER_ON_FILL)


def test_bigger_value_never_shrinks_a_left_anchored_bar():
    small = render_bar(20, 0.0, 1.0, 0.2, 0.0, 0.0, 1.0)
    large = render_bar(20, 0.0, 1.0, 0.8, 0.0, 0.0, 1.0)
    assert large.count(FILL) > small.count(FILL)


def test_value_at_zero_shows_an_anchor_tick_not_an_empty_track():
    bar = render_bar(20, -1.0, 1.0, 0.0, 0.0, -0.5, 0.5)
    assert ANCHOR in bar


def test_markers_show_the_window_extremes():
    bar = render_bar(20, 0.0, 1.0, 0.5, 0.0, 0.25, 0.75)
    marks = [i for i, c in enumerate(bar) if c in (MARKER, MARKER_ON_FILL)]
    assert len(marks) == 2
    assert marks[0] < marks[1]
    assert 3 <= marks[0] <= 6 and 13 <= marks[1] <= 16


def test_marker_over_fill_stays_distinguishable():
    """A marker inside the filled span must not read as a gap in the bar."""
    bar = render_bar(20, 0.0, 1.0, 0.5, 0.0, 0.2, 0.9)
    assert MARKER_ON_FILL in bar
    assert FILL in bar


def test_out_of_axis_value_clamps_instead_of_overflowing():
    bar = render_bar(20, 0.0, 1.0, 5.0, 0.0, 0.0, 1.0)
    assert len(bar) == 20


def test_degenerate_axis_renders_a_constant_track():
    assert "constant" in render_bar(20, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)


# -- frame -----------------------------------------------------------------

def test_frame_fits_the_terminal_budget():
    dash = Dashboard(width=MAX_WIDTH)
    dash.update(sample())
    lines = dash.render()
    assert len(lines) <= MAX_HEIGHT
    assert max(len(ln) for ln in lines) <= MAX_WIDTH


@pytest.mark.parametrize("width", [96, 120, 140, 200, 240])
def test_every_row_is_exactly_the_frame_width(width):
    """The border is static: no row reflows with the data inside it."""
    dash = Dashboard(width=width)
    dash.update(sample())
    lines = dash.render()
    assert {len(ln) for ln in lines} == {width}


def test_frame_geometry_is_stable_across_updates():
    """Growing digits and sign flips must not resize or reflow the frame."""
    dash = Dashboard(width=140)
    dash.update(sample())
    before = dash.render()
    dash.update(sample(**{
        "blueprince/episodes": 999_999_999,
        "rollout/ep_rew_mean": -12.5,          # sign flip + extra digit
        "train/policy_gradient_loss": 0.5,
    }))
    after = dash.render()
    assert len(before) == len(after)
    assert [len(a) for a in before] == [len(b) for b in after]


def cell(dash: Dashboard, label: str) -> str:
    """The one panel cell holding ``label`` (rows carry two columns).

    Splits on the border sequence "│ " rather than on "│" alone: the bare
    glyph is also the min/max marker, so a plain split cuts bars in half.
    """
    for line in dash.render():
        for part in line.split("│ "):
            if part.strip().startswith(label + " "):
                return part
    raise AssertionError(f"no row for {label}")


def varying(dash: Dashboard, n: int = 5) -> Dashboard:
    for i in range(n):
        dash.update(sample(**{k: v * (1 + 0.05 * i)
                              for k, v in sample().items()}))
    return dash


def test_monotonic_counters_have_no_bar():
    """Bars are meaningless for episodes/iterations/timesteps/elapsed."""
    dash = varying(Dashboard(width=140))
    for label in ("episodes", "iterations", "timesteps", "elapsed", "n_updates"):
        row = cell(dash, label)
        assert FILL not in row and "[" not in row


def test_rate_and_quality_metrics_do_have_bars():
    dash = varying(Dashboard(width=140))
    for label in ("fps", "win_rate_1k", "approx_kl", "value_loss"):
        row = cell(dash, label)
        assert "[" in row and "]" in row


#: Settings rather than health signals - they have no "better" direction.
NO_DIRECTION = {"train/clip_range", "train/learning_rate", "rollout/ep_len_mean"}


def test_goal_hint_is_shown_for_every_health_metric():
    """Requirement: each bar says what 'good' looks like."""
    for spec in SPECS:
        if spec.bar and spec.key not in NO_DIRECTION:
            assert spec.goal != "-", spec.key


def test_first_rollout_shows_warming_up_not_a_fake_bar():
    """One sample is no range; the track must not imply a measured spread."""
    dash = Dashboard(width=140)
    dash.update(sample())
    assert "warming up" in cell(dash, "win_rate_1k")
    assert FILL not in cell(dash, "win_rate_1k")


def test_constant_metric_reads_as_constant():
    dash = Dashboard(width=140)
    for _ in range(5):
        dash.update(sample())
    assert "constant" in cell(dash, "clip_range")


def test_history_window_is_bounded():
    dash = Dashboard(width=140)
    for i in range(1500):
        dash.update(sample(**{"train/approx_kl": i * 1e-6}))
    assert len(dash.series["train/approx_kl"].values) == 1000


def test_numpy_style_scalars_are_recorded():
    """sb3 records train/approx_kl as an np.float32, which is not a float."""
    class Float32:                       # stand-in: no numpy dep in this suite
        def __float__(self):
            return 0.0123

    dash = Dashboard(width=140)
    dash.update({"train/approx_kl": Float32()})
    assert dash.series["train/approx_kl"].last == pytest.approx(0.0123)


def test_long_subtitle_cannot_overflow_the_frame():
    """A long --checkpoint-dir path must clip, not widen the title row."""
    dash = Dashboard(title="blueprince-train",
                     subtitle="/very/long/" + "path/" * 40 + "runs/x",
                     width=140)
    assert {len(ln) for ln in dash.render()} == {140}


def test_unknown_and_non_numeric_keys_are_ignored():
    dash = Dashboard(width=140)
    dash.update({"train/std": "n/a", "some/unknown": 1.0, "train/loss": 0.1})
    assert "some/unknown" not in dash.series
    assert "train/std" not in dash.series
    assert dash.series["train/loss"].last == 0.1


def test_events_appear_in_frame_and_are_capped():
    dash = Dashboard(width=140, event_lines=3)
    for i in range(5):
        dash.note(f"[train] checkpoint {i}")
    text = "\n".join(dash.render())
    assert "checkpoint 4" in text
    assert "checkpoint 1" not in text


def test_renders_before_any_metrics_arrive():
    """The first rollout takes a while; the frame must draw empty first."""
    lines = Dashboard(width=140).render()
    assert {len(ln) for ln in lines} == {140}


# -- live redraw -----------------------------------------------------------

def test_live_redraw_moves_the_cursor_up_instead_of_scrolling():
    buf = io.StringIO()
    dash = LiveDashboard(width=140, stream=buf)
    dash.update(sample())
    first = buf.getvalue()
    height = first.count("\n")
    buf.truncate(0), buf.seek(0)
    dash.update(sample())
    second = buf.getvalue()
    assert f"\x1b[{height}A" in second      # rewinds exactly one frame
    assert second.count("\n") == height     # and emits exactly one frame


def test_live_close_restores_the_cursor():
    buf = io.StringIO()
    dash = LiveDashboard(width=140, stream=buf)
    dash.update(sample())
    dash.close()
    assert "\x1b[?25l" in buf.getvalue()    # hidden while running
    assert buf.getvalue().endswith("\x1b[?25h")
