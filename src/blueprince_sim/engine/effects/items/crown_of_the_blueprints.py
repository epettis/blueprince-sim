"""Crown of the Blueprints: guaranteed in Room 46, but gated out of the
spawn pipeline until Room 46 has been reached on an earlier day
(``cfg.room46_reached``).

The wiki's obtain rule is *"It cannot be obtained the first time the room is
reached, but is present in other times."* ``cfg.room46_reached`` is the
permanent carry-over flag that first turns True at the *next* day's reset, so
reading it here blocks the whole day on which Room 46 is first entered and
allows every later day -- the same day-granularity convention the eight
Sanctum Keys already use for this flag (special_items.configure) and that
``GameConfig.gem_gate_active`` uses.

The item's own effect (a first-Red-Room draft-pool removal) is not modelled;
its record stays ``implemented: false`` and this module owns only the gate.
"""

from __future__ import annotations

ITEM_ID = "crown_of_the_blueprints"


def gate(cfg, gated: list[str]) -> None:
    """Appends ``crown_of_the_blueprints`` to ``gated`` until Room 46 has been
    reached on an earlier day."""
    if not cfg.room46_reached:
        gated.append(ITEM_ID)
