"""Archives: mystery drafts that conceal one option's identity.

Split out of the old test_game.py, which keeps the general game-loop tests.
"""

from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.state import DraftOption


def test_archives_hides_a_draftable_mystery(registry, cfg):
    """Drafting out of the Archives conceals exactly one option's identity;
    the mystery is still a real room that places normally at no step cost."""
    g = Game(cfg, seed=3)
    # Stand in the Archives and draft out of its north door.
    g._place_room(registry.by_id["archives"], 7, N | S)
    g.state.pos = 7
    g.state.entered[7] = True
    g.state.gems = 9  # afford whatever the mystery turns out to be
    pending = g.open_door(7, N)
    hidden = [o for o in pending.options if o.hidden]
    assert len(hidden) == 1                       # exactly one mystery option
    assert not pending.options[0].hidden          # a visible option remains
    # the mystery is still a real, placeable room
    steps_before = g.state.steps
    g.choose(hidden[0].slot)
    assert g.state.grid[12] >= 0                   # room placed at the north cell
    assert g.phase is Phase.NAVIGATE
    assert g.state.steps == steps_before           # placing costs no step


def test_archives_mystery_still_shows_gem_cost(registry, cfg):
    """A hidden (mystery) option's room identity is concealed in the obs, but
    its gem cost stays visible so the agent can budget for it."""
    from blueprince_sim.engine.state import PendingDraft
    from blueprince_sim.env import obs as O

    g = Game(cfg, seed=1)
    gem_room = next(r for r in registry.rooms if r.gem_cost > 0 and r.rarity)
    g.state.pos = 2
    g.phase = Phase.DRAFTING
    pd = PendingDraft(from_cell=2, direction=N, target_cell=7)
    pd.options = [DraftOption(room_idx=gem_room.idx, orientation=gem_room.door_mask,
                              gem_cost=gem_room.gem_cost, slot=2, hidden=True)]
    g.state.gems = 9
    g.state.pending = pd
    row = O.encode(g)["options"][2]                 # obs row for slot 2
    assert row[0] == 0                              # identity (room id) concealed
    assert row[2] == g._effective_cost(gem_room, pd.options[0])  # gem cost visible
    assert row[2] > 0
