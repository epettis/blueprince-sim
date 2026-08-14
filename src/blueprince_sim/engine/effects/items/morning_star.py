"""Morning Star: a Sledge Hammer variant (shares the data-driven "smash" tag
handled generically in special_items.py) that also grants a permanent star.

Wiki (blueprince.wiki.gg/wiki/Morning_Star, action=raw): "Additionally, if in
your inventory at the end of the day, you gain 1 star." The infobox phrases
the same effect as "Tomorrow morning, gain 1 Star" -- both describe one
end-of-day-held check, not a pickup-time grant: an item picked up and then
stolen (Lost & Found) or traded away before day end must NOT grant the star.

Checked from special_items.end_of_day_carry, the same day-end call site as
moon_pendant.carry_over, rather than on pickup. No deferred pending-trigger
is needed the way Battery Pack needs one: Battery Pack defers because its
roll needs rng that is not in scope at pickup time, but this grant is
unconditional (no roll) and only needs to observe "held right now" at the
one moment special_items already calls end_of_day_carry. Nothing within
today can observe the new star early either: state.stars is a live-growing
counter, but every within-day gate reads cfg.stars instead -- the frozen
start-of-day snapshot (e.g. effects/items/telescope.py::gate) -- so a star
added anytime before shops.carryover() reads state.stars already behaves as
"tomorrow morning" with no extra machinery.

Silent on how many days in a row the grant repeats; read literally ("if...at
the end of the day"), it fires again on any later day the item is still
held, which is how this is implemented -- there's nothing in the source to
say otherwise.
"""

from __future__ import annotations

ITEM_ID = "morning_star"


def grant_star_if_held(state) -> None:
    """+1 permanent star (state.stars) iff a Morning Star is held right now."""
    if state.inventory.get(ITEM_ID, 0) > 0:
        state.stars += 1
