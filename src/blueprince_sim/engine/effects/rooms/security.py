"""Security: entering the terminal permanently unlocks its offline mode, so
cutting power at the Utility Closet later swings every security door open.

``Capability.SECURITY_LEVEL`` is read by ``Game.can_set_security_level`` (via
``Game._capability_cell``) to gate the security-level terminal menu to this
room's cell, without ``game.py`` naming this room's id directly.
"""

from __future__ import annotations

from .. import Capability, Hook, provides, room_hook

provides("security", Capability.SECURITY_LEVEL)


@room_hook("security", Hook.ON_ENTER)
def unlock_offline_mode(game, room, ctx_room) -> None:
    if not game.cfg.door_locks:
        return
    game.state.offline_unlocked = True
