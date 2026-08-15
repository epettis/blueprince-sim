"""Tests for the Upgrade Disk draw mechanism (engine wiring, chunk 2).

These tests pin observable behaviour — what a player or RL agent can see —
not data file contents (those belong in tools/validate_data.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.decks import apply_upgrade
from blueprince_sim.engine.draft import DraftContext, redeal, room_draftable
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import N
from blueprince_sim.engine.model import Registry
from blueprince_sim.engine.upgrades import root_base_id, upgraded_slots
from blueprince_sim.env.multiday import DayChain


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def registry() -> Registry:
    """Registry loaded once — includes upgrade_tables after chunk 2."""
    return Registry.load()


def _game_at_security(seed: int = 0, **cfg_kwargs) -> Game:
    """A fresh game with the player positioned inside the Security room.

    Security is placed at cell 7 (rank 2 center) and the player is moved
    there without consuming steps. The game is in NAVIGATE phase.
    """
    g = Game(GameConfig(special_items=True, **cfg_kwargs), seed=seed)
    sec = g.registry.by_id["security"]
    # Place Security at cell 7 (rank 2 center); orientation E|S|W (mask 14)
    # which gives doors to the east, south, and west — south faces Entrance Hall
    g._place_room(sec, 7, 14)
    g.state.pos = 7
    g.state.entered[7] = True
    return g


def _grant_disk(game: Game, disk_id: str = "upgrade_disk_vault_304") -> None:
    """Add one upgrade disk to the game's inventory."""
    si.grant(game.state, game.registry, disk_id, source="test")


# ---------------------------------------------------------------------------
# disk_reader flag
# ---------------------------------------------------------------------------

def test_a_disk_reader_room_is_distinguishable_from_an_ordinary_one(registry: Registry) -> None:
    """The disk_reader flag actually reaches the parsed Room and separates rooms.

    Which rooms carry the flag is a data question, checked in
    tools/validate_data.py; asserting the id set here would only re-read
    rooms.json back through the registry.
    """
    readers = [r for r in registry.rooms if r.disk_reader]
    assert readers, "at least one room must be a disk reader or the feature is unreachable"
    assert any(not r.disk_reader for r in registry.rooms), "the flag must not be universal"


# ---------------------------------------------------------------------------
# can_insert_disk / disk_reader_here
# ---------------------------------------------------------------------------

def test_can_insert_disk_no_disk() -> None:
    """can_insert_disk is False when the player holds no upgrade disk."""
    g = _game_at_security()
    assert not g.can_insert_disk()


def test_can_insert_disk_wrong_room() -> None:
    """can_insert_disk is False when the player is not in a disk-reader room."""
    g = Game(GameConfig(special_items=True), seed=0)
    _grant_disk(g)
    # Player starts at Entrance Hall, which has no disk_reader
    assert not g.disk_reader_here()
    assert not g.can_insert_disk()


def test_can_insert_disk_true() -> None:
    """can_insert_disk is True in NAVIGATE phase, holding a disk, inside Security."""
    g = _game_at_security()
    _grant_disk(g)
    assert g.phase is Phase.NAVIGATE
    assert g.disk_reader_here()
    assert g.can_insert_disk()


def test_disk_reader_in_outer_room(registry: Registry) -> None:
    """disk_reader_here is True when the player is inside the Shelter outer room."""
    g = Game(GameConfig(west_gate_unlatched=True, special_items=True), seed=0)
    # Simulate the player being inside the outer room (area == "shelter")
    g.placed_ids.add("shelter")
    g.state.area = "shelter"
    assert g.disk_reader_here()


def test_all_four_grid_and_outer_room_terminals_still_read_as_disk_readers(
    registry: Registry,
) -> None:
    """Regression guard: Security, Laboratory, Office (on-grid) and Shelter
    (outer room) all still read as disk-reader locations after the Grotto's
    off-grid branch was added to disk_reader_here() -- the new branch must
    not have disturbed the on-grid/outer-room checks it sits alongside."""
    for room_id in ("security", "laboratory", "office"):
        g = Game(GameConfig(special_items=True), seed=0)
        room = registry.by_id[room_id]
        g._place_room(room, 7, room.rotations[0])
        g.state.pos = 7
        g.state.entered[7] = True
        assert g.disk_reader_here(), f"{room_id} must still read as a disk reader"

    g = Game(GameConfig(west_gate_unlatched=True, special_items=True), seed=0)
    g.placed_ids.add("shelter")
    g.state.area = "shelter"
    assert g.disk_reader_here(), "shelter must still read as a disk reader"


