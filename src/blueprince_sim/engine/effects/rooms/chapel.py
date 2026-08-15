"""Chapel: registers the Keeper of Tithes coin-banking capability.

``engine/effects/tier1.py``'s shared ``grant`` handler reads
``Capability.TITHE`` (via ``provides_capability``, matched on a room's own id
or its ``variant_of`` so an upgrade variant still qualifies) to decide
whether a negative coins grant should also bank the coins actually taken into
``game.state.special.chapel_tithes`` -- see that handler's own docstring for
the banking rule itself. Registering the capability here, rather than naming
"chapel" inline in the shared handler, is what lets ``grant`` stay generic
across every other room it already serves.
"""

from __future__ import annotations

from .. import Capability, provides

provides("chapel", Capability.TITHE)
