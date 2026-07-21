"""Datamined random-rotation weights for drafted floorplans.

When a drawn floorplan has more than one legal orientation, the game does not
pick uniformly: it rolls a weighted orientation that is biased toward keeping a
south-facing door (and away from north-facing ones). The Compass shifts that
bias the other way, toward north-facing doors (the Ornate Compass is a stronger,
manual rotate-at-will handled in the Game orchestrator, not a weight change).

Weights are keyed by the floorplan's shape (T = 3 doors, L = 2 adjacent doors),
the direction of the *connecting* door back to the room drafted from (``back``),
and the in-game day. Source: Blue Prince Wiki, "Drafting/Advanced" (datamined by
TFMurphy). Orientations are identified by which door is *missing* (T-shapes) or
which non-back door is present (L-shapes). Values are percentages.

Confidence: datamined for South/West/East; the North rows and every Compass
column not published there are marked below and default to the base roll.
"""

from __future__ import annotations

from .grid import DIRS, N, E, S, W

# Each entry: (compass, day1_2, day3_20, day21plus) as percentage weights.

# --- T-shapes (3 doors), keyed by [back][missing door] -----------------------
_T: dict[int, dict[int, tuple[float, float, float, float]]] = {
    S: {  # drafted needing a south door ("3-way from South")
        N: (0.0, 70.0, 64.0, 60.0),   # ╦ {E,S,W}: no north door - favored
        E: (50.0, 15.0, 18.0, 20.0),  # ╠ {N,S,E}
        W: (50.0, 15.0, 18.0, 20.0),  # ╣ {N,S,W}
    },
    W: {  # "3-way from West"
        N: (5.0, 55.0, 50.0, 50.0),     # ╦ {E,S,W}: no north door
        E: (47.5, 35.0, 38.0, 38.0),    # ╣ {N,S,W}
        S: (47.5, 10.0, 12.0, 12.0),    # ╩ {N,E,W}: no south door
    },
    E: {  # mirror of West (swap E<->W)
        N: (5.0, 55.0, 50.0, 50.0),
        W: (47.5, 35.0, 38.0, 38.0),
        S: (47.5, 10.0, 12.0, 12.0),
    },
    N: {  # "3-way from North": near-uniform, Compass column unpublished
        S: (40.0, 40.0, 40.0, 40.0),   # ╩ {N,E,W}: no south door
        E: (30.0, 30.0, 30.0, 30.0),
        W: (30.0, 30.0, 30.0, 30.0),
    },
}

# --- L-shapes (2 adjacent doors), keyed by [back][other (non-back) door] ------
_L: dict[int, dict[int, tuple[float, float, float, float]]] = {
    W: {
        S: (10.0, 57.0, 55.0, 55.0),   # ╗ {S,W}: south door - favored
        N: (90.0, 43.0, 45.0, 45.0),   # ╝ {N,W}
    },
    E: {  # mirror of West
        S: (10.0, 57.0, 55.0, 55.0),   # ╔ {S,E}
        N: (90.0, 43.0, 45.0, 45.0),   # ╚ {N,E}
    },
    N: {E: (50.0, 50.0, 50.0, 50.0), W: (50.0, 50.0, 50.0, 50.0)},
    S: {E: (50.0, 50.0, 50.0, 50.0), W: (50.0, 50.0, 50.0, 50.0)},
}


def _col(day: int, compass: bool) -> int:
    if compass:
        return 0
    if day <= 2:
        return 1
    if day <= 20:
        return 2
    return 3


def _missing(mask: int) -> int:
    for d in DIRS:
        if not mask & d:
            return d
    return 0


def _other(mask: int, back: int) -> int:
    for d in DIRS:
        if mask & d and d != back:
            return d
    return 0


def orientation_weights(masks: list[int], back: int, day: int,
                        compass: bool) -> tuple[float, ...]:
    """Weights (parallel to ``masks``) for a weighted orientation roll.

    ``back`` is the connecting-door direction (OPPOSITE of the entry direction).
    Falls back to uniform weights for any shape/direction not in the datamined
    tables, and whenever the selected column would zero out every legal mask.
    """
    if len(masks) <= 1:
        return (1.0,) * len(masks)
    doors = bin(masks[0]).count("1")
    table = _T if doors == 3 else _L if doors == 2 else None
    col = _col(day, compass)
    weights = []
    for m in masks:
        row = table.get(back) if table else None
        key = _missing(m) if doors == 3 else _other(m, back)
        entry = row.get(key) if row else None
        weights.append(entry[col] if entry else 1.0)
    if sum(weights) <= 0:  # e.g. a Compass column that zeroes the only options
        return (1.0,) * len(masks)
    return tuple(weights)
