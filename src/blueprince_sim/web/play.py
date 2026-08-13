"""Human-play session: drives BluePrinceEnv the same way the trainer does.

A session lets a person play blueprince-sim by hand through the web UI while
every action is recorded through the exact entry points MaskablePPO uses
(``action_masks()`` / ``step()``), never by touching ``Game`` directly. That is
what makes a saved session a legitimate behavioural-cloning demonstration: it
is provably something the trainer's action space could have produced.

The record shape written by :meth:`PlaySession.save` matches
``rl.train.EpisodeRecorder.on_episode_end`` field-for-field (see that
docstring) so a saved demo replays through ``replay.build_frames`` with no
special-casing, and loads in the Runs tab like any other recorded episode.
Two deliberate differences from the trainer's records: ``why`` is always
``"human"`` (not ``"random"``/``"top_window"``), and ``modes`` is all ``"1"``
(exploit) because a human is never exploring in the PPO resampled-policy
sense -- every action here is the one the player deliberately picked.

HTTP routing lives in ``server.py``; this module is pure session/game-loop
logic so it can be exercised directly in tests without spinning up a server.
"""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

from ..config import GameConfig
from ..engine.game import Game, Phase
from ..engine.grid import DIR_NAMES, N_CELLS
from ..engine.locks import DOOR_LOCKED, DOOR_OPEN, DOOR_SEALED, DOOR_SECURITY
from ..env import actions as A
from ..env.blueprince_env import BluePrinceEnv
from ..env.multiday import DayChain
from ..rl.train import all_unlocks_config, fresh_save_config
from .replay import _frame

# Lock-state id -> label, for the debug door-lock overlay.
_DOOR_STATE_NAMES: dict[int, str] = {
    DOOR_OPEN: "open",
    DOOR_LOCKED: "locked",
    DOOR_SECURITY: "security",
    DOOR_SEALED: "sealed",
}


class IllegalActionError(ValueError):
    """Raised by :meth:`PlaySession.act` when ``action_id`` is not in the live mask.

    Carries the id so the HTTP layer can report exactly what was rejected
    without re-parsing the message text.
    """

    def __init__(self, action_id: int) -> None:
        super().__init__(f"action {action_id} is not legal in the current state")
        self.action_id = action_id


def action_group(action_id: int) -> str:
    """Classify a flat action id into one of the UI's grouping buckets.

    Mirrors the ``*_BASE`` boundaries declared in ``env/actions.py`` exactly
    (see its module docstring for the authoritative layout), so every id in
    ``0..N_ACTIONS-1`` lands in a named bucket rather than falling through.
    """
    if action_id < A.CHOOSE_BASE:
        return "draft"
    if action_id < A.REDRAW_ACTION:
        return "choose"
    if action_id == A.REDRAW_ACTION:
        return "control"
    if action_id == A.OUTER_DRAFT_ACTION:
        return "draft"
    if action_id == A.TOGGLE_POWER_ACTION:
        return "control"
    if A.SET_LEVEL_BASE <= action_id < A.SET_LEVEL_BASE + 3:
        return "control"
    if action_id == A.ROTATE_ACTION:
        return "control"
    if A.MOVE_TO_BASE <= action_id < A.BUY_BASE:
        return "move"
    if A.BUY_BASE <= action_id < A.TRADE_BASE:
        return "buy"
    if A.TRADE_BASE <= action_id < A.FABRICATE_BASE:
        return "trade"
    if A.FABRICATE_BASE <= action_id < A.SCEPTER_BASE:
        return "fabricate"
    if A.SCEPTER_BASE <= action_id < A.SMASH_VASE_ACTION:
        return "use"
    if action_id in (A.SMASH_VASE_ACTION, A.OPEN_CONTAINER_ACTION, A.OPEN_CAR_TRUNK_ACTION,
                      A.OPEN_VAULT_BOX_ACTION, A.LIGHT_ACTION, A.INSTALL_LEVER_ACTION,
                      A.INSERT_DISK_ACTION):
        return "use"
    if A.CHOOSE_UPGRADE_BASE <= action_id < A.TRAVEL_BASE:
        return "choose"
    if A.TRAVEL_BASE <= action_id < A.OPEN_SIGIL_DOOR_BASE:
        return "travel"
    if A.OPEN_SIGIL_DOOR_BASE <= action_id <= A.START_SETUP_ACTION:
        return "use"
    if A.EXP_TRIGGER_BASE <= action_id < A.TOGGLE_EXPERIMENT_ACTION:
        return "choose"
    if action_id == A.TOGGLE_EXPERIMENT_ACTION:
        return "control"
    if action_id == A.TOGGLE_DARKROOM_ACTION:
        return "control"
    if A.CHOOSE_COLOUR_BASE <= action_id < A.DONATE_BASE:
        return "choose"
    if A.DONATE_BASE <= action_id < A.TAKE_BACK_OFFERING_ACTION:
        return "buy"
    if action_id == A.TAKE_BACK_OFFERING_ACTION:
        return "use"
    if action_id == A.BERRY_PICK_ACTION:
        return "choose"
    if action_id == A.TAKE_GROTTO_CHIP_ACTION:
        return "use"
    return "other"


