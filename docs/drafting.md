# Draw behavior: the drafting algorithm

How a hand of 1-of-3 room options is produced when the player opens a
doorway. This reproduces the decompiled v1.3 algorithm; the code path is
`engine/decks.py` → `engine/draft.py` → `engine/placement.py` →
`engine/rotation.py`.

## Decks

Eight solitaire decks are built at day start from the enabled pools: 4
rarities (commonplace / standard / unusual / rare) × free / gem-cost
(`engine/decks.py`). Dealing is solitaire-style — a dealt room does not
repeat until its deck depletes and reshuffles. Rooms injected during the
day (The Pool, Pool Hall, Schoolhouse) are shuffled into the live decks via
`inject_rooms`, which reshuffles the whole target deck and rewinds its
cursor — correct for those once-per-day callers.

A card's effective rarity IS the deck it sits in — dealing never reads a
card's own rarity, only the rarity index handed to it. Two primitives move
cards between decks without disturbing the rest: `inject_rooms_undealt`
(for an effect that injects copies many times a day, so a whole-deck
reshuffle would keep un-dealing already-drawn cards) and
`set_dynamic_rarity` (moves a room's cards to a different rarity's deck of
the same free/gem class for the day, tracked in `GameState.dynamic_rarity`;
idempotent, and preserves dealt-ness by landing dealt copies before the
destination cursor). Both are groundwork for the `add_aquariums` experiment
effect and are currently unwired — no production call site exists yet.

## Per-slot rarity roll

Each of the three option slots is dealt independently:

1. **Rarity roll** from the datamined weight tables in `data/weights.json`,
   keyed by rank (1–9), slot (slot 1 vs slots 2&3), game stage
   (week 1 / week 2 / late), and Solarium presence (the Solarium flips to a
   flatter, rarer table). **Slot 1 is always free**; slots 2–3 may deal
   gem-cost rooms.
2. **Uniform deal** from that rarity's deck(s), skipping rooms that fail the
   placement filters below.
3. **Four draw attempts** per slot: if the rolled rarity's deck can't
   produce a legal room, the roll is retried (up to four times total),
   ending in a **forced Closet** if everything fails.

**Deck-size gates** suppress decks that have run low: free decks need ≥ 3
cards; gem decks need 5/5/4/4 (by rarity) once veteran mode, day ≥ 16, or
Room 46 has been reached (`GameConfig.gem_gate_active`).

**Priority draws** (`data/priority_draws.json`) are an additional filter that
runs ahead of the normal roll, on EVERY slot (not just slot 3): the Patio
group at 5% (raised to 50% while a Greenhouse is placed), Commissary/
Observatory at 13%, Garage/Classroom at 3%. Each named floorplan gets its
own independent acceptance roll, then the accepted ones are dealt through
the same per-rarity deck machinery the normal roll uses, so a hit actually
consumes the card. An entry may also carry an optional `condition` tag (the
same vocabulary `category_biases` entries use, e.g. `greenhouse_or_king`);
such an entry is skipped, rolling no chance at all, while that condition
isn't active — the Chronograph's Tomorrow Rooms row and the two
add_aquariums rows use one. This is distinct from the Garage's own *Forced
Draw* (`forced_draws`), a different, once-per-day mechanic that is Slot-3-only.

## Placement filters

A candidate room must be placeable behind the opened doorway
(`engine/placement.py`):

- **Door-back rule**: the room needs a door facing back through the opened
  doorway (`entry_dir` is the direction the player moved, so the room needs
  a door on the opposite side).
- **No door may face the outer wall.** This single rule keeps 4-way rooms
  off edges, restricts corner cells to L-shapes and Dead Ends, and fixes a
  T-shape's orientation against an edge.
- **Draft conditions** (`Room.draft_conditions`, AND semantics): wing/corner
  /rank restrictions (Garage, Boiler Room, Her Ladyship's Chamber, …),
  cannot-draft-from-Library, and item-gated rooms (Pool → Swimming-gated
  rooms, Secret Garden key, Room 8 key, breakfast) via
  `GameConfig.satisfied_conditions`.
- Duplicates: a room already on the grid can't be dealt again (Chamber of
  Mirrors lifts this).

## Orientation roll

A floorplan with several legal orientations is rolled with datamined,
south-door-biased weights that drift by day — e.g. a T needing a south door
rolls 70/15/15 early, 60/20/20 late (`engine/rotation.py`). The **Compass**
(`cfg.compass`, or the held Compass item — see `special_items.compass_active`)
flips the bias toward north doors. Free rotation to any legal orientation is
granted by the **Ornate Compass** (`cfg.ornate_compass` or the held item, every
draft), the **Rotunda** (while placed), and the **Dovecote** (while drawn).

Known gap: orientation weights are datamined for the South, West and East
connecting-door cases; the North case uses the published near-uniform
40/30/30, and the Compass column for North (and the 50/50 North/South 2-way
case) is unpublished, so those fall back to the base roll.

## Redraws

The whole 3-option hand can be redrawn (per-slot semantics unverified, so
the sim redraws all three):

- **Study**: 1 gem per redraw, max 8 per draft, while the Study is placed.
- **Classroom**: free redraws equal to the drafting-room count.
- **Ivory Dice**: spend a die for a redraw.

## Other draft-time modifiers

- **Archives** (`archive_floorplan`): house-wide and non-stacking, not a
  from-room effect. Once one is on the estate, every draft through any
  doorway archives one of its three dealt options — a uniformly random slot,
  drawn from its own named RNG stream (`archives_slot`) and re-rolled on
  every redraw. Archived is a property of the floorplan, distinct from
  hidden (a property of how it was dealt): the archived option is always
  also hidden, never the reverse. Negated by Shelter/Knight's Shield, spent
  once at the Archives' own placement (`engine/effects/rooms/archives.py`).
- **Darkroom** (`conceal_all_floorplans`): a from-room effect — drafting from
  its own doorway hides all three options face-down, live-read against
  `state.darkroom_lights_on` on every deal and redraw. Its lights start on
  but blow a fuse (switch flips off) the first time the Darkroom is entered
  each day, unless the switch was already off or Shelter/Knight's Shield
  negates it (`engine/effects/rooms/darkroom.py`). The Utility Closet's
  "Darkroom" switch can restore power at any time afterward, disabling the
  concealment for later doorways from the room — but flipping it off then on
  again *before* the Darkroom is first entered does not stop the fuse from
  blowing.
- A hidden or archived option is still fully draftable, sight unseen; a
  concealed floorplan's rarity is visible when drafting through a security
  door.
- **Conservatory**: on draft, re-rolls the rarity of 3 random undealt deck
  cards.
- **Hovel**: gem costs can be paid with steps at 3 steps : 1 gem.
- **Terrace**: green rooms cost no gems.

## Verifying the math

`tests/test_draft_stats.py` is a chi-square suite (30k draws per table
cell) asserting the engine reproduces the datamined rarity distributions.
Treat failures there as evidence the draft math regressed, not as flaky
tests. Useful anchors: late-game slot 1 at rank 1 is 91.8% commonplace;
with a Solarium, slots 2–3 at rank 9 deal 10/20/50/20.