# ---------------------------------------------------------------------------
# Blackbridge Grotto -- the 5th, off-grid terminal (areas.json's Area.disk_reader)
# ---------------------------------------------------------------------------

def test_disk_reader_here_true_at_blackbridge_grotto() -> None:
    """disk_reader_here is True when the player stands off-grid at the
    Blackbridge Grotto area node -- the 5th Upgrade Disk terminal, which has
    no rooms.json record and so is recognised through Area.disk_reader
    instead of Room.disk_reader."""
    g = Game(GameConfig(special_items=True), seed=0)
    g.state.area = "blackbridge_grotto"
    assert g.off_grid
    assert not g.inside_outer_room
    assert g.disk_reader_here()


def test_disk_reader_here_false_at_a_different_off_grid_area() -> None:
    """disk_reader_here is False at an off-grid area node that is NOT the
    Grotto -- pins that the off-grid branch keys on Area.disk_reader rather
    than on being off-grid at all (which would wrongly offer a terminal
    everywhere off the 5x9 grid)."""
    g = Game(GameConfig(special_items=True), seed=0)
    g.state.area = "private_drive"
    assert g.off_grid
    assert not g.disk_reader_here()


def test_can_insert_disk_true_at_blackbridge_grotto() -> None:
    """can_insert_disk is True off-grid at the Grotto while holding a disk,
    mirroring test_can_insert_disk_true's on-grid Security case."""
    g = Game(GameConfig(special_items=True), seed=0)
    g.state.area = "blackbridge_grotto"
    _grant_disk(g)
    assert g.phase is Phase.NAVIGATE
    assert g.can_insert_disk()


def test_insert_disk_and_choose_upgrade_completes_at_blackbridge_grotto() -> None:
    """The full terminal flow -- insert a held disk, receive three options,
    choose one -- completes off-grid at the Grotto exactly as it does at
    Security: the disk is consumed and the chosen variant is applied."""
    g = Game(GameConfig(special_items=True), seed=5)
    g.state.area = "blackbridge_grotto"
    _grant_disk(g)
    assert g.insert_disk() is True
    assert g.phase is Phase.UPGRADE_PENDING
    options = list(g.state.pending_upgrade_options)
    assert len(options) == 3
    assert g.held_disk_ids() == [], "the inserted disk must be consumed immediately"
    g.choose_upgrade(1)
    assert g.phase is Phase.NAVIGATE
    assert options[1] in g.state.applied_upgrades


# ---------------------------------------------------------------------------
# insert_disk / choose_upgrade — basic flow
# ---------------------------------------------------------------------------

def test_insert_disk_phase_transition() -> None:
    """insert_disk transitions phase to UPGRADE_PENDING and sets pending fields."""
    g = _game_at_security(seed=1)
    _grant_disk(g)
    result = g.insert_disk()
    assert result is True
    assert g.phase is Phase.UPGRADE_PENDING
    assert g.state.pending_upgrade_slot is not None
    assert len(g.state.pending_upgrade_options) == 3


def test_insert_disk_consumes_disk() -> None:
    """insert_disk removes exactly one disk from inventory."""
    g = _game_at_security(seed=2)
    _grant_disk(g, "upgrade_disk_vault_304")
    _grant_disk(g, "upgrade_disk_commissary")
    assert len(g.held_disk_ids()) == 2
    g.insert_disk()
    assert len(g.held_disk_ids()) == 1


def test_choose_upgrade_returns_to_navigate() -> None:
    """choose_upgrade returns phase to NAVIGATE and clears pending fields."""
    g = _game_at_security(seed=3)
    _grant_disk(g)
    g.insert_disk()
    assert g.phase is Phase.UPGRADE_PENDING
    g.choose_upgrade(0)
    assert g.phase is Phase.NAVIGATE
    assert g.state.pending_upgrade_slot is None
    assert g.state.pending_upgrade_options == ()


