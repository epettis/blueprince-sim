"""Checkpoint resolution for `blueprince-train --evaluate [--model PATH]`."""

from pathlib import Path

from blueprince_sim.engine.model import Registry
from blueprince_sim.rl.train import (
    all_studio_additions,
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
