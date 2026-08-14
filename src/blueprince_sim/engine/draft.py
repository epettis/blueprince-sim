"""The drafting algorithm.

Implements the datamined procedure: once per round (see _resolve_free_gem),
roll whether Slot 2/3 (this engine's 0-indexed slots 1/2) are Free or Gem
Draws -- Slot 1 (engine slot 0) is always free. Then, for each of the 3
option slots: (1) roll a rarity from the weight table (rank x slot x stage x
Solarium), (2) deal a room of that rarity solitaire-style from ONLY the deck
class (free or gem) the round's Free/Gem Draw decision picked for that slot,
subject to the doorway's filters -- a Free Draw and a Gem Draw never share a
deal. Four attempts per slot: full rules -> ignore priority filters ->
reshuffle decks -> forced Closet. Priority draws (an additional per-floorplan
acceptance filter that only applies on attempt 1 -- see _priority_draw) can
force specific rooms into ANY slot; the separate Forced Draw mechanism
(_forced_draw_garage) is Slot-3-only.

The Mechanarium's cardinal door mask is derived in this module (see
_mechanarium_orientation) from the number of placed Mechanical rooms rather
than rolled, so it never consumes an "orientation" RNG draw. Mechanical rooms
beyond the four cardinal doors open diagonal compartments instead, modelled
as containers at the Mechanarium's cell rather than as doors here --
engine/effects/rooms/mechanarium.py seeds the per-placement compartment
count, and engine/special_items.py's containers.kinds
mechanarium_lever/_key/_upgrade/_sanctum hold their loot.

Colour-selective drafting (Secret Passage / Spare Secret Passage): a doorway
dealt with ``DraftContext.colour`` set restricts every slot to that one
category (Room.is_category), threaded through the single ``room_draftable``
gate so it composes for free with the priority draws, forced draws, and
category bias that already call it -- none of those need their own colour
guard. A thin colour's pool draw (the ordinary rank/rarity attempts 1-3)
falls back to the wiki's published default triple (priority_draws.json's
colour_defaults); for a colour-locked slot this default triple IS the final
fallback, standing in for the universal forced-Closet attempt 4, since
Closet's category is never one of the five selectable colours and the wiki
states the colour invariant with no exhaustion exception. Reserve copies --
the wiki's other thin-pool fallback, tried between the pool and the default
triple -- are deliberately not modelled (see docs/drafting.md's
colour-selective drafting section), so a default is still filtered through
room_draftable and can lose to the one-copy-per-grid rule like any other
candidate; if every default is unavailable too, the slot is left unfilled
rather than dealing an off-colour Closet. Game.open_door/choose_colour own
the doorway-level phase gating; this module only owns the deal itself.

Crown of the Blueprints: the same ``room_draftable`` gate also excludes any
room id the Crown has filtered for the rest of today, unconditionally (no
colour exemption -- owner ruling 2026-08-12 voids the wiki's claim that
colour-selective drafts, the Silver Key, the Prism Key, and ducts can still
draw a blocked Red Room). Game.can_crown_block/crown_block own the
player-choice side; this module only enforces the resulting filter.

Day 1 opening draw: the very first round of the very first draft of Day 1
fixes the whole hand to priority_draws.json's day1_opening_draw triple
(Bedroom, Closet, Hallway, in that order -- see _day1_active/
_day1_opening_draw_option), ahead of the Tunnel chain, Reading Nook Library,
Silver Key bias, Garage Forced Draw, and priority draws -- a wiki "Guaranteed
Draw", not one of this module's other three JSON-driven mechanisms
(priority_draws/forced_draws/category_biases).
"""

from __future__ import annotations

from ..config import GameConfig
from .decks import roll_rarity
from .grid import N, OPPOSITE, neighbor, rank_of, rotate_mask
from .model import Registry, Room
from .placement import legal_orientations, satisfies_draft_conditions
from .rng import Rng
from .rotation import orientation_weights
from .special_items import (
    chronograph_active_from_state,
    compass_active_from_state,
    crown_room_blocked_from_state,
    dowsing_rod_active_from_state,
    electromagnet_active_from_state,
)
from .state import DraftOption, GameState, PendingDraft, resolve_gem_cost
from .upgrades import root_base_id

CLOSET_ID = "closet"
DAY1_OPENING_DRAW_KEY = "day1_opening_draw"  # priority_draws.json top-level key
TUNNEL_ID = "tunnel"
READING_NOOK_ID = "reading_nook__ix99"
LIBRARY_ID = "library"
MECHANARIUM_ID = "mechanarium"
DARKROOM_ID = "darkroom"
AQUARIUM_EXPERIMENT_ID = "aquarium__experiment"
SECRET_PASSAGE_IDS = ("secret_passage", "spare_secret_passage__ix138")

# The five colours a Secret Passage door (or a Prism Key) can restrict a draft
# to (blueprince.wiki.gg/wiki/Drafting_effects#Color-selective_drafting). Not
# blueprint/blackprint -- "There is no way to select Blueprints or Blackprints
# specifically."
COLOUR_CATEGORIES = ("bedroom", "hallway", "green", "shop", "red")

def _category_matches(room: Room, entry: dict) -> bool:
    """True when ``room`` matches a category_biases entry's target category.

    Most entries are a plain ``Room.is_category`` check on ``category``. An
    entry may instead name a ``category_base`` plus ``category_extra_rooms``,
    for a target that is a category plus specific rooms outside it -- the
    Electro Magnet targets Mechanical Rooms plus the Rotunda, which is a
    blueprint room. The rooms live in the record so this stays generic.
    """
    base = entry.get("category_base")
    if base is not None:
        return (room.is_category(base)
                or room.id in entry.get("category_extra_rooms", ()))
    return room.is_category(entry["category"])


class DraftContext:
    """Bundles the per-draft references so helpers stay signature-light."""

    __slots__ = ("state", "registry", "cfg", "rng", "placed_ids", "from_room", "from_library",
                 "colour")

    def __init__(self, state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
                 placed_ids: set[str], from_room: Room | None,
                 colour: str | None = None) -> None:
        self.state = state
        self.registry = registry
        self.cfg = cfg
        self.rng = rng
        self.placed_ids = placed_ids
        self.from_room = from_room  # room being drafted FROM, or None (positional condition source)
        self.from_library = from_room is not None and from_room.id == "library"
        # Secret Passage colour-selective restriction; None for an ordinary hand.
        self.colour = colour


