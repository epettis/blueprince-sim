"""Master Key: opens any locked door for free while held -- no key is spent
and passability checks never budget a key for a door it can clear.

Movement across an already-drafted locked segment still resolves this
automatically (Game._unlock_for_passage -> special_items.open_locked_free);
at a fresh drafting doorway (Phase.LOCK_PENDING) it is instead its own
special-keys-menu row the player selects explicitly (Game.can_use_special_key_at_lock
/ use_special_key_at_lock), per the owner's "the player chooses how to open
it" ruling -- held()/fits() below back that row.
"""

from .. import ItemCapability, item_capability_any, item_provides

ITEM_ID = "master_key"

item_provides(ITEM_ID, ItemCapability.MASTER_KEY)


def held(state, registry) -> bool:
    """True while a Master Key (or anything else providing the capability) is held."""
    return item_capability_any(state, registry, ItemCapability.MASTER_KEY)


def fits(game, cell: int, direction: int) -> bool:
    """The Master Key opens any standard locked door (wiki: 'Unlocks: Any
    standard locked door'). Phase.LOCK_PENDING only ever parks on a
    DOOR_LOCKED segment (Game.open_door), so this is trivially True
    whenever it can be asked -- a real predicate, not hardcoded in the
    engine, matching silver_key.fits."""
    return True
