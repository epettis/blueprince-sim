"""Chronograph: while held, a 40% Tomorrow-Rooms priority draw (the
data/priority_draws.json 'chronograph' entry, gated by draft.py's
``chronograph_active_from_state``). Its other effect -- REWIND, restoring a
hand a redraw replaced -- needs no data-driven tag: it is driven entirely by
``PendingDraft.rewind_stack`` and ``Game.can_rewind``/``rewind`` (engine/
game.py), both gated the same way on this capability.
"""

from .. import ItemCapability, item_provides

item_provides("chronograph", ItemCapability.CHRONOGRAPH)
