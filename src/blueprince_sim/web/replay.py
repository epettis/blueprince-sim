"""Rebuild an episode frame-by-frame from a recorded ``{seed, actions}`` line.

Replays run through a real ``BluePrinceEnv`` (same code path as training:
invalid-action no-ops, dead-end detection, truncation), so given the engine's
tested determinism invariant the reconstruction is exact when the record carries
a ``day_config`` diff (multi-day mode) or is a single-day record.

Records without ``day_config`` (legacy, recorded before this field was added)
may diverge from the original run because per-day starting conditions are lost;
divergences are detected and surfaced rather than silently rendered.
"""

from __future__ import annotations

import dataclasses

from ..config import GameConfig
from ..engine.game import Game, Phase
from ..engine.grid import DIR_NAMES
from ..engine.items import expected_yields
from ..env import actions as A


def rooms_meta(registry) -> list[dict]:
    """Static per-room metadata the client needs to draw the house.

    ``yields`` is the data-derived expectation of steps/keys/gems/luck from
    one draft+entry of the room (see :func:`engine.items.expected_yields`).
    """
    return [
        {"idx": r.idx, "id": r.id, "name": r.name, "category": r.category,
         "layout": r.layout, "rarity": r.rarity,
         "yields": expected_yields(r, registry)}
        for r in registry.rooms
    ]


def _pending_dict(game: Game) -> dict | None:
    """JSON view of the pending draft hand; None when no draft is open.

    Hidden (Archives mystery) options keep cost and affordability visible but
    report room_idx -1, name "???", and no identity/orientation fields.
    """
    p = game.state.pending
    if p is None:
        return None
    options = []
    for opt in p.options:
        room = game.registry.rooms[opt.room_idx]
        if opt.hidden:
            options.append({
                "slot": opt.slot, "room_idx": -1, "name": "???", "category": None,
                "rarity": None, "layout": None, "orientation": 0,
                "cost": game._effective_cost(room, opt),
                "affordable": game.affordable(room, opt),
                "forced": opt.forced, "hidden": True,
            })
            continue
        options.append({
            "slot": opt.slot, "room_idx": opt.room_idx, "name": room.name,
            "category": room.category, "rarity": room.rarity, "layout": room.layout,
            "orientation": opt.orientation,
            "cost": game._effective_cost(room, opt),
            "affordable": game.affordable(room, opt),
            "forced": opt.forced, "hidden": False,
        })
    return {
        "from_cell": p.from_cell,
        "direction": DIR_NAMES.get(p.direction),
        "target_cell": p.target_cell,
        "options": options,
    }


def _frame(game: Game, action: dict | None, facing: str | None) -> dict:
    """Snapshot the visible state as one replay frame.

    ``action`` describes the step that PRODUCED this state (None for the
    initial frame); ``facing`` is the client-side sprite direction.
    ``scepter_color`` is the Royal Scepter category bias active this episode
    (one of blueprint/green/red/bedroom/hallway/shop), or null when none.
    ``area`` is the area-graph node id the player is currently at, or null
    when the player is on the 5x9 grid (``pos`` is authoritative in that case).
    """
    st = game.state
    return {
        "phase": game.phase.name,
        "grid": list(st.grid),
        "doors": list(st.placed_doors),
        "pos": st.pos,
        "area": st.area,
        "facing": facing,
        "resources": {
            "steps": st.steps, "gems": st.gems, "keys": st.keys,
            "coins": st.coins, "dice": st.dice, "luck": st.luck,
        },
        "deepest_rank": game.deepest_rank,
        "reason": game.termination_reason,
        "pending": _pending_dict(game),
        "action": action,
        "scepter_color": st.shops.scepter_color,
    }


