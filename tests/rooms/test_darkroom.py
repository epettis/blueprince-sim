"""Darkroom: mystery drafts that conceal every option's identity.

Split out of the old test_game.py, which keeps the general game-loop tests.
"""

from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import E, N, S


def test_darkroom_hides_all_three_options(registry, cfg):
    """Drafting out of the Darkroom hides every option's identity; the hidden
    options remain real, placeable rooms."""
    g = Game(cfg, seed=3)
    # Stand in the Darkroom and draft out of its north door.
    # Darkroom layout is "t"; place it so a north doorway is available.
    darkroom = registry.by_id["darkroom"]
    # Use a t-orientation that opens N/E/S (mask 7 = N|E|S)
    g._place_room(darkroom, 7, N | E | S)
    g.state.pos = 7
    g.state.entered[7] = True
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
    """When drafting from the Darkroom, the obs zeroes the room id of every
    option slot (nothing leaks to the agent)."""
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=3)
    darkroom = registry.by_id["darkroom"]
    g._place_room(darkroom, 7, N | E | S)
    g.state.pos = 7
    g.state.entered[7] = True
    g.state.gems = 9
    pending = g.open_door(7, N)
    g.state.pending = pending
    obs = O.encode(g)["options"]
    for slot_idx in range(len(pending.options)):
        assert obs[slot_idx][0] == 0                # room identity concealed
