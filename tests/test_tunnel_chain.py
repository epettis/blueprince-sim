"""Tunnel chain-draft effect tests.

The Tunnel (straight, N-S only) guarantees another Tunnel when the player
opens its north door.  Per the owner's ruling from playing the real game
(confirmed by blueprince.wiki.gg/wiki/Drafting/Advanced: "When drafting from
a Tunnel, a Tunnel is drawn into Slot 1" -- the wiki's 1-indexed Slot 1 is
this engine's slot 0), the chain deals a normal THREE-option hand with slot 0
guaranteed to be a Tunnel; it does not collapse the hand to a single forced
card.  Tests cover:
  (a) a normal 3-option hand, exactly one Tunnel, in slot 0, when drafting
      north from a placed Tunnel -- including when that very Tunnel is
      already on the grid (the deck_copies:1 / one-copy-on-grid exemption)
  (b) the chain repeats across the full rank 2-8 span (7 Tunnels), each hop
      guaranteeing slot 0 without the deck or the already-placed check
      killing it, then ends naturally at rank 9 with a normal 3-option hand
  (c) drafting from a Tunnel through the south door (non-north) deals
      normally, with no guaranteed Tunnel
  (d) determinism: the same seed deals the same hand (including which rooms
      land in slots 1/2, since those now consume RNG that the old one-card
      chain never touched)
  (e) non-Tunnel drafting across a full episode remains deterministic and
      seed-sensitive (unaffected by the Tunnel-chain change)
"""

from __future__ import annotations

import random

from blueprince_sim.config import GameConfig
from blueprince_sim.engine import locks
from blueprince_sim.engine.game import Game, Phase
from blueprince_sim.engine.grid import DIRS, N, S, neighbor, rank_of
from blueprince_sim.engine.model import Registry


# ---------------------------------------------------------------------------
# helpers

def _make_game(registry: Registry, cfg: GameConfig, seed: int = 1) -> Game:
    return Game(cfg, seed=seed, registry=registry)


def _place_tunnel_at(g: Game, registry: Registry, cell: int, orientation: int) -> None:
    """Place a Tunnel at *cell* with *orientation*, marking it entered.

    Its doorways are forced open: these tests target the chain-draft effect,
    not the door-lock rolls (high ranks would otherwise need keys).
    """
    tunnel = registry.by_id["tunnel"]
    g._place_room(tunnel, cell, orientation)
    for d in DIRS:
        if orientation & d and neighbor(cell, d) != -1:
            g.state.door_state[locks.segment_key(cell, d)] = locks.DOOR_OPEN
    g.state.door_version += 1
    g.state.pos = cell
    g.state.entered[cell] = True


# ---------------------------------------------------------------------------
# (a) opening north door of a placed Tunnel yields a 3-option hand with one
#     guaranteed Tunnel in slot 0


def test_tunnel_north_draft_deals_three_options_with_guaranteed_tunnel(registry, cfg):
    """Drafting north from a Tunnel deals a normal 3-option hand, not a single
    forced card -- this is the regression test for the reported bug, where the
    sim dealt exactly one option and removed all player choice."""
    g = _make_game(registry, cfg)
    # Place a Tunnel at rank 2 center (cell 7), north door connects to cell 12.
    _place_tunnel_at(g, registry, 7, N | S)
    assert "tunnel" in g.placed_ids, "precondition: the Tunnel is already on the grid"

    pending = g.open_door(7, N)
    assert len(pending.options) == 3, "a Tunnel chain must deal a normal 3-option hand"

    tunnel_idx = registry.by_id["tunnel"].idx
    tunnel_slots = [o.slot for o in pending.options if o.room_idx == tunnel_idx]
    assert tunnel_slots == [0], "exactly one guaranteed Tunnel, and it is in slot 0"

    opt = pending.options[0]
    assert opt.forced, "the guaranteed Tunnel is marked forced (bypassed the rarity lottery)"
    assert opt.gem_cost == 0, "slot 0 (and the chain Tunnel specifically) is always free"
    assert opt.orientation == (N | S), "Tunnel orientation must be N|S"

    # The other two slots are real, ordinarily-dealt options (not the Tunnel,
    # not forced, and not left empty by a chain that short-circuited them).
    for opt in pending.options[1:]:
        assert opt.room_idx != tunnel_idx, "only one Tunnel per hand"
        assert not opt.forced, "slots 1/2 came from the ordinary pipeline"


# ---------------------------------------------------------------------------
# (b) the chain repeats across every legal rank, unblocked by deck_copies:1
#     or the one-copy-on-grid rule, and ends naturally at rank 9