def _apply_day_config(base_cfg: GameConfig, day_config: dict) -> GameConfig:
    """Apply a serialized day_config diff onto base_cfg via dataclasses.replace.

    Lists are converted back to frozensets for fields whose type annotation
    contains ``frozenset`` (detected by inspecting dataclasses.fields).
    Other values pass through directly.
    """
    frozenset_fields = {
        f.name
        for f in dataclasses.fields(GameConfig)
        if "frozenset" in str(f.type)
    }
    kwargs = {}
    for key, val in day_config.items():
        if key in frozenset_fields and isinstance(val, list):
            kwargs[key] = frozenset(val)
        else:
            kwargs[key] = val
    return dataclasses.replace(base_cfg, **kwargs)


def build_frames(record: dict) -> tuple[list[dict], dict | None]:
    """Frame 0 is the post-reset state; frame i+1 follows ``actions[i]``.

    Returns ``(frames, divergence)`` where ``divergence`` is ``None`` when the
    replay matched the recorded actions exactly, or a dict with keys:
      - ``"first_invalid_index"``: index of the first action that could not be
        applied (was not in the action mask at that step).
      - ``"invalid_count"``: total number of such actions across the episode.
    A divergence means the replayed house is incomplete and the frames should
    be rendered with a warning.

    Records carrying ``"day_config"`` (multi-day mode) are replayed with the
    day's exact GameConfig; records without it (single-day or legacy) use the
    base all_unlocks_config, which may diverge when per-day state differs.
    """
    from ..env.blueprince_env import BluePrinceEnv
    from ..rl.train import all_unlocks_config

    # ``day_config`` is a diff against the DayChain's base config, so it only
    # reconstructs correctly when replayed onto that same base.  The trainer
    # builds its chain from ``all_unlocks_config(reward)``
    # (rl/train.py::make_single_env), which is what we rebuild here.  If the
    # trainer ever grows a config override, the diff's base must be recorded
    # alongside it or replays will silently drift again.
    base_cfg = all_unlocks_config(record.get("reward", "shaped"))
    day_config = record.get("day_config")
    cfg = _apply_day_config(base_cfg, day_config) if day_config is not None else base_cfg

    env = BluePrinceEnv(cfg=cfg)
    env.reset(seed=record["seed"])
    facing = "N"
    frames = [_frame(env.game, None, facing)]
    modes = record.get("modes", "")
    first_invalid: int | None = None
    invalid_count = 0

    for i, action in enumerate(record["actions"]):
        if env.game.phase is Phase.TERMINAL:
            break  # defensive: never replay past the recorded terminal state
        action = int(action)
        # Check the action mask BEFORE stepping: if the recorded action is not
        # legal, the reconstruction has diverged.
        mask = env.action_masks()
        action_invalid = not mask[action]
        if action_invalid:
            invalid_count += 1
            if first_invalid is None:
                first_invalid = i

        text = A.describe_action(env.game, action)
        explore = i < len(modes) and modes[i] == "0"
        # Facing after a walk macro = direction of the path's last hop
        # (computed pre-step; the walk may be cut short by termination).
        walk_facing = None
        if A.MOVE_TO_BASE <= action < A.MOVE_TO_BASE + 45:
            path = env.game._path_dirs(action - A.MOVE_TO_BASE)
            if path:
                walk_facing = DIR_NAMES[path[-1]]
        _, _, term, trunc, _ = env.step(action)
        if walk_facing is not None:
            facing = walk_facing
        pending = env.game.state.pending
        if pending is not None:
            facing = DIR_NAMES.get(pending.direction, facing)
        frame = _frame(
            env.game,
            {"index": i, "action": action, "text": text, "explore": explore},
            facing)
        if action_invalid:
            frame["invalid"] = True
        frames.append(frame)
        if term or trunc:
            break

    divergence = None
    if first_invalid is not None:
        divergence = {
            "first_invalid_index": first_invalid,
            "invalid_count": invalid_count,
            # A legacy record (no day_config) has a known cause: its per-day
            # starting conditions were never written down.  A record that DOES
            # carry day_config but still diverges is a real, unexplained bug —
            # the UI must not misattribute it to the legacy format.
            "legacy_record": day_config is None,
        }
    return frames, divergence