def room_draftable(ctx: DraftContext, room: Room, cell: int, entry_dir: int,
                   exclude: set[int],
                   tunnel_chain: bool = False) -> bool:
    """Full eligibility check for dealing ``room`` at the target doorway.

    Combines the one-copy-on-the-grid rule (waived entirely while the Chamber
    of Mirrors is placed, for Tunnels dealt via the chain, and for
    aquarium__experiment once add_aquariums has fired today), the room's
    draft conditions, and door-geometry legality. ``exclude`` holds room
    indices already dealt into earlier slots of this hand. While
    ``ctx.colour`` is set (a Secret Passage colour-selective draft), a room
    also needs to carry that colour (Room.is_category) and must not itself be
    a Secret Passage variant -- "The Secret Passage cannot itself be drawn
    during a color-selective draft" (wiki).

    Also excludes any room id the Crown of the Blueprints has filtered for
    the rest of today (``SpecialItemsState.crown_blocked_rooms``), with NO
    colour exemption -- owner ruling 2026-08-12 overrides the wiki's claim
    that a blocked Red Room stays obtainable through colour-selective drafts,
    the Silver Key, the Prism Key, or ducts. Checked unconditionally, ahead
    of the colour gate, so it applies to every candidate this function ever
    sees.
    """
    if room.idx in exclude:
        return False
    if crown_room_blocked_from_state(ctx.state, room.id):
        return False
    if ctx.colour is not None:
        if room.id in SECRET_PASSAGE_IDS:
            return False
        if not room.is_category(ctx.colour):
            return False
    if room.id in ctx.placed_ids and "chamber_of_mirrors" not in ctx.placed_ids:
        # Allow a second (or third) Tunnel when it is force-dealt from a Tunnel's
        # north exit (tunnel_chain=True).  The duplicate-id check would otherwise
        # block the chain once the first Tunnel is on the grid.  Allow any number
        # of aquarium__experiment copies once add_aquariums has fired: all three
        # (and every later injected copy) share this one id, so without this the
        # grid would cap at 2 total (the base Aquarium plus one experiment copy).
        # The base Aquarium itself keeps the ordinary one-copy limit -- only the
        # experiment-added id is named here.
        waived = (tunnel_chain and room.id == TUNNEL_ID) or (
            room.id == AQUARIUM_EXPERIMENT_ID and ctx.state.add_aquariums_active)
        if not waived:
            return False  # one copy of a room on the grid at a time
    if not satisfies_draft_conditions(room, cell, entry_dir, ctx.state, ctx.cfg,
                                      ctx.placed_ids, ctx.from_library):
        return False
    if not legal_orientations(room, cell, entry_dir, ctx.state, ctx.cfg):
        return False
    return True


def _deal_from_rarity(ctx: DraftContext, rarity_idx: int, slot: int, cell: int,
                      entry_dir: int, exclude: set[int], is_gem: bool) -> Room | None:
    """Deal the next eligible room of a rarity from the round's Free/Gem-classified
    deck (solitaire semantics).

    ``is_gem`` is this round's already-rolled Free/Gem Draw decision for
    ``slot`` (see :func:`_resolve_free_gem`; always False for slot 0, which the
    wiki pins as always-free). A Free Draw searches ONLY the free deck of
    ``rarity_idx``, a Gem Draw ONLY the gem deck -- the two are never combined
    for a single draw (blueprince.wiki.gg/wiki/Drafting/Advanced: "Free Draws
    only use the four decks made out of free rooms, while Gem Draws only use
    the four decks made out of gem rooms").
    """
    rooms = ctx.registry.rooms

    def pred(card: int) -> bool:
        return room_draftable(ctx, rooms[card], cell, entry_dir, exclude)

    card = ctx.state.deck(rarity_idx, is_gem).deal_next(pred)
    return rooms[card] if card is not None else None


def _priority_draw(ctx: DraftContext, cell: int, entry_dir: int,
                   exclude: set[int], is_gem: bool) -> Room | None:
    """Roll the priority draws (Patio group, Commissary/Observatory, Garage/Classroom,
    Tomorrow Rooms): an additional filter applied during attempt 1 of EVERY slot
    (blueprince.wiki.gg/wiki/Drafting/Advanced, Filters > Priority Draws) -- distinct
    from the Slot-3-only Forced Draw mechanism (_forced_draw_garage) it used to be
    conflated with.

    ``is_gem`` is this round's Free/Gem Draw decision for the slot being dealt (see
    :func:`_resolve_free_gem`): the priority filter is an additional filter applied
    within whichever Free/Gem group the round is already working in, so a candidate
    is only eligible when its own class (``not room.is_free``) matches ``is_gem`` --
    the same convention ``_deal_from_rarity`` uses via ``ctx.state.deck``.

    Each floorplan named by an active entry gets its OWN independent acceptance
    roll at the entry's chance -- "each floorplan has a chance to get accepted"
    (wiki) -- rather than one roll for the whole named group; this is what makes
    Commissary and Observatory (and Garage/Classroom) each independently reachable
    instead of the first room in list order winning outright whenever it happens
    to be draftable. Accepted rooms are then dealt through the same per-rarity deck
    machinery ``_deal_from_rarity`` uses (``deck.deal_next``), searching rarity 0..3
    in a fixed order (matching ``_deal_biased``'s existing "search every rarity"
    pattern for a biased re-deal), so a hit is actually removed from its deck --
    "the floorplan gets added to the discard filter for future draws" (wiki) --
    rather than staying available to be dealt again.

    An entry may carry an optional ``condition`` tag (the same vocabulary
    ``_active_conditions`` feeds to ``_apply_category_bias``'s ``category_biases``
    entries); such an entry is skipped, consuming no RNG, while that condition
    isn't active. The active-condition set is computed lazily, only once some
    entry actually carries a ``condition``, so the common (today: universal)
    unconditional path never pays for it.

    An entry targets its candidate rooms either with an explicit ``rooms`` list
    (a named, fixed set) or with a ``category`` selector, resolved here to every
    room currently carrying that category (``Room.is_category``) -- the
    Chronograph's Tomorrow Rooms bias uses ``category`` so its twelve room ids
    (including the Mail Room's three upgrade variants) are never hand-typed and
    stay correct if a variant is added later.
    """
    rooms = ctx.registry.rooms
    pool_ids = {rooms[c].id for d in ctx.state.decks for c in d.order}
    active: set[str] | None = None
    for entry in ctx.registry.priority["priority_draws"]:
        condition = entry.get("condition")
        if condition is not None:
            if active is None:
                active = _active_conditions(ctx)
            if condition not in active:
                continue
        chance = entry["chance"]
        if ctx.state.greenhouse_placed and "chance_with_greenhouse" in entry:
            chance = entry["chance_with_greenhouse"]
        entry_rooms = entry.get("rooms")
        if not entry_rooms:
            entry_rooms = [r.id for r in rooms if r.is_category(entry["category"])]

        accepted: set[str] = set()
        for rid in entry_rooms:
            if not (rid in pool_ids or rid in ctx.registry.by_id and
                    ctx.registry.by_id[rid].pool == "base"):
                continue
            room = ctx.registry.by_id.get(rid)
            if room is None or room.rarity is None or room.is_free == is_gem:
                continue
            if ctx.rng.chance(f"priority_{entry['label']}_{rid}", chance):
                accepted.add(rid)
        if not accepted:
            continue

        def pred(card: int, _accepted: set[str] = accepted) -> bool:
            r = rooms[card]
            return r.id in _accepted and room_draftable(ctx, r, cell, entry_dir, exclude)

        for rarity_idx in range(4):
            card = ctx.state.deck(rarity_idx, is_gem).deal_next(pred)
            if card is not None:
                return rooms[card]
    return None


