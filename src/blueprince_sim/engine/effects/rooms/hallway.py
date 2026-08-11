"""Hallway variants: the trunk upgrade, and the Tomorrow Hallway's cross-day
extra-copy carry.

Implemented:
  - hallway__ix75 -- "+1 locked trunk" (blueprince.wiki.gg/wiki/Hallway: "a
    Hallway upgrade always contains a trunk", guaranteed rather than luck-
    rolled). No handler here: the container system already keys a room's
    containers by id (data/special_items.json containers.rooms), and
    engine/special_items.py's containers_in()/open_container() read that
    table generically, so declaring "hallway__ix75": {"trunk": 1} there is
    the entire change. Opening (smash or 1 key, per the trunk kind's own
    ``opener`` list) is the existing container action, unchanged.
  - hallway__ix76 -- "Add an extra HALLWAY to tomorrow's draft pool"
    (blueprince.wiki.gg/wiki/Hallway/Upgrades). Cumulative: drafting N copies
    today adds N extra Hallways tomorrow. count_drafted_today increments a
    per-day counter at ON_PLACE (fires once per Tomorrow Hallway actually
    drafted); shops.py::carryover() reports it as "hallway_tomorrow_extra";
    env/multiday.py::DayChain replaces (not merges) GameConfig's field of the
    same name from that report each advance(), a one-day pulse like
    mail_cycle/mail_transit_days, not a running total.
  - inject_tomorrow_copies -- registered on the Entrance Hall's own ON_PLACE,
    which fires exactly once at the top of every reset() (regardless of
    GameConfig.special_items, unlike shops.on_day_start), after decks are
    already built -- so this is the earliest unconditional day-start hook
    available to add GameConfig.hallway_tomorrow_extra copies of the plain
    Hallway to TODAY's pool via Game.inject_rooms.

Not modelled:
  - The wiki's per-copy placement quirk (added copies may land on edges but
    never horizontally into B1/D1/B9/D9, and the last copy added reverts to
    the normal placement rule) -- this data model has one placement rule per
    room id, with no way to express "this specific injected copy differs from
    every other Hallway card in the deck". The extra copies are ordinary
    Hallways, subject to the normal Hallway draft conditions.
"""

from __future__ import annotations

from .. import Hook, room_hook

HALLWAY_ID = "hallway"
TOMORROW_HALLWAY_ID = "hallway__ix76"


@room_hook(TOMORROW_HALLWAY_ID, Hook.ON_PLACE)
def count_drafted_today(game, room, ctx_room) -> None:
    """Each Tomorrow Hallway drafted today adds one to tomorrow's carry."""
    game.state.hallway_tomorrow_count += 1


@room_hook("entrance_hall", Hook.ON_PLACE)
def inject_tomorrow_copies(game, room, ctx_room) -> None:
    """Adds yesterday's carried Tomorrow Hallway copies to today's pool."""
    extra = game.cfg.hallway_tomorrow_extra
    if extra > 0:
        game.inject_rooms([HALLWAY_ID] * extra)
