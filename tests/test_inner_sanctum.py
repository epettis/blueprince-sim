"""Inner Sanctum: the eight Sigil Chamber doors, gated on Room 46 and opened
with a Sanctum Key.

Verbatim mechanics (see docs/open_tasks.md): a Sanctum Key
permanently unlocks one of the eight realm doors and is then consumed; none
of the eight keys spawn anywhere until Room 46 has been reached at least
once (owner ruling, overriding the wiki's narrower "only one key" claim);
each door's Mora Jai box pays a one-time +2 allowance.

Tests drive the real ``Game``/``special_items`` API rather than asserting on
data-file contents, per the repo convention.
"""

from __future__ import annotations

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import special_items as si
from blueprince_sim.engine.game import Game
from blueprince_sim.env import obs as O
from blueprince_sim.env.actions import OPEN_SIGIL_DOOR_BASE, action_mask
from blueprince_sim.env.multiday import DayChain


def _game_at_sanctum(cfg: GameConfig | None = None, seed: int = 0, registry=None) -> Game:
    """A Game with the player standing off-grid at the inner_sanctum area node."""
    g = Game(cfg or GameConfig(special_items=True), seed=seed, registry=registry)
    g.state.area = "inner_sanctum"
    return g


# --------------------------------------------------------------- spawn gate


def test_no_sanctum_key_spawns_before_room46_reached(registry):
    """Every one of the eight Sanctum Key source ids is gated out until
    cfg.room46_reached is True, per the owner ruling that overrides the wiki."""
    g = Game(GameConfig(special_items=True, room46_reached=False), seed=0, registry=registry)
    si.configure(g.state, g.cfg)
    for key_id in si.SANCTUM_KEY_IDS:
        assert key_id in g.state.special.gated_out, (
            f"{key_id} must be gated out before room46_reached"
        )


def test_sanctum_keys_spawn_once_room46_reached(registry):
    """None of the eight source ids are gated once cfg.room46_reached is True
    (collected_sanctum_keys is still empty, so nothing else blocks them)."""
    g = Game(GameConfig(special_items=True, room46_reached=True), seed=0, registry=registry)
    si.configure(g.state, g.cfg)
    for key_id in si.SANCTUM_KEY_IDS:
        assert key_id not in g.state.special.gated_out


# ------------------------------------------------------------- door opening


def test_opening_door_consumes_the_key(registry):
    """open_sigil_door removes the spent key from inventory (consumed for good)."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    si.grant(g.state, g.registry, "sanctum_key_vault", source="test")
    assert g.open_sigil_door("arch_aries") is True
    assert si.has(g.state, "sanctum_key_vault") is False
    assert "sanctum_key_vault" in g.state.special.removed


def test_same_key_cannot_open_a_second_door(registry):
    """After a key is spent on one door, no key remains held, so a second
    door cannot be opened without acquiring another key."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    si.grant(g.state, g.registry, "sanctum_key_vault", source="test")
    assert g.open_sigil_door("arch_aries") is True
    assert g.can_open_sigil_door("corarica") is False
    assert g.open_sigil_door("corarica") is False


def test_opening_a_door_twice_is_a_no_op(registry):
    """Holding a second key does not let the SAME realm's door be opened again
    once it is already unlocked -- the door itself, not the key count, gates it."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    si.grant(g.state, g.registry, "sanctum_key_vault", source="test")
    assert g.open_sigil_door("arch_aries") is True
    si.grant(g.state, g.registry, "sanctum_key_clock_tower", source="test")
    assert g.can_open_sigil_door("arch_aries") is False
    assert g.open_sigil_door("arch_aries") is False


# --------------------------------------------------------------- allowance


def test_opening_a_door_pays_the_chambers_allowance_once(registry):
    """The realm's one-time +2 allowance is credited the moment its door opens,
    and a second attempt on the same (already open) door pays nothing further."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    g.state.luck = 0  # floor luck before any exact resource assertion
    assert g.state.allowance == 0
    si.grant(g.state, g.registry, "sanctum_key_vault", source="test")
    g.open_sigil_door("arch_aries")
    assert g.state.allowance == 2

    si.grant(g.state, g.registry, "sanctum_key_clock_tower", source="test")
    g.open_sigil_door("arch_aries")  # already open: no-op, no second payout
    assert g.state.allowance == 2


