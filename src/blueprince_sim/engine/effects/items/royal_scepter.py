"""Royal Scepter: obtainable in-run only via the unmodeled Treasure Trove /
Key of Aries puzzle, so it is gated out of the ordinary spawn pipeline until
``cfg.royal_scepter_found`` (a carry-over discovery from an earlier day),
at which point it is granted fresh at every day's reset instead. Its own
held-fact also gates colour activation (``shops.can_activate_scepter``).
"""

from __future__ import annotations

ITEM_ID = "royal_scepter"


def gate(cfg, gated: list[str]) -> None:
    """Appends ``royal_scepter`` to ``gated`` unless discovered via carry-over."""
    if not cfg.royal_scepter_found:
        gated.append(ITEM_ID)


def grant_carry_over(state, registry, cfg) -> None:
    """Grants a fresh Royal Scepter at day start when cfg.royal_scepter_found."""
    if not cfg.royal_scepter_found:
        return
    from ...special_items import grant
    grant(state, registry, ITEM_ID, source="day_start")


def held(state) -> bool:
    """True while a Royal Scepter is currently in inventory."""
    return state.inventory.get(ITEM_ID, 0) > 0