def test_choose_upgrade_adds_to_applied() -> None:
    """choose_upgrade adds the chosen variant id to state.applied_upgrades."""
    g = _game_at_security(seed=4)
    _grant_disk(g)
    g.insert_disk()
    options = list(g.state.pending_upgrade_options)
    g.choose_upgrade(0)
    assert options[0] in g.state.applied_upgrades


# ---------------------------------------------------------------------------
# Immediacy — the core design invariant
# ---------------------------------------------------------------------------

def test_immediacy_same_day_dealable(registry: Registry) -> None:
    """After applying an upgrade mid-day, the variant is in the undealt deck
    and the base room is not, without waiting for the next day's build_decks.

    This is the behaviour that distinguishes in-place deck substitution from
    a simpler next-day config approach.
    """
    g = _game_at_security(seed=5)
    _grant_disk(g)

    g.insert_disk()
    options = list(g.state.pending_upgrade_options)

    # Choose the first offered variant
    chosen_variant_id = options[0]
    g.choose_upgrade(0)

    variant = registry.by_id[chosen_variant_id]
    base = registry.by_id[variant.variant_of]

    # Each card is looked up in its OWN bucket's deck, so the assertion holds
    # for same-bucket substitutions and cross-bucket (Cloister) moves alike.
    variant_deck = g.state.deck(variant.rarity_idx, not variant.is_free)
    base_deck = g.state.deck(base.rarity_idx, not base.is_free)
    assert variant.idx in variant_deck.order[variant_deck.pos:], \
        "variant must be dealable the same day the disk was inserted"
    assert base.idx not in base_deck.order[base_deck.pos:], \
        "base must stop being dealable the same day the disk was inserted"


def test_upgrade_survives_a_deck_reshuffle(registry: Registry) -> None:
    """An upgraded base floorplan stays retired even after the deck reshuffles.

    draft.py's attempt 3 reshuffles every deck and resets the cursor to 0, so an
    upgrade that only rewrote the undealt slice would hand the un-upgraded room
    back to the player later the same day.
    """
    variant = registry.by_id["hallway_closet__ix39"]
    base = registry.by_id["closet"]

    g = Game(GameConfig(special_items=True), seed=0)
    deck = g.state.deck(base.rarity_idx, not base.is_free)
    # Deal until the base card itself has been dealt (deck_copies is 1, so once
    # dealt it is the only copy and none remains undealt).
    while base.idx in deck.order[deck.pos:]:
        deck.deal_next(lambda card: True)
    assert base.idx in deck.order[:deck.pos], "base card must now sit in the dealt prefix"

    apply_upgrade(g.state, g.registry, variant.id, g.rng)
    deck.reshuffle(lambda lst: None)

    assert base.idx not in deck.order, \
        "the retired base floorplan must not come back when the deck reshuffles"
    assert variant.idx in deck.order[deck.pos:], \
        "the variant must be dealable after the reshuffle"


def test_cloister_variant_moves_unusual_gem_to_standard_gem(registry: Registry) -> None:
    """A non-Draxus Cloister upgrade moves the card across decks: the base leaves
    the unusual/gem deck and the variant appears in the standard/gem deck.
    """
    variant = registry.by_id["cloister_of_orinda__ix35"]
    cloister = registry.by_id["cloister"]
    # Precondition for a cross-deck move: the buckets genuinely differ.
    assert (cloister.rarity_idx, cloister.is_free) != (variant.rarity_idx, variant.is_free)

    g = Game(GameConfig(special_items=True), seed=0)
    src = g.state.deck(cloister.rarity_idx, not cloister.is_free)   # unusual/gem
    dst = g.state.deck(variant.rarity_idx, not variant.is_free)     # standard/gem
    n_base = src.order[src.pos:].count(cloister.idx)
    assert n_base > 0, "Cloister must start in the unusual/gem deck for this test to mean anything"
    src_size_before, dst_size_before = len(src.order), len(dst.order)

    apply_upgrade(g.state, g.registry, variant.id, g.rng)

    assert cloister.idx not in src.order[src.pos:], "base must leave the unusual/gem deck"
    assert dst.order[dst.pos:].count(variant.idx) == n_base, \
        "one variant card must arrive in standard/gem for each base card removed"
    assert len(src.order) == src_size_before - n_base
    assert len(dst.order) == dst_size_before + n_base


