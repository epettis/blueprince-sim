# Special items — wiki research digest

Compiled 2026-07-25 from https://blueprince.wiki.gg (fetched pages cited inline as
`wiki/<Page>`). This is the source-of-truth reference for `data/special_items.json`;
confidence for everything here is `wiki` unless marked `datamined` (numeric tables the
wiki reproduces from the game data) or `inferred` (our modeling assumption).

## Taxonomy and global rules

The wiki (`wiki/Items`) splits items into *resource items* (coins, gems, keys, food,
ivory dice, allowance — UI counters, already modeled as `GameState` resources) and
*special items* (inventory-slot items), subdivided into: Standard Items, Special Keys,
Contraptions, Showroom Items, Armory Items, Unique Items.

**Persistence**: by default ALL special items are lost at end of day. Carry channels:
Coat Check (stores exactly 1 item), Moon Pendant (2 random inventory items carry
overnight). Self-persisting exceptions: Key 8 (permanent), Sanctum Keys (until used),
Vault Keys (until used, then removed from the pool forever), File Cabinet Keys.
Carrying an item overnight removes it (contraptions: their primary components) from the
next day's spawn pool.

**There is no Kiosk** — `wiki/Kiosk` 404s; not a Blue Prince room.

## Standard items

| Item | Effect | Sources | Notes |
|---|---|---|---|
| Battery Pack | No standalone use; contraption component. | Spawns: Attic, Archives, Laboratory, Mail Room, Patio, Storeroom, Wine Cellar, Workshop (high luck: Spare Room, Garage, Utility Closet, Kitchen). Trading Post. Garage trunk. | Tier 1 |
| Broken Lever | No inherent use; placeable on broken machines (Greenhouse Antechamber lever, Casino slot). | Spawns in 14 rooms: Aquarium, Attic, Drafting Studio, Laboratory, Locker Room, Observatory, Patio, Sauna, Security, Storeroom, Weight Room, Wine Cellar, Workshop, Servant's Quarters. Rare dig (0.96%). | NOT tradeable |
| Coin Purse | +1 coin interest per 3 coins collected (net ×4/3 income). Excludes its own payouts and Casino/Laundry. | Spawns: Closet, Walk-In Closet, Parlor, Attic, Workshop, Dining Room, Bedroom (high luck: Gallery, Ballroom, Drawing Room, Foyer). | Tier 2 |
| Compass | Biases floorplan orientation toward north (orientation only, not which rooms). | Spawns: Aquarium, Attic, Closet, Drafting Studio, Guest Bedroom, Observatory, Terrace, Walk-In Closet, Workshop. Commissary 6g. Mail Room. | Tier 2. Sim already has the datamined rotation column (config.compass). |
| Coupon Book | −1 gold on every shop purchase (reduction, not refund). | Spawns: Attic, Conference Room, Dining Room, Library, Mail Room, Nook, Office, Vault, Walk-In Closet, Morning Room (high luck: Den, Pantry, Secret Passage). | Tier 2 |
| Gear Wrench | When drafting a Mechanical Room: permanently set that room's rarity. | Toolshed; Lost & Found. | Tier 4 |
| Hall Pass | No step cost moving between adjoining Hallways; Hallways drafted from a Hallway cost 0 gems. | Classroom, Dormitory; Lost & Found. | Tier 4 |
| Lock Pick Kit | Chance to open key-locked doors free. Datamined per-day attempt rates 54/101, 35/101, 30/101, then 19/101. Pity: 3 consecutive fails → auto-success, counter resets. Regular key doors only. | Spawns: Archives, Attic, Rumpus Room, Security, Vault, Walk-In Closet, Wine Cellar, Workshop, Darkroom, Furnace, Closed Exhibit, Toolshed. Locksmith 10g. | Tier 3. Component of Pick Sound Amplifier. |
| Lucky Rabbit's Foot | +3 Luck while held (`wiki/Luck`). | Spawns: Closet, Walk-In Closet, Rumpus Room, Nursery, Maid's Chamber, Morning Room, Classroom (high luck: Ballroom, Den, Foyer, Gallery, Casino). | Component of Lucky Purse |
| Magnifying Glass | Inspect documents (lore interaction). | Spawns in 16 rooms: Archives, Attic, Boudoir, Chapel, Drafting Studio, Guest Bedroom, Her Ladyship's Chamber, Laboratory, Library, Mail Room, Nook, Observatory, Office, Parlor, Study, Workshop. Commissary 4g. | Tier 1 |
| Metal Detector | Extra basic keys/coins spawn in rooms drafted while held (coins > keys, mostly 1-coin piles, luck-independent, not retroactive). Also a proximity beeper (UI only). | Spawns: Archives, Attic, Closet, Courtyard, Greenhouse, Mail Room, Patio, Servant's Quarters, Veranda, Workshop (high luck: Garage, Boiler Room). Commissary 10g. | Component of Detector Shovel, Burning Glass, Pick Sound Amplifier |
| Repellent | Use in any room: from tomorrow that floorplan is removed from house+pool for 7 days. Max 3 active. Consumed. | Lost & Found (guaranteed in pool); Spare Bedroom. | |
| Running Shoes | Prevents step loss on a distance trigger (~every third room-length; datamined activation 60–99% in special areas). | Spawns: Closet, Gymnasium, Locker Room, Rumpus Room, Sauna, The Pool, Walk-In Closet, Weight Room (high luck: Foyer, Garage). Commissary 8g. | |
| Salt Shaker | +1 step per food item eaten, applied BEFORE Silver Spoon doubling (banana 3→4→8). | Spawns: Rumpus Room, Walk-In Closet, Billiard Room, Dining Room, Morning Room (high luck: Pantry, Kitchen). Commissary 5g. Trading Post. | Tier 1 |
| Shovel | Digs dig spots (each once/day). Datamined dig table: 28.8% junk, 25.2% coins 1–4 (sub-split 45/38/15/2%), 14.4% turnip (+6 steps), 10.8% key, 8% gold coin, 8% nothing, 2.16% Scrap of Paper, 0.96% Broken Lever, 0.48% Silver Key, 0.384% each Vault Key 304/149 + Secret Garden Key, 0.24% SG Key variant, 0.144% VK 233, 0.048% VK 370. | Spawns: Aquarium, Attic, Closet, Courtyard, Greenhouse, Patio, Storeroom, Terrace, Veranda, Wine Cellar, Workshop. Commissary 6g. Trading Post. | Tier 2. Component of Jack Hammer, Detector Shovel, Dowsing Rod |
| Sledge Hammer | Shatters padlocked trunks (no key); smashes Entrance Hall vases (microchip). | Spawns: Attic, Closet, Courtyard, Greenhouse, Storeroom, Veranda, Workshop, Wine Cellar (+Furnace, Secret Garden). Commissary 8g. Trading Post. | Tier 2. Component of Power Hammer |
| Sleeping Mask | +5 steps on first entry to each bedroom after obtaining (Bunk Room ×2). | Spawns: Bedroom, Boudoir, Closet, Master Bedroom, Sauna, Walk-In Closet (high luck: Foyer). Commissary 8g. Mail Room. | Tier 1 |
| Stopwatch | First find per day: 60 real-time seconds of zero step/key/gem costs (still need ≥1 of the resource held). Removed at expiry, unobtainable again that day. | Clock Tower; Lost & Found. | Real-time — needs a turn-based simplification |
| Telescope | Observatory second night sky; Planetarium planet unlocks. | Her Ladyship's Chamber, Walk-In Closet, Planetarium, Lost & Found; Trading Post. | Tier 4 |
| Treasure Map | X at one of 8 cells (A5, B6, B8, C8, D6, D9, E5, E8 — 9×5 grid, never corners). Dig at the marked cell (needs a digging tool): uniform 1/3 of 40 gold / 8 gems / 25 gold + 3 gems. Once/day. | Spawns: Attic, Drafting Studio, Library, Mail Room, Observatory, Rumpus Room, Study, Wine Cellar (high luck: Den, Secret Passage, Trophy Room). Trunks, lockers. | Tier 2 |
| Watering Can | Capacity 3 water; first entry to each Green Room: spend 1 water → 1 gem. | Greenhouse; Toolshed, Hovel; Lost & Found. | Tier 4 |
| Vault Key 149/233/304/370 | Each opens its numbered Vault deposit box; persists until used, then permanently out of the pool. | 149: Attic, Rumpus Room, Security + digs. 233: Office, Sauna, Wine Cellar + digs. 304: Conference Room, Her Ladyship's Chamber, Walk-In Closet + digs. 370: Lost & Found + digs. | Tier 3 |

