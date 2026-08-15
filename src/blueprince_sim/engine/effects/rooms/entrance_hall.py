"""Entrance Hall: provides its container-kinds overlay and the vase-smash
capability.

registry.special.containers["rooms"] carries no static Entrance Hall entry
-- every trunk here comes from ``state.special.entrance_hall_trunks``, which
two unrelated sources bump under one shared cap: the entrance_hall_trunk
experiment effect (experiments.py::apply_effect) and The Twins constellation
(constellations.py::apply_effect). Reuses the existing ``trunk``
containers.kinds entry rather than a distinct kind, per the wiki: "There is
no difference between a 'small chest' and a regular trunk."

``Capability.VASE`` is read by shops.py's ``can_smash_vase`` to gate the
west-side vase-smash discovery action to this room.
"""

from __future__ import annotations

from .. import Capability, provides, provides_containers
from ... import special_items

provides("entrance_hall", Capability.VASE)


@provides_containers("entrance_hall")
def container_kinds(state, registry, cell: int) -> dict[str, int]:
    """The Entrance Hall's container kinds: its static table plus today's overlay."""
    kinds = special_items.containers_in(registry, "entrance_hall")
    extra = state.special.entrance_hall_trunks
    if extra:
        kinds = dict(kinds)
        kinds["trunk"] = kinds.get("trunk", 0) + extra
    return kinds