def test_tunnel_chain_walks_every_rank_then_ends_at_rank9(registry, cfg):
    """Choosing the guaranteed Tunnel repeatedly walks the chain from rank 2
    through rank 8 (7 Tunnels total); neither the deck's deck_copies:1 nor the
    one-copy-on-grid rule may kill the chain early, and rank 9 (rank_lte_8)
    ends it with a normal, Tunnel-free hand."""
    g = _make_game(registry, cfg)
    # Column 0 (west wing), not column 2: the Antechamber pre-occupies rank 9
    # center (cell 42), which would make the walk hit "invalid doorway" one
    # rank early for reasons unrelated to what this test checks.
    cell = 5  # rank 2, col 0
    _place_tunnel_at(g, registry, cell, N | S)
    tunnel_idx = registry.by_id["tunnel"].idx
    placements = 1

    while rank_of(cell) < 8:
        pending = g.open_door(cell, N)
        assert len(pending.options) == 3
        assert pending.options[0].room_idx == tunnel_idx and pending.options[0].forced, (
            f"chain must still guarantee a Tunnel at rank {rank_of(cell)}"
        )
        g.choose(0)
        cell = neighbor(cell, N)
        assert g.state.grid[cell] == tunnel_idx
        placements += 1
        # Force the new Tunnel's doors open and stand inside it, same as
        # _place_tunnel_at: these tests target the chain-draft effect, not
        # the door-lock rolls that would otherwise require keys at high ranks.
        for d in DIRS:
            if (N | S) & d and neighbor(cell, d) != -1:
                g.state.door_state[locks.segment_key(cell, d)] = locks.DOOR_OPEN
        g.state.door_version += 1
        g.state.pos = cell
        g.state.entered[cell] = True

    assert placements == 7, "ranks 2 through 8 inclusive is 7 Tunnels"

    # One more north draft, now targeting rank 9: rank_lte_8 makes the Tunnel
    # illegal there, so the chain ends and a normal hand (no Tunnel) is dealt.
    pending = g.open_door(cell, N)
    assert len(pending.options) == 3
    assert all(o.room_idx != tunnel_idx for o in pending.options), (
        "chain ends naturally at rank 9: no Tunnel anywhere in the fallback hand"
    )
    assert all(not o.forced for o in pending.options), (
        "the fallback hand at rank 9 is fully ordinary"
    )


# ---------------------------------------------------------------------------
# (c) drafting from a Tunnel through the SOUTH door deals normally


def test_tunnel_south_draft_is_normal(registry, cfg):
    """Opening the SOUTH door of a Tunnel does not trigger the chain: a normal
    3-option hand is dealt with no guaranteed (or otherwise) Tunnel."""
    g = _make_game(registry, cfg)
    # Place a Tunnel at rank 5 center (cell 22): south neighbor is cell 17 (rank 4).
    _place_tunnel_at(g, registry, 22, N | S)

    pending = g.open_door(22, S)
    assert len(pending.options) == 3
    tunnel_idx = registry.by_id["tunnel"].idx
    assert all(o.room_idx != tunnel_idx for o in pending.options), (
        "south-door draft must not produce a Tunnel (chain keys on north only, "
        "and the Tunnel's studio_addition pool isn't enabled by the default cfg)"
    )
    assert all(not o.forced for o in pending.options)


# ---------------------------------------------------------------------------
# (d) determinism: same seed, same hand


def test_tunnel_chain_hand_is_deterministic(registry, cfg):
    """Two games built from the same seed deal bit-identical Tunnel-chain hands,
    including slots 1/2 -- which now consume RNG the old one-card chain never
    touched, so this is the seeded-determinism invariant for the new code path."""

    def deal(seed: int) -> list[tuple[int, int, int, int, bool]]:
        g = _make_game(registry, cfg, seed=seed)
        _place_tunnel_at(g, registry, 7, N | S)
        pending = g.open_door(7, N)
        return [(o.room_idx, o.orientation, o.gem_cost, o.slot, o.forced)
                for o in pending.options]

    assert deal(7) == deal(7), "same seed must deal the same hand"
    assert deal(7) != deal(8), "different seeds must (in general) diverge"


# ---------------------------------------------------------------------------
# (e) non-Tunnel drafting across a full episode remains deterministic


def test_non_tunnel_drafting_determinism(cfg):
    """A full greedy-rank episode is bit-identical for a fixed seed and diverges
    across seeds, confirming the Tunnel-chain rewrite didn't disturb the RNG
    substream discipline that determinism depends on."""
    from blueprince_sim.cli.policies import greedy_rank

    def transcript(seed: int) -> list:
        g = Game(cfg, seed=seed)
        rnd = random.Random(0)
        log = []
        while g.phase is not Phase.TERMINAL and len(log) < 200:
            greedy_rank(g, rnd)
            log.append((g.phase.value, g.state.steps, g.state.gems,
                        g.rooms_placed, tuple(g.state.grid)))
        return log

    # Two runs with the same seed must be bit-identical.
    t1 = transcript(42)
    t2 = transcript(42)
    assert t1 == t2, "same-seed episodes must be identical"

    # Different seed must diverge.
    t3 = transcript(43)
    assert t3 != t1, "different-seed episodes must diverge"