def test_draxus_lands_in_free_deck(registry: Registry) -> None:
    """Cloister of Draxus (gem_cost 0) must go to the standard/free deck,
    not the standard/gem deck, when applied as an upgrade.
    """
    draxus = registry.by_id["cloister_of_draxus__ix36"]
    cloister = registry.by_id["cloister"]

    g = Game(GameConfig(special_items=True), seed=0)

    # Apply Draxus directly via apply_upgrade
    src_deck = g.state.deck(cloister.rarity_idx, not cloister.is_free)
    # Ensure at least one base card is undealt (it should be from build_decks)
    if cloister.idx not in src_deck.order[src_deck.pos:]:
        src_deck.order.append(cloister.idx)

    free_deck_before = g.state.deck(draxus.rarity_idx, False)  # standard/free
    gem_deck_before = g.state.deck(draxus.rarity_idx, True)   # standard/gem
    free_size_before = len(free_deck_before.order)
    gem_size_before = len(gem_deck_before.order)

    apply_upgrade(g.state, g.registry, draxus.id, g.rng)

    free_deck_after = g.state.deck(draxus.rarity_idx, False)
    gem_deck_after = g.state.deck(draxus.rarity_idx, True)

    assert draxus.idx in free_deck_after.order[free_deck_after.pos:], \
        "Draxus must be in the standard/free deck"
    assert draxus.idx not in gem_deck_after.order[gem_deck_after.pos:], \
        "Draxus must NOT be in the standard/gem deck"
    assert len(free_deck_after.order) == free_size_before + 1
    assert len(gem_deck_after.order) == gem_size_before  # gem deck unchanged


# ---------------------------------------------------------------------------
# Same-bucket size invariant
# ---------------------------------------------------------------------------

def test_same_bucket_upgrade_preserves_sizes_dealt_cards_and_positions(
    registry: Registry,
) -> None:
    """A same-bucket upgrade rewrites base cards in place: every deck keeps its
    size, the already-dealt prefix is untouched, and no undealt card moves slot.

    Position preservation is what makes the substitution seed-deterministic —
    a reshuffle here would resurrect cards already dealt today.
    """
    variant = registry.by_id["hallway_closet__ix39"]
    base = registry.by_id["closet"]
    assert (base.rarity_idx, base.is_free) == (variant.rarity_idx, variant.is_free)

    g = Game(GameConfig(special_items=True), seed=0)
    deck = g.state.deck(base.rarity_idx, not base.is_free)
    # Deal several non-base cards so pos > 0 (making the dealt-prefix assertion
    # non-vacuous) while leaving a base card undealt to be substituted.
    for _ in range(3):
        deck.deal_next(lambda card: card != base.idx)
    assert deck.pos > 0, "test needs a non-empty dealt prefix to be meaningful"
    assert base.idx in deck.order[deck.pos:], "base must still be undealt to be substituted"

    sizes_before = [len(d.order) for d in g.state.decks]
    dealt_before = [list(d.order[:d.pos]) for d in g.state.decks]
    order_before = list(deck.order)

    apply_upgrade(g.state, g.registry, variant.id, g.rng)

    assert [len(d.order) for d in g.state.decks] == sizes_before, "deck sizes must not change"
    assert [list(d.order[:d.pos]) for d in g.state.decks] == dealt_before, \
        "already-dealt cards must never be altered by an upgrade"
    # Every slot holds either its original card or, where it held the base, the
    # variant — so nothing was reordered.
    for i, (old, new) in enumerate(zip(order_before, deck.order)):
        expected = variant.idx if (old == base.idx and i >= deck.pos) else old
        assert new == expected, f"card at slot {i} moved or changed unexpectedly"
    assert base.idx not in deck.order[deck.pos:], "no undealt base card may survive"


# ---------------------------------------------------------------------------
# Draft counters
# ---------------------------------------------------------------------------

