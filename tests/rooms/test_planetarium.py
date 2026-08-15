"""Planetarium: 2 Stars for ENDING the day there, not for merely walking in.

Effect text (blueprince.wiki.gg/wiki/Planetarium, infobox): "If you call it a
day in PLANETARIUM, gain {{icon|star|2}}" -- and the body text: "Ending the
day in the Planetarium will increase star count by 2." Both gate the grant on
day-end, not on entry.

The room's own "grant" effect fires on ON_ENTER by default (see
engine/effects/tier1.py); the Planetarium overrides that default with a
"when": "on_day_end" param so the same handler fires at Game._terminate's
single ON_DAY_END call site (engine/game.py) instead. state.stars is a
carried-forward permanent counter (see GameState.stars), the same shape as
allowance -- these tests also cover that a Planetarium star survives the day
boundary.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.game import Game
from blueprince_sim.engine.grid import N, S
from blueprince_sim.env.multiday import DayChain


def test_entering_the_planetarium_without_ending_the_day_there_grants_no_stars(registry, cfg):
    """Walking into the Planetarium and then leaving (or simply not ending
    the day there) must not grant the 2 Stars -- the historical bug had the
    "grant" effect firing on ON_ENTER, before the day-end gate the wiki
    describes."""
    g = Game(cfg, seed=1, registry=registry)
    room = registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)  # enters the Planetarium; stops short of ending the day here
    assert g.state.pos == 7
    assert g.state.stars == 0


def test_ending_the_day_in_the_planetarium_grants_two_stars(registry, cfg):
    """Draining the player's steps to 0 while standing in the Planetarium
    grants exactly 2 Stars, matching the wiki's flat amount."""
    g = Game(cfg, seed=2, registry=registry)
    room = registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)
    g.state.steps = 0
    g._check_termination()
    assert g.is_done()[0]
    assert g.state.stars == 2


def test_ending_the_day_elsewhere_grants_no_stars(registry, cfg):
    """A Planetarium sitting on the grid, unvisited (or visited but not the
    room the day ends in), never pays out -- the grant is keyed to the
    ON_DAY_END room, not to the Planetarium's mere presence or a past visit."""
    g = Game(cfg, seed=3, registry=registry)
    room = registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)  # visit it...
    g.move(S)  # ...then leave, back to the Entrance Hall
    g.state.steps = 0
    g._check_termination()
    assert g.is_done()[0]
    assert g.state.stars == 0


def test_a_planetarium_star_carries_over_to_the_next_day(registry):
    """Stars earned ending a day in the Planetarium show up in the next
    day's starting state.stars via DayChain -- the same permanent,
    replace-wholesale carryover shape as allowance (GameState.stars)."""
    chain = DayChain(GameConfig(), n_days=5)

    g1 = Game(chain.next_config(), seed=4, registry=registry)
    room = registry.by_id["planetarium"]
    g1._place_room(room, 7, N | S)
    g1.move(N)
    g1.state.steps = 0
    g1._check_termination()
    assert g1.state.stars == 2

    chain.advance(g1.carryover())
    day2_cfg = chain.next_config()
    assert day2_cfg.stars == 2
    g2 = Game(day2_cfg, seed=5, registry=registry)
    assert g2.state.stars == 2


# ==================================================== TELESCOPE-IN-PLANETARIUM

from dataclasses import replace as _dc_replace  # noqa: E402

from blueprince_sim.engine import special_items as si  # noqa: E402
from blueprince_sim.engine.special_items import configure  # noqa: E402
from blueprince_sim.engine.state import GameState  # noqa: E402

# Hard-coded from the wiki (Telescope's "another use"/"all planetarium
# upgrades" SpoilerBoxes, verbatim): "The planets seem to appear in a random
# order, except Mora which is always last... Once all five planets appear,
# the Telescope can no longer be used in the Planetarium." Gallery captions:
# "Dauja: Plantetarium spawns with a Trunk.", "Fennmora: ... an Apple.",
# "Mamora: ... a single Ivory Die.", "Veia: ... a Dirt Pile.", "Mora: ... a
# Prism Key." Deliberately hard-coded rather than read from
# registry.special.planetarium_planets, so these tests cannot pass by
# echoing a data-entry bug back at itself.
_WIKI_PLANET_IDS = frozenset({"dauja", "fennmora", "mamora", "veia", "mora"})
_WIKI_MORA_ID = "mora"


def _with_telescope(cfg: GameConfig) -> GameConfig:
    """``cfg`` plus a starting Telescope, preserving any other starting_items."""
    return _dc_replace(cfg, starting_items=frozenset(cfg.starting_items) | {"telescope"})


def _game_with_telescope(seed: int = 0, cfg: GameConfig | None = None) -> Game:
    """A Game holding a Telescope, standing in a placed, entered Planetarium
    at cell 7 -- the same layout test_a_planetarium_star... above uses."""
    g = Game(_with_telescope(cfg or GameConfig()), seed=seed)
    room = g.registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)
    return g


