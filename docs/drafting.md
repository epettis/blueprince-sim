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
day (The Pool, Pool Hall, Schoolhouse) are shuffled into the live decks.

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

**Priority draws** (`data/priority_draws.json`) can override slot 3 before
the normal roll: the Patio group at 5% (raised to 50% while a Greenhouse is
placed), Commissary/Observatory at 13%, Classroom at 3%.

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
(`cfg.compass`) flips the bias toward north doors. Free rotation to any
legal orientation is granted by the **Ornate Compass** (`cfg.ornate_compass`,
every draft), the **Rotunda** (while placed), and the **Dovecote** (while
drawn).

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

- **Archives / Darkroom** (`reduce_draft_options`): drafting *from* these
  rooms marks options face-down — Archives one "mystery" option, Darkroom
  all three. A hidden option is still draftable, sight unseen.
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