def _garage_dead_end_gate(ctx: DraftContext, earlier_options: list[DraftOption]) -> bool:
    """Wiki gate: "the first two slots are not both a Dead End, or Slot 2 was not
    drawn by a normal draw" (1-indexed wiki Slot 2 = this engine's slot index 1).

    Reading: the Forced Draw attempt is blocked only when BOTH (a) slots 0 and 1
    are both Dead End rooms AND (b) slot index 1 was placed by a normal roll-based
    draw. "Normal draw" is read here as ``DraftOption.forced is False`` -- forced
    marks priority draws, the Tunnel chain guarantee, and the forced-Closet
    fallback, all of which bypassed the rarity lottery; a category-bias
    substitution is still treated as normal since it re-deals the same
    rarity-rolled slot rather than forcing a placement. If either slot hasn't
    been dealt yet (a rare failure path), "both Dead End" is trivially false and
    the gate passes.
    """
    if len(earlier_options) < 2:
        return True
    rooms = ctx.registry.rooms
    slot0_room = rooms[earlier_options[0].room_idx]
    slot1_room = rooms[earlier_options[1].room_idx]
    both_dead_end = slot0_room.layout == "dead_end" and slot1_room.layout == "dead_end"
    slot1_normal = not earlier_options[1].forced
    return not (both_dead_end and slot1_normal)


def _forced_draw_garage(ctx: DraftContext, cell: int, entry_dir: int, exclude: set[int],
                        earlier_options: list[DraftOption]) -> Room | None:
    """Roll the Garage's once-per-day Forced Draw into slot 3 (data/priority_draws.json
    "forced_draws"; blueprince.wiki.gg/wiki/Garage).

    Distinct from :func:`_priority_draw`: this targets one specific room's own
    draft conditions (not a named group), is gated on Veteran Mode/Day 3 and the
    slot-0/1 Dead-End clause, and can succeed (permanently disabling itself for
    today) even when the resulting placement then fails because the Garage
    already occupies an earlier slot of this same hand.
    """
    state, cfg = ctx.state, ctx.cfg
    if state.garage_forced_draw_succeeded:
        return None
    if not (cfg.veteran_mode or state.day >= 3):
        return None
    entry = next((e for e in ctx.registry.priority.get("forced_draws", [])
                  if e["room"] == "garage"), None)
    garage = ctx.registry.by_id.get("garage")
    if entry is None or garage is None:
        return None
    if not _garage_dead_end_gate(ctx, earlier_options):
        return None
    # "Spawning requirements met": the Garage's own draft conditions/geometry at
    # this doorway, ignoring same-hand dedup (exclude=set()) -- the wiki says the
    # roll still tries even if the Garage already occupies an earlier slot of
    # this hand; only the eventual placement fails in that case (checked below,
    # after the roll, against the caller's real `exclude`).
    if not room_draftable(ctx, garage, cell, entry_dir, set()):
        return None
    west_gate = cfg.west_gate_unlatched or state.west_gate_unlatched
    chance = entry["chance_with_west_gate"] if west_gate else entry["chance"]
    if not ctx.rng.chance(f"forced_draw_{entry['label']}", chance):
        return None
    # The roll has succeeded: no more Forced Draw attempts for the Garage today,
    # regardless of whether the placement below actually goes through.
    state.garage_forced_draw_succeeded = True
    if garage.idx in exclude:
        return None  # already dealt into an earlier slot this hand: draw fails regardless
    return garage


def _active_conditions(ctx: DraftContext) -> set[str]:
    """Return the category-bias condition tags that are currently satisfied.

    Most conditions are global (read off ``GameState``); a few are positional,
    keyed on the room being drafted FROM (``ctx.from_room``), which is why this
    takes the whole context rather than just ``state``.
    """
    state = ctx.state
    conds: set[str] = set()
    if state.furnace_placed:
        conds.add("furnace_or_king")
    if state.greenhouse_placed:
        conds.add("greenhouse_or_king")
    # Royal Scepter: once a color is activated, inject the scepter_<color> condition
    # so _apply_category_bias picks up the corresponding priority_draws.json entry.
    if state.shops.scepter_color is not None:
        conds.add(f"scepter_{state.shops.scepter_color}")
    if state.schoolhouse_placed:
        conds.add("schoolhouse")
    if state.southern_cross_active:
        conds.add("southern_cross_constellation")
    if state.draxus_active:
        conds.add("draxus_constellation")
    if state.add_aquariums_active:
        conds.add("add_aquariums")
    if electromagnet_active_from_state(state, ctx.registry):
        conds.add("electromagnet")
    if chronograph_active_from_state(state, ctx.registry):
        conds.add("chronograph")
    # King's Chess Piece (Banner of the King) is deliberately NOT emitted here: no
    # source models how the Banner is obtained or a per-day color pick, and the five
    # king_* tags must fire one at a time (mirroring scepter_<color>), never all at
    # once. See priority_draws.json's king_* entries for the shaped-but-inert tags.
    if ctx.from_library:
        conds.add("drafting_from_library")
    return conds


def _deal_biased(ctx: DraftContext, slot: int, cell: int,
                 entry_dir: int, exclude: set[int],
                 pred, is_gem: bool) -> Room | None:
    """Deal the first card passing ``pred`` from the round's Free/Gem-classified
    decks across all four rarities.

    ``is_gem`` is the same once-per-round decision ``_deal_from_rarity`` uses
    (see :func:`_resolve_free_gem`); callers pass False for slot 0, which is
    always free-only. Like ``_deal_from_rarity``, only ONE of the free/gem
    classes is ever searched -- the Silver Key cross/t bias and every
    category bias are still ordinary draws for Free/Gem Draw purposes.
    """
    rooms = ctx.registry.rooms
    for rarity_idx in range(4):
        card = ctx.state.deck(rarity_idx, is_gem).deal_next(pred)
        if card is not None:
            return rooms[card]
    return None


def _deal_cross_t_biased(ctx: DraftContext, slot: int, cell: int,
                         entry_dir: int, exclude: set[int], is_gem: bool) -> DraftOption | None:
    """Try to deal a cross/t-layout room for the Silver Key draft bias.

    Returns a DraftOption or None if no cross/t card qualifies; the caller
    then falls back to the normal draw. Silver Key wiki: biases toward cross/t
    layouts; straight/L is the fallback (modeled assumption).
    """
    rooms = ctx.registry.rooms

    def pred_cross_t(card: int) -> bool:
        r = rooms[card]
        return r.layout in ("cross", "t") and room_draftable(ctx, r, cell, entry_dir, exclude)

    room = _deal_biased(ctx, slot, cell, entry_dir, exclude, pred_cross_t, is_gem)
    if room is None:
        return None
    return _make_option(ctx, room, slot, cell, entry_dir)


