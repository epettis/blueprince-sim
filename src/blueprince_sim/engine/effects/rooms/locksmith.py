"""Locksmith: registers its daily stock builder, including the special-key
offer and the Electromagnet robbery.

Registered via ``shops.register_stock_builder``, the same shape
``commissary.py`` uses. The Electromagnet robbery -- previously a second
``room.id == "locksmith"`` branch fired by ``shops.on_enter_shop`` right
after the stock roll -- is folded into the end of the builder itself: it
only ever needs to run once, at the same first-entry moment the stock is
rolled (``on_enter_shop``'s once-per-room-per-day guard already covers
both). Robbery disables the ``key``/``set_of_3_keys`` rows by marking them
``"disabled"``, a generic flag ``shops._priced_entry`` treats as sold_out
for any shop's entry, not a Locksmith-specific check in ``shops.py``.
"""

from __future__ import annotations

from ..items import car_keys, silver_key
from ... import shops
from ... import special_items as si


def _roll_locksmith(game, table: dict) -> None:
    """Build the Locksmith's daily stock including the special-key offer,
    then fire the Electromagnet robbery if it applies."""
    state = game.state
    registry = game.registry

    entries = []
    for raw in table.get("stock", []):
        entry = dict(raw)
        entry.setdefault("sold", 0)
        if raw.get("not_if_owned") and raw.get("kind") == "item":
            if si.has(state, raw["id"]):
                continue
        entries.append(entry)

    # Roll the special key (30/40/30 priority lists)
    special_key_data = table.get("special_key", {})
    rolls = special_key_data.get("rolls", [])
    price = special_key_data.get("price", 8)
    fallback = special_key_data.get("fallback", [car_keys.ITEM_ID, silver_key.ITEM_ID])

    # Roll which priority list to use (cumulative chance)
    chosen_order = None
    total = 0
    roll_val = game.rng.uniform("shop_stock", 0.0, 100.0)
    for roll_entry in rolls:
        total += roll_entry["chance"]
        if roll_val < total:
            chosen_order = roll_entry["order"]
            break
    if chosen_order is None and rolls:
        chosen_order = rolls[-1]["order"]

    special_key_id = None
    if chosen_order:
        for kid in chosen_order:
            if si._is_available(state, kid, registry):
                special_key_id = kid
                break

    if special_key_id is None:
        # Walk fallback list
        for kid in fallback:
            # car_keys: must be available; silver_key: always ok (non-unique)
            if si._is_available(state, kid, registry):
                special_key_id = kid
                break
            # silver_key at end of fallback is non-unique so _is_available passes
        # If we still have nothing, force silver_key (non-unique; _is_available passes)
        if special_key_id is None:
            special_key_id = fallback[-1] if fallback else silver_key.ITEM_ID

    state.shops.special_key_offer = special_key_id
    # Append the synthetic special-key entry
    synthetic = {
        "id": special_key_id,
        "kind": "item",
        "price": price,
        "special_key": True,
        "sold": 0,
    }
    entries.append(synthetic)

    # Electromagnet robbery: auto-collect 24 keys and disable the key/
    # set_of_3_keys rows for the rest of the day (the special key is exempt
    # -- wiki-confirmed). Checked once, right after today's stock is built.
    for item_id, cnt in state.inventory.items():
        if cnt <= 0:
            continue
        item = registry.special.by_id.get(item_id)
        if item is None:
            continue
        e = item.effect("locksmith_rob")
        if e is not None:
            n_keys = e.param("keys", 24)
            state.keys += n_keys
            state.items_found_log.append(("key", n_keys))
            state.shops.locksmith_robbed = True
            for entry in entries:
                if entry.get("id") in ("key", "set_of_3_keys") and not entry.get("special_key"):
                    entry["disabled"] = True
            break

    state.shops.stock["locksmith"] = entries


shops.register_stock_builder("locksmith", _roll_locksmith)
