"""Rebuild an episode frame-by-frame from a recorded ``{seed, actions}`` line.

Replays run through a real ``BluePrinceEnv`` (same code path as training:
invalid-action no-ops, dead-end detection, truncation), so given the engine's
tested determinism invariant the reconstruction is exact.
"""

from __future__ import annotations

from ..engine.game import Game, Phase
from ..engine.grid import DIR_NAMES
from ..env import actions as A


def rooms_meta(registry) -> list[dict]:
    """Static per-room metadata the client needs to draw the house."""
    return [
        {"idx": r.idx, "id": r.id, "name": r.name, "category": r.category,
         "layout": r.layout, "rarity": r.rarity}
        for r in registry.rooms
    ]


def _pending_dict(game: Game) -> dict | None:
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
    st = game.state
    return {
        "phase": game.phase.name,
        "grid": list(st.grid),
        "doors": list(st.placed_doors),
        "pos": st.pos,
        "facing": facing,
        "resources": {
            "steps": st.steps, "gems": st.gems, "keys": st.keys,
            "coins": st.coins, "dice": st.dice, "luck": st.luck,
        },
        "deepest_rank": game.deepest_rank,
        "reason": game.termination_reason,
        "pending": _pending_dict(game),
        "action": action,
    }


def build_frames(record: dict) -> list[dict]:
    """Frame 0 is the post-reset state; frame i+1 follows ``actions[i]``."""
    from ..env.blueprince_env import BluePrinceEnv
    from ..rl.train import all_unlocks_config

    env = BluePrinceEnv(cfg=all_unlocks_config(record.get("reward", "shaped")))
    env.reset(seed=record["seed"])
    facing = "N"
    frames = [_frame(env.game, None, facing)]
    modes = record.get("modes", "")
    for i, action in enumerate(record["actions"]):
        if env.game.phase is Phase.TERMINAL:
            break  # defensive: never replay past the recorded terminal state
        action = int(action)
        text = A.describe_action(env.game, action)
        explore = i < len(modes) and modes[i] == "0"
        _, _, term, trunc, _ = env.step(action)
        if A.MOVE_BASE <= action < A.MOVE_BASE + 4:
            facing = DIR_NAMES[A.DIRS[action - A.MOVE_BASE]]
        pending = env.game.state.pending
        if pending is not None:
            facing = DIR_NAMES.get(pending.direction, facing)
        frames.append(_frame(
            env.game,
            {"index": i, "action": action, "text": text, "explore": explore},
            facing))
        if term or trunc:
            break
    return frames