def _apply_category_bias(ctx: DraftContext, room: Room, slot: int, cell: int,
                         entry_dir: int, exclude: set[int], is_gem: bool) -> Room:
    """After a normal draw, apply any active category biases.

    ``is_gem`` is the round's Free/Gem Draw decision for ``slot`` (see
    :func:`_resolve_free_gem`), threaded through to ``_deal_biased`` so a
    category-bias substitution still only searches the deck class the round
    already committed to for this slot -- it never lets a Free Draw slot
    surface a gem room, or vice versa.

    For each bias whose condition holds, roll its chance (via a dedicated named
    RNG substream that is only consumed when the bias is active).  On a hit,
    attempt to deal a room matching the target category/layout/flag from the
    remaining undealt cards.  If a matching room is found it replaces the
    original draw (the original stays consumed from its deck).  If no match is
    available the original draw is kept unchanged.

    A target category is usually a colour identity check (Furnace/Greenhouse/
    King's Chess Piece/Royal Scepter all bias toward drafting a room of that
    colour), so it goes through ``_category_matches`` and
    can match a multi-category room such as the Aquarium or Maid's Chamber on
    any colour it counts as. A few categories (see ``CATEGORY_UNIONS``) also
    pull in specific rooms outside that category, like the Electro Magnet's
    Rotunda.

    An entry can also carry ``exclude_rooms`` (specific ids to leave out) and
    ``exclude_upgrade_variants`` (drop every room with a ``variant_of``, the
    direct link an upgrade variant carries to the base room it replaces) —
    the Southern Cross's 4-way bias needs both to match the wiki's own query.
    """
    active = _active_conditions(ctx)
    if not active:
        return room

    rooms = ctx.registry.rooms

    for entry in ctx.registry.priority.get("category_biases", []):
        if entry.get("condition") not in active:
            continue
        if not ctx.rng.chance(f"cat_bias_{entry['label']}", entry["chance"]):
            continue

        target_cat = entry.get("category")
        target_layout = entry.get("layout")
        target_flag = entry.get("flag")
        target_room_ids = set(entry.get("rooms", []))
        exclude_room_ids = set(entry.get("exclude_rooms", []))
        exclude_upgrade_variants = entry.get("exclude_upgrade_variants", False)

        def _pred(card: int,
                  _tc=target_cat, _entry=entry, _tl=target_layout,
                  _tf=target_flag,
                  _tr=target_room_ids, _xr=exclude_room_ids,
                  _xu=exclude_upgrade_variants) -> bool:
            r = rooms[card]
            if _tr and r.id not in _tr:
                return False
            if _xr and r.id in _xr:
                return False
            if _xu and r.variant_of is not None:
                return False
            if _tc and not _category_matches(r, _entry):
                return False
            if _tl and r.layout != _tl:
                return False
            if _tf == "powered" and not r.powered:
                return False
            if _tf == "duct" and not r.duct:
                return False
            return room_draftable(ctx, r, cell, entry_dir, exclude)

        biased = _deal_biased(ctx, slot, cell, entry_dir, exclude, _pred, is_gem)
        if biased is not None:
            room = biased

    return room


def _colour_default_triple(ctx: DraftContext, colour: str) -> tuple[str, ...]:
    """This colour's default floorplans, in the order the deal should try them.

    Read from priority_draws.json's colour_defaults rather than named here, so
    the published table stays data. Its swap rule replaces one default with
    another while a listed upgrade is applied -- the Cloister leaves green when
    upgraded, and the Solarium takes its place.
    """
    defaults = ctx.registry.priority["colour_defaults"]
    triple = tuple(defaults["triples"][colour])
    swap = defaults.get("swap")
    if (swap is not None and colour == swap["colour"]
            and any(v in ctx.state.applied_upgrades for v in swap["swap_when_upgraded"])):
        triple = tuple(swap["with"] if rid == swap["replace"] else rid for rid in triple)
    return triple


def _deal_colour_default(ctx: DraftContext, cell: int, entry_dir: int,
                         exclude: set[int]) -> Room | None:
    """First of ``ctx.colour``'s published default floorplans still draftable here.

    Tried in wiki order through the same ``room_draftable`` gate as any other
    candidate, so a default can never relax the out-drafting invariant or
    duplicate a room already on the grid -- the reserve-copy tier that would
    allow that is deliberately not modelled. Returns None if all three are
    unavailable here (the caller then falls through to the forced-Closet
    attempt, same as an ordinary exhausted slot).
    """
    assert ctx.colour is not None
    for room_id in _colour_default_triple(ctx, ctx.colour):
        room = ctx.registry.by_id.get(room_id)
        if room is not None and room_draftable(ctx, room, cell, entry_dir, exclude):
            return room
    return None


def _free_gem_table(ctx: DraftContext) -> dict:
    """The ``free_gem_draws`` section of weights.json (published table, not code)."""
    return ctx.registry.weights["free_gem_draws"]


def _resolve_free_gem(ctx: DraftContext, rank: int, round_num: int) -> tuple[bool, bool]:
    """Roll the once-per-round Free/Gem Draw decision (blueprince.wiki.gg/wiki/
    Drafting/Advanced "Free/Gem Draws"). Returns ``(slot1_is_gem, slot2_is_gem)``
    using THIS ENGINE's 0-indexed slots: wiki Slot 2 -> engine slot 1, wiki
    Slot 3 -> engine slot 2 (wiki Slot 1 -> engine slot 0 is always free and is
    handled entirely by callers, never here).

    Rolled exactly once per round (not once per slot) via ``_fill_options``,
    since a single Slot-2 success also forces Slot 3 to Gem. Two fresh named
    RNG substreams are used (``free_gem_slot2``/``free_gem_slot3``), neither
    reused anywhere else in the engine, so this cannot perturb any existing
    golden transcript.

    Quoting the wiki verbatim, in the order this function evaluates it:

        First, certain draws are always Free Draws:
        * Slot 1 always makes a Free Draw.
        * On Day 1-3, all draws will be Free Draws in the first few drafts:
        ** If Veteran Mode is enabled, the first 2 drafts always produce Free
           Draws.
        ** Otherwise, the first (6-Day) drafts always produce Free Draws.

        If the condition above is not met, Slot 2 has a chance to become a
        Gem Draw, based on rank and the amount of gems you have: [see
        weights.json's free_gem_draws.slot2_gem_chance for the 9x3 table]

        If this chance succeeds, both Slot 2 and Slot 3 become Gem Draws.
        Otherwise, Slot 2 is a Free Draw, and there is an additional chance
        for Slot 3 to become a Gem Draw:
        * If this is the third round or later this draft, Slot 3 is always a
          Gem Draw.
        * In the first two drafts:
        ** If you have 2+ gems, there is a 20% chance for a Gem Draw, 80% for
           a Free Draw.
        ** Otherwise, it is always a Free Draw.
        * In the first five drafts: If you have 0-1 gems, there is a 20%
          chance for a Gem Draw, 80% for a Free Draw.
        * Otherwise, the probability for a Gem Draw is based on rank: [see
          weights.json's free_gem_draws.slot3_rank_chance]
        Otherwise, Slot 3 becomes a Free Draw.

    The day-1-3/Veteran-Mode carve-out and the "third round or later"/"first
    two drafts"/"first five drafts" thresholds are formulas, not published
    numbers, so they are code here rather than duplicated into weights.json
    (matching deck_size_gates.gem_gate_condition's existing code/data split);
    only the percentages themselves (the 9x3 table, 20%, 93.75/87.5/75) are
    read from ``free_gem_draws``.
    """
    state, cfg, rng = ctx.state, ctx.cfg, ctx.rng

    if state.day in (1, 2, 3):
        limit = 2 if cfg.veteran_mode else (6 - state.day)
        if state.drafts_today <= limit:
            return False, False

    table = _free_gem_table(ctx)
    gems = state.gems
    gem_bucket = 0 if gems == 0 else (1 if gems <= 3 else 2)
    slot2_chance = table["slot2_gem_chance"][str(rank)][gem_bucket] / 100.0
    if rng.chance("free_gem_slot2", slot2_chance):
        return True, True

    if round_num >= 3:
        return False, True
    low_chance = table["slot3_low_gem_chance"] / 100.0
    if state.drafts_today <= 2:
        if gems < 2:
            return False, False
        return False, rng.chance("free_gem_slot3", low_chance)
    if state.drafts_today <= 5 and gems <= 1:
        return False, rng.chance("free_gem_slot3", low_chance)
    rank_chance = table["slot3_rank_chance"][str(rank)] / 100.0
    return False, rng.chance("free_gem_slot3", rank_chance)


