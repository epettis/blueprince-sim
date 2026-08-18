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

import copy
import dataclasses

from ..config import GameConfig, config_digest
from ..engine.game import ANTECHAMBER_CELL, Game, Phase, RedrawKind
from ..engine.grid import DIR_NAMES
from ..engine.items import expected_yields
from ..engine.locks import DOOR_SECURITY
from ..engine.placement import legal_orientations
from ..env import actions as A
from ..env import rewards


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


def _option_legal_orientations(game: Game, p, opt) -> list[int]:
    """Every door mask ``opt``'s room could legally be placed in at this doorway.

    ``opt.orientation`` (the dealt/rotated orientation) is always a member of
    this list. A length > 1 is the signal the Play tab needs to tell the player
    "this room has another legal orientation" -- purely informational, because
    picking one per option is NOT a mechanic: an option arrives with a rolled
    orientation, and the only way to reach a different one this hand is
    ``ROTATE_ACTION``, which advances every option together. (A vestigial
    per-option "alternate orientation" action block once existed but was never
    reachable from the mask, and was removed along with it.) Outer-room drafts
    have no doorway to rotate against (``target_cell == -1``, fixed
    orientation), and hidden options have no known room, so both return [].
    """
    if p.target_cell == -1 or opt.hidden:
        return []
    room = game.registry.rooms[opt.room_idx]
    return legal_orientations(room, p.target_cell, p.direction, game.state, game.cfg)


def _redraw_info(game: Game) -> dict:
    """What clicking REDRAW would cost right now, or why it is unavailable.

    Delegates eligibility to ``env.actions._redraw_kind`` -- the action mask's
    own source of truth for whether REDRAW_ACTION is legal -- so this display
    summary can never claim "available" when the mask disagrees. Reports the
    concrete cost (free hand-redraws left, a die, or a gem plus how many of
    the 8 Study redraws remain) rather than the bare "redraw" label the mask
    exposes, since not knowing what it would spend was the owner's complaint.
    """
    st = game.state
    pending = st.pending
    kind = A._redraw_kind(game)
    if kind is None:
        # Outer-room drafts redraw the same as grid drafts (owner-ruled,
        # externally corroborated -- see Game.redraw); FREE (Classroom) is the
        # only source that's structurally unreachable there, since an outer
        # hand has no from-cell to be "drafting from the Classroom" with, so
        # it never shows up as a missing-source reason.
        missing = []
        if st.dice < 1:
            missing.append("no dice")
        if not st.study_placed:
            missing.append("Study not placed")
        elif st.gems < 1:
            missing.append("no gems for a Study redraw")
        elif pending is not None and pending.study_redraws_used >= 8:
            missing.append("Study redraws used up (8/8)")
        reason = "; ".join(missing) or "no redraw source available"
        return {"available": False, "kind": None, "reason": reason}
    info: dict = {"available": True, "kind": kind.value}
    if kind is RedrawKind.FREE:
        info["free_left"] = pending.redraws_left
    elif kind is RedrawKind.STUDY:
        info["study_used"] = pending.study_redraws_used
        info["study_cap"] = 8
    return info


