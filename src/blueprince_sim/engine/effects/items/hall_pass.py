"""Hall Pass: hallway-to-hallway moves cost no step counter, and drafting a
hallway room from a hallway doorway costs no gem, for as long as it is held.
"""

from .. import ItemCapability, item_provides

item_provides("hall_pass", ItemCapability.FREE_HALLWAY_MOVES)