def test_draft_counts_increment_on_placement(registry: Registry) -> None:
    """Placing a room increments state.draft_counts keyed by root base room id."""
    g = Game(GameConfig(special_items=True), seed=0)
    closet = registry.by_id["closet"]
    assert g.state.draft_counts.get("closet", 0) == 0
    # Place closet at a valid cell
    g._place_room(closet, 7, 6)  # E|S orientation
    assert g.state.draft_counts.get("closet", 0) == 1
    g._place_room(closet, 8, 6)
    assert g.state.draft_counts.get("closet", 0) == 2


def test_draft_counts_key_by_root_base_id(registry: Registry) -> None:
    """Drafting an upgrade variant counts toward its root base room id, not the variant id."""
    g = Game(GameConfig(special_items=True), seed=0)
    variant = registry.by_id["hallway_closet__ix39"]
    assert variant.variant_of == "closet"
    g._place_room(variant, 7, 6)
    assert g.state.draft_counts.get("closet", 0) == 1, \
        "upgraded variant draft must count toward root base 'closet'"
    assert g.state.draft_counts.get("hallway_closet__ix39", 0) == 0


def test_entrance_hall_not_counted(registry: Registry) -> None:
    """The Entrance Hall pre-placement at reset does not appear in draft_counts."""
    g = Game(GameConfig(special_items=True), seed=0)
    assert "entrance_hall" not in g.state.draft_counts
    assert g.state.draft_counts == {}


# ---------------------------------------------------------------------------
# root_base_id / upgraded_slots helpers
# ---------------------------------------------------------------------------

def test_root_base_id_base_room(registry: Registry) -> None:
    """root_base_id returns the room's own id when it is not a variant."""
    closet = registry.by_id["closet"]
    assert root_base_id(registry, closet) == "closet"


def test_root_base_id_first_level_variant(registry: Registry) -> None:
    """root_base_id returns the base room id for a first-level variant."""
    variant = registry.by_id["hallway_closet__ix39"]
    assert root_base_id(registry, variant) == "closet"


def test_root_base_id_second_level_spare(registry: Registry) -> None:
    """root_base_id walks the chain to the true root for spare 2nd-level variants."""
    # servants_spare_quarters__ix134 has variant_of=spare_bedroom__ix131
    # spare_bedroom__ix131 has variant_of=spare_room
    sv = registry.by_id["servants_spare_quarters__ix134"]
    assert root_base_id(registry, sv) == "spare_room"


def test_upgraded_slots_empty(registry: Registry) -> None:
    """upgraded_slots returns empty frozenset when no upgrades are applied."""
    result = upgraded_slots(frozenset(), registry)
    assert result == frozenset()


def test_upgraded_slots_ordinary_variant(registry: Registry) -> None:
    """A first-level closet variant implies the 'closet' slot."""
    result = upgraded_slots(frozenset({"hallway_closet__ix39"}), registry)
    assert result == frozenset({"closet"})


def test_upgraded_slots_spare_first_level(registry: Registry) -> None:
    """A first-level spare variant implies spare_1."""
    result = upgraded_slots(frozenset({"spare_bedroom__ix131"}), registry)
    assert "spare_1" in result
    assert "spare_2" not in result


def test_upgraded_slots_spare_second_level(registry: Registry) -> None:
    """A second-level spare variant implies both spare_1 and spare_2."""
    result = upgraded_slots(frozenset({"servants_spare_quarters__ix134"}), registry)
    assert "spare_1" in result
    assert "spare_2" in result


# ---------------------------------------------------------------------------
# Spare 1 then Spare 2
# ---------------------------------------------------------------------------

