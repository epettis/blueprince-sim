"""Checkpoint resolution for `blueprince-train --evaluate [--model PATH]`."""

from pathlib import Path

from blueprince_sim.engine.model import Registry
from blueprince_sim.env.multiday import _CARRYOVER_KEYS
from blueprince_sim.rl.train import (
    all_studio_additions,
    all_unlocks_config,
    _STUDIO_ADDITION_EXCLUSIONS,
    resolve_eval_checkpoint,
)


def test_defaults_to_latest_zip_in_checkpoint_dir():
    """Without --model, evaluation loads <checkpoint-dir>/latest.zip."""
    assert resolve_eval_checkpoint(Path("runs/all-unlocks"), None) == \
        Path("runs/all-unlocks/latest.zip")


def test_explicit_model_path_wins():
    """An explicit --model path overrides the checkpoint-dir default, so
    released models can be evaluated directly."""
    model = Path("models/baseline-ep8275991/model.zip")
    assert resolve_eval_checkpoint(Path("runs/all-unlocks"), model) == model


def test_studio_additions_all_accounted_for():
    """Every studio_addition room is either in all_studio_additions() or in the
    documented exclusion set; no room can be silently omitted.

    This pins the derivation relationship rather than a literal count, so a
    newly-added room in rooms.json is caught immediately by CI rather than
    quietly dropped from training.  To add a new room: implement its behaviour,
    then remove it from _STUDIO_ADDITION_EXCLUSIONS.
    """
    registry = Registry.load()
    all_in_data = frozenset(r.id for r in registry.rooms if r.pool == "studio_addition")
    accounted_for = all_studio_additions() | _STUDIO_ADDITION_EXCLUSIONS
    unaccounted = all_in_data - accounted_for
    assert not unaccounted, (
        f"studio_addition rooms not in all_studio_additions() or exclusion set: {unaccounted!r}. "
        "Implement the room's behaviour, or add it to "
        "_STUDIO_ADDITION_EXCLUSIONS (if unimplemented) with a reason comment."
    )


def test_all_unlocks_config_sets_every_carryover_key():
    """all_unlocks_config() enables every unlock regardless of its GameConfig
    default: no member of env/multiday.py::_CARRYOVER_KEYS (the permanent,
    earned-in-play carry flags) may be left False.

    This pins the agreement between the two modules rather than a literal
    flag list, so a flag added to _CARRYOVER_KEYS and forgotten in
    all_unlocks_config() fails here immediately instead of silently shipping
    an incomplete training baseline.
    """
    cfg = all_unlocks_config()
    unset = sorted(k for k in _CARRYOVER_KEYS if not getattr(cfg, k))
    assert not unset, (
        f"all_unlocks_config() leaves these _CARRYOVER_KEYS flags False: {unset!r}. "
        "Set each explicitly True in all_unlocks_config() with a comment "
        "naming what it unlocks."
    )


def test_all_unlocks_config_sets_both_grotto_conjuncts():
    """all_unlocks_config() promises 'every permanent unlock', but the
    Blackbridge Grotto's two conjuncts are SAVE-scoped carve-outs carried on
    named DayChain attributes rather than members of _CARRYOVER_KEYS, so the
    test above cannot see them -- which is how lab_powered came to be missing
    while lab_visited was set. Each conjunct is judged on its own, so setting
    one alone still leaves the edge shut.

    This names the two flags instead of deriving them. The obvious general
    rule -- every GameConfig bool that DayChain mirrors outside
    _CARRYOVER_KEYS -- also catches sauna_bonus, morning_room_bonus and
    no_contact_due, which are per-day state that all-unlocks must NOT force
    true, so a derived assertion would encode something false.
    """
    cfg = all_unlocks_config()
    unset = [k for k in ("lab_visited", "lab_powered") if not getattr(cfg, k)]
    assert not unset, (
        f"all_unlocks_config() leaves these Grotto conjuncts False: {unset!r}. "
        "Both are needed: the edge stays shut while either is unset."
    )
