"""Treasure Map: marks a buried-treasure cell on first arrival after
pickup, then pays out a one-per-day coins/gems reward the first time the
player digs that cell with a tool held.

Both fire for effect (mutating state.special.treasure_cell /
state.special.treasure_dug directly) rather than returning a value through
any ItemHook, so neither fits any of the six ItemHook members; nothing else
competes for either event. Called directly from special_items.on_arrive
(cell resolution) and special_items.dig_all (reward payout) at their
existing call sites -- the same direct-dispatch shape as watering_can and
sleeping_mask.

Both draws stay on the "treasure_map" rng substream and fire in the same
relative order they always did: on_arrive resolves the cell before it calls
dig_all, so the cell draw always precedes the reward draw. The
"treasure_map" data section (registry.special.treasure_map: cells, rewards)
is a published table and stays loaded in special_items.py -- only the two
draws that consume it move here.
"""

from __future__ import annotations

ITEM_ID = "treasure_map"


def resolve_cell(game) -> None:
    """Picks the buried-treasure cell on first arrival after pickup, if the
    map is held and no cell has been resolved yet today."""
    state = game.state
    if state.inventory.get(ITEM_ID, 0) <= 0 or state.special.treasure_cell != -1:
        return
    cells = game.registry.special.treasure_map["cells"]
    state.special.treasure_cell = game.rng.choice(ITEM_ID, cells)


def dig_reward(game, cell: int, tool_item) -> bool:
    """Pays out the one-per-day dig reward at the marked cell, once a dig
    tool is held. Returns True if the reward fired, so the caller can chain
    the same room-unlock effect a regular dig spot triggers."""
    state = game.state
    registry = game.registry
    if not (state.special.treasure_cell == cell
            and not state.special.treasure_dug
            and tool_item is not None):
        return False
    from ...special_items import on_coins_granted
    rewards = registry.special.treasure_map["rewards"]
    reward = game.rng.choice(ITEM_ID, rewards)
    coins = reward.get("coins", 0)
    gems = reward.get("gems", 0)
    if coins > 0:
        bonus = on_coins_granted(state, registry, coins)
        state.coins += coins + bonus
        state.items_found_log.append(("coins", coins))
    if gems > 0:
        state.gems += gems
        state.items_found_log.append(("gem", gems))
    state.special.treasure_dug = True
    return True