## Special keys

| Key | Effect | Sources | Persistence |
|---|---|---|---|
| Basement Key | Opens basement doors; not consumed. | Antechamber central table (guaranteed first entry). | Doors permanent |
| Car Keys | Garage car trunk: Upgrade Disk + loot, or 2 random items. Not consumed. | 15 spawn rooms; Locksmith 8g (fallback 4th special key). | Day |
| Key 8 | Locked doors into Rank 8: skips the draw, drafts Room 8. | Gallery art puzzle chest; Lost & Found from Day 365. | PERMANENT |
| Keycard | Opens security doors; not consumed. | 16 spawn rooms (already modeled via locks.json source_rooms). | Day |
| Master Key | Opens all standard-key doors; not consumed. | Showroom 80g. | Day. Tier 5 |
| Prism Key | Fits locks in colored rooms; unlocking triggers a draft drawing floorplans of that color. Consumed but returned to pool. | Music Room; Lost & Found; Locksmith 8g. | Day, recycles. Tier 4 |
| Sanctum Key (×8) | Each permanently unlocks 1 of 8 Inner Sanctum doors; consumed; interchangeable. | 8 fixed sources (Room 46, Vault 370, Clock Tower, Reservoir, Throne Room, Safehouse, Music Room, Mechanarium); each respawns until its key is used. | Until used. Tier 5 |
| Secret Garden Key | Locked doors on West/East Wing edge ranks 3–8: unlocks + immediately drafts the Secret Garden. Consumed, NOT returned — max 1/day. | Attic; Music Room; Lost & Found; Locksmith 8g; digs. | Day, consumed. Tier 4 |
| Silver Key | Unlocks a locked door; the resulting draft always draws 4-way/T-shape rooms if possible (fallback straight/L). Returned to pool after use. | Closet, Music Room, Her Ladyship's Chamber; Locksmith 8g; digs (0.48%). | Day, recycles. Tier 3 |

