"""Laboratory: the Experimental Setup terminal, and both halves of the
Blackbridge Grotto unlock (Private Drive -> Blackbridge Grotto, docs/areas.md).

The owner's rule has two conjuncts, and this room owns both latches:

  - ``open_grotto_gate`` (ON_ENTER) sets ``state.lab_visited``.
  - ``latch_power`` (ON_DRAFT_ROOM) sets ``state.lab_powered`` once this
    Laboratory is powered (docs/power.md).

Both are one-time for the whole save, so each records an in-run discovery on
``GameState`` that ``shops.carryover`` ORs with its ``GameConfig`` counterpart.

``Capability.EXPERIMENT_TERMINAL`` is read by ``Game.at_laboratory_terminal``
to gate the Experimental Setup menu (``can_start_setup`` and the rest of the
experiment-configuration actions) to this room -- the same shape as the
Planetarium's Telescope-reveal capability (``effects/rooms/planetarium.py``):
both terminals are single-room mechanics with no shared tag handler to hang
off, so a dedicated ``Capability`` replaces the room-id-literal check
``Game`` used to make directly.
"""

from __future__ import annotations

from .. import Capability, Hook, provides, room_hook

provides("laboratory", Capability.EXPERIMENT_TERMINAL)


@room_hook("laboratory", Hook.ON_ENTER)
def open_grotto_gate(game, room, ctx_room) -> None:
    game.state.lab_visited = True


@room_hook("laboratory", Hook.ON_DRAFT_ROOM)
def latch_power(game, room, ctx_room) -> None:
    """Record that this Laboratory has been powered, the moment it is.

    ON_DRAFT_ROOM is the right hook because placement is the only thing that
    can change the power network: power reads the grid and the door masks
    alone, both written in ``_place_room``, and this hook is broadcast to
    every placed room on every placement -- including the Laboratory's own
    (``ctx_room is room``), which covers a Laboratory drafted next to a Boiler
    Room that was already standing.

    Cheap to fire: the power map is memoized per grid/door layout on ``Game``,
    and once the latch is set the handler returns before touching it.
    """
    if game.state.lab_powered:
        return
    if game.room_powered(room):
        game.state.lab_powered = True
