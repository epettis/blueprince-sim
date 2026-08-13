"""Battery Pack: a Mechanarium third-compartment grant candidate and a
fabrication-recipe component (shovel+battery_pack+broken_lever->jack_hammer,
sledge_hammer+battery_pack+broken_lever->power_hammer,
compass+battery_pack->powered_electromagnet -- special_items.json's
fabrication table).

On pickup, sets the Workshop's Dynamic Rarity to Standard or Unusual at a
50/50 (wiki). The roll is deferred to the next hand dealt
(resolve_pending, called from Game._deal_and_cache) rather than drawn at
pickup, because grant() deliberately takes no rng -- see
special_items._on_pickup's docstring and treasure_map.py, which resolves its
own marked cell the same way. The second and later triggers in the same day
do not re-roll: they deterministically toggle to the other option (wiki:
"Triggering this effect multiple times in a day will always switch to the
other one").
"""

from __future__ import annotations

ITEM_ID = "battery_pack"


def on_pickup(state, item) -> None:
    """Records one pending Dynamic Rarity trigger; the roll/toggle itself is
    deferred to :func:`resolve_pending`, where rng is in scope."""
    e = item.effect(ITEM_ID)
    if e is not None:
        state.special.battery_pack_pending += 1


def resolve_pending(game) -> None:
    """Drains today's pending triggers in pickup order: the first applies a
    fresh 50/50, every later one toggles to the other option.

    Room id and the two rarity options come from
    ``registry.special.battery_pack`` (data), not a Python branch on the room
    id, per repo doctrine that published tables belong in data.
    """
    state = game.state
    special = state.special
    if special.battery_pack_pending <= 0:
        return
    from ... import decks  # decks -> state -> special_items -> here: local import breaks the cycle

    data = game.registry.special.battery_pack
    room_id = data.get("room")
    options = data.get("options", ())
    if not room_id or not options:
        special.battery_pack_pending = 0
        return

    while special.battery_pack_pending > 0:
        special.battery_pack_pending -= 1
        if special.battery_pack_last_rarity == -1:
            idx = game.rng.randint("battery_pack_rarity", 0, len(options) - 1)
        else:
            idx = (special.battery_pack_last_rarity + 1) % len(options)
        special.battery_pack_last_rarity = idx
        rarity_idx = decks.RARITIES.index(options[idx])
        decks.set_dynamic_rarity(state, game.registry, room_id, rarity_idx, game.rng,
                                 label="battery_pack_set_dynamic_rarity")
