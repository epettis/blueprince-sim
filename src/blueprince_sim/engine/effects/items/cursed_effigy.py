"""Cursed Effigy: gated out of the spawn pipeline until the Gift Shop's
Cursed Coffers has been purchased once (``cfg.cursed_effigy_unlocked``). Its
pickup effect (clamps steps down to a fixed value) is already read generically
via the ``set_steps_on_pickup`` data tag in special_items._on_pickup, so this
module only owns the spawn gate.
"""

from __future__ import annotations

ITEM_ID = "cursed_effigy"


def gate(cfg, gated: list[str]) -> None:
    """Appends ``cursed_effigy`` to ``gated`` while it has not been unlocked."""
    if not cfg.cursed_effigy_unlocked:
        gated.append(ITEM_ID)