def test_spare_1_then_spare_2(registry: Registry) -> None:
    """After applying a spare_1 variant, insert_disk can select spare_2 and
    offer that variant's three sub-variants (not spare_room's first-level ones).
    """
    g = _game_at_security(seed=10)
    _grant_disk(g)

    # Force spare_1 to be applied by directly manipulating state
    g.state.applied_upgrades.add("spare_bedroom__ix131")

    _grant_disk(g, "upgrade_disk_commissary")
    g.insert_disk()

    # If spare_2 was selected, the options should be sub-variants of spare_bedroom
    if g.state.pending_upgrade_slot == "spare_2":
        expected_sub_variants = {r.id for r in registry.rooms if r.variant_of == "spare_bedroom__ix131"}
        offered = set(g.state.pending_upgrade_options)
        assert offered == expected_sub_variants, \
            "spare_2 options must be sub-variants of the applied spare_1 variant"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_insert_disk_determinism() -> None:
    """Same seed and same actions produce the same slot, options, and deck state."""
    def _run(seed: int) -> tuple:
        g = _game_at_security(seed=seed)
        _grant_disk(g)
        g.insert_disk()
        slot = g.state.pending_upgrade_slot
        options = tuple(g.state.pending_upgrade_options)
        if options:
            g.choose_upgrade(0)
        decks_snapshot = tuple(tuple(d.order) for d in g.state.decks)
        return slot, options, decks_snapshot

    r1 = _run(42)
    r2 = _run(42)
    assert r1 == r2, "same seed must produce identical selection + deck state"


def test_different_seeds_may_differ() -> None:
    """Different seeds typically produce different outcomes (probabilistic check)."""
    def _slot(seed: int) -> str | None:
        g = _game_at_security(seed=seed)
        _grant_disk(g)
        g.insert_disk()
        return g.state.pending_upgrade_slot

    results = {_slot(s) for s in range(20)}
    assert len(results) > 1, "different seeds should produce varied slot selections"


# ---------------------------------------------------------------------------
# Carryover
# ---------------------------------------------------------------------------

def test_carryover_upgrade_persists_next_day() -> None:
    """An upgrade applied today appears in the next day's GameConfig.upgrade_disks."""
    from blueprince_sim.engine.shops import carryover

    g = _game_at_security(seed=7)
    _grant_disk(g)
    g.insert_disk()
    chosen_variant = g.state.pending_upgrade_options[0]
    g.choose_upgrade(0)

    co = carryover(g)
    assert chosen_variant in co["upgrade_disks"], \
        "applied upgrade variant must appear in carryover upgrade_disks"


def test_carryover_draft_counts_accumulate() -> None:
    """Draft counts from today appear in carryover and accumulate across days via DayChain."""
    from blueprince_sim.engine.shops import carryover

    g = Game(GameConfig(special_items=True), seed=0)
    closet = g.registry.by_id["closet"]
    g._place_room(closet, 7, 6)

    co = carryover(g)
    assert co["draft_counts"].get("closet", 0) == 1

    chain = DayChain(GameConfig(special_items=True))
    chain.advance(co)
    cfg2 = chain.next_config()
    assert cfg2.draft_counts.get("closet", 0) == 1


def test_carryover_clears_on_wrap() -> None:
    """Applied upgrades and draft counts reset to empty on chain wrap."""
    from blueprince_sim.engine.shops import carryover

    g = _game_at_security(seed=8)
    _grant_disk(g)
    g.insert_disk()
    g.choose_upgrade(0)

    co = carryover(g)
    chain = DayChain(GameConfig(special_items=True), n_days=1)
    chain.advance(co)
    # After 1-day chain: current_day wraps back to 1; all state cleared
    cfg_after_wrap = chain.next_config()
    assert cfg_after_wrap.upgrade_disks == frozenset(), \
        "upgrade_disks must be empty after chain wrap"
    assert cfg_after_wrap.draft_counts == {}, \
        "draft_counts must be empty after chain wrap"


def test_daychain_passes_upgrade_disks_to_next_config() -> None:
    """DayChain.next_config includes applied_upgrades in GameConfig.upgrade_disks."""
    chain = DayChain(GameConfig())
    chain.applied_upgrades = frozenset({"hallway_closet__ix39"})
    cfg = chain.next_config()
    assert "hallway_closet__ix39" in cfg.upgrade_disks


def test_daychain_passes_draft_counts_to_next_config() -> None:
    """DayChain.next_config includes draft_counts in GameConfig.draft_counts."""
    chain = DayChain(GameConfig())
    chain.draft_counts = {"closet": 3}
    cfg = chain.next_config()
    assert cfg.draft_counts.get("closet") == 3


