"""Coercion rules for GameConfig.from_dict / --set overrides.

These pin the string-vs-iterable handling of the set-valued unlock fields, where
a wrong coercion is silent: the override simply matches nothing and the run
proceeds as if it had never been given.
"""

from __future__ import annotations

import dataclasses

from blueprince_sim.config import GameConfig, _SET_VALUED_FIELDS
from blueprince_sim.engine.game import Game


def test_single_id_string_is_one_id_not_its_characters() -> None:
    """`--set upgrade_disks=<id>` yields that one id, never a set of letters.

    frozenset("abc") is {"a","b","c"}, which matches no room and so silently
    disables the override -- a forced-upgrade arm configured this way would
    quietly measure its own control.
    """
    cfg = GameConfig.from_dict({"upgrade_disks": "cloister_of_orinda__ix35"})
    assert cfg.upgrade_disks == frozenset({"cloister_of_orinda__ix35"})


def test_comma_separated_string_becomes_several_ids() -> None:
    """A comma-separated --set value splits into ids, tolerating surrounding spaces."""
    cfg = GameConfig.from_dict({"studio_additions": "solarium, casino ,dovecote"})
    assert cfg.studio_additions == frozenset({"solarium", "casino", "dovecote"})


def test_empty_string_is_an_empty_set() -> None:
    """`--set upgrade_disks=` clears the field rather than producing {''}."""
    assert GameConfig.from_dict({"upgrade_disks": ""}).upgrade_disks == frozenset()


def test_list_values_still_coerce(tmp_path) -> None:
    """A YAML list of ids keeps working -- the string branch must not break it."""
    cfg = GameConfig.from_dict({"upgrade_disks": ["a", "b"]})
    assert cfg.upgrade_disks == frozenset({"a", "b"})


def test_set_valued_fields_are_derived_from_the_annotations() -> None:
    """Every frozenset field is coerced, with no hand-maintained list to fall behind.

    A new frozenset field that nobody remembered to register would pass its raw
    value straight through to the dataclass.
    """
    expected = {
        f.name for f in dataclasses.fields(GameConfig) if "frozenset" in f.type
    }
    assert _SET_VALUED_FIELDS == expected
    assert "draft_counts" not in _SET_VALUED_FIELDS  # a dict, not a set of ids


def test_upgrade_disk_override_actually_reaches_the_deck() -> None:
    """A --set upgrade_disks override swaps the variant into the live draft deck.

    The end-to-end check that matters: coercing correctly is only useful if the
    id then replaces its base room, which is what makes a forced-upgrade arm real.
    """
    cfg = GameConfig.from_dict({"upgrade_disks": "cloister_of_orinda__ix35", "day": 20})
    game = Game(cfg, seed=1)
    deck_ids = {game.registry.rooms[i].id for d in game.state.decks for i in d.order}
    assert "cloister_of_orinda__ix35" in deck_ids
    assert "cloister" not in deck_ids, "the upgraded variant replaces its base room"
