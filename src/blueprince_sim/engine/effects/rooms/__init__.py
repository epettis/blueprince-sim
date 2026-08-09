"""Per-room effect handler modules, keyed by room id via ``room_hook``.

Empty for now: this package is the phase-3 destination for the 13 singleton
effect tags (``docs/open_tasks.md`` task 17), one module per room mirroring
``tests/rooms/``. Each module registers its handlers with ``room_hook`` on
import, the same way ``effects/tier1.py`` registers tag handlers with
``effect`` -- so landing a room module here only requires importing it from
this file.
"""

from __future__ import annotations
