"""Darkroom: mystery drafts that conceal every option's identity, driven by
the Utility Closet's "Darkroom" switch (state.darkroom_lights_on).
"""

from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import E, N, S


def _enter_darkroom(g: Game, cell: int = 7) -> None:
    """Place the Darkroom (t-shape, N|E|S orientation) at ``cell`` and enter
    it for real, firing ON_ENTER so effects/rooms/darkroom.py's fuse-blow
    hook runs."""
    darkroom = g.registry.by_id["darkroom"]
    g._place_room(darkroom, cell, N | E | S)
    g.state.pos = cell
    g._enter(cell)


def test_darkroom_first_entry_blows_the_fuse_when_switch_is_on(registry, cfg):
    """Entering a freshly-drafted Darkroom for the first time blows its fuse
    (switch flips off) when nobody has touched the Utility Closet -- the
    switch's own default state, matching the wiki's typical-playthrough case."""
    g = Game(cfg, seed=3)
    assert g.state.darkroom_lights_on
    _enter_darkroom(g)
    assert not g.state.darkroom_lights_on


def test_darkroom_hides_all_three_options(registry, cfg):
    """Drafting out of a dark Darkroom hides every option's identity; the
    hidden options remain real, placeable rooms."""
    g = Game(cfg, seed=3)
    _enter_darkroom(g)
    g.state.gems = 9  # afford whatever comes up
    pending = g.open_door(7, N)
    hidden = [o for o in pending.options if o.hidden]
    assert len(hidden) == len(pending.options)      # every option is hidden
    assert all(o.hidden for o in pending.options)   # no visible option remains
    # all hidden options are still real, placeable rooms
    steps_before = g.state.steps
    g.choose(hidden[0].slot)
    assert g.state.grid[12] >= 0                    # room placed at the north cell
    assert g.phase is Phase.NAVIGATE
    assert g.state.steps == steps_before            # placing costs no step


def test_darkroom_obs_hides_identity_for_all_slots(registry, cfg):
    """When drafting from a dark Darkroom, the obs zeroes the room id of
    every option slot (nothing leaks to the agent)."""
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=3)
    _enter_darkroom(g)
    g.state.gems = 9
    pending = g.open_door(7, N)
    g.state.pending = pending
    obs = O.encode(g)["options"]
    for slot_idx in range(len(pending.options)):
        assert obs[slot_idx][0] == 0                # room identity concealed


def test_lights_on_disables_concealment_for_a_later_doorway(registry, cfg):
    """Restoring power at the Utility Closet after the fuse blows disables
    concealment for the next doorway drafted from the Darkroom -- "while the
    lights are on, the Darkroom's negative drafting effect is disabled"."""
    g = Game(cfg, seed=3)
    _enter_darkroom(g)
    assert not g.state.darkroom_lights_on
    g.state.darkroom_lights_on = True  # simulate flipping the breaker back on
    g.state.gems = 9
    pending = g.open_door(7, E)
    assert not any(o.hidden for o in pending.options)


def test_switch_already_off_at_first_entry_means_the_fuse_never_blows(registry, cfg):
    """If the switch was already off before the Darkroom is ever entered, no
    fuse blows -- distinguishable from a genuine blow because no Shelter/
    Knight's Shield charge is ever consulted or released for it. The Darkroom
    still claims a charge at its draft, as every red room drafted after the
    Shelter does; the claim it keeps unreleased is what says the negation path
    was never consulted."""
    g = Game(cfg, seed=3)
    g.red_negations = 3
    g.state.darkroom_lights_on = False  # pre-emptively flipped off
    _enter_darkroom(g)
    assert not g.state.darkroom_lights_on
    assert g.red_negations == 2, "the draft claimed one charge for the Darkroom"
    assert "darkroom" in g.shelter_protected_ids, (
        "nothing to blow, so that claim was never consulted or released"
    )


def test_off_then_on_before_first_entry_still_blows_the_fuse(registry, cfg):
    """Flipping the switch off and back on at the Utility Closet before the
    Darkroom is ever entered does not stop the fuse from blowing on that
    first entry -- only the switch's state at the moment of entry matters,
    not any earlier toggling."""
    g = Game(cfg, seed=3)
    utility_closet = g.registry.by_id["utility_closet"]
    darkroom = g.registry.by_id["darkroom"]
    g._place_room(utility_closet, 22, N | S)
    g._place_room(darkroom, 7, N | E | S)

    g.state.pos = 22
    assert g.can_toggle_darkroom_lights()
    g.set_darkroom_lights(False)
    g.set_darkroom_lights(True)
    assert g.state.darkroom_lights_on

    g.state.pos = 7
    g._enter(7)

    assert not g.state.darkroom_lights_on, "the fuse still blows"


def test_shelter_keeps_the_lights_on_and_spends_one_charge(registry, cfg):
    """Shelter (or Knight's Shield) can also keep the Darkroom lit on first
    entry, spending one charge -- same _red_negated mechanism as every other
    red-room penalty, consulted only because the switch was actually on. The
    charge is claimed at the Darkroom's draft and released here, at the entry
    that would otherwise blow the fuse."""
    g = Game(cfg, seed=3)
    g.red_negations = 1
    _enter_darkroom(g)
    assert g.state.darkroom_lights_on
    assert g.red_negations == 0
    assert "darkroom" not in g.shelter_protected_ids, "the claim was released"