def _pending_dict(game: Game) -> dict | None:
    """JSON view of the pending draft hand; None when no draft is open.

    Hidden options (Darkroom's own doorway while its lights are off, or the
    one slot an active Archives archived) keep cost and affordability visible
    but report room_idx -1, name "???", and no identity/orientation fields;
    ``archived`` distinguishes the latter from a plain Darkroom conceal.
    Rarity leaks through when drafting via a security door, same as
    env/obs.py. ``redraw`` and each option's ``legal_orientations`` let the
    client show what a redraw would cost and whether a drafted room has an
    orientation other than the one it was dealt in -- see ``_redraw_info`` and
    ``_option_legal_orientations`` for why those need engine calls rather than
    being derivable from ``orientation`` alone. ``from_room`` is the name of
    the room the draft was opened from (None for the outer-room draft, whose
    ``from_cell`` is -1) -- the client needs this to label the draft panel by
    room rather than by bare grid coordinate (see env/actions.py::_room_name_at).
    """
    p = game.state.pending
    if p is None:
        return None
    # Outer-room drafts (from_cell == -1) have no doorway segment to check;
    # they are never hidden today anyway (open_outer_draft deals through its
    # own path, never through draft._fill_options, so neither Darkroom's
    # from-room check nor Archives' house-wide one ever runs against them),
    # but guard explicitly rather than rely on that staying true.
    security = (p.from_cell != -1
                and game.door_state_of(p.from_cell, p.direction) == DOOR_SECURITY)
    options = []
    for opt in p.options:
        room = game.registry.rooms[opt.room_idx]
        if opt.hidden:
            options.append({
                "slot": opt.slot, "room_idx": -1, "name": "???", "category": None,
                "rarity": room.rarity if security else None, "layout": None,
                "orientation": 0, "legal_orientations": [],
                "cost": game._effective_cost(room, opt),
                "affordable": game.affordable(room, opt),
                "forced": opt.forced, "hidden": True, "archived": opt.archived,
            })
            continue
        options.append({
            "slot": opt.slot, "room_idx": opt.room_idx, "name": room.name,
            "category": room.category, "rarity": room.rarity, "layout": room.layout,
            "orientation": opt.orientation,
            "legal_orientations": _option_legal_orientations(game, p, opt),
            "cost": game._effective_cost(room, opt),
            "affordable": game.affordable(room, opt),
            "forced": opt.forced, "hidden": False, "archived": False,
        })
    return {
        "from_cell": p.from_cell,
        "from_room": A._room_name_at(game, p.from_cell),
        "direction": DIR_NAMES.get(p.direction),
        "target_cell": p.target_cell,
        "options": options,
        "redraw": _redraw_info(game),
        "rotations_used": p.rotations_used,
    }


def _inventory_list(game: Game) -> list[dict]:
    """Held special items as ``[{id, name, count}, ...]``, sorted by name.

    Sourced from ``GameState.inventory`` (item id -> count, see
    engine/special_items.py) via the special-items registry for display
    names -- the raw dict only has ids, which is what the owner could not read
    off the old display. Items at count 0 are omitted rather than listed at
    zero, so an empty-handed player sees an empty list, not a wall of zeros.
    """
    st = game.state
    by_id = game.registry.special.by_id
    items = []
    for item_id, count in st.inventory.items():
        if count <= 0:
            continue
        item = by_id.get(item_id)
        items.append({"id": item_id, "name": item.name if item is not None else item_id,
                      "count": count})
    items.sort(key=lambda d: d["name"])
    return items


def _frame(game: Game, action: dict | None, facing: str | None,
           debug: bool = False) -> dict:
    """Snapshot the visible state as one replay frame.

    ``action`` describes the step that PRODUCED this state (None for the
    initial frame); ``facing`` is the client-side sprite direction.
    ``scepter_color`` is the Royal Scepter category bias active this episode
    (one of blueprint/green/red/bedroom/hallway/shop), or null when none.
    ``area`` is the area-graph node id the player is currently at, or null
    when the player is on the 5x9 grid (``pos`` is authoritative in that case).
    ``inventory`` is the held special items (see ``_inventory_list``); replay
    frames are rebuilt on demand from recorded actions and never stored, so
    adding this field costs no disk for existing recordings.
    """
    st = game.state
    return {
        "phase": game.phase.name,
        "grid": list(st.grid),
        "doors": list(st.placed_doors),
        "pos": st.pos,
        "area": st.area,
        # Today's drafted outer room id, or null before the outer draft.  Exactly
        # one exists per day, so the Observatory collapses the eight outer-room
        # anchors into a single slot named after this one.
        "outer_room": (game.drafted_outer_room.id
                       if game.drafted_outer_room is not None else None),
        "facing": facing,
        "resources": {
            "steps": st.steps, "gems": st.gems, "keys": st.keys,
            "coins": st.coins, "dice": st.dice, "luck": st.luck,
        },
        "inventory": _inventory_list(game),
        "deepest_rank": game.deepest_rank,
        "reason": game.termination_reason,
        "pending": _pending_dict(game),
        # Per-option counterfactual rewards, only when the caller asked: each
        # entry deep-copies the game, so computing it for every frame of every
        # run would be paid by viewers who never open the panel.
        "option_rewards": option_rewards(game) if debug else None,
        "action": action,
        "scepter_color": st.shops.scepter_color,
    }


# Config keys seen in replay records that no longer exist on GameConfig.  Populated
# by _apply_day_config so build_frames can flag the resulting divergence.
_STALE_DAY_CONFIG_KEYS: set[str] = set()


