"""Checkpoint resolution for `blueprince-train --evaluate [--model PATH]`."""

from pathlib import Path

from blueprince_sim.engine.model import Registry
from blueprince_sim.env.multiday import _CARRYOVER_KEYS
from blueprince_sim.rl.train import (
    all_found_floorplans,
    all_studio_additions,
    all_unlocks_config,
    _FOUND_FLOORPLAN_EXCLUSIONS,
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


def test_found_floorplans_all_accounted_for():
    """Every found_floorplan room is either in all_found_floorplans() or in the
    documented exclusion set; no room can be silently omitted.

    The found_floorplan counterpart of test_studio_additions_all_accounted_for,
    pinning the same derivation relationship for the second unlockable pool so
    that a room moved between the two pools cannot fall through the gap between
    the two allowlists and land in training unnoticed.
    """
    registry = Registry.load()
    all_in_data = frozenset(r.id for r in registry.rooms if r.pool == "found_floorplan")
    accounted_for = all_found_floorplans() | _FOUND_FLOORPLAN_EXCLUSIONS
    unaccounted = all_in_data - accounted_for
    assert not unaccounted, (
        f"found_floorplan rooms not in all_found_floorplans() or exclusion set: {unaccounted!r}. "
        "Implement the room's behaviour, or add it to "
        "_FOUND_FLOORPLAN_EXCLUSIONS (if unimplemented) with a reason comment."
    )


def test_unmodelled_found_floorplans_never_reach_the_training_pool():
    """Treasure Trove and Closed Exhibit are not draftable under
    all_unlocks_config(), because neither room's reward is modelled.

    Named as literals rather than read from _FOUND_FLOORPLAN_EXCLUSIONS: a test
    phrased against that set passes vacuously the moment an id is deleted from
    it, which is the exact regression worth catching. Promoting a room means
    implementing its behaviour and then deleting its line here, deliberately.

    The outcome is asserted, not the mechanism, because the two rooms are held
    out by different guards and both must hold. Withholding an id from
    cfg.found_floorplans is enough for Closed Exhibit, but Treasure Trove also
    has a dedicated door (cfg.treasure_trove_blackprint, which
    all_unlocks_config sets True), so for that room banned_rooms is what
    actually stops it.
    """
    from blueprince_sim.engine.decks import eligible_pool

    pool_ids = {r.id for r in eligible_pool(Registry.load(), all_unlocks_config())}
    leaked = sorted({"treasure_trove", "closed_exhibit"} & pool_ids)
    assert not leaked, (
        f"unmodelled found floorplans reached the training draft pool: {leaked!r}"
    )


def test_every_modelled_found_floorplan_is_draftable_in_training():
    """all_unlocks_config() makes every found floorplan outside the exclusion
    set draftable, so an unlock that stops reaching the pool cannot pass unseen.

    all_unlocks_config feeds cfg.found_floorplans from all_found_floorplans();
    dropping that field, or filing a room under the wrong pool, would silently
    shrink the training pool rather than fail anything -- the pool is only ever
    checked for rooms that must stay OUT.
    """
    from blueprince_sim.engine.decks import eligible_pool

    pool_ids = {r.id for r in eligible_pool(Registry.load(), all_unlocks_config())}
    missing = sorted(all_found_floorplans() - pool_ids)
    assert not missing, (
        f"modelled found floorplans absent from the training draft pool: {missing!r}"
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
