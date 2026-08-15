"""Laboratory: the Experimental Setup terminal is gated on the room's own id.

tests/test_experiments.py already drives the Laboratory (via its own
_game_at_laboratory helper) through nearly the whole setup/pause/resume/
trigger/effect system -- that file is the real per-room coverage and is left
alone. The one thing it never actually exercises is the claim its own
test_setup_masked_out_when_not_in_laboratory docstring makes ("even standing
in another disk-reader room like Security"): that test only checks the
Entrance Hall, never a real Security room. Game.at_laboratory_terminal's
docstring says the gate checks the room id directly rather than the shared
disk_reader flag (Security, Laboratory, Office and Shelter all carry
disk_reader=True) -- this is the missing case proving that id check is what
actually keeps the terminal Laboratory-only.
"""

from __future__ import annotations

from blueprince_sim.engine.game import Game, Phase


def test_a_fellow_disk_reader_room_does_not_unlock_the_setup_terminal(registry, cfg):
    """Standing in Security -- disk_reader=True, same as the Laboratory --
    does not make can_start_setup() legal: the Experimental Setup menu is
    specific to the Laboratory's own id, not the shared disk-reader flag."""
    g = Game(cfg, seed=0, registry=registry)
    sec = g.registry.by_id["security"]
    g._place_room(sec, 7, sec.door_mask)
    g.state.pos = 7
    g.state.entered[7] = True
    g.phase = Phase.NAVIGATE

    assert g.disk_reader_here(), "Security must still register as a disk-reader room"
    assert not g.can_start_setup(), "the Experimental Setup terminal is Laboratory-only"