def draw_slot(ctx: DraftContext, slot: int, cell: int, entry_dir: int,
              exclude: set[int], earlier_options: list[DraftOption] = (),
              is_gem: bool = False) -> DraftOption | None:
    """Fill one option slot via the four-attempt procedure.

    ``earlier_options`` holds the already-dealt slot-0/1 options of this hand
    (only meaningful, and only passed, at ``slot == 2``); it feeds the Garage
    Forced Draw's Dead-End gate. ``is_gem`` is this round's Free/Gem Draw
    decision for ``slot`` (see :func:`_resolve_free_gem`; callers pass False
    for slot 0, always-free by the wiki's own rule) -- attempts 1-3 below only
    ever deal from the matching free-or-gem deck class, never both.
    """
    state, registry, cfg, rng = ctx.state, ctx.registry, ctx.cfg, ctx.rng
    rank = rank_of(cell)

    # Forced draws push one specific room into slot 3 with a very high chance,
    # ahead of the named-group priority draws below (see _forced_draw_garage).
    if slot == 2:
        forced = _forced_draw_garage(ctx, cell, entry_dir, exclude, list(earlier_options))
        if forced is not None:
            return _make_option(ctx, forced, slot, cell, entry_dir, forced_draw=True)

    # Priority draws: an additional attempt-1-only filter, applied to every
    # slot (not just slot 3 -- see _priority_draw's docstring for the wiki
    # citation distinguishing this from the Forced Draw above).
    forced = _priority_draw(ctx, cell, entry_dir, exclude, is_gem)
    if forced is not None:
        return _make_option(ctx, forced, slot, cell, entry_dir, forced_draw=True)

    # Attempts 1 & 2 (identical here once the priority filter has run above).
    for _attempt in (1, 2):
        rarity = roll_rarity(state, registry, cfg, rng, slot, rank, ctx.from_library)
        if rarity is not None:
            room = _deal_from_rarity(ctx, rarity, slot, cell, entry_dir, exclude, is_gem)
            if room is not None:
                room = _apply_category_bias(ctx, room, slot, cell, entry_dir, exclude, is_gem)
                return _make_option(ctx, room, slot, cell, entry_dir)

    # Attempt 3: reshuffle every deck and retry once.
    for i, deck in enumerate(state.decks):
        deck.reshuffle(lambda lst, i=i: rng.shuffle(f"reshuffle_{i}", lst))
    rarity = roll_rarity(state, registry, cfg, rng, slot, rank, ctx.from_library)
    if rarity is not None:
        room = _deal_from_rarity(ctx, rarity, slot, cell, entry_dir, exclude, is_gem)
        if room is not None:
            room = _apply_category_bias(ctx, room, slot, cell, entry_dir, exclude, is_gem)
            return _make_option(ctx, room, slot, cell, entry_dir)

    # Colour-selective draft (Secret Passage): the pool is thin, so fall back
    # to the published default triple -- see _deal_colour_default. This is
    # the wiki's own fallback ladder for a colour-selective draft (draft pool
    # -> reserve copies [not modelled, see this module's docstring] ->
    # default triple); "During a color-selective draft, only floorplans of
    # that color can be drawn" is stated with no exhaustion exception
    # (blueprince.wiki.gg/wiki/Drafting_effects#Color-selective_drafting), so
    # the universal forced-Closet attempt below -- which belongs to
    # *ordinary* drafting only (Drafting/Advanced#Normal Draws: "Normal
    # drawing does not normally occur when ... drafting [from a] Secret
    # Passage") -- must never run for a colour-locked slot: Closet's category
    # is "blueprint", never one of the five selectable colours.
    if ctx.colour is not None:
        room = _deal_colour_default(ctx, cell, entry_dir, exclude)
        if room is not None:
            return _make_option(ctx, room, slot, cell, entry_dir, forced_draw=True)
        # Every default is also unavailable here (all three already placed or
        # geometrically illegal at this doorway). This branch is reachable
        # ONLY because the wiki's reserve-copies tier -- which sits between
        # the pool and the default triple and would almost certainly have
        # supplied something on-colour before exhaustion -- is not modelled
        # (see this module's docstring); it is a modelling artifact, not a
        # game rule. The slot is left unfilled, the same already-precedented
        # outcome as the ordinary forced-Closet-already-excluded edge case
        # below (see _fill_options' Reading Nook docstring); the caller
        # (Game.open_door/choose_colour) falls back to NAVIGATE when the
        # whole hand ends up empty this way, rather than parking in DRAFTING
        # with nothing to choose.
        return None

    # Attempt 4: forced Closet - cannot fail (Closet is a free commonplace
    # dead end, so it always has a legal orientation). Ordinary drafting
    # only -- a colour-selective draft never reaches this line (see above).
    closet = registry.by_id.get(CLOSET_ID)
    if closet is not None and closet.idx not in exclude:
        return _make_option(ctx, closet, slot, cell, entry_dir, forced_draw=True)
    return None


def _mechanarium_orientation(ctx: DraftContext, cell: int, entry_dir: int) -> int:
    """Derive the Mechanarium's door mask at draft time -- never rolled.

    Wiki (blueprince.wiki.gg/wiki/Mechanarium): "it contains one doorway per
    Mechanical room in the estate, including the Mechanarium itself. The
    first door is always the one that the Mechanarium is drafted from... The
    next doors that spawn are forward, left and right drafting doors that
    lead into open space. If a Mechanarium doorway would lead in an existing
    room... If that room has no door at that position... the Mechanarium
    skips that doorway and tries again at the next position." The count and
    orientation are "set in stone the moment it is drafted" -- later
    Mechanical-room drafts never add doors to an already-placed Mechanarium.

    ``entry_dir`` is the direction the player moved to reach ``cell`` (see
    grid.py), so "forward" continues that same direction; "left"/"right" are
    its counterclockwise/clockwise quarter turns under this grid's N/E/S/W
    bit convention (rotate_mask's quarter-turn direction).

    A skipped candidate (an occupied neighbour with no facing door) does not
    consume its slot -- the next candidate direction gets the door instead
    (owner ruling). An empty neighbour, or one with a facing door, is fine.
    Capped at the four cardinal directions; surplus Mechanical rooms open
    diagonal compartments instead, seeded separately by
    effects/rooms/mechanarium.py once this mask is actually placed (see
    module docstring) -- not derived here, since that seeding needs the
    Mechanarium's own final placed-door popcount, not this preview mask.
    """
    rooms = ctx.registry.rooms
    mechanical_rooms = sum(
        1 for idx in ctx.state.grid if idx >= 0 and rooms[idx].is_category("mechanical"))
    # n = mechanical_rooms + 1 (this Mechanarium, not yet placed); the back door
    # already accounts for one of the n doors, so n - 1 remain to be tried below,
    # capped at 3 (forward/left/right -- the fourth and last cardinal direction).
    doors_left = min(mechanical_rooms, 3)
    back = OPPOSITE[entry_dir]
    mask = back
    forward = entry_dir
    right = rotate_mask(entry_dir, 1)
    left = rotate_mask(entry_dir, 3)
    for d in (forward, left, right):
        if doors_left <= 0:
            break
        nb = neighbor(cell, d)
        if nb == -1:
            continue  # never a door; unreachable under interior_only, kept defensively
        if ctx.state.grid[nb] != -1 and not ctx.state.placed_doors[nb] & OPPOSITE[d]:
            continue  # occupied neighbour has no facing door: skip without consuming the slot
        mask |= d
        doors_left -= 1
    return mask


