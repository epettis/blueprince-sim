"""Archives: house-wide, non-stacking archiving of one dealt floorplan per draft.

See docs/drafting.md and engine/effects/rooms/archives.py for how archiving is
modelled.
"""

from blueprince_sim.engine.game import Game, Phase, RedrawKind
from blueprince_sim.engine.grid import N, S
from blueprince_sim.engine.state import DraftOption


def _house_with_archives(seed: int, registry, cfg) -> Game:
    """An Archives placed at cell 7, plus a plain Corridor at cell 12 whose
    north doorway is the one drafted from -- proves the effect is not scoped
    to the Archives' own doorway."""
    g = Game(cfg, seed=seed)
    g._place_room(registry.by_id["archives"], 7, N | S)
    g._place_room(registry.by_id["corridor"], 12, N | S)
    g.state.pos = 12
    g.state.entered[12] = True
    g.state.gems = 9  # afford whatever the archived/visible options turn out to be
    return g


def test_archives_archives_one_option_from_any_doorway(registry, cfg):
    """A draft through a doorway that has nothing to do with the Archives'
    own position still archives exactly one option, once an Archives is
    anywhere on the estate."""
    g = _house_with_archives(seed=3, registry=registry, cfg=cfg)
    pending = g.open_door(12, N)
    archived = [o for o in pending.options if o.archived]
    assert len(archived) == 1
    assert archived[0].hidden, "archived implies hidden"


def test_archived_implies_hidden_never_the_converse(registry, cfg):
    """Every archived option is hidden, but a hidden option need not be
    archived (a Darkroom-hidden option with no Archives on the estate)."""
    g = Game(cfg, seed=5)
    darkroom = registry.by_id["darkroom"]
    g._place_room(darkroom, 7, N | S)
    g.state.pos = 7
    g.state.entered[7] = True
    g.state.darkroom_lights_on = False  # already dark, no Archives placed
    g.state.gems = 9
    pending = g.open_door(7, N)
    assert all(o.hidden for o in pending.options)
    assert not any(o.archived for o in pending.options)


def test_two_archives_act_as_one(registry, cfg):
    """A second Archives does not archive a second option -- the flag it
    sets is a plain boolean, so multiple Archives act identically to one."""
    g = Game(cfg, seed=7)
    g._place_room(registry.by_id["archives"], 7, N | S)
    g._place_room(registry.by_id["archives"], 32, N | S)
    g._place_room(registry.by_id["corridor"], 12, N | S)
    g.state.pos = 12
    g.state.entered[12] = True
    g.state.gems = 9
    pending = g.open_door(12, N)
    archived = [o for o in pending.options if o.archived]
    assert len(archived) == 1


def test_archived_slot_is_uniformly_random_and_seed_deterministic(registry, cfg):
    """The archived slot varies across seeds and covers all three positions;
    replaying the same seed reproduces the same slot (the tested determinism
    invariant), pinning that the choice is a real, seeded RNG draw and not a
    fixed index."""
    def _archived_slot(seed: int) -> int:
        g = _house_with_archives(seed=seed, registry=registry, cfg=cfg)
        pending = g.open_door(12, N)
        return next(o.slot for o in pending.options if o.archived)

    seen = {_archived_slot(seed) for seed in range(30)}
    assert seen == {0, 1, 2}, f"expected all three slots to appear, got {seen}"

    for seed in (1, 2, 3, 42):
        assert _archived_slot(seed) == _archived_slot(seed), (
            f"seed {seed} did not reproduce the same archived slot"
        )


def test_archived_option_still_selectable_and_placeable(registry, cfg):
    """The archived floorplan is a real room: choosing its slot places it at
    no step cost, same as any other draft."""
    g = _house_with_archives(seed=3, registry=registry, cfg=cfg)
    pending = g.open_door(12, N)
    archived = next(o for o in pending.options if o.archived)
    steps_before = g.state.steps
    g.choose(archived.slot)
    assert g.state.grid[17] >= 0  # room placed at the north cell (12 + 5)
    assert g.phase is Phase.NAVIGATE
    assert g.state.steps == steps_before


def test_redraw_rearchives_the_fresh_hand(registry, cfg):
    """A redraw deals a brand new hand, and the Archives effect re-applies to
    it: exactly one of the three new options comes back archived."""
    g = _house_with_archives(seed=3, registry=registry, cfg=cfg)
    g.state.dice = 1
    pending = g.open_door(12, N)
    assert sum(1 for o in pending.options if o.archived) == 1

    g.redraw(RedrawKind.DIE)

    assert sum(1 for o in pending.options if o.archived) == 1


def test_shelter_negates_archiving_and_spends_one_charge(registry, cfg):
    """Shelter (or Knight's Shield) suppresses archiving for the whole day,
    consumed exactly once at the Archives' placement -- not once per doorway
    drafted afterward, which would silently drain all three Shelter charges
    on the first three doors opened."""
    g = Game(cfg, seed=3)
    g.red_negations = 3
    g._place_room(registry.by_id["archives"], 7, N | S)
    assert not g.state.archives_active
    assert g.red_negations == 2, "exactly one charge spent, at placement"

    g._place_room(registry.by_id["corridor"], 12, N | S)
    g.state.pos = 12
    g.state.entered[12] = True
    g.state.gems = 9
    pending = g.open_door(12, N)
    assert not any(o.archived for o in pending.options)
    assert g.red_negations == 2, "no further charge spent by drafting doorways"


def test_archives_mystery_still_shows_gem_cost(registry, cfg):
    """A hidden option's room identity is concealed in the obs, but its gem
    cost stays visible so the agent can budget for it."""
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