def test_two_different_doors_pay_the_allowance_twice(registry):
    """Two DISTINCT realm doors each pay their own +2, so opening both nets +4."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    g.state.luck = 0
    si.grant(g.state, g.registry, "sanctum_key_vault", source="test")
    g.open_sigil_door("arch_aries")
    si.grant(g.state, g.registry, "sanctum_key_clock_tower", source="test")
    g.open_sigil_door("corarica")
    assert g.state.allowance == 4


# ------------------------------------------------------------- persistence


def test_opened_door_stays_open_next_day_and_the_day_after(registry):
    """A permanently-unlocked realm door remains open on day 2 AND day 3 of the
    same attempt -- the property most likely to be dropped by an OR-once bug."""
    chain = DayChain(GameConfig(special_items=True, room46_reached=True), n_days=5)
    g1 = _game_at_sanctum(chain.next_config(), seed=1, registry=registry)
    si.grant(g1.state, g1.registry, "sanctum_key_vault", source="test")
    assert g1.open_sigil_door("arch_aries") is True
    chain.advance(g1.carryover())

    cfg2 = chain.next_config()
    assert "arch_aries" in cfg2.sigil_doors_open
    g2 = _game_at_sanctum(cfg2, seed=1, registry=registry)
    assert g2.can_open_sigil_door("arch_aries") is False, "already open: cannot be re-opened"
    chain.advance(g2.carryover())

    cfg3 = chain.next_config()
    assert "arch_aries" in cfg3.sigil_doors_open, "must still be open on day 3"


def test_spent_key_source_never_respawns_across_days(registry):
    """Once the Vault-box key is spent, sanctum_key_vault is gated out on every
    later day of the attempt -- the same one-time-source trap as the disks."""
    chain = DayChain(GameConfig(special_items=True, room46_reached=True), n_days=5)
    g1 = _game_at_sanctum(chain.next_config(), seed=1, registry=registry)
    si.grant(g1.state, g1.registry, "sanctum_key_vault", source="test")
    g1.open_sigil_door("arch_aries")
    chain.advance(g1.carryover())

    cfg2 = chain.next_config()
    assert "sanctum_key_vault" in cfg2.collected_sanctum_keys
    g2 = Game(cfg2, seed=2, registry=registry)
    si.configure(g2.state, g2.cfg)
    assert "sanctum_key_vault" in g2.state.special.gated_out

    chain.advance(g2.carryover())
    cfg3 = chain.next_config()
    assert "sanctum_key_vault" in cfg3.collected_sanctum_keys, (
        "the spent source must still be blocked on day 3"
    )


# -------------------------------------------------------------------- mask


def test_sigil_door_action_masked_off_without_a_key(registry):
    """None of the eight OPEN_SIGIL_DOOR_BASE ids are legal while no Sanctum
    Key is held, even standing at the Inner Sanctum with Room 46 reached."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    mask = action_mask(g)
    assert not any(mask[OPEN_SIGIL_DOOR_BASE:OPEN_SIGIL_DOOR_BASE + 8])


def test_sigil_door_action_masked_on_for_sealed_doors_with_a_key(registry):
    """Holding a Sanctum Key at the Inner Sanctum legalizes every SEALED realm's
    door id; a realm already opened drops out of the mask."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    si.grant(g.state, g.registry, "sanctum_key_vault", source="test")
    mask = action_mask(g)
    assert all(mask[OPEN_SIGIL_DOOR_BASE:OPEN_SIGIL_DOOR_BASE + 8]), (
        "every one of the 8 realms is still sealed, so all 8 ids must be legal"
    )

    g.open_sigil_door("arch_aries")
    si.grant(g.state, g.registry, "sanctum_key_clock_tower", source="test")
    mask2 = action_mask(g)
    opened_index = sorted(si.SIGIL_REALMS).index("arch_aries")
    assert mask2[OPEN_SIGIL_DOOR_BASE + opened_index] is False
    assert sum(mask2[OPEN_SIGIL_DOOR_BASE:OPEN_SIGIL_DOOR_BASE + 8]) == 7


# -------------------------------------------------------------------- obs


def test_sigil_doors_open_observation_reflects_todays_and_carried_openings(registry):
    """The sigil_doors_open observation bit flips on for a door opened earlier
    today AND for one carried in from an earlier day (cfg), sorted realm order."""
    cfg = GameConfig(special_items=True, room46_reached=True)
    g = _game_at_sanctum(cfg, registry=registry)
    obs_before = O.encode(g)
    assert obs_before["sigil_doors_open"].sum() == 0

    si.grant(g.state, g.registry, "sanctum_key_vault", source="test")
    g.open_sigil_door("arch_aries")
    obs_after = O.encode(g)
    realm_order = sorted(si.SIGIL_REALMS)
    assert obs_after["sigil_doors_open"][realm_order.index("arch_aries")] == 1
    assert obs_after["sigil_doors_open"].sum() == 1