def _make_option(ctx: DraftContext, room: Room, slot: int, cell: int, entry_dir: int,
                 forced_draw: bool = False) -> DraftOption:
    """Build the DraftOption for a dealt room, rolling its floorplan orientation.

    A single legal orientation is taken as-is; otherwise the datamined
    south-biased roll picks one. Slot 0 is always free; other slots carry the
    room's resolved gem cost. ``forced_draw`` marks priority-draw, forced-
    Closet, and Tunnel-chain deals. The Mechanarium's mask is derived instead
    (see _mechanarium_orientation) and consumes no "orientation" RNG draw.
    """
    if room.id == MECHANARIUM_ID:
        orientation = _mechanarium_orientation(ctx, cell, entry_dir)
    else:
        orientations = legal_orientations(room, cell, entry_dir, ctx.state, ctx.cfg)
        if not orientations:  # forced Closet fallback path
            orientations = [room.door_mask]
        if len(orientations) == 1:
            orientation = orientations[0]
        else:
            # A drawn floorplan is rolled into a legal orientation with datamined,
            # south-biased weights (the Ornate Compass flips the bias northward).
            weights = orientation_weights(orientations, OPPOSITE[entry_dir],
                                          ctx.state.day,
                                          compass_active_from_state(
                                              ctx.state, ctx.registry, ctx.cfg))
            orientation = orientations[ctx.rng.roll_weighted("orientation", weights)]
    cost = 0 if slot == 0 else resolve_gem_cost(room, ctx.state, ctx.registry.rooms)
    return DraftOption(room_idx=room.idx, orientation=orientation, gem_cost=cost,
                       slot=slot, forced=forced_draw)


def _tunnel_chain_option(ctx: DraftContext, cell: int, entry_dir: int) -> DraftOption | None:
    """Return the guaranteed slot-0 Tunnel option for drafting north from a Tunnel cell.

    The Tunnel's chain-draft effect: opening the north door of a placed Tunnel
    guarantees a Tunnel in slot 0 of the normal three-slot hand (see
    ``_fill_options``), provided the Tunnel is still legal at the target cell
    (rank_gte_2 / rank_lte_8 conditions + valid orientation).  This helper
    itself consumes no RNG: the orientation is always N|S (the Tunnel's only
    valid mask — a straight room drafted through a N doorway must be oriented
    N-S).

    Returns None if the Tunnel is illegal at the target (chain ends naturally,
    and the caller deals slot 0 normally instead).
    """
    tunnel = ctx.registry.by_id.get(TUNNEL_ID)
    if tunnel is None:
        return None
    # Check legality with tunnel_chain=True to allow duplicate placement.
    if not room_draftable(ctx, tunnel, cell, entry_dir, set(), tunnel_chain=True):
        return None
    # Tunnel is a straight room; the only valid N-S orientation is N|S (=5).
    # legal_orientations will confirm this — we trust it to stay N|S.
    orientations = legal_orientations(tunnel, cell, entry_dir, ctx.state, ctx.cfg)
    if not orientations:
        return None
    # There is only one legal orientation for a straight drafted northward (N|S).
    orientation = orientations[0]
    return DraftOption(room_idx=tunnel.idx, orientation=orientation, gem_cost=0,
                       slot=0, forced=True)


def _day1_active(ctx: DraftContext, pending: PendingDraft) -> bool:
    """True only for the very first round of the very first draft of Day 1.

    "The very first draw on Day 1 is Bedroom, Closet, and Hallway in that
    order" (blueprince.wiki.gg/wiki/Drafting/Advanced, Special Draws >
    Guaranteed Draws). ``state.drafts_today`` is already incremented by
    ``deal_draft`` before ``_fill_options`` runs, so it reads 1 on the day's
    first draft; ``pending.round_num`` is 1 only for the initial deal, not a
    redraw -- excluded defensively even though nothing on Day 1's first
    doorway can trigger a redraw before any room besides the pre-placed
    Entrance Hall/Antechamber exists. "Ending Day 1 without drafting skips
    this forced draw" needs no extra code: the guarantee only ever runs from
    inside an actual draft.
    """
    return ctx.state.day == 1 and ctx.state.drafts_today == 1 and pending.round_num == 1


def _day1_opening_draw_option(ctx: DraftContext, slot: int, cell: int, entry_dir: int) -> DraftOption:
    """Force ``slot`` to Day 1's published opening triple (data/priority_draws.json's
    day1_opening_draw: Bedroom/Closet/Hallway, in that order -- engine slot 0/1/2).

    A Guaranteed Draw, not a Priority/Forced Draw or category bias -- the wiki
    places it under "Special Draws", which "try to occur" BEFORE "using the
    normal drafting algorithm", so (like the Tunnel and Reading Nook Library
    guarantees) this never rolls a rarity or consults the round's Free/Gem
    Draw decision, and (like Reading Nook Library) never runs the ordinary
    draftability gate (``room_draftable``) -- the option is built
    unconditionally through ``_make_option``'s forced-orientation fallback, so
    the guarantee cannot fail regardless of doorway geometry. The room is
    still dealt from its own deck (searched free-then-gem, matching
    ``_reading_nook_library_option``) so it is actually removed from the
    draft pool -- "the floorplan gets added to the discard filter for future
    draws" is the same wiki language ``_priority_draw`` cites for its own
    per-floorplan removal -- keeping later draws today from misreading a
    card that this hand already spent.
    """
    room_id = ctx.registry.priority[DAY1_OPENING_DRAW_KEY]["rooms"][slot]
    room = ctx.registry.by_id[room_id]
    for is_gem in (False, True):
        if ctx.state.deck(room.rarity_idx, is_gem).deal_next(lambda c: c == room.idx) is not None:
            break
    return _make_option(ctx, room, slot, cell, entry_dir, forced_draw=True)


