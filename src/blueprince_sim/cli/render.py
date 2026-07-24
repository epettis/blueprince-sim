"""ASCII rendering of the manor grid."""

from __future__ import annotations

from ..engine.game import Game, Phase
from ..engine.grid import E, N, S, W

# Door-mask -> box-drawing glyph, so a drafted room's orientation is visible at
# a glance (lines point in the directions the room has doors). Same characters
# the rotation model is described with.
DOOR_GLYPH = {
    0: "·",
    N: "╵", E: "╶", S: "╷", W: "╴",
    N | S: "║", E | W: "═",
    N | E: "╚", N | W: "╝", S | E: "╔", S | W: "╗",
    N | E | S: "╠", N | S | W: "╣", N | E | W: "╩", E | S | W: "╦",
    N | E | S | W: "╬",
}


def door_glyph(mask: int) -> str:
    return DOOR_GLYPH.get(mask, "·")


CAT_COLOR = {
    "blueprint": "\033[94m", "bedroom": "\033[95m", "hallway": "\033[33m",
    "green": "\033[92m", "shop": "\033[93m", "red": "\033[91m",
    "blackprint": "\033[90m", "studio_addition": "\033[96m",
    "outer": "\033[36m", "objective": "\033[1;97m",
}
RESET = "\033[0m"


def _code(name: str) -> str:
    """Two-letter cell code for a room name: initials of the first two words, else first two letters."""
    words = name.replace("'", "").split()
    return (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1])).upper()


def render_grid(game: Game, color: bool = True) -> str:
    """Render the 5x9 manor as ASCII, rank 9 (Antechamber) on top.

    Each placed room is a two-letter code (ANSI-colored by category unless
    ``color`` is False) with ``|``/``-`` stubs on its door sides; ``@`` marks
    the player and ``.`` an empty cell.
    """
    st = game.state
    reg = game.registry
    lines = []
    for rank in range(9, 0, -1):
        top, mid, bot = [], [], []
        for col in range(5):
            cell = (rank - 1) * 5 + col
            idx = st.grid[cell]
            if idx < 0:
                top.append("     ")
                mid.append("  .  ")
                bot.append("     ")
                continue
            room = reg.rooms[idx]
            doors = st.placed_doors[cell]
            code = _code(room.name)
            if color:
                code = CAT_COLOR.get(room.category, "") + code + RESET
            here = "@" if st.pos == cell else " "
            top.append(f"  {'|' if doors & N else ' '}  ")
            mid.append(f"{'-' if doors & W else ' '}{here}{code}{'-' if doors & E else ' '}")
            bot.append(f"  {'|' if doors & S else ' '}  ")
        lines.append(f"  {''.join(top)}")
        lines.append(f"{rank} {''.join(mid)}")
        lines.append(f"  {''.join(bot)}")
    return "\n".join(lines)


def render_status(game: Game) -> str:
    """One-line resource/progress summary; adds a security line when door locks are enabled."""
    st = game.state
    line = (f"Steps {st.steps:3d} | Gems {st.gems} | Keys {st.keys} | Coins {st.coins} | "
            f"Dice {st.dice} | Luck {st.luck} | Rank {game.deepest_rank} | Day {st.day} ({st.stage})")
    if game.cfg.door_locks:
        card = "yes" if st.has_keycard else "no"
        power = "on" if st.keycard_power_on else "off"
        doors = "openable" if game.security_openable() else "sealed"
        line += (f"\nSecurity: level {st.security_level} | power {power} | "
                 f"keycard {card} | security doors {doors}")
    return line


def render_options(game: Game) -> str:
    """List the pending draft options, one line per slot; "" outside the DRAFTING phase.

    Each line shows the orientation glyph, name, rarity, layout, and effective
    cost, flagging unaffordable and forced options; an Archives mystery slot
    hides identity and orientation.
    """
    if game.phase is not Phase.DRAFTING or game.state.pending is None:
        return ""
    lines = []
    pending = game.state.pending
    for opt in pending.options:
        room = game.registry.rooms[opt.room_idx]
        afford = "" if game.affordable(room, opt) else " (can't afford)"
        cost = game._effective_cost(room, opt)
        if opt.hidden:
            # Identity and orientation are hidden for an Archives mystery.
            lines.append(f"  [{opt.slot + 1}] ? {'??? (mystery room)':<22} "
                         f"{'hidden':<12} {'?':<9} cost {cost}{afford}")
            continue
        glyph = door_glyph(opt.orientation)
        forced = " [forced]" if opt.forced else ""
        eff = room.effects[0].tag if room.effects else ""
        lines.append(f"  [{opt.slot + 1}] {glyph} {room.name:<22} {room.rarity or '-':<12} "
                     f"{room.layout:<9} cost {cost}{afford}{forced}  {eff}")
    return "\n".join(lines)
