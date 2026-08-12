"""Silver Spoon: doubles food step gains while held (applied after Salt
Shaker's flat +1 bonus).
"""

from .. import ItemCapability, item_provides

item_provides("silver_spoon", ItemCapability.FOOD_MULTIPLIER)
