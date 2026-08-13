"""Silver Key: consumed (not a regular key) to open a locked doorway when
drafting through it -- never when merely moving through an already-drafted
one -- and biases the next deal toward cross/t layouts. Also a candidate
grant in the Mechanarium's second diagonal compartment, ahead of the
Keycard/Secret Garden Key/Vault Key 233 fallbacks.
"""

from __future__ import annotations

ITEM_ID = "silver_key"


def held(state) -> bool:
    """True while at least one Silver Key is in inventory."""
    from ...special_items import has
    return has(state, ITEM_ID)


def fits(game, cell: int, direction: int) -> bool:
    """The Silver Key opens any standard locked door, same as a regular key
    (wiki: 'Unlocks: Any standard locked door'). Phase.LOCK_PENDING only ever
    parks on a DOOR_LOCKED segment (Game.open_door), so this is trivially
    True whenever it can be asked -- a real predicate, not hardcoded in the
    engine, matching master_key.fits."""
    return True


def consume_for_draft(state) -> bool:
    """Consumes a held Silver Key for a draft-time (not movement) locked-door
    open, flagging the next deal for cross/t-layout bias.

    Returns False without any effect when none is held, so callers can use
    the return value as the "handled" branch of an if/elif.
    """
    from ...special_items import has, remove
    if not has(state, ITEM_ID):
        return False
    remove(state, ITEM_ID, consumed=False)
    state.special.silver_key_draft = True
    return True


def mechanarium_grant(state, registry, game) -> str | None:
    """Second Mechanarium key-chain compartment step: grants a Silver Key if
    not already held and still available, else declines (None) so the caller
    can fall through to its next candidate."""
    from ...special_items import _apply_grant, _is_available, has
    if has(state, ITEM_ID) or not _is_available(state, ITEM_ID, registry):
        return None
    return _apply_grant(state, registry, game, {"kind": "item", "id": ITEM_ID})