## Showroom items (`wiki/Showroom`)

Moon Pendant 20g (2 random items carry overnight), Chronograph 30g (REWIND last draft
after any redraw + 40% Tomorrow-Room priority draw), Silver Spoon 30g (food step gains
×2, applied last), Ornate Compass 50g (rotate floorplans at will on every draft —
already modeled as config.ornate_compass), Emerald Bracelet 60g (floorplan gem costs
waived; other gem spends unaffected), Master Key 80g. After buying all four displayed:
Trophy of Wealth 100g (no effect; collection item). Stock: 4 slots — two from the 20–30g
trio, two from the 50–80g trio, avoiding already-owned.

## Armory items (`wiki/Armory`; blackprint room)

Knight's Shield 8g (once/day ignore one Red Room's negative effect while drafting),
Morning Star 8g (works as Sledge Hammer; held at end of day → +1 Star next morning),
The Axe 32g (permanently remove one room's gem cost; consumed; max 3 active, 4th use
un-axes the 3rd), Torch 8g (lights candles/fuses; interchangeable with Burning Glass).

## Unique items

| Item | Effect | Sources |
|---|---|---|
| Allowance Token | +2 permanent allowance (daily gold packet in Entrance Hall). | Vault boxes, Reservoir, Trading Post tier-5 trades, one-time puzzles. |
| Crown of the Blueprints | First Red Room drawn per draft: may remove it from today's pool → +1 gem + redraw. | Room 46 (later visits). |
| Cursed Effigy | Pickup: steps set to 13 (only if above 13); 2-day curse; unlocks Curse Mode. | Shrine, after buying Cursed Coffers from the Gift Shop (needs Sledge Hammer). |
| Diary Key | Permanently unlocks Her Ladyship's Sleep Diary (lore). | Tomb; respawns daily. |
| File Cabinet Key (×3) | Each opens one specific drawer; consumed. | Aquarium digs (drained), Crate Tunnel. |
| Key of Aries | Opens the Treasure Trove black box → Royal Scepter. | Precipice clock puzzle. |
| Lunch Box | +10 steps auto-consumed on reaching Rank 5 while holding it (immediate if picked up at Rank 5+). Counts as food (Salt Shaker/Silver Spoon apply). | Gift Shop 15g one-time post-game purchase; afterwards spawns in every Dining Room daily. |
| Microchip (×3) | Placed in holders to open outer areas. Middle chip: Entrance Hall west vase (Sledge Hammer). Largest: buried on the West Path right of the bridge (Shovel; same walking cost as the Outer Room door). Smallest: pre-placed in Blackbridge Grotto. | As listed. Placed chips permanent; lost unplaced chips respawn nearby. |
| Paper Crown | If no Red Room among the first 3 floorplans drawn: free redraw, once per draft. | Closed Exhibit security puzzle. |
| Royal Scepter | On pickup choose a color → that color's floorplans more common all day; re-selectable once/day; color persists if the scepter is lost. | Key of Aries → Treasure Trove; after unlock, spawns in the Entrance Hall every morning. NOT tradeable. |
| Upgrade Disk (×16) | Terminal FLOORPLAN UPGRADE: permanently upgrade one room, picked by weighted/chained rules (3 options offered, applied immediately). See `docs/upgrade-disks-design.md`. | 15 fixed one-time spots + Trading Post tier-5 trades. |
| Wind-up Key | Opens one Parlor box; consumed. | Parlor desk (1/day); digs. Non-unique (can hold several). |

## Shops