def _build_cfg(unlocks: str, reward: str) -> GameConfig:
    """The two owner-approved presets: ``"all"`` unlocks or a ``"fresh"`` save."""
    return fresh_save_config(reward) if unlocks == "fresh" else all_unlocks_config(reward)


def _walk_facing(game: Game, action_id: int) -> str | None:
    """Sprite-facing direction a MOVE_TO action would end walking, or None.

    Must be computed BEFORE the action is applied (the path is a function of
    the player's current position), mirroring ``replay.build_frames``'s
    pre-step facing computation exactly so live play and replay agree.
    """
    if not (A.MOVE_TO_BASE <= action_id < A.MOVE_TO_BASE + N_CELLS):
        return None
    path = game._path_dirs(action_id - A.MOVE_TO_BASE)
    if not path:
        return None
    return DIR_NAMES[path[-1]]


def _debug_info(game: Game) -> dict:
    """Overlay data the trained agent's observation does NOT encode directly.

    ``optimistic_distances``/``open_path_count``/``door_locks`` are all
    engine-internal signals (used for the shaped reward's potential and the
    action mask) that env/obs.py never puts in the trained observation, so
    they must stay opt-in behind the UI's debug toggle rather than quietly
    becoming part of what "observation parity" means by default.
    """
    opt_dist = None if game.off_grid else list(game.optimistic_distances())
    door_locks: dict[int, dict[str, str]] = {}
    for cell, mask in enumerate(game.state.placed_doors):
        if mask == 0:
            continue
        segs = {}
        for d, name in DIR_NAMES.items():
            if mask & d:
                segs[name] = _DOOR_STATE_NAMES.get(game.door_state_of(cell, d), "open")
        if segs:
            door_locks[cell] = segs
    return {
        "optimistic_distances": opt_dist,
        "open_path_count": len(game.frontier_doorways()),
        "door_locks": door_locks,
    }