def _reading_nook_library_option(ctx: DraftContext, cell: int, entry_dir: int) -> DraftOption:
    """Force LIBRARY into slot 2 for a hand dealt from the Reading Nook's own doorway.

    "the floorplan in the third slot will always be the Library. This happens
    even if floorplans are redrawn; even if the Library is no longer in the
    draft pool due to being drafted elsewhere; even when using Silver Key or
    Prism Key; and even if it has been removed entirely via Repellent."
    (blueprince.wiki.gg/wiki/Nook/Upgrades)

    A Library card is still pulled from its own rarity's decks when one
    remains -- "drafting the Library this way will still pull it from the
    draft pool" -- but the option itself is built unconditionally through
    _make_option's forced-orientation fallback, so an empty deck (or a
    Repellent ban, which only ever affects deck membership) never breaks the
    guarantee.
    """
    library = ctx.registry.by_id[LIBRARY_ID]
    for is_gem in (False, True):
        deck = ctx.state.deck(library.rarity_idx, is_gem)
        if deck.deal_next(lambda c: c == library.idx) is not None:
            break
    return _make_option(ctx, library, 2, cell, entry_dir, forced_draw=True)


def _pick_dowsing_slot(ctx: DraftContext, pending: PendingDraft) -> None:
    """Point a held Dowsing Rod at one of this hand's dealt options.

    Wiki (Dowsing_Rod page, main body): while drafting, the Rod's model
    "settl[es] on one of the three floorplans. Choosing and drafting that
    floorplan after this point triggers the Dowsing Rod's effect"; "If
    floorplans are redrawn, the Dowsing Rod will reselect one of the new
    floorplans." Called from ``_fill_options``, shared by ``deal_draft`` (the
    initial deal) and ``redeal`` (every redraw), so a fresh pick happens
    every single time this function runs -- satisfying "reselect" for free,
    with no separate redraw-specific code path. Also called directly by
    ``game.py``'s ``_deal_outer_options`` (both the initial outer-room deal
    and every outer redraw), since the outer draft is drafting "like the
    doors in the house" (wiki, West_Path page) and this pick is a drafting
    effect unrelated to the draft pool's composition -- the same reasoning
    that lets Study/die redraws apply there too. Sharing this one function
    keeps the reselect-on-redraw guarantee and the avoid-list preference
    identical between the grid and outer pipelines rather than risking a
    second, divergent copy.

    Its own 26-room avoid-list DataMinedBox: "In the case that all three
    offered rooms are one of the rooms on this list, the Dowsing Rod will
    still pick one of them; in all other cases it picks a different room" --
    read as: prefer a dealt slot whose room is NOT on
    ``data/items.json``'s ``dowsing_rod.avoid_rooms`` (matched via
    ``upgrades.root_base_id``, so an upgraded variant of an avoid-listed
    room -- e.g. Hallway Closet -- still counts as that family); if every
    dealt slot is avoid-listed, any of them is fair game. The wiki does not
    publish a distribution among the eligible candidates; uniform is the
    modelled assumption. Uses a fresh, dedicated RNG label
    ("dowsing_rod_slot") never consumed anywhere else in the engine, so
    holding the Rod cannot perturb any existing golden transcript.

    Sets ``pending.dowsed_slot`` to the picked ``DraftOption.slot`` (0..2),
    or ``None`` while the Rod is not held, special items are disabled, or
    the hand ended up with no dealt options at all (the rare forced-Closet-
    already-excluded failure -- see ``draw_slot``'s docstring).
    """
    pending.dowsed_slot = None
    if not ctx.cfg.special_items:
        return
    if not dowsing_rod_active_from_state(ctx.state, ctx.registry):
        return
    if not pending.options:
        return
    avoid = ctx.registry.item_rules["dowsing_rod"]["avoid_rooms"]
    rooms = ctx.registry.rooms

    def _avoided(opt: DraftOption) -> bool:
        return root_base_id(ctx.registry, rooms[opt.room_idx]) in avoid

    preferred = [opt for opt in pending.options if not _avoided(opt)]
    candidates = preferred if preferred else pending.options
    pending.dowsed_slot = ctx.rng.choice("dowsing_rod_slot", candidates).slot


