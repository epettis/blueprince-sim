# Locked doors and the security-door system

Both systems live in `engine/locks.py` with tables in `data/locks.json`
(datamined from TFMurphy's lock/security datamine, reddit `1lfxyex`, via
wiki.gg Doors). State is per doorway *segment* — the shared edge between two
cells — in `GameState.door_state`, keyed by `locks.segment_key`. The whole
system is disabled by `cfg.door_locks=false`.

## Locked doors

Every doorway segment rolls its lock state from a table keyed by rank and
orientation:

- Never locked below rank 4 by chance; 25% inside rank 4, climbing to
  110%/130% at ranks 8–9. Values over 100% are guaranteed locks at neutral
  bias.
- A daily **bias multiplier** softens streaks: hitting a locked door
  subtracts 0.385 (capped at 1), an unlocked one adds 0.35 (floored at 1),
  with datamined second-roll exemptions above 100% and below 31%.
- **Corridor and Corriyard doors are guaranteed unlocked.**

Opening a locked door consumes one key — at a frontier doorway when
drafting through it, or mid-walk when a path routes through a locked door
between placed rooms. The pathfinder is **key-aware**: a locked door en
route is keyed through or walked around, whichever the key and step budgets
allow. With no key, the detour distance is what counts — a lock can put the
Antechamber out of reach of your remaining steps.

**In-drafting opens doors free**: a drafted room whose floorplan has a door
facing an existing locked or security door swings it open without spending
a key.

## Security doors

Doors of whitelisted mechanical rooms (Security, Workshop, Pump Room,
Archives, …) can spawn as keycard doors when close enough to the
Antechamber: `rand(0,75) > distance`, with a 60-unit cutoff. Spawns are
capped per day by the **security level** — low 3 / normal 4 / high 6, with
high forcing every whitelist door's chance to 100%. Keys never open
security doors.

Three interacting controls:

- The **Keycard** (found by chance in Archives/Office/Laboratory/Vault/…)
  opens security doors while the system is powered.
- The **Utility Closet** breaker toggles keycard power.
- The **Security terminal** sets the security level and its offline mode:
  unpowered doors open for free once Security has been visited (the sim
  assumes the player flips offline mode to Unlocked), and are sealed to
  everyone — keycard included — otherwise.

So the two winning configurations are: powered + keycard in hand, or
unpowered + offline mode Unlocked (requires a Security visit).

## The Antechamber's doors

The Antechamber's doorways roll on the ordinary rank 8↔9 lock table
(130% ⇒ locked at neutral bias), but drafting a connecting room opens them
via in-drafting, so entry stays free once connected. The real game's
bespoke Antechamber locks are not modeled.

## Known simplifications

- Locks roll when the first door on a segment is *placed*, not lazily on
  first click as in the real game, so the bias sequence follows placement
  order.
- The per-door Left/Forward/Right security table is collapsed to one chance
  per room (its strongest door).
- Not modeled: the "Set"-door double-trigger, Great Hall/Vestibule
  guaranteed states (including the Vestibule re-locking a random door on
  each entry — deferred, though the key-aware pathfinder is ready for it),
  Lock Pick Kit, special keys, Master Key, Foyer/Kennel/Shelter unlock
  effects, and the Passageway high-security distance waiver.
- The Keycard is found by flat chance (25%, inferred) on first entry to a
  wiki-listed source room.
- Visiting Security always sets offline mode to Unlocked (the strategically
  dominant choice); toggles are free actions while standing in the room.
