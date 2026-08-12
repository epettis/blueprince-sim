"""Behavioural-cloning warm start built from recorded demo days.

MaskablePPO (sb3-contrib) has no native behavioural cloning; this module adds
it as a supervised pretraining pass over the *same* policy network that
``rl/train.py`` hands to ``model.learn()``, so warm-started weights need no
save/load round trip through a mismatched policy class (see the
``MixedExplorationPolicy`` trap documented in ``rl/train.py``'s resume path).

**Demo records carry actions only, never observations** (see
``web/play.py::PlaySession._close_day`` and ``rl/train.py::EpisodeRecorder``,
which write byte-identical JSONL schemas): one JSON line per completed day
with ``seed``, ``actions`` (the flat env action ids, in order), ``n_actions``
(the action-space size at record time), ``unlocks`` (which ``GameConfig``
preset the day's ``day_config`` diffs against), and an optional
``day_config`` diff for multi-day records. Turning that into training data
means *replaying* each demo through a real ``BluePrinceEnv`` — exactly what
``web/play.py::PlaySession._rebuild`` and ``web/replay.py::build_frames`` do —
to regenerate the ``(observation, action, action_mask)`` triples the network
never saw at record time. Engine determinism given a seed is a tested
invariant, so replay is exact rather than a lossy reconstruction.

Two independent halves, split so the loader/replay/collate path stays
importable and testable without the ``.[rl]`` extra:

- **Loading & replay** (this module's top half): pure stdlib + numpy +
  gymnasium, same as the rest of ``env/``. No torch import at module scope.
- **Pretraining** (``pretrain`` / ``masked_accuracy``): torch + sb3-contrib,
  imported lazily inside the functions that need them.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

from ..config import GameConfig
from ..engine.game import Phase


class DemoError(ValueError):
    """Base class for demo-loading/replay failures."""


class StaleDemoError(DemoError):
    """A demo record's ``n_actions`` doesn't match the current action space.

    Action ids are positional (see ``env/actions.py``'s layout comment), so a
    record written against a different action space cannot be replayed at
    all -- the same integer names a different action now.  Raised loudly
    rather than silently replayed as nonsense, per the ``n_actions`` field's
    documented purpose in ``web/play.py``.
    """


class MixedPresetError(DemoError):
    """A demo set mixes ``unlocks`` presets without an explicit filter.

    ``day_config`` is a diff against whichever preset (``all_unlocks_config``
    or ``fresh_save_config``) produced it; replaying a fresh-save diff onto
    the all-unlocks base (or vice versa) silently drifts (this is exactly the
    bug ``web/replay.py::build_frames`` documents and stamps ``unlocks`` to
    avoid). A general-purpose load with no explicit ``unlocks`` filter must
    not guess, so a mixed set is rejected rather than arbitrarily picking one.
    """


class ReplayDivergenceError(DemoError):
    """A recorded action was not legal when replayed.

    Both known producers (``PlaySession.act`` and the trainer's
    ``EpisodeRecorder``, fed from ``env.action_masks()``/``env.step()``) only
    ever record actions that were legal in the live mask at record time, so a
    divergence on replay means the reconstructed ``GameConfig`` doesn't match
    what produced the recording (wrong ``unlocks``/``day_config``), not that
    the demo itself is corrupt busywork to silently paper over.
    """


def normalize_unlocks(unlocks: str) -> str:
    """Canonicalize a record/CLI ``unlocks`` value to ``"fresh"`` or ``"all"``.

    Two different producers spell "fresh save" differently: the trainer's
    ``--unlocks`` flag uses ``"none"`` (``rl/train.py::make_single_env``)
    while the Play tab's preset selector uses ``"fresh"``
    (``web/play.py::_build_cfg``). ``web/replay.py::build_frames`` already
    treats both as equivalent (``unlocks in ("none", "fresh")``); mirrored
    here so a demo set combining both spellings isn't wrongly flagged as
    mixing presets.
    """
    return "fresh" if unlocks in ("none", "fresh") else "all"


def _iter_jsonl_records(paths: Iterable[str | Path]) -> Iterator[tuple[Path, int, dict]]:
    """Yield ``(file, line_no, record)`` for every non-blank line under ``paths``.

    Each path may be a ``.jsonl`` file or a directory (expanded to its sorted
    ``*.jsonl`` children, for a demos-per-session directory layout).
    """
    for raw in paths:
        p = Path(raw)
        files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
        for f in files:
            with f.open() as fh:
                for line_no, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield f, line_no, json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise DemoError(f"{f}:{line_no}: invalid JSON in demo file") from exc


def load_demo_dataset(paths: Iterable[str | Path], n_actions: int,
                       unlocks: str | None = None) -> list[dict]:
    """Load and validate demo records from ``paths`` (files and/or directories).

    Every record's ``n_actions`` must equal the current action space's size
    (``env.actions.N_ACTIONS``, passed in by the caller so this module never
    imports it as a hidden default) -- a mismatch raises :class:`StaleDemoError`
    immediately rather than continuing with a partially-loaded set, since a
    stale action space is a systemic problem, not a one-off bad line.

    ``unlocks``, if given (normalized via :func:`normalize_unlocks`), filters
    the set to matching records only, silently dropping the rest -- this is
    the caller (e.g. ``blueprince-train --unlocks``) deliberately picking the
    one preset its fresh PPO env will train under. If ``unlocks`` is omitted,
    every record in ``paths`` must share the same (normalized) preset, or
    :class:`MixedPresetError` is raised: with no explicit choice, silently
    training on a blend of two ``day_config`` bases would drift in ways that
    are hard to diagnose after the fact (see ``web/replay.py``'s docstring for
    the same class of failure).
    """
    wanted = normalize_unlocks(unlocks) if unlocks is not None else None
    records: list[dict] = []
    seen_presets: set[str] = set()
    for f, line_no, rec in _iter_jsonl_records(paths):
        rec_n = rec.get("n_actions")
        if rec_n != n_actions:
            raise StaleDemoError(
                f"{f}:{line_no}: demo (episode={rec.get('episode')}, "
                f"seed={rec.get('seed')}) was recorded with n_actions={rec_n!r}, "
                f"but the current action space has {n_actions} actions -- "
                "refusing to replay it as if the ids still meant the same thing")
        preset = normalize_unlocks(rec.get("unlocks", "all"))
        if wanted is not None and preset != wanted:
            continue
        seen_presets.add(preset)
        records.append(rec)
    if wanted is None and len(seen_presets) > 1:
        raise MixedPresetError(
            f"demo set under {list(paths)} mixes unlocks presets {sorted(seen_presets)}; "
            "pass unlocks='all' or unlocks='none' to load_demo_dataset to pick one "
            "explicitly (day_config only reconstructs against the preset it was "
            "diffed from)")
    return records


def _apply_day_config_diff(base_cfg: GameConfig, day_config: dict | None) -> GameConfig:
    """Apply a record's ``day_config`` diff onto ``base_cfg``.

    Deliberately independent of ``web/replay.py::_apply_day_config`` (same
    ~10-line ``dataclasses.replace`` technique) rather than importing it:
    ``web/`` is being edited concurrently by another agent this round, and
    this module has no other reason to depend on it. Unknown keys (a renamed
    or removed ``GameConfig`` field from an older record) are dropped rather
    than raised -- a demo is a historical artifact of whatever the config
    schema looked like when it was recorded, same rationale as replay.py.
    """
    if not day_config:
        return base_cfg
    frozenset_fields = {
        f.name for f in dataclasses.fields(GameConfig) if "frozenset" in str(f.type)
    }
    valid = {f.name for f in dataclasses.fields(GameConfig)}
    kwargs = {}
    for key, val in day_config.items():
        if key not in valid:
            continue
        kwargs[key] = frozenset(val) if key in frozenset_fields and isinstance(val, list) else val
    return dataclasses.replace(base_cfg, **kwargs)


def config_for_record(record: dict) -> GameConfig:
    """The exact ``GameConfig`` a demo record was played under.

    Selects ``all_unlocks_config``/``fresh_save_config`` (imported lazily to
    avoid a training-module import at load time) by the record's normalized
    ``unlocks``, using its own ``reward`` name (mirrors ``web/replay.py``'s
    per-record reconstruction), then layers ``day_config`` on top when present.
    """
    from .train import all_unlocks_config, fresh_save_config  # local: avoid import cycle noise

    reward = record.get("reward", "shaped")
    base_cfg = (fresh_save_config(reward) if normalize_unlocks(record.get("unlocks", "all")) == "fresh"
                else all_unlocks_config(reward))
    return _apply_day_config_diff(base_cfg, record.get("day_config"))


def replay_demo(record: dict) -> list[tuple[dict, int, np.ndarray]]:
    """Replay one demo record through a real ``BluePrinceEnv``.

    Returns the ``(observation, action, action_mask)`` triple recorded BEFORE
    each action was applied -- the observation and mask the human (or
    scripted policy) actually saw when they chose that action, which is
    exactly the supervision signal a BC loss needs. Follows the reconstruction
    order ``PlaySession._rebuild`` uses: build the config, ``reset(seed=...)``,
    then step through the full recorded action list.
    """
    from ..env.blueprince_env import BluePrinceEnv  # local: keeps env import out of load-only paths

    cfg = config_for_record(record)
    env = BluePrinceEnv(cfg=cfg)
    obs, _info = env.reset(seed=int(record["seed"]))
    triples: list[tuple[dict, int, np.ndarray]] = []
    for raw_action in record["actions"]:
        if env.game.phase is Phase.TERMINAL:
            break  # defensive: never replay past a terminal state
        action = int(raw_action)
        mask = env.action_masks()
        if not (0 <= action < len(mask)) or not mask[action]:
            raise ReplayDivergenceError(
                f"demo episode={record.get('episode')} seed={record.get('seed')}: "
                f"action {action} was not legal at this replayed step -- the "
                "reconstructed GameConfig (unlocks/day_config) likely doesn't "
                "match what actually produced this recording")
        triples.append((obs, action, mask))
        obs, _reward, _terminated, _truncated, _info = env.step(action)
    return triples


def replay_dataset(records: Iterable[dict]) -> list[tuple[dict, int, np.ndarray]]:
    """Replay every record and concatenate their ``(obs, action, mask)`` triples."""
    triples: list[tuple[dict, int, np.ndarray]] = []
    for record in records:
        triples.extend(replay_demo(record))
    return triples


def collate(triples: list[tuple[dict, int, np.ndarray]]
            ) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Stack a list of ``(obs, action, mask)`` triples into batched arrays.

    The observation space is a ``gymnasium.spaces.Dict``, so batching means
    stacking each key across the batch (matching what SB3's vec-env obs
    stacking produces) rather than flattening it by hand.
    """
    obs_list, actions, masks = zip(*triples)
    obs_batch = {k: np.stack([o[k] for o in obs_list]) for k in obs_list[0]}
    actions_arr = np.asarray(actions, dtype=np.int64)
    masks_arr = np.asarray(masks, dtype=bool)
    return obs_batch, actions_arr, masks_arr


def synthetic_demo_records(unlocks: str, reward: str, n_days: int, seed: int,
                            action_rng_seed: int = 0, use_chain: bool = True) -> list[dict]:
    """Generate ``n_days`` of demo records with a seeded uniform-random masked policy.

    Used to build BC fixtures without a human in the loop or checked-in
    binary data: no real demos.jsonl exists anywhere in the repo yet (the
    Play tab that records them shipped, but nobody has played and saved a
    session), so this is what develops and tests against until one does.
    Written in the exact schema ``PlaySession._close_day`` and
    ``EpisodeRecorder.on_episode_end`` produce (``why`` is ``"synthetic"``
    rather than ``"human"``/``"random"``/``"top_window"``, the one
    intentional difference).

    ``use_chain=False`` produces single-day records with no ``day_config``
    key (the trainer's non-multi-day mode); ``use_chain=True`` (default)
    drives a real ``DayChain`` so ``day_config`` is present, matching how the
    Play tab always records (every ``PlaySession`` drives a chain).
    """
    from ..env import actions as A
    from ..env.blueprince_env import BluePrinceEnv
    from ..env.multiday import DayChain
    from .train import all_unlocks_config, fresh_save_config

    norm = normalize_unlocks(unlocks)
    cfg = fresh_save_config(reward) if norm == "fresh" else all_unlocks_config(reward)
    chain = DayChain(cfg, n_days=n_days) if use_chain else None
    env = BluePrinceEnv(cfg=cfg, day_chain=chain)
    rng = np.random.default_rng(action_rng_seed)

    _, info = env.reset(seed=seed)
    episode_seed = int(info["episode_seed"])
    records: list[dict] = []
    actions_today: list[int] = []
    target_days = n_days if use_chain else 1
    days_done = 0
    while days_done < target_days:
        mask = env.action_masks()
        action = int(rng.choice(np.flatnonzero(mask)))
        _, _reward_val, terminated, truncated, info = env.step(action)
        actions_today.append(action)
        if terminated or truncated:
            days_done += 1
            record = {
                "episode": days_done,
                "seed": episode_seed,
                "reward": reward,
                "actions": list(actions_today),
                "modes": "1" * len(actions_today),
                "win": bool(env.game.state.room46_reached),
                "deepest_rank": int(info.get("deepest_rank", 0)),
                "rooms_placed": int(info.get("rooms_placed", 0)),
                "reason": info.get("termination_reason"),
                "saved_at": "1970-01-01T00:00:00",
                "n_actions": A.N_ACTIONS,
                "why": "synthetic",
                "unlocks": unlocks,
            }
            day_config = info.get("day_config")
            if day_config is not None:
                record["day_config"] = day_config
            records.append(record)
            actions_today = []
            if days_done < target_days:
                _, info = env.reset()
                episode_seed = int(info["episode_seed"])
    return records


# --------------------------------------------------------------------------
# Torch-dependent half: pretraining and evaluation. Imported lazily so this
# module (and the loader/replay path above) stays importable without the
# `.[rl]` extra -- mirrors how `rl/train.py` and `rl/mixed_policy.py` defer
# their own torch imports.
# --------------------------------------------------------------------------

def pretrain(policy, triples: list[tuple[dict, int, np.ndarray]], *,
             epochs: int, batch_size: int, lr: float, seed: int = 0,
             on_epoch=None) -> list[float]:
    """Masked cross-entropy pretraining of ``policy`` on replayed demo triples.

    Loss is ``-log_prob(demo_action)`` under the MASKED action distribution --
    ``policy.evaluate_actions(obs, actions, action_masks=...)`` is the exact
    method ``MaskablePPO.train()`` calls for its own PPO loss (see
    ``sb3_contrib.ppo_mask.ppo_mask.MaskablePPO.train``), so this reuses the
    same masking path the rollout objective uses rather than training the
    unmasked head and hoping PPO's own masking papers over the mismatch --
    an unmasked BC objective would push probability mass onto illegal actions
    that PPO never samples, wasting the pretraining on logits that are never
    read.

    Optimiser: Adam (SB3's own default for these policies -- see
    ``MaskableActorCriticPolicy.__init__``'s ``optimizer_class`` default),
    plain minibatch SGD-with-Adam over the flattened triple list, reshuffled
    every epoch. Epochs/batch size/learning rate are the caller's choice
    (exposed as ``blueprince-train --pretrain-epochs/--pretrain-batch-size/
    --pretrain-lr`` flags) rather than baked in here, since the right values
    depend entirely on how many demo days are available.

    Mutates ``policy`` in place (no return value beyond the loss curve) and
    leaves it in eval mode (``set_training_mode(False)``) on return, matching
    the state ``model.policy`` is expected to be in between ``model.learn()``
    calls.
    """
    import torch

    if not triples:
        raise ValueError("no demo (obs, action, mask) triples to pretrain on")
    rng = np.random.default_rng(seed)
    optimizer = torch.optim.Adam(policy.parameters(), lr=lr)
    policy.set_training_mode(True)
    n = len(triples)
    epoch_losses: list[float] = []
    for epoch in range(epochs):
        order = rng.permutation(n)
        batch_losses: list[float] = []
        for start in range(0, n, batch_size):
            batch = [triples[i] for i in order[start:start + batch_size]]
            obs_batch, actions, masks = collate(batch)
            obs_t, _ = policy.obs_to_tensor(obs_batch)
            actions_t = torch.as_tensor(actions, device=policy.device)
            # float32 0/1, matching MaskableRolloutBuffer's stored mask dtype.
            masks_t = torch.as_tensor(masks.astype(np.float32), device=policy.device)
            _, log_prob, _entropy = policy.evaluate_actions(obs_t, actions_t,
                                                              action_masks=masks_t)
            loss = -log_prob.mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            batch_losses.append(float(loss.item()))
        mean_loss = sum(batch_losses) / len(batch_losses)
        epoch_losses.append(mean_loss)
        if on_epoch is not None:
            on_epoch(epoch, mean_loss)
    policy.set_training_mode(False)
    return epoch_losses


def masked_accuracy(policy, triples: list[tuple[dict, int, np.ndarray]],
                     batch_size: int = 512) -> float:
    """Fraction of triples where the masked argmax action matches the demo action.

    A simple, human-readable companion to the BC loss: "if the agent always
    played its most-confident legal action, how often would it agree with
    the human/scripted demonstrator." Evaluation-mode only (no gradient).
    """
    import torch

    if not triples:
        return 0.0
    policy.set_training_mode(False)
    correct = 0
    with torch.no_grad():
        for start in range(0, len(triples), batch_size):
            batch = triples[start:start + batch_size]
            obs_batch, actions, masks = collate(batch)
            obs_t, _ = policy.obs_to_tensor(obs_batch)
            masks_t = torch.as_tensor(masks, device=policy.device)
            dist = policy.get_distribution(obs_t, action_masks=masks_t)
            pred = dist.distribution.probs.argmax(dim=1).cpu().numpy()
            correct += int((pred == actions).sum())
    return correct / len(triples)