def test_preset_upgrade_disks_survive_the_day_chain() -> None:
    """A config that presets upgrade_disks keeps them on day 1 and after a wrap.

    Unlike the other carry-over fields, upgrade_disks is also a configuration
    input, so seeding DayChain from empty would silently discard a preset
    upgrade the moment the run went multi-day.
    """
    preset = frozenset({"pool_hall__ix12"})
    chain = DayChain(GameConfig(upgrade_disks=preset), n_days=2)
    assert preset <= chain.next_config().upgrade_disks, "day 1 must keep the preset upgrade"

    # Walk past the end of the attempt so the chain wraps back to day 1.
    for _ in range(2):
        chain.advance({})
    assert chain.current_day == 1, "chain should have wrapped"
    assert preset <= chain.next_config().upgrade_disks, \
        "a wrap clears earned upgrades but must not clear the configured baseline"


# ---------------------------------------------------------------------------
# Game.catacombs_unlocked() — same-day outer-room flag
# ---------------------------------------------------------------------------

def _game_with_outer_room_placed(
    room_id: str, entered: bool = False
) -> Game:
    """Set up a Game whose outer room slot is filled by the named room.

    Bypasses the draft to avoid randomness: directly manipulates placed_ids
    and outer_room_entered exactly as the real draft + enter flow would,
    without triggering ON_PLACE / ON_ENTER effects.
    """
    g = Game(GameConfig(west_gate_unlatched=True, special_items=False), seed=0)
    g.placed_ids.add(room_id)
    g.state.outer_room_drafted = True
    g.state.area = room_id if entered else "west_path"
    g.state.outer_room_entered = entered
    return g


def test_catacombs_unlocked_false_before_entry():
    """catacombs_unlocked() is False when the Tomb is drafted but not yet entered.

    Physical access is required; placing the Tomb at the doorstep is not sufficient.
    """
    g = _game_with_outer_room_placed("tomb", entered=False)
    assert not g.catacombs_unlocked()


def test_catacombs_unlocked_true_after_entry():
    """catacombs_unlocked() is True once a room flagged unlocks_catacombs has been entered.

    Entering the Tomb solves the angel-statue puzzle; same-day access is then active.
    """
    g = _game_with_outer_room_placed("tomb", entered=True)
    assert g.catacombs_unlocked()


def test_catacombs_unlocked_false_for_non_tomb_outer_room():
    """catacombs_unlocked() is False when an entered outer room lacks the unlocks_catacombs flag.

    Entering any other outer room should not unlock the Catacombs.
    """
    g = _game_with_outer_room_placed("toolshed", entered=True)
    assert not g.catacombs_unlocked()


def test_catacombs_unlocked_does_not_persist_across_days():
    """catacombs_unlocked() is False on a fresh day even if tomb was entered yesterday.

    The flag is same-day only; reset() clears outer_room_entered and placed_ids.
    """
    g = _game_with_outer_room_placed("tomb", entered=True)
    assert g.catacombs_unlocked(), "sanity: should be True before reset"
    g.reset()  # new day
    assert not g.catacombs_unlocked(), "must not persist after reset — same-day only"


# ---------------------------------------------------------------------------
# One copy per FLOORPLAN: a base room and its upgrade variants are one floorplan
# ---------------------------------------------------------------------------

_PARLOR = "parlor"
_PARLOR_VARIANT = "parlor__ix108"
_DRAFT_CELL = 17          # rank 4, centre column: no wing/rank condition applies
_EMPTY_CELL = 12          # rank 3, centre column: where the placed room is parked


def _parlor_upgraded_after_placing(registry: Registry, *, place_base: bool = True,
                                   place_variant: bool = False,
                                   chamber: bool = False, seed: int = 0) -> Game:
    """A day where the Parlor floorplan was upgraded AFTER a Parlor was placed.

    Mirrors ``Game.choose_upgrade``'s two steps (record the variant, substitute
    the live deck cards), then reshuffles every deck so the substituted card is
    undealt again -- the state ``draft.py``'s own attempt-3 reshuffle reaches.
    """
    g = Game(GameConfig(), seed=seed, registry=registry)
    for rid, placed in ((_PARLOR, place_base), (_PARLOR_VARIANT, place_variant)):
        if not placed:
            continue
        room = registry.by_id[rid]
        g.state.grid[_EMPTY_CELL] = room.idx
        g.state.placed_doors[_EMPTY_CELL] = room.door_mask
        g.placed_ids.add(room.id)
    if chamber:
        g.placed_ids.add("chamber_of_mirrors")
    g.state.applied_upgrades.add(_PARLOR_VARIANT)
    apply_upgrade(g.state, registry, _PARLOR_VARIANT, g.rng)
    for i, deck in enumerate(g.state.decks):
        deck.reshuffle(lambda lst, i=i: g.rng.shuffle(f"reshuffle_{i}", lst))
    return g


