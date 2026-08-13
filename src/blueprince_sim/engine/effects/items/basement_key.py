"""Basement Key: unlocks doors within the Basement, permanently, never
consumed. This sim models the Basement purely as an off-grid area-graph
destination (rooms.json has no "basement" room; see docs/areas.md's
basement_key_foundation / basement_key_well gates, gated on this item id
via GateContext, not via st.door_state) -- so no on-grid DOOR_LOCKED
doorway segment is ever a Basement door. Confirmed by the Doors wiki page:
"THE BASEMENT DOOR IS LOCKED, and any normal or special key other than a
Basement Key does not fit" -- the converse also holds, a Basement Key does
not fit an ordinary locked door. fits() below is therefore correctly
always False for the draft-time lock menu (Phase.LOCK_PENDING, which only
ever parks on an on-grid segment): a structural fact about this sim's room
model, not an unimplemented feature.
"""

ITEM_ID = "basement_key"


def held(state) -> bool:
    """True while at least one Basement Key is in inventory."""
    from ...special_items import has
    return has(state, ITEM_ID)


def fits(game, cell: int, direction: int) -> bool:
    """Never true: see the module docstring -- no on-grid doorway is ever
    a Basement door in this sim's model."""
    return False