def _fill_options(ctx: DraftContext, pending: PendingDraft, from_room: Room | None) -> None:
    """Deal the three option slots, then apply concealment.

    Two independent passes, composed rather than computed as one index:

    - Darkroom (from-room, live-read every deal/redraw): while
      ``state.darkroom_lights_on`` is False, every option dealt from its
      doorway is hidden face-down.
    - Archives (house-wide, non-stacking): once ``state.archives_active`` is
      set, every draft through any doorway archives exactly one of its three
      dealt options -- a uniformly random slot, drawn from its own named RNG
      stream. An archived option is always also hidden (``archived`` implies
      ``hidden``, never the converse).

    A hidden or archived option is still fully draftable; only its identity
    and orientation are concealed from the player (and from the RL
    observation). The two effects compose: a Darkroom hand dealt with an
    Archives on the estate has all three options hidden and exactly one of
    them archived.

    Tunnel chain: drafting north from a placed Tunnel deals a normal
    three-slot hand with slot 0 guaranteed to be a Tunnel — the wiki
    (blueprince.wiki.gg/wiki/Drafting/Advanced) states "When drafting from a
    Tunnel, a Tunnel is drawn into Slot 1", and its 1-indexed Slot 1 is this
    engine's slot 0 (confirmed by the same page's "Slot 1 always makes a Free
    Draw", matching slot 0's existing free-only convention here). Slots 1 and
    2 are dealt through the ordinary pipeline and cannot re-deal a second
    Tunnel (its index is pre-excluded). The guaranteed Tunnel is marked
    ``forced`` — like a priority draw, it bypassed the rarity lottery even
    though (like a priority draw) it sits alongside two ordinarily-dealt
    options; it is a real, choosable slot, not a sole non-choice. The chain
    ends naturally when the Tunnel is illegal at the target (rank 9 blocked by
    rank_lte_8, or the target already occupied) — slot 0 then falls back to an
    ordinary draw, so the hand is three ordinary options with no Tunnel.

    Reading Nook: slot 2 is always LIBRARY when ``from_room`` is
    reading_nook__ix99 (see _reading_nook_library_option), on both the
    initial deal and every redraw (redeal() calls this same function). If an
    earlier slot in the same hand fails to deal at all — the pre-existing,
    exceedingly rare forced-Closet-already-excluded failure in draw_slot —
    the guarantee still targets list index 2 specifically, which then lands
    on a visually earlier option than "third"; that already-rare edge case is
    not special-cased further here.

    Colour-selective draft (``pending.colour`` set): the Silver Key's cross/t
    bias is skipped entirely rather than merely narrowed by the colour filter
    -- "If the Silver Key is used in the Secret Passage, the Secret Passage's
    effect will take priority and the Silver Key's effect is ignored" (wiki).
    Every other pass (Foundation removal, Darkroom/Archives concealment) is
    unaffected; ``room_draftable`` (see its docstring) is what keeps every
    slot on-colour.

    Crown of the Blueprints: every call here deals a fresh hand (the initial
    deal via ``deal_draft``, or a redraw via ``redeal``), so the Crown's
    once-per-hand filter option becomes available again right here --
    "unlimited hands" per the owner ruling. See
    ``SpecialItemsState.crown_block_used``.
    """
    ctx.state.special.crown_block_used = False
    # Tunnel chain-draft: north exit of a placed Tunnel guarantees a Tunnel in
    # slot 0 of an otherwise-normal three-slot hand (see docstring above).
    exclude: set[int] = set()
    tunnel_forced_option: DraftOption | None = None
    if (from_room is not None and from_room.id == TUNNEL_ID
            and pending.direction == N):
        tunnel_forced_option = _tunnel_chain_option(ctx, pending.target_cell, pending.direction)
        if tunnel_forced_option is not None:
            exclude.add(tunnel_forced_option.room_idx)

    # The Foundation: wiki says drafting on Rank 3 has a 90% chance to remove
    # it from the draft pool "for that draft" - rolled ONCE per hand (not once
    # per card, which would make the RNG draw count depend on deck order and
    # break determinism), and only when the Foundation could otherwise be dealt
    # at all (not already on the grid), to avoid disturbing the RNG stream on
    # doorways where it was never a candidate. See docs/foundation-design.md.
    foundation = ctx.registry.by_id.get("the_foundation")
    if (foundation is not None and foundation.id not in ctx.placed_ids
            and rank_of(pending.target_cell) == 3
            and ctx.rng.chance("foundation_rank3", 0.90)):
        exclude.add(foundation.idx)

    # Free/Gem Draws: rolled ONCE per round (draft.py::_resolve_free_gem),
    # ahead of the per-slot loop, since a Slot-2 Gem success also forces
    # Slot 3 to Gem -- see that function's docstring for the full cascade and
    # the wiki passage it implements. Engine slot 0 (wiki Slot 1) is always
    # free and never consults this.
    is_gem_by_slot = (False,) + _resolve_free_gem(
        ctx, rank_of(pending.target_cell), pending.round_num)

    # Silver Key: on the initial deal, try cross/t layouts first for each slot,
    # falling back to the normal draw when no cross/t card qualifies. Ignored
    # outright during a colour-selective draft (see docstring above).
    # Redraws clear the flag before calling _fill_options via redeal (flag already False).
    silver_key_bias = ctx.state.special.silver_key_draft and ctx.colour is None
    # Day 1 opening draw: the very first round of the very first draft of Day 1
    # fixes all three slots to the published triple, ahead of every other
    # guarantee below (none of which can legitimately fire on this same draw
    # anyway -- see _day1_active's docstring).
    day1_opening = _day1_active(ctx, pending)
    for slot in range(3):
        if day1_opening:
            opt = _day1_opening_draw_option(ctx, slot, pending.target_cell, pending.direction)
            pending.options.append(opt)
            exclude.add(opt.room_idx)
            continue
        if slot == 0 and tunnel_forced_option is not None:
            pending.options.append(tunnel_forced_option)
            continue
        if slot == 2 and from_room is not None and from_room.id == READING_NOOK_ID:
            # Reading Nook: slot 2 is always LIBRARY, ahead of (and instead
            # of) the Silver Key bias, the Garage Forced Draw, and the
            # priority draws -- see _reading_nook_library_option.
            opt = _reading_nook_library_option(ctx, pending.target_cell, pending.direction)
        else:
            opt = None
            if silver_key_bias:
                opt = _deal_cross_t_biased(ctx, slot, pending.target_cell,
                                           pending.direction, exclude, is_gem_by_slot[slot])
            if opt is None:
                opt = draw_slot(ctx, slot, pending.target_cell, pending.direction, exclude,
                                pending.options, is_gem=is_gem_by_slot[slot])
        if opt is not None:
            pending.options.append(opt)
            exclude.add(opt.room_idx)
    # Clear after the initial deal; redraws of this hand use normal odds.
    ctx.state.special.silver_key_draft = False

    _pick_dowsing_slot(ctx, pending)

    # Darkroom: obscures every option dealt from its own doorway while its
    # lights are off (effects/rooms/darkroom.py flips the switch off on first
    # entry, unless negated -- see its docstring).
    if (from_room is not None and from_room.id == DARKROOM_ID
            and not ctx.state.darkroom_lights_on):
        for opt in pending.options:
            opt.hidden = True

    # Archives: house-wide once placed (effects/rooms/archives.py), applies to
    # every doorway's hand, not just its own -- archives exactly one slot,
    # uniformly at random, independently of the Darkroom pass above.
    if ctx.state.archives_active and pending.options:
        idx = ctx.rng.randint("archives_slot", 0, len(pending.options) - 1)
        pending.options[idx].hidden = True
        pending.options[idx].archived = True


def deal_draft(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
               placed_ids: set[str], from_cell: int, direction: int,
               target_cell: int, colour: str | None = None) -> PendingDraft:
    """Deal a fresh three-option hand for the doorway ``from_cell`` -> ``target_cell``.

    Entry point used by ``Game.open_door``/``Game.choose_colour`` the first
    time a doorway is opened (the result is cached per doorway, so reopening
    shows the same hand). Library no-draft filtering, Darkroom hiding, and
    the Tunnel chain all key off the room being drafted FROM; Archives hiding
    keys off house state instead (see ``_fill_options``). ``colour``
    restricts every slot to one of COLOUR_CATEGORIES (Secret Passage
    variants only); it is stamped onto the returned ``PendingDraft`` so a
    later ``redeal`` of this same hand stays on-colour without the caller
    having to pass it again.

    Increments ``state.drafts_today`` first, so the hand being dealt sees its
    own (1-indexed) draft number -- draft.py::_resolve_free_gem's "first N
    drafts" rules read this. A cached-hand reopen of the same doorway never
    reaches this function at all (Game._deal_and_cache only calls it on a
    cache miss), so a doorway only ever counts once no matter how many times
    it is reopened.
    """
    state.drafts_today += 1
    from_room = registry.rooms[state.grid[from_cell]] if state.grid[from_cell] >= 0 else None
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_room, colour=colour)
    pending = PendingDraft(from_cell=from_cell, direction=direction, target_cell=target_cell,
                           colour=colour)
    _fill_options(ctx, pending, from_room)
    return pending


def redeal(state: GameState, registry: Registry, cfg: GameConfig, rng: Rng,
           placed_ids: set[str], pending: PendingDraft) -> None:
    """Redraw all three options in place (Study / Classroom / dice redraw).

    Reuses ``pending.colour`` (set by the original ``deal_draft``) so a
    redraw of a colour-selective hand stays restricted to the same colour.
    Bumps ``pending.round_num`` first (this is a new round of the SAME draft,
    not a new draft -- ``state.drafts_today`` is untouched), which is what
    lets draft.py::_resolve_free_gem's "third round or later this draft"
    Slot 3 rule ever fire.
    """
    pending.round_num += 1
    from_room = registry.rooms[state.grid[pending.from_cell]] \
        if state.grid[pending.from_cell] >= 0 else None
    ctx = DraftContext(state, registry, cfg, rng, placed_ids, from_room, colour=pending.colour)
    pending.options.clear()
    pending.rotations_used = 0  # fresh hand, fresh rotation budget
    _fill_options(ctx, pending, from_room)
