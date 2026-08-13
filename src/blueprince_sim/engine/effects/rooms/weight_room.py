"""Weight Room: a red room that halves the player's remaining steps on draft,
and on entry pulls the Antechamber's south lever (design doc
antechamber-lever-design.md).

The halving is a red-room penalty, so Shelter's negation (and Knight's
Shield) can cancel it, same as the Chapel's coin loss or the Maid's
Chamber's anti-luck.
"""

from __future__ import annotations

from ... import experiments
from ...grid import N
from ...locks import DOOR_SEALED, segment_key
from .. import Hook, provides_lever, room_hook
from ..items import power_hammer
from ..tier1 import _red_negated

SOUTH_SEGMENT_CELL = 37  # rank 8 center: its north face is the Antechamber's south door


@room_hook("weight_room", Hook.ON_PLACE)
def halve_remaining_steps(game, room, ctx_room) -> None:
    if _red_negated(game, room):
        return
    game.state.steps -= game.state.steps // 2


def pull_south_lever(game, cell: int) -> None:
    """Open the sealed south segment, if a Power Hammer has broken the wall.

    A wall already broken on a prior visit (weight_room_wall_broken
    carries over) also counts; the break is recorded the first time it
    happens.
    """
    if not game.cfg.antechamber_levers:
        return
    st = game.state
    seg = segment_key(SOUTH_SEGMENT_CELL, N)
    if st.door_state.get(seg) != DOOR_SEALED:
        return
    can_break = (
        game.cfg.weight_room_wall_broken
        or st.shops.weight_room_wall_broken
        or (game.cfg.special_items and power_hammer.held(st))
    )
    if not can_break:
        return
    st.shops.weight_room_wall_broken = True
    game._open_segment(SOUTH_SEGMENT_CELL, N)
    experiments.on_lever_pulled(game, SOUTH_SEGMENT_CELL, N)


provides_lever("weight_room", pull_south_lever)
