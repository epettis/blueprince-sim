"""Per-room effect handler modules, keyed by room id via ``room_hook``.

One module per room, mirroring ``tests/rooms/``. Each module registers its
handlers with ``room_hook`` on import, the same way ``effects/tier1.py``
registers tag handlers with ``effect`` -- so landing a room module here only
requires importing it from this file.
"""

from __future__ import annotations

from . import conservatory  # noqa: F401  (registers room_hook handlers on import)
from . import furnace  # noqa: F401
from . import greenhouse  # noqa: F401
from . import schoolhouse  # noqa: F401
from . import solarium  # noqa: F401
from . import study  # noqa: F401