def test_using_the_telescope_reveals_one_planet_and_spends_the_daily_cap():
    """"Doing this does not consume the Telescope, but only one upgrade can
    be done per day." One use reveals exactly one of the five wiki planets
    and immediately spends today's cap: a second use the same day is illegal."""
    g = _game_with_telescope(seed=1)
    assert g.can_use_telescope_planetarium()
    revealed = g.use_telescope_planetarium()
    assert revealed in _WIKI_PLANET_IDS
    assert g.state.planetarium_planets == (revealed,)
    assert g.state.special.planetarium_telescope_used is True
    assert not g.can_use_telescope_planetarium()


def test_telescope_is_not_consumed_by_planetarium_use():
    """"Doing this does not consume the Telescope" -- the item stays held
    after upgrading the Planetarium."""
    g = _game_with_telescope(seed=2)
    g.use_telescope_planetarium()
    assert si.has(g.state, "telescope")
    assert g.state.inventory["telescope"] == 1


def test_mora_is_always_revealed_last_across_many_seeds():
    """"The planets seem to appear in a random order, except Mora which is
    always last." Reveals all five (bypassing the once-per-day cap via
    direct special_items calls -- special_items.use_telescope_in_planetarium
    itself does not enforce the cap; Game.use_telescope_planetarium's own
    assert does, and is exercised separately above) across 40 different
    seeds, checking the invariant holds for EVERY one, never just most --
    this is a deterministic per-seed rule, not a statistical claim, so no
    threshold is asserted."""
    for seed in range(40):
        g = _game_with_telescope(seed=seed)
        cell = g.state.pos
        order = [si.use_telescope_in_planetarium(g, cell) for _ in range(5)]
        assert set(order) == _WIKI_PLANET_IDS, f"seed={seed}: {order}"
        assert order[-1] == _WIKI_MORA_ID, f"seed={seed}: Mora not last in {order}"
        assert _WIKI_MORA_ID not in order[:4], f"seed={seed}: Mora appeared early in {order}"


def test_each_planets_wiki_payload_is_granted_when_revealed():
    """Wiki gallery captions (verbatim): "Dauja: Plantetarium spawns with a
    Trunk.", "Fennmora: ... an Apple.", "Mamora: ... a single Ivory Die.",
    "Veia: ... a Dirt Pile.", "Mora: ... a Prism Key." Checks each payload's
    OBSERVABLE effect the moment its planet is revealed, matched against
    these hard-coded wiki names -- not against the payload "kind" the
    engine's own planetarium_planets table happens to carry for that id."""
    g = _game_with_telescope(seed=3)
    cell = g.state.pos
    seen: set[str] = set()
    for _ in range(5):
        steps_before = g.state.steps
        dice_before = g.state.dice
        dig_before = g.state.special.veia_dig_bonus.get(cell, 0)
        had_prism_key_before = si.has(g.state, "prism_key")
        # A container's mere EXISTENCE (not whether the player can currently
        # afford to open it -- can_open_container also gates on holding a
        # key/smash tool, which this game has neither of).
        trunk_existed_before = si._next_container_kind(g.state, g.registry, cell) == "trunk"

        planet_id = si.use_telescope_in_planetarium(g, cell)
        assert planet_id not in seen, f"{planet_id} revealed twice"
        seen.add(planet_id)

        if planet_id == "dauja":
            assert not trunk_existed_before, "no Trunk should exist before Dauja"
            assert si._next_container_kind(g.state, g.registry, cell) == "trunk", (
                "Dauja must spawn a Trunk"
            )
        elif planet_id == "fennmora":
            assert g.state.steps > steps_before, "an Apple must grant steps"
        elif planet_id == "mamora":
            assert g.state.dice == dice_before + 1, "a single Ivory Die grants +1 die"
        elif planet_id == "veia":
            assert g.state.special.veia_dig_bonus.get(cell, 0) == dig_before + 1, (
                "Veia must add exactly 1 permanent dig spot"
            )
        elif planet_id == "mora":
            assert not had_prism_key_before
            assert si.has(g.state, "prism_key"), "Mora must grant a Prism Key"
        else:
            raise AssertionError(f"unknown planet id {planet_id!r}")
    assert seen == _WIKI_PLANET_IDS


def test_after_five_days_all_planets_revealed_telescope_becomes_unusable():
    """"Once all five planets appear, the Telescope can no longer be used in
    the Planetarium." Runs 5 real days via DayChain (one reveal per day, the
    once-per-day cap resetting each day boundary), then a 6th day where the
    cap has reset but all five planets are already gone -- the Telescope
    must stay unusable there for a DIFFERENT reason than the daily cap."""
    chain = DayChain(GameConfig(), n_days=10)
    revealed: list[str] = []
    for day in range(5):
        g = Game(_with_telescope(chain.next_config()), seed=100 + day)
        room = g.registry.by_id["planetarium"]
        g._place_room(room, 7, N | S)
        g.move(N)
        assert g.can_use_telescope_planetarium(), f"day {day + 1}: should still have planets left"
        revealed.append(g.use_telescope_planetarium())
        chain.advance(g.carryover())
    assert set(revealed) == _WIKI_PLANET_IDS
    assert revealed[-1] == _WIKI_MORA_ID

    g6 = Game(_with_telescope(chain.next_config()), seed=106)
    room = g6.registry.by_id["planetarium"]
    g6._place_room(room, 7, N | S)
    g6.move(N)
    assert si.has(g6.state, "telescope"), (
        "the daily cap reset, so held-item state is not the blocker"
    )
    assert not g6.can_use_telescope_planetarium(), "all five planets are already unlocked"


