"""Security: entering the terminal permanently unlocks its offline mode, so
cutting power at the Utility Closet later swings every security door open.
"""

from __future__ import annotations

from .. import Hook, room_hook


@room_hook("security", Hook.ON_ENTER)
def unlock_offline_mode(game, room, ctx_room) -> None:
    if not game.cfg.door_locks:
        return
    game.state.offline_unlocked = True