def _ctx(g: Game, registry: Registry) -> DraftContext:
    """A DraftContext over ``g``'s live state, as ``deal_draft`` builds one."""
    return DraftContext(g.state, registry, g.cfg, g.rng, g.placed_ids, None)


def test_upgraded_parlor_is_undraftable_while_the_base_parlor_stands(registry: Registry) -> None:
    """An Upgrade Disk upgrades a floorplan rather than adding one, so the
    upgraded Parlor is not draftable while the base Parlor is on the grid.

    Without this the player gets two Parlors in one day off a single
    floorplan -- the duplication the Chamber of Mirrors is supposed to be the
    only route to.
    """
    g = _parlor_upgraded_after_placing(registry)
    variant = registry.by_id[_PARLOR_VARIANT]
    assert any(variant.idx in d.order[d.pos:] for d in g.state.decks), (
        "sanity: the substituted variant card must be undealt, or the assertion "
        "below would pass for want of a card rather than by the floorplan rule")
    assert not room_draftable(_ctx(g, registry), variant, _DRAFT_CELL, N, set())


def test_upgraded_parlor_is_draftable_when_no_parlor_stands(registry: Registry) -> None:
    """The same upgraded Parlor, same cell and same direction, IS draftable on a
    grid holding no Parlor -- so the refusal above is the one-copy rule and not
    a geometry or draft-condition failure at that doorway."""
    g = _parlor_upgraded_after_placing(registry, place_base=False)
    variant = registry.by_id[_PARLOR_VARIANT]
    assert room_draftable(_ctx(g, registry), variant, _DRAFT_CELL, N, set())


def test_base_parlor_is_undraftable_while_an_upgraded_parlor_stands(registry: Registry) -> None:
    """The rule is symmetric: a placed variant blocks its base floorplan too.

    The base can still reach a hand -- the Chamber of Mirrors returns
    floorplans to the pool -- so the grid check has to bar it from the other
    direction as well.
    """
    g = _parlor_upgraded_after_placing(registry, place_base=False, place_variant=True)
    base = registry.by_id[_PARLOR]
    assert not room_draftable(_ctx(g, registry), base, _DRAFT_CELL, N, set())


def test_chamber_of_mirrors_still_lifts_the_floorplan_rule(registry: Registry) -> None:
    """The Chamber of Mirrors waives the one-copy rule wholesale, and keying it
    on the floorplan rather than the room id does not narrow that waiver: the
    upgraded Parlor stays draftable beside a placed base Parlor while the
    Chamber is on the grid."""
    g = _parlor_upgraded_after_placing(registry, chamber=True)
    variant = registry.by_id[_PARLOR_VARIANT]
    assert room_draftable(_ctx(g, registry), variant, _DRAFT_CELL, N, set())


def test_upgraded_parlor_never_dealt_into_a_hand_beside_its_base(registry: Registry) -> None:
    """End-to-end over the real dealer: 40 redeals of one hand, on a grid
    already holding the base Parlor, never offer the upgraded Parlor.

    ``room_draftable`` is the only gate between the reshuffled variant card and
    a player's three options, so this is the property the owner actually
    observed being violated.
    """
    g = _parlor_upgraded_after_placing(registry)
    pending = g.open_door(2, N)
    assert pending is not None, "sanity: the entrance hall's north doorway must deal a hand"
    seen: set[str] = set()
    for _ in range(40):
        seen.update(registry.rooms[o.room_idx].id for o in pending.options)
        redeal(g.state, registry, g.cfg, g.rng, g.placed_ids, pending)
    assert seen, "sanity: the redeals must have produced options to inspect"
    assert _PARLOR_VARIANT not in seen
    assert _PARLOR not in seen, "the base Parlor is on the grid and must not recur either"