def _apply_day_config(base_cfg: GameConfig, day_config: dict) -> GameConfig:
    """Apply a serialized day_config diff onto base_cfg via dataclasses.replace.

    Lists are converted back to frozensets for fields whose type annotation
    contains ``frozenset`` (detected by inspecting dataclasses.fields).
    Other values pass through directly.

    Keys naming a config field that no longer exists are DROPPED rather than
    raising.  A record is a historical artifact: it was written against whatever
    GameConfig looked like at the time, and fields do get renamed and deleted.
    Passing an unknown key to dataclasses.replace raises TypeError instead,
    which would surface as a 500 and make the whole run un-viewable.  Dropping
    the key replays that day against the base value instead, which is a
    divergence, so the dropped names are returned for the caller to flag.
    """
    frozenset_fields = {
        f.name
        for f in dataclasses.fields(GameConfig)
        if "frozenset" in str(f.type)
    }
    valid = {f.name for f in dataclasses.fields(GameConfig)}
    kwargs = {}
    dropped = []
    for key, val in day_config.items():
        if key not in valid:
            dropped.append(key)
            continue
        if key in frozenset_fields and isinstance(val, list):
            kwargs[key] = frozenset(val)
        else:
            kwargs[key] = val
    if dropped:
        _STALE_DAY_CONFIG_KEYS.update(dropped)
    return dataclasses.replace(base_cfg, **kwargs)


def _current_n_actions() -> int:
    """The action-space size this build replays against."""
    from ..env import actions as A
    return A.N_ACTIONS


def option_rewards(game: Game) -> list[dict] | None:
    """What each option of the open hand would score if it were taken.

    For every dealt option, copies the game, applies ``choose(slot)`` to the
    copy and scores the resulting step with the ``shaped`` reward, alongside
    the diagnostics that usually explain the number: the ways forward the
    placement opens, the surviving routes to the Antechamber, and whether the
    Antechamber is still walkable at all.

    A copy per option, so nothing here can disturb the replay being rendered.
    Returns None when no hand is open. Only ``shaped`` is scored: it is what
    every run to date trains against, and offering three modes would invite
    reading a number the policy was never shown.

    This answers "why did it take THAT room" directly. On seed 1139797120 the
    hand at move 37 scored Bedroom +0.009 against Utility Closet -1.001, so
    the reward was unambiguous and the choice was the policy's, not the
    reward's -- a distinction no amount of staring at the board can settle.
    """
    pending = game.state.pending
    if pending is None:
        return None
    prev = rewards.snapshot(game)
    out: list[dict] = []
    for opt in pending.options:
        sim = copy.deepcopy(game)
        try:
            sim.choose(opt.slot)
        except Exception:
            # An option the engine refuses (unaffordable, illegal placement)
            # has no counterfactual reward; say so rather than invent one.
            out.append({"slot": opt.slot, "reward": None, "error": True})
            continue
        out.append({
            "slot": opt.slot,
            "reward": rewards.shaped(sim, prev, terminated=False),
            "open_ways": rewards._open_ways(sim, pending.target_cell),
            "ante_paths": rewards._ante_paths(sim),
            "ante_reachable": sim.distance_map()[ANTECHAMBER_CELL] >= 0,
            "deepest_rank": sim.deepest_rank,
            "error": False,
        })
    return out