- **Commissary** (`wiki/Commissary`): 4 slots per draft from: Gem 3g, Key 10g, Banana 3g,
  Set of Gems 10g, Magnifying Glass 4g, Salt Shaker 5g, Compass 6g, Shovel 6g, Sleeping
  Mask 8g, Running Shoes 8g, Sledge Hammer 8g, Metal Detector 10g, Upgrade Disk 15g
  (reserve). Selection: 7 standard combinations at 1/7 each; a combination only appears
  if all its items are still in the pool; owned special items never restock. Sale
  (days 20–21): prices halved rounded up.
- **Locksmith** (`wiki/Locksmith`): Key 5g (unlimited); Set of 3 Keys 12g; Special Key 8g
  one per day — rolled 30% Silver→SG→Prism / 40% SG→Prism→Silver / 30% Prism→SG→Silver
  priority lists, fallback Car Keys; Lock Pick Kit 10g (not sold if owned). Never rolls
  for luck.
- **Showroom**: see above.
- **Gift Shop**: Cursed Coffers (→ Cursed Effigy) and one-time Lunch Box 15g. (Full
  inventory not fetched — known gap.)
- **Trading Post** (`wiki/Trading_Post`, outer room, West Path): NO fixed trade table —
  procedural: your item → an equal-tier item or dice (~10% dice baseline); tier-5 items
  50% Allowance Token / Upgrade Disk offers. Offers reroll as new items spawn; traded
  items return to the pool. Trades per day: undocumented.
- **Kitchen**: food. **Bookshop**: lore books. **Laundry Room**: coin/step swaps.

## Workshop fabrication (`wiki/Workshop`)

Inputs consumed; output picked up; no per-day limit. Workshop always contains one free
component item (fallback 5 coins). All 8 assembled → Trophy of Invention.

| Contraption | Recipe | Effect |
|---|---|---|
| Burning Glass | Metal Detector + Magnifying Glass | Lights candles/fuses (Torch-equivalent). Does NOT keep the inputs' effects. |
| Detector Shovel | Metal Detector + Shovel | Both effects + upgraded dig table (24% key, 17.5% 4 coins, 12.5% each junk×2, 10.5% 3 coins, 4% each Silver / SG Key, 3.5% each 1–2 coins, 1.8% Broken Lever, ~1.6–0.2% Vault Keys). |
| Dowsing Rod | Compass + Shovel | Marks one of the 3 offered floorplans as item-rich; picking it grants +32 Luck bypassing the Luck Penalty. Loses digging; does NOT keep Compass effect. |
| Jack Hammer | Shovel + Battery Pack + Broken Lever | Upgraded Shovel: less junk, multi-drops, better table (incl. 39/176 2 gems, 3/176 Wind-up Key, rare Knight's Shield / Allowance Token). |
| Lucky Purse | Lucky Rabbit's Foot + Coin Purse | Doubles all gold found (1:1 interest) + keeps the +3 Luck. |
| Pick Sound Amplifier | Lock Pick Kit + Metal Detector | Upgraded lockpicking: 90/101, 85/101, 70/101, then 65/101; no pity system. |
| Power Hammer | Sledge Hammer + Battery Pack + Broken Lever | All Sledge Hammer uses + breaks walls/structures. |
| Powered Electromagnet | Compass + Battery Pack | Compass effect persists all day even if lost; +40% Mechanical-Room priority draw; auto-collects all coin piles + basic keys on room entry. |

## Lost & Found (`wiki/Lost_%26_Found` — note the %26)

L-shape corner, Unusual, 0 gems, Red Room; added to the draft pool after a lore
discovery (underground map + Magnifying Glass). On entry: removes ONE RANDOM special
item from inventory (not chosen; not returned to the pool; empty inventory → no effect;
resource items exempt). Gives TWO items from a fixed rare pool: Ivory Dice, Gear
Wrench, Hall Pass, Lucky Rabbit's Foot, Prism Key, Repellent, Secret Garden Key,
Stopwatch, Telescope, Upgrade Disk, Vault Key 370, Watering Can.

## Spawn mechanics (`wiki/Luck`)

Luck (base 10 daily) drives extra items in newly drafted rooms; the wiki's banded table
differs in detail from the sim's linear model (see docs/luck.md — keeping the sim's
model). Rooms that never roll for luck: Entrance Hall, Rotunda, Room 8, Closet, Walk-in
Closet, Attic, Chamber of Mirrors, Freezer, Antechamber, Passageway, Locksmith,
Showroom, Gift Shop, Vestibule, Mechanarium, Treasure Trove, Toolshed, Shelter, Shrine.
The exact per-room special-item spawn RATES are not documented — the sim's spawn share
model is `inferred`.

## Known gaps

Trading Post trades/day; Commissary combination contents (A–G lists not published);
Gift Shop full stock; luck bands 5–10 and 19–22 imprecise on the wiki itself;
persistence not restated on several standard-item pages (global daily-loss rule
assumed); Crown of the Blueprints / Paper Crown / Wind-up Key persistence unstated.
