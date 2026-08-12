"""Sledge Hammer: a Mechanarium third-compartment grant candidate.

Its "smash" effect tag (data/special_items.json) stays in data -- it is a
parameterless marker shared with Power Hammer and Morning Star, read
generically by special_items._has_item_effect, and this module's own scope
does not otherwise touch that read path.
"""

from __future__ import annotations

ITEM_ID = "sledge_hammer"