def build_frames(record: dict, debug: bool = False) -> tuple[list[dict], dict | None]:
    """Frame 0 is the post-reset state; frame i+1 follows ``actions[i]``.

    Returns ``(frames, divergence)`` where ``divergence`` is ``None`` when the
    replay matched the recorded actions exactly AND (when the record carries
    one) the recorded ``config_digest`` matches the reconstructed config, or
    a dict with keys:
      - ``"first_invalid_index"``: index of the first action that could not be
        applied (was not in the action mask at that step), or ``None`` if
        every recorded action stayed legal.
      - ``"invalid_count"``: total number of such actions across the episode.
      - ``"config_digest_mismatch"``: ``True`` when the record carries a
        ``config_digest`` that doesn't match ``config.config_digest`` of the
        reconstructed config. Advisory only (this function never raises on
        it, unlike ``rl.behavioral_cloning.config_for_record``): a record
        with no ``config_digest`` (predates the field) is treated as absent,
        not mismatched, so legacy records replay exactly as before. A
        mismatch can occur even with zero invalid actions -- replaying under
        the wrong config usually completes without any action becoming
        illegal, so this is often the ONLY signal a replay diverged.
    A divergence means the replayed house may be wrong (incomplete, in the
    invalid-action case, or exact-but-under-the-wrong-config in the digest
    case) and the frames should be rendered with a warning.

    Records carrying ``"day_config"`` (multi-day mode) are replayed with the
    day's exact GameConfig; records without it (single-day or legacy) use the
    base all_unlocks_config, which may diverge when per-day state differs.
    """
    from ..env.blueprince_env import BluePrinceEnv

    _STALE_DAY_CONFIG_KEYS.clear()  # per-record, not cumulative
    from ..rl.train import all_unlocks_config, fresh_save_config

    # ``day_config`` is a diff against the DayChain's base config, so it only
    # reconstructs correctly when replayed onto that same base.  Both producers
    # stamp which preset they used in ``"unlocks"``: the trainer's
    # ``--unlocks {all,none}`` (rl/train.py::make_single_env) and the play UI's
    # preset selector (web/play.py).  Records without the field predate it and
    # default to all-unlocks, which is what the trainer's default produced.
    #
    # A record without the field, replayed onto the wrong base, silently
    # diverges at the first action whose legality differs from what was
    # recorded.
    reward = record.get("reward", "shaped")
    unlocks = record.get("unlocks", "all")
    base_cfg = fresh_save_config(reward) if unlocks in ("none", "fresh") \
        else all_unlocks_config(reward)
    day_config = record.get("day_config")
    cfg = _apply_day_config(base_cfg, day_config) if day_config is not None else base_cfg

    env = BluePrinceEnv(cfg=cfg)
    env.reset(seed=record["seed"])
    facing = "N"
    frames = [_frame(env.game, None, facing, debug)]
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
        # Out of range counts as invalid, not IndexError.  A record is only
        # replayable against the action space it was written for, and a viewer
        # must degrade rather than 500 on a historical or corrupted record.
        out_of_range = not (0 <= action < len(mask))
        action_invalid = out_of_range or not mask[action]
        if action_invalid:
            invalid_count += 1
            if first_invalid is None:
                first_invalid = i
        if out_of_range:
            # The record names an action this build does not have, so it was
            # written against a different action space and nothing after this
            # point can be reconstructed.  Stop rather than hand the id to
            # env.step, which indexes the mask with it and raises IndexError.
            invalid_count += len(record["actions"]) - i - 1
            break

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
            facing, debug)
        if action_invalid:
            frame["invalid"] = True
        frames.append(frame)
        if term or trunc:
            break

    stale_keys = set(_STALE_DAY_CONFIG_KEYS)
    # Advisory-only digest check: never raises (unlike
    # rl.behavioral_cloning.config_for_record), since an unviewable replay
    # would turn a legacy/tampered record into a 500 in this UI. A missing
    # recorded digest (predates the field) is treated as absent, not
    # mismatched, so existing records with no config_digest keep replaying
    # exactly as before.
    recorded_digest = record.get("config_digest")
    digest_mismatch = (recorded_digest is not None
                        and recorded_digest != config_digest(cfg))
    divergence = None
    if first_invalid is not None or digest_mismatch:
        divergence = {
            "first_invalid_index": first_invalid,
            "invalid_count": invalid_count,
            # A legacy record (no day_config) has a known cause: its per-day
            # starting conditions were never written down.  A record that DOES
            # carry day_config but still diverges is a real, unexplained bug —
            # the UI must not misattribute it to the legacy format.
            "legacy_record": day_config is None,
            # Action ids are positional, so a record written against a different
            # action space replays as nonsense.  Comparing recorded_n_actions
            # against current_n_actions lets the UI attribute a divergence to an
            # action-space mismatch instead of surfacing it as unexplained.  None
            # means the record predates this stamp, which is itself evidence it
            # was written against an older action space.
            "recorded_n_actions": record.get("n_actions"),
            "current_n_actions": _current_n_actions(),
            # Config keys in the record that no longer exist on GameConfig; the
            # day was replayed against base values for those, so it can diverge.
            "stale_config_keys": sorted(stale_keys),
            # True when the record's stamped config_digest doesn't match the
            # reconstructed config's -- see this function's docstring. Can be
            # the ONLY signal of a divergence: replaying under the wrong
            # config usually leaves every recorded action legal.
            "config_digest_mismatch": digest_mismatch,
        }
    return frames, divergence