def test_planetarium_progress_survives_a_daychain_attempt_wrap():
    """SAVE-scoped like stars/main_course_bonus (owner ruling): an unlocked
    planet is not lost when a DayChain attempt wraps back to day 1, unlike
    draft_counts/foundation_cell, which the wrap DOES clear. n_days=1 forces
    an immediate wrap on the very first advance(), the same technique
    test_shrine_state_is_save_scoped_across_a_daychain_attempt_wrap uses."""
    chain = DayChain(GameConfig(), n_days=1)
    g1 = Game(_with_telescope(chain.next_config()), seed=7)
    room = g1.registry.by_id["planetarium"]
    g1._place_room(room, 7, N | S)
    g1.move(N)
    revealed = g1.use_telescope_planetarium()

    chain.advance(g1.carryover())
    assert chain.current_day == 1, "n_days=1 must have wrapped back to day 1"
    assert chain.next_config().planetarium_planets == (revealed,)


def test_telescope_gated_out_of_the_spawn_pool_below_one_star():
    """"The Telescope is only present in the item pool if the player has at
    least 1 star at start the day, and cannot spawn otherwise." Gates on
    state.stars_at_day_start (the frozen start-of-day snapshot), the
    royal_scepter-style configure()/gated_out idiom used throughout this
    codebase for spawn-pool gates."""
    st = GameState()
    st.special.enabled = True
    st.stars_at_day_start = 0
    configure(st, GameConfig())
    assert "telescope" in st.special.gated_out


def test_telescope_allowed_in_the_spawn_pool_at_one_star():
    """The same gate, the other side: >= 1 start-of-day star un-gates it."""
    st = GameState()
    st.special.enabled = True
    st.stars_at_day_start = 1
    configure(st, GameConfig())
    assert "telescope" not in st.special.gated_out


def test_mid_day_star_does_not_un_gate_the_telescope(registry, cfg):
    """A star earned mid-day (Observatory/Starfish Aquarium/Morning Star) must
    not un-gate the Telescope until tomorrow's start-of-day snapshot reflects
    it: the gate reads state.stars_at_day_start (frozen at reset()), never the
    live-growing state.stars."""
    g = Game(cfg, seed=3, registry=registry)
    assert "telescope" in g.state.special.gated_out
    g.state.stars += 1  # simulate an Observatory draft's mid-day star grant
    # configure() returns early once `configured` is set, so its mid-day call
    # sites are no-ops; clearing the flag is what makes the gate actually run
    # again against a diverged live/frozen pair.
    g.state.special.configured = False
    si.configure(g.state, g.cfg, g.registry)
    assert "telescope" in g.state.special.gated_out


def test_stars_at_day_start_snapshot_is_unaffected_by_mid_day_growth(registry, cfg):
    """state.stars_at_day_start stays put while the live state.stars counter
    grows during the day -- the frozen-vs-live split the Telescope gate
    depends on."""
    g = Game(cfg, seed=4, registry=registry)
    before = g.state.stars_at_day_start
    g.state.stars += 1  # simulate an Observatory draft's mid-day star grant
    assert g.state.stars_at_day_start == before
    assert g.state.stars == before + 1


def test_carried_stars_seed_the_snapshot_and_reach_the_telescope_gate(registry, cfg):
    """A star carried into the day via cfg.stars reaches the gate: Game.reset
    seeds state.stars_at_day_start from it, and 1 star un-gates the Telescope.

    Drives the real reset path instead of writing the snapshot by hand, which
    is what makes it fail if the seeding step is dropped -- the gate's own
    tests set the snapshot themselves and stay green without it.
    """
    g = Game(_dc_replace(cfg, stars=1), seed=5, registry=registry)
    assert g.state.stars_at_day_start == 1, "reset must seed the snapshot from cfg.stars"
    assert "telescope" not in g.state.special.gated_out


def test_telescope_no_longer_guaranteed_on_first_planetarium_entry():
    """Owner ruling: guaranteed_in dropped -- no wiki text supports a
    guaranteed Telescope on first Planetarium entry. The Planetarium's own
    rooms.json record carries additional_max=0 (no luck-based extra item
    ever rolls there), so a Telescope in inventory after first entry could
    ONLY have come from the removed guaranteed_in path -- this assertion is
    deterministic, not an artifact of the seed rolling no luck-spawn."""
    g = Game(GameConfig(), seed=9)  # no starting Telescope
    room = g.registry.by_id["planetarium"]
    g._place_room(room, 7, N | S)
    g.move(N)
    assert "telescope" not in g.state.inventory
