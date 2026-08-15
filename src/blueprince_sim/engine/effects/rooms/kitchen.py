"""Kitchen: registers its daily stock builder.

Registered via ``shops.register_stock_builder``, the same shape
``commissary.py`` uses.
"""

from __future__ import annotations

from ... import shops


def _roll_kitchen(game, table: dict) -> None:
    """Build the Kitchen's daily stock: static entries + one rolled special dish.

    Static stock (banana × limit 5, club_sandwich × limit 1) is always present.
    Exactly ONE special is selected from the ``special_roll`` list using a
    cumulative-chance roll (substream ``shop_stock``, same pattern as the
    Locksmith's priority roll). Each special carries ``kind``, ``grant``,
    ``price``, and ``limit`` in the data record.
    """
    state = game.state
    entries = []

    # Static entries (always offered)
    for raw in table.get("stock", []):
        entry = dict(raw)
        entry.setdefault("sold", 0)
        entries.append(entry)

    # Roll the daily special (40% Bacon & Eggs / 30% Chef Salad / 30% Tomato Soup)
    specials = table.get("special_roll", [])
    if specials:
        roll_val = game.rng.uniform("shop_stock", 0.0, 100.0)
        total = 0.0
        chosen_special = specials[-1]  # fallback: last entry
        for s in specials:
            total += s["chance"]
            if roll_val < total:
                chosen_special = s
                break
        entry = {k: v for k, v in chosen_special.items() if k != "chance"}
        entry.setdefault("sold", 0)
        entries.append(entry)

    state.shops.stock["kitchen"] = entries


shops.register_stock_builder("kitchen", _roll_kitchen)
