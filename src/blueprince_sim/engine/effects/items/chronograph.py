"""Chronograph: while held, a 40% Tomorrow-Rooms priority draw (the
data/priority_draws.json 'chronograph' entry, gated by draft.py's
``chronograph_active_from_state``). Its other effect, rewinding to a past
redraw, needs redraw history the sim does not retain and is unmodelled.
"""

from .. import ItemCapability, item_provides

item_provides("chronograph", ItemCapability.CHRONOGRAPH)
