# TFMurphy decompiled room table (v1.3) — verbatim extraction

Source: docs.google.com/spreadsheets/d/1DGozAX_yHmQqAvrWBegxNg5b92d5zigtPOshj_7FoZ8
Extracted 2026-07-20 via Google Drive MCP read of the workbook (direct HTTP export endpoints are 403).
Currency glyphs are UTF-8 mojibake from the export: bare `ð` = key (U+1F5DD) or gem (U+1F48E) — ambiguous;
`ð£` = steps (U+1F463); `ð°` = coins (U+1F4B0); `ð²` = dice (U+1F3B2); `✨` = stars. `\-`/`\+`/`\#` are markdown escapes.
Blank cells in the three boolean columns mean false; `Yes` means true.
NOTE: table covers rooms #1-#77 (main directory pages + Bedrooms/Hallways/Green Rooms/Shops).
Red Rooms page, Studio Additions, Outer Rooms, Blackprints were not present in this tab.

| \# | Name | Category | Base Rarity | Gem Cost | Effect | Color | Type 1 | Type 2 | Type 3 | Unlock Conditions | Draft Conditions | Layout | Cannot Draft From Library | Is Powered Room | Is Duct Room | Internal Index |
| 1 | The Foundation | Rooms 001-012 | Rare | \- | Does not reset each day. | Blue | Blueprint | Permanent | \- | \- | \- | T | \- |  |  | 150 |
| 2 | Entrance Hall | Rooms 001-012 | \- | \- | \- | Blue | Blueprint | Permanent | \- | \- | \- | 4-Door | \- |  |  | 59 |
| 3 | Spare Room | Rooms 001-012 | Commonplace | \- | \- | Blue | Blueprint | \- | \- | \- | \- | Straight | \- |  |  | 130 |
| 3 | Spare Bedroom | Rooms 001-012 | Commonplace | \- | \- | Purple | Bedroom | \- | \- | Upgrade Spare Room | \- | Straight | \- |  |  | 131 |
| 3 | Spare Greenroom | Rooms 001-012 | Commonplace | \- | \- | Green | Green Room | \- | \- | Upgrade Spare Room | \- | Straight | \- |  |  | 132 |
| 3 | Spare Hall | Rooms 001-012 | Commonplace | \- | \- | Orange | Hallway | \- | \- | Upgrade Spare Room | \- | Straight | \- |  |  | 133 |
| 3 | Servant's Spare Quarters | Rooms 001-012 | Commonplace | \- | \+1ð for each Bedroom in your house. | Purple | Bedroom | \- | \- | Upgrade Spare Bedroom | \- | Straight | \- |  |  | 134 |
| 3 | Her Ladyship's Spare Room | Rooms 001-012 | Commonplace | \- | The next time you enter BOUDOIR, gain 10ð£  The next time you enter WALK-IN CLOSET, gain 3ð | Purple | Bedroom | \- | \- | Upgrade Spare Bedroom | \- | Straight | \- |  |  | 135 |
| 3 | Spare Master Bedroom | Rooms 001-012 | Commonplace | \- | \+1ð£ for each room in your house. | Purple | Bedroom | \- | \- | Upgrade Spare Bedroom | \- | Straight | \- |  |  | 136 |
| 3 | Spare Foyer | Rooms 001-012 | Commonplace | \- | Hallway Doors are always unlocked. | Orange | Hallway | \- | \- | Upgrade Spare Hall | \- | Straight | \- |  |  | 137 |
| 3 | Spare Secret Passage | Rooms 001-012 | Commonplace | \- | Leads to a room of a color of your choice. | Orange | Hallway | Patio | \- | Upgrade Spare Hall | \- | Straight | \- |  |  | 138 |
| 3 | Spare Great Hall | Rooms 001-012 | Commonplace | \- | 7 Locked Doors | Orange | Hallway | \- | \- | Upgrade Spare Hall | \- | 4-Door | \- |  |  | 139 |
| 3 | Spare Veranda | Rooms 001-012 | Commonplace | \- | Greater chance of finding items in Green Rooms. | Green | Green Room | Patio | \- | Upgrade Spare Greenroom | \- | Straight | \- |  |  | 140 |
| 3 | Spare Terrace | Rooms 001-012 | Commonplace | \- | Green Rooms do not cost ð to draft. | Green | Green Room | \- | \- | Upgrade Spare Greenroom | \- | Straight | \- |  |  | 141 |
| 3 | Spare Patio | Rooms 001-012 | Commonplace | \- | Spread ð in each Green Room. | Green | Green Room | Spread | Patio | Upgrade Spare Greenroom | \- | Straight | \- |  |  | 142 |
| 4 | Rotunda | Rooms 001-012 | Rare | 3 | Can Rotate | Blue | Blueprint | \- | \- | \- | \- | 4-Door | \- |  |  | 118 |
| 5 | Parlor | Rooms 001-012 | Commonplace | \- | \- | Blue | Blueprint | Puzzle | \- | \- | \- | L | \- |  |  | 107 |
| 5 | Parlor | Rooms 001-012 | Commonplace | \- | 3ð Prize | Blue | Blueprint | Puzzle | \- | Upgrade Parlor | \- | L | \- |  |  | 108 |
| 5 | Parlor | Rooms 001-012 | Commonplace | \- | 2 Wind-up Keys | Blue | Blueprint | Puzzle | \- | Upgrade Parlor | \- | L | \- |  |  | 109 |
| 5 | Funeral Parlor | Rooms 001-012 | Commonplace | \- | ðprize is equal to RED ROOMS in your house.  If you open an empty box in FUNERAL PARLOR, lose 30ð£. | Red | Red Room | Puzzle | \- | Upgrade Parlor | \- | L | \- |  |  | 110 |
| 6 | Billiard Room | Rooms 001-012 | Commonplace | \- | \- | Blue | Blueprint | Puzzle | \- | \- | \- | L | \- |  |  | 9 |
| 6 | Speakeasy | Rooms 001-012 | Commonplace | \- | Basic Addition | Blue | Blueprint | Puzzle | \- | Upgrade Billiard Room | \- | L | \- |  |  | 10 |
| 6 | Break Room | Rooms 001-012 | Commonplace | \- | If you call it a day in BREAK ROOM, tomorrow you will begin the day with a staff keycard. | Blue | Blueprint | Puzzle | Tomorrow | Upgrade Billiard Room | \- | L | \- |  |  | 11 |
| 6 | Pool Hall | Rooms 001-012 | Commonplace | \- | Adds GREAT HALL, FOYER and SECRET PASSAGE to today's Draft Pool. | Orange | Hallway | Puzzle | Drafting | Upgrade Billiard Room | \- | L | \- |  |  | 12 |
| 7 | Gallery | Rooms 001-012 | Rare | \- | \- | Blue | Blueprint | Puzzle | \- | \- | \- | Straight | \- |  |  | 63 |
| 8 | Room 8 | Rooms 001-012 | Rare | \- | \- | Blue | Blueprint | Puzzle | \- | \- | Room 8 Key | L | \- |  |  | 115 |
| 9 | Closet | Rooms 001-012 | Commonplace | \- | 2 items | Blue | Blueprint | \- | \- | \- | \- | Dead End | Yes |  |  | 38 |
| 9 | Hallway Closet | Rooms 001-012 | Commonplace | \- | 2 items  \+1 extra item if drafted adjoined to a Hallway | Blue | Blueprint | \- | \- | Upgrade Closet | \- | Dead End | Yes |  |  | 39 |
| 9 | Bedroom Closet | Rooms 001-012 | Commonplace | \- | 2 items  \+2 extra items if drafted adjoined to a Bedroom | Blue | Blueprint | \- | \- | Upgrade Closet | \- | Dead End | Yes |  |  | 40 |
| 9 | Empty Closet | Rooms 001-012 | Commonplace | \- | 0 items  \+4 extra items if drafted adjoined to a Red Room | Red | Red Room | \- | \- | Upgrade Closet | \- | Dead End | Yes |  |  | 41 |
| 10 | Walk-In Closet | Rooms 001-012 | Standard | 1 | 4 items | Blue | Blueprint | \- | \- | \- | \- | Dead End | \- |  |  | 164 |
| 11 | Attic | Rooms 001-012 | Rare | 3 | 8 items | Blue | Blueprint | \- | \- | \- | \- | Dead End | \- |  |  | 6 |
| 12 | Storeroom | Rooms 001-012 | Commonplace | \- | \+1ð, 1ð, 1ð° | Blue | Blueprint | \- | \- | \- | \- | Dead End | Yes |  |  | 143 |
| 12 | Storeroom | Rooms 001-012 | Commonplace | \- | \+2ð, 1ð, 1ð° | Blue | Blueprint | \- | \- | Upgrade Storeroom | \- | Dead End | Yes |  |  | 144 |
| 12 | Storeroom | Rooms 001-012 | Commonplace | \- | \+1ð, 2ð, 1ð° | Blue | Blueprint | \- | \- | Upgrade Storeroom | \- | Dead End | Yes |  |  | 145 |
| 12 | Storeroom | Rooms 001-012 | Commonplace | \- | \+1ð, 1ð, 10ð° | Blue | Blueprint | \- | \- | Upgrade Storeroom | \- | Dead End | Yes |  |  | 146 |
| 13 | Nook | Rooms 013-024 | Commonplace | \- | \+1ð | Blue | Blueprint | \- | \- | \- | \- | L | \- |  |  | 96 |
| 13 | Nook | Rooms 013-024 | Commonplace | \- | \+2ð | Blue | Blueprint | \- | \- | Upgrade Nook | \- | L | \- |  |  | 97 |
| 13 | Breakfast Nook | Rooms 013-024 | Commonplace | \- | \+1ð + Bacon & Eggs | Blue | Blueprint | \- | \- | Upgrade Nook | \- | L | \- |  |  | 98 |
| 13 | Reading Nook | Rooms 013-024 | Commonplace | \- | \+1ð  You will always draw LIBRARY while drafting in this room. | Blue | Blueprint | Drafting | \- | Upgrade Nook | \- | L | \- |  |  | 99 |
| 14 | Garage | Rooms 013-024 | Commonplace | 1 | \+3ð | Blue | Blueprint | \- | \- | \- | West Wing | Dead End | \- | Yes |  | 64 |
| 15 | Music Room | Rooms 013-024 | Unusual | 2 | 1 Major ð, 1 Minor ð | Blue | Blueprint | \- | \- | \- | \- | L | \- |  |  | 95 |
| 16 | Locker Room | Rooms 013-024 | Standard | 1 | Spread ð throughout the house. | Blue | Blueprint | Spread | \- | \- | Pool Drafted | Straight | \- | Yes | Yes | 84 |
| 17 | Den | Rooms 013-024 | Commonplace | \- | \+1ð | Blue | Blueprint | \- | \- | \- | \- | T | \- |  |  | 52 |
| 18 | Wine Cellar | Rooms 013-024 | Unusual | \- | \+3ð | Blue | Blueprint | \- | \- | \- | \- | Dead End | \- |  |  | 167 |
| 19 | Trophy Room | Rooms 013-024 | Rare | 5 | \+8ð | Blue | Blueprint | \- | \- | \- | \- | L | \- |  |  | 158 |
| 20 | Ballroom | Rooms 013-024 | Unusual | 2 | Whenever you enter BALLROOM, set your ð to 2ð | Blue | Blueprint | Entry | \- | \- | \- | Straight | \- |  |  | 7 |
| 21 | Pantry | Rooms 013-024 | Commonplace | \- | \+4ð° | Blue | Blueprint | \- | \- | \- | \- | L | \- |  |  | 106 |
| 22 | Rumpus Room | Rooms 013-024 | Standard | 1 | \+8ð° | Blue | Blueprint | \- | \- | \- | \- | Straight | \- |  |  | 119 |
| 23 | Vault | Rooms 013-024 | Unusual | 3 | \+40ð° | Blue | Blueprint | \- | \- | \- | \- | Dead End | \- |  |  | 161 |
| 24 | Office | Rooms 013-024 | Standard | 2 | Opportunity to earn and spread ð° | Blue | Blueprint | Spread | \- | \- | \- | L | \- |  |  | 105 |
| 25 | Drawing Room | Rooms 025-036 | Commonplace | 1 | You may draw new Floor Plans while drafting in this room. | Blue | Blueprint | Drafting | \- | \- | \- | T | \- |  |  | 57 |
| 26 | Study | Rooms 025-036 | Unusual | \- | While drafting, you may spend ðgems to redraw floorplans up to 8 times. | Blue | Blueprint | Drafting | \- | \- | \- | Dead End | \- |  |  | 147 |
| 27 | Library | Rooms 025-036 | Standard | \- | Discover less common Floor Plans while drafting in the LIBRARY. | Blue | Blueprint | Drafting | \- | \- | \- | L | \- |  |  | 83 |
| 28 | Chamber of Mirrors | Rooms 025-036 | Rare | \- | You can now draft second copies of rooms you already have in your house. | Blue | Blueprint | Drafting | \- | \- | \- | Dead End | \- |  |  | 24 |
| 29 | The Pool | Rooms 025-036 | Standard | 1 | Adds LOCKER ROOM, SAUNA and PUMP ROOM to today's Draft Pool. | Blue | Blueprint | Drafting | \- | \- | \- | T | \- |  |  | 152 |
| 30 | Drafting Studio | Rooms 025-036 | Unusual | 2 | Select a new floorplan to permanently add to your estate's draft pool. | Blue | Blueprint | Drafting | \- | \- | \- | Straight | \- |  |  | 56 |
| 31 | Utility Closet | Rooms 025-036 | Standard | \- | Breaker Box | Blue | Blueprint | Mechanical | \- | \- | \- | Dead End | \- |  |  | 160 |
| 32 | Boiler Room | Rooms 025-036 | Unusual | 1 | Power Source | Blue | Blueprint | Mechanical | \- | \- | \- | T | \- | Yes |  | 13 |
| 33 | Pump Room | Rooms 025-036 | Standard | \- | Control water flow throughout the Estate | Blue | Blueprint | Mechanical | \- | \- | Pool Drafted | L | \- | Yes |  | 114 |
| 34 | Security | Rooms 025-036 | Commonplace | 1 | View inventory of all items currently in the house. | Blue | Blueprint | Mechanical | \- | \- | \- | T | \- | Yes | Yes | 124 |
| 35 | Workshop | Rooms 025-036 | Unusual | \- | Combine inventory to create new items | Blue | Blueprint | Mechanical | \- | \- | \- | Straight | \- |  |  | 168 |
| 36 | Laboratory | Rooms 025-036 | Standard | 1 | Experimental House Features | Blue | Blueprint | Mechanical | \- | \- | \- | L | \- | Yes |  | 80 |
| 37 | Sauna | Rooms 037-046 | Standard | \- | Tomorrow, you will start the day with 20 extrað£. | Blue | Blueprint | Tomorrow | \- | \- | Pool Drafted | Dead End | \- |  |  | 120 |
| 38 | Coat Check | Rooms 037-046 | Standard | \- | Check one item and retrieve it on another day. | Blue | Blueprint | Tomorrow | \- | \- | \- | Dead End | \- |  |  | 42 |
| 39 | Mail Room | Rooms 037-046 | Unusual | \- | A package will be delivered here the day after drafting this room. | Blue | Blueprint | Tomorrow | \- | \- | \- | Dead End | \- |  |  | 88 |
| 39 | Mail Room | Rooms 037-046 | Unusual | \- | Same Day Delivery. The package will be delivered here after you reach rank 8. | Blue | Blueprint | Tomorrow | \- | Upgrade Mail Room | \- | Dead End | \- |  |  | 89 |
| 39 | Mail Room | Rooms 037-046 | Unusual | \- | No Contact Delivery. The package will be dropped off on the entrance steps the day after drafting this room. | Blue | Blueprint | Tomorrow | \- | Upgrade Mail Room | \- | Dead End | \- |  |  | 90 |
| 39 | Mail Room | Rooms 037-046 | Unusual | \- | Freight Shipping. A very large package will be delivered here 3 days after drafting this room. | Blue | Blueprint | Tomorrow | \- | Upgrade Mail Room | \- | Dead End | \- |  |  | 91 |
| 40 | Freezer | Rooms 037-046 | Unusual | \- | Freezes your accounts.  (ð° and ð amounts will not reset at the end of the day and they cannot be adjusted or used until tomorrow.) | Blue | Blueprint | Tomorrow | \- | \- | \- | Dead End | \- |  |  | 62 |
| 41 | Dining Room | Rooms 037-046 | Standard | \- | Each day, a meal is served in the DINING ROOM after Rank 8 has been reached. | Blue | Blueprint | \- | \- | \- | \- | T | \- |  |  | 53 |
| 42 | Observatory | Rooms 037-046 | Standard | 1 | \+1✨ for each time you've drafted OBSERVATORY. | Blue | Blueprint | \- | \- | \- | \- | L | \- |  |  | 104 |
| 43 | Conference Room | Rooms 037-046 | Unusual | \- | Whenever items would be spread throughout the house, they are placed in this room instead. | Blue | Blueprint | Spread | \- | \- | \- | T | \- |  |  | 44 |
| 44 | Aquarium | Rooms 037-046 | Unusual | 1 | AQUARIUM is every color of room. | All | Blueprint / Green Room / Shop / Hallway / Red Room / Bedroom / Blackprint | \- | \- | \- | \- | T | \- |  |  | 1 |
| 44 | Goldfish Aquarium | Rooms 037-046 | Unusual | 1 | AQUARIUM is every color of room.  \+10ð° | All | Blueprint / Green Room / Shop / Hallway / Red Room / Bedroom / Blackprint | \- | \- | Upgrade Aquarium | \- | T | \- |  |  | 2 |
| 44 | Starfish Aquarium | Rooms 037-046 | Unusual | 1 | AQUARIUM is every color of room.  \+1✨ | All | Blueprint / Green Room / Shop / Hallway / Red Room / Bedroom / Blackprint | \- | \- | Upgrade Aquarium | \- | T | \- |  |  | 3 |
| 44 | Electric Eel Aquarium | Rooms 037-046 | Unusual | 1 | AQUARIUM is every color of room.  Power Source | All | Blueprint / Green Room / Shop / Hallway / Red Room / Bedroom / Blackprint | Mechanical | \- | Upgrade Aquarium | \- | T | \- | Yes |  | 4 |
| 45 | Antechamber | Rooms 037-046 | \- | \- | \- | Blue | Blueprint | Objective | \- | \- | \- | Dead End | \- |  |  | 0 |
| 46 | Room 46 | Rooms 037-046 | \- | \- | \- | Blue | Blueprint | Objective | \- | \- | Antechamber North Door | Dead End | \- |  |  | 116 |
| 47 | Bedroom | Bedrooms | Commonplace | \- | Whenever you enter this room, gain 2ð£ | Purple | Bedroom | Entry | \- | \- | \- | L | Yes |  |  | 8 |
| 48 | Boudoir | Bedrooms | Standard | \- | \- | Purple | Bedroom | \- | \- | \- | \- | L | Yes |  |  | 15 |
| 48 | Boudoir | Bedrooms | Standard | \- | \+1ð | Purple | Bedroom | \- | \- | Upgrade Boudoir | \- | L | Yes |  |  | 16 |
| 48 | Boudoir | Bedrooms | Standard | \- | \+2ð² | Purple | Bedroom | \- | \- | Upgrade Boudoir | \- | L | Yes |  |  | 17 |
| 48 | Boudoir | Bedrooms | Standard | \- | \+3ð | Purple | Bedroom | \- | \- | Upgrade Boudoir | \- | L | Yes |  |  | 18 |
| 49 | Guest Bedroom | Bedrooms | Commonplace | \- | \+10ð£ | Purple | Bedroom | \- | \- | \- | \- | Dead End | Yes |  |  | 68 |
| 49 | Geist Bedroom | Bedrooms | Commonplace | \- | \+2ð²  If you have TOMB on the estate today, gain an additional 4ð². | Purple | Bedroom | \- | \- | Upgrade Guest Bedroom | \- | Dead End | Yes |  |  | 69 |
| 49 | Guess Bedroom | Bedrooms | Commonplace | \- | Hidden effect of a random BEDROOM in your draft pool? | Purple | Bedroom | \- | \- | Upgrade Guest Bedroom | \- | Dead End | Yes |  |  | 70 |
| 49 | Quest Bedroom | Bedrooms | Commonplace | \- | \+10ð£  If you enter ANTECHAMBER today, add 2ð° to your allowance. | Purple | Bedroom | Objective | \- | Upgrade Guest Bedroom | \- | Dead End | Yes |  |  | 71 |
| 50 | Nursery | Bedrooms | Commonplace | 1 | Whenever you draft a Bedroom, gain 5ð£ | Purple | Bedroom | Drafting | \- | \- | \- | Dead End | Yes |  |  | 100 |
| 50 | Nursery | Bedrooms | Commonplace | 1 | Whenever you draft a Bedroom, gain 8ð£ | Purple | Bedroom | Drafting | \- | Upgrade Nursery | \- | Dead End | Yes |  |  | 101 |
| 50 | Nurse's Station | Bedrooms | Commonplace | 1 | If you have less than 10ð£ when you enter this room, set your ð£ to 20. | Purple | Bedroom | Entry | \- | Upgrade Nursery | \- | Dead End | Yes |  |  | 102 |
| 50 | Indoor Nursery | Bedrooms | Commonplace | 1 | Whenever you draft another GREEN ROOM, 2ð will sprout in this room. | Green | Green Room | Drafting | \- | Upgrade Nursery | \- | Dead End | Yes |  |  | 103 |
| 51 | Servant's Quarters | Bedrooms | Unusual | 1 | \+1ð for each Bedroom in your house. | Purple | Bedroom | \- | \- | \- | \- | Dead End | \- |  |  | 125 |
| 52 | Bunk Room | Bedrooms | Standard | \- | This room counts as 2 BEDROOMS. | Purple | Bedroom | \- | \- | \- | \- | Dead End | \- |  |  | 19 |
| 52 | Bunk Room | Bedrooms | Standard | \- | This room counts as 2 BEDROOMS.  If you have exactly 2 HALLWAYS when drafting this room, DOUBLE your ð | Purple | Bedroom | \- | \- | Upgrade Bunk Room | \- | Dead End | \- |  |  | 20 |
| 52 | Bunk Room | Bedrooms | Standard | \- | This room counts as 2 BEDROOMS.  If you have exactly 2 GREEN ROOMS when drafting this room, DOUBLE your ð | Purple | Bedroom | \- | \- | Upgrade Bunk Room | \- | Dead End | \- |  |  | 21 |
| 52 | Bunk Room | Bedrooms | Standard | \- | This room counts as 2 BEDROOMS.  If you have exactly 2 SHOPS when drafting this room, DOUBLE your ð° | Purple | Bedroom | \- | \- | Upgrade Bunk Room | \- | Dead End | \- |  |  | 22 |
| 53 | Her Ladyship's Chamber | Bedrooms | Commonplace | \- | The next time you enter BOUDOIR, gain 10ð£  The next time you enter WALK-IN CLOSET, gain 3ð | Purple | Bedroom | \- | \- | \- | West Wing From South-Facing Door | Dead End | \- |  |  | 77 |
| 54 | Master Bedroom | Bedrooms | Unusual | 2 | \+1ð£ for each room in your house. | Purple | Bedroom | \- | \- | \- | East Wing | Dead End | \- |  |  | 92 |
| 55 | Hallway | Hallways | Commonplace | \- | \- | Orange | Hallway | \- | \- | \- | \- | T | Yes |  |  | 73 |
| 55 | Hallway | Hallways | Commonplace | \- | \+1ð | Orange | Hallway | \- | \- | Upgrade Hallway | \- | T | Yes |  |  | 74 |
| 55 | Hallway | Hallways | Commonplace | \- | \+1 locked trunk | Orange | Hallway | \- | \- | Upgrade Hallway | \- | T | Yes |  |  | 75 |
| 55 | Hallway | Hallways | Commonplace | \- | Add an extra HALLWAY to tomorrow's draft pool. | Orange | Hallway | Tomorrow | \- | Upgrade Hallway | \- | T | Yes |  |  | 76 |
| 56 | West Wing Hall | Hallways | Commonplace | \- | \- | Orange | Hallway | \- | \- | \- | \- | T | \- |  |  | 166 |
| 57 | East Wing Hall | Hallways | Standard | \- | \- | Orange | Hallway | \- | \- | \- | \- | T | \- |  |  | 58 |
| 58 | Corridor | Hallways | Commonplace | \- | CORRIDOR is always left unlocked. | Orange | Hallway | \- | \- | \- | \- | Straight | Yes |  |  | 46 |
| 59 | Passageway | Hallways | Commonplace | 2 | \- | Orange | Hallway | \- | \- | \- | \- | 4-Door | \- | Yes | Yes | 111 |
| 60 | Secret Passage | Hallways | Unusual | 1 | Leads to a room of a color of your choice. | Orange | Hallway | Patio | \- | \- | \- | Dead End / Straight | \- |  |  | 123 |
| 61 | Foyer | Hallways | Unusual | 2 | Hallway Doors are always unlocked. | Orange | Hallway | \- | \- | \- | \- | Straight | \- |  |  | 60 |
| 62 | Great Hall | Hallways | Unusual | \- | 7 Locked Doors | Orange | Hallway | \- | \- | \- | \- | 4-Door | \- |  |  | 66 |
| 63 | Terrace | Green Rooms | Rare | \- | Green Rooms do not cost ð to draft. | Green | Green Room | \- | \- | \- | West Wing or East Wing | Dead End | \- |  |  | 148 |
| 64 | Patio | Green Rooms | Commonplace | 1 | Spread ð in each Green Room. | Green | Green Room | Spread | Patio | \- | West Wing or East Wing | L | \- |  |  | 112 |
| 65 | Courtyard | Green Rooms | Commonplace | 1 | \- | Green | Green Room | \- | \- | \- | \- | T | Yes |  |  | 47 |
| 65 | Courtyard | Green Rooms | Commonplace | 1 | \+2ð | Green | Green Room | \- | \- | Upgrade Courtyard | \- | T | Yes |  |  | 48 |
| 65 | Courtyard | Green Rooms | Commonplace | 1 | 5 dig spots | Green | Green Room | \- | \- | Upgrade Courtyard | \- | T | Yes |  |  | 49 |
| 65 | Corriyard | Green Rooms | Commonplace | 1 | CORRIYARD is always left unlocked. | Green / Orange | Green Room | Hallway | \- | Upgrade Courtyard | \- | T | Yes |  |  | 50 |
| 66 | Cloister | Green Rooms | Unusual | 3 | \- | Green | Green Room | \- | \- | \- | \- | 4-Door | \- |  |  | 28 |
| 66 | Cloister of Rynna | Green Rooms | Standard | 3 | Raise your ðLUCK with each GREEN ROOM you draft from this CLOISTER. | Green | Green Room | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 29 |
| 66 | Cloister of Joya | Green Rooms | Standard | 3 | Permanently add an extra 5ð£ to the MAIN COURSE for each KITCHEN, PANTRY, or FURNACE you draft from this CLOISTER. | Green | Green Room | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 30 |
| 66 | Cloister of Dauja | Green Rooms | Standard | 3 | Gain 2✨ for each room with an animal you draft from this CLOISTER. | Green | Green Room | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 31 |
| 66 | Cloister of Veia | Green Rooms | Standard | 3 | Find 8 dirt piles in each room with a fireplace you draft from this CLOISTER. | Green | Green Room | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 32 |
| 66 | Cloister of Mila | Green Rooms | Standard | 3 | Find an extra item in each BEDROOM you draft from this CLOISTER. | Green | Green Room | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 33 |
| 66 | Cloister of Lydia | Green Rooms | Standard | 3 | Add 2ð° to your allowance for each SHOP you draft from this CLOISTER. | Green | Green Room | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 34 |
| 66 | Cloister of Orinda | Green Rooms | Standard | 3 | Open a random door of the ANTECHAMBER for each BLACKPRINT you draft from this CLOISTER. | Black | Blackprint | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 35 |
| 66 | Cloister of Draxus | Green Rooms | Standard | \- | Gain 4ð² for each DEAD-END room that you WILL draft from this CLOISTER. | Red | Red Room | \- | \- | Upgrade Cloister | \- | 4-Door | \- |  |  | 36 |
| 67 | Veranda | Green Rooms | Standard | 2 | Greater chance of finding items in Green Rooms. | Green | Green Room | Patio | \- | \- | West Wing or East Wing | Straight | \- |  |  | 162 |
| 68 | Greenhouse | Green Rooms | Commonplace | 1 | You are more likely to draw GREEN ROOMS while drafting. | Green | Green Room | Drafting | Patio | \- | West Wing or East Wing | Dead End / L | \- |  |  | 67 |
| 69 | Morning Room | Green Rooms | Commonplace | \- | \+2ð  Tomorrow, you will start with 2ð | Green | Green Room | Tomorrow | Patio | \- | Eat Bacon & Eggs in Kitchen or Breakfast Nook | L | \- |  |  | 94 |
| 70 | Secret Garden | Green Rooms | Rare | \- | Spread Fruit throughout the House. | Green | Green Room | Spread | \- | \- | Secret Garden Key  West Wing or East Wing | T | \- |  |  | 122 |
| 71 | Commissary | Shops | Commonplace | 1 | Items for Sale | Yellow | Shop | \- | \- | \- | \- | L | \- |  |  | 43 |
| 72 | Kitchen | Shops | Commonplace | 1 | Food for Sale | Yellow | Shop | \- | \- | \- | \- | L | \- |  |  | 79 |
| 73 | Locksmith | Shops | Standard | 1 | Keys for Sale | Yellow | Shop | \- | \- | \- | \- | Dead End | \- |  |  | 85 |
| 74 | Showroom | Shops | Unusual | 2 | Luxury Items for Sale | Yellow | Shop | \- | \- | \- | \- | Straight | \- |  |  | 127 |
| 75 | Laundry Room | Shops | Rare | 1 | Launder Currency | Yellow | Shop | \- | \- | \- | \- | Dead End | \- | Yes |  | 81 |
| 76 | Bookshop | Shops | Rare | 1 | Books for sale | Yellow | Shop | \- | \- | \- | Draft From Library | L | \- |  |  | 14 |
| 77 | The Armory | Shops | Standard | \- | Weapons & Armor for sale | Yellow / Black | Shop | Blackprint | \- | Knight Chess Piece Active | \- | L | \- |  |  | 149 |
