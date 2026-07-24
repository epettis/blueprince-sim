"""Checkpoint resolution for `blueprince-train --evaluate [--model PATH]`."""

from pathlib import Path

from blueprince_sim.rl.train import resolve_eval_checkpoint


def test_defaults_to_latest_zip_in_checkpoint_dir():
    """Without --model, evaluation loads <checkpoint-dir>/latest.zip."""
    assert resolve_eval_checkpoint(Path("runs/all-unlocks"), None) == \
        Path("runs/all-unlocks/latest.zip")


def test_explicit_model_path_wins():
    """An explicit --model path overrides the checkpoint-dir default, so
    released models can be evaluated directly."""
    model = Path("models/baseline-ep8275991/model.zip")
    assert resolve_eval_checkpoint(Path("runs/all-unlocks"), model) == model