class PlaySession:
    """One human-played multi-day attempt, recorded action by action.

    Drives ``BluePrinceEnv`` (never ``Game`` directly) through
    ``action_masks()`` and ``step()`` -- see the module docstring. All
    mutating methods take ``self.lock`` since the server is a
    ``ThreadingHTTPServer`` and requests can arrive concurrently.
    """

    def __init__(self, seed: int | None, n_days: int, reward: str, unlocks: str) -> None:
        self.lock = threading.RLock()
        self.seed = seed if seed is not None else random.randrange(2**31)
        self.n_days = n_days
        self.reward = reward
        self.unlocks = unlocks
        self.cfg = _build_cfg(unlocks, reward)
        self.chain = DayChain(self.cfg, n_days=n_days)
        self.env = BluePrinceEnv(cfg=self.cfg, day_chain=self.chain)
        self.actions: list[int] = []           # current (in-progress) day's action ids
        self.facing: str = "N"
        self.day_reward: float = 0.0           # cumulative reward this day
        self.last_action: dict | None = None   # {"index","action","text","explore"} for the frame
        self.day_records: list[dict] = []      # completed EpisodeRecorder-shaped records
        self.attempt_over: bool = False
        self._saved_upto: int = 0              # day_records[:_saved_upto] already on disk
        _, info = self.env.reset(seed=self.seed)
        self._episode_seed: int = info["episode_seed"]

    # ------------------------------------------------------------- reads

    def state(self) -> dict:
        """Frame + legal actions + progress, everything the client needs to render."""
        with self.lock:
            mask = self.env.action_masks()
            legal = [
                {"id": i, "label": A.describe_action(self.env.game, i), "group": action_group(i)}
                for i, ok in enumerate(mask) if ok
            ]
            day = self.env.game.state.day
            frame = _frame(self.env.game, self.last_action, self.facing)
            return {
                "frame": frame,
                "legal_actions": legal,
                "day": day,
                "n_days": self.n_days,
                "days_remaining": max(self.n_days - day + 1, 0),
                "day_over": self.env.game.phase is Phase.TERMINAL,
                "attempt_over": self.attempt_over,
                "reward": self.day_reward,
                "n_actions_today": len(self.actions),
                "completed_days": len(self.day_records),
                "seed": self.seed,
                "episode_seed": self._episode_seed,
                "n_actions": A.N_ACTIONS,
                "reward_kind": self.reward,
                "unlocks": self.unlocks,
                "debug": _debug_info(self.env.game),
            }

    # ------------------------------------------------------------ mutate

    def act(self, action_id: int) -> dict:
        """Apply one action after re-validating it against the LIVE mask.

        Client-side filtering is not enough: a stale page must never be able
        to record an action the mask would not currently offer, so this
        re-checks ``env.action_masks()`` unconditionally before touching
        anything, and raises :class:`IllegalActionError` (-> HTTP 400) rather
        than silently no-op-ing.
        """
        with self.lock:
            if self.attempt_over:
                raise IllegalActionError(action_id)
            mask = self.env.action_masks()
            if not (0 <= action_id < len(mask)) or not mask[action_id]:
                raise IllegalActionError(action_id)
            text = A.describe_action(self.env.game, action_id)
            walk_facing = _walk_facing(self.env.game, action_id)
            _, reward, terminated, truncated, info = self.env.step(action_id)
            self.actions.append(action_id)
            self.day_reward += reward
            if walk_facing is not None:
                self.facing = walk_facing
            pending = self.env.game.state.pending
            if pending is not None:
                self.facing = DIR_NAMES.get(pending.direction, self.facing)
            self.last_action = {"index": len(self.actions) - 1, "action": action_id,
                                 "text": text, "explore": False}
            if terminated or truncated:
                self._close_day(info, attempt_final=terminated)
            return self.state()

    def _close_day(self, info: dict, attempt_final: bool) -> None:
        """Append the just-finished day as an EpisodeRecorder-shaped record.

        Caller holds the lock. ``attempt_final`` marks the chain's true
        terminal (the ``n_days``-th day ending); a mid-attempt day end is a
        truncation the env reports so bootstrapping works during training --
        for us it just means "advance to tomorrow", not "stop recording".
        """
        episode = len(self.day_records) + 1
        record = {
            "episode": episode,
            "seed": int(self._episode_seed),
            "reward": self.reward,
            "actions": list(self.actions),
            # A human is never "exploring" in the PPO resampled-policy sense:
            # every recorded action is the one the player deliberately chose.
            "modes": "1" * len(self.actions),
            # game.state.room46_reached is the authoritative win flag
            # (Game.success()); read directly off the engine rather than
            # through info, which does not carry this key at top level.
            "win": bool(self.env.game.state.room46_reached),
            "deepest_rank": int(info.get("deepest_rank", 0)),
            "rooms_placed": int(info.get("rooms_placed", 0)),
            "reason": info.get("termination_reason"),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # Action ids are positional; stamping the action-space size lets a
            # loader refuse a demo recorded against a different space loudly
            # instead of replaying it as nonsense.
            "n_actions": A.N_ACTIONS,
            "why": "human",
            # day_config is a DIFF, so it only reconstructs against the same
            # base it was computed from. Stamping which preset that was is what
            # lets replay.build_frames rebuild the right one; without it a
            # fresh-save record silently replays onto the all-unlocks base and
            # drifts.
            "unlocks": self.unlocks,
            # Digest of the exact GameConfig this day ran under (see
            # config.config_digest / BluePrinceEnv._episode_config_digest).
            # bc.config_for_record raises if a reconstructed replay's digest
            # doesn't match this -- catches a wrong unlocks/day_config
            # reconstruction at step 0 instead of a silently wrong replay.
            "config_digest": info["config_digest"],
        }
        # A PlaySession always drives a DayChain, so info["day_config"] is
        # always present (see BluePrinceEnv._info) -- unlike the trainer's
        # single-day mode, there is no legacy no-chain case to omit it for.
        day_config = info.get("day_config")
        if day_config is not None:
            record["day_config"] = day_config
        self.day_records.append(record)
        self.attempt_over = attempt_final
        self.actions = []
        self.day_reward = 0.0
        self.last_action = None
        if not attempt_final:
            _, reset_info = self.env.reset()
            self._episode_seed = reset_info["episode_seed"]
            self.facing = "N"

    def undo(self) -> dict:
        """Undo the last action of the CURRENT (in-progress) day only.

        A day boundary already closed a record and started the next day's
        Game; that Game no longer exists once its record is written, so undo
        never reopens a finished day. Returns the refreshed state with
        ``"undone": True``, or ``"undone": False`` plus a ``"message"`` when
        there is nothing to undo (no actions yet this day, or the attempt is
        already over).
        """
        with self.lock:
            if self.attempt_over:
                result = self.state()
                result["undone"] = False
                result["message"] = "attempt is over; nothing to undo"
                return result
            if not self.actions:
                result = self.state()
                result["undone"] = False
                result["message"] = "no actions recorded yet this day"
                return result
            self._rebuild(self.actions[:-1])
            result = self.state()
            result["undone"] = True
            return result

    def _rebuild(self, current_day_actions: list[int]) -> None:
        """Recreate the chain/env from ``self.seed`` and replay every action.

        Exact rather than a snapshot/restore: seeded determinism is a tested
        engine invariant, so replaying every completed day's full action list
        (unchanged) plus the truncated current-day list reproduces the
        identical state, and is far simpler than trying to snapshot engine
        state directly.
        """
        self.chain = DayChain(self.cfg, n_days=self.n_days)
        self.env = BluePrinceEnv(cfg=self.cfg, day_chain=self.chain)
        _, info = self.env.reset(seed=self.seed)
        for rec in self.day_records:
            for a in rec["actions"]:
                self.env.step(a)
            _, info = self.env.reset()
        self._episode_seed = info["episode_seed"]
        self.day_reward = 0.0
        self.facing = "N"
        self.last_action = None
        for idx, a in enumerate(current_day_actions):
            text = A.describe_action(self.env.game, a)
            walk_facing = _walk_facing(self.env.game, a)
            _, reward, _terminated, _truncated, _info = self.env.step(a)
            self.day_reward += reward
            if walk_facing is not None:
                self.facing = walk_facing
            pending = self.env.game.state.pending
            if pending is not None:
                self.facing = DIR_NAMES.get(pending.direction, self.facing)
            self.last_action = {"index": idx, "action": a, "text": text, "explore": False}
        self.actions = list(current_day_actions)

    def save(self, path: Path) -> int:
        """Append newly-completed day records to ``path`` as JSON lines.

        Idempotent across repeated calls: only records added since the
        previous ``save()`` are written. Returns the count written by THIS
        call (0 if nothing new).
        """
        with self.lock:
            pending = self.day_records[self._saved_upto:]
            if not pending:
                return 0
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                for rec in pending:
                    f.write(json.dumps(rec) + "\n")
            self._saved_upto = len(self.day_records)
            return len(pending)
