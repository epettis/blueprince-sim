"""Per-room effect handler modules, keyed by room id via ``room_hook``.

One module per room, mirroring ``tests/rooms/``. Each module registers its
handlers with ``room_hook`` on import, the same way ``effects/tier1.py``
registers tag handlers with ``effect`` -- so landing a room module here only
requires importing it from this file.
"""

from __future__ import annotations

from . import boiler_room  # noqa: F401  (registers room_hook handlers on import)
from . import bunk_room  # noqa: F401
from . import classroom  # noqa: F401
from . import closet  # noqa: F401
from . import cloister  # noqa: F401
from . import conservatory  # noqa: F401
from . import dovecote  # noqa: F401  (no handler; imported for the predicate helper)
from . import furnace  # noqa: F401
from . import great_hall  # noqa: F401  (no handler; imported for the lever helper)
from . import greenhouse  # noqa: F401
from . import hovel  # noqa: F401
from . import mail_room  # noqa: F401
from . import quest_bedroom  # noqa: F401
from . import room_8  # noqa: F401
from . import rotunda  # noqa: F401
from . import schoolhouse  # noqa: F401
from . import secret_garden  # noqa: F401
from . import security  # noqa: F401
from . import shelter  # noqa: F401
from . import solarium  # noqa: F401
from . import study  # noqa: F401
from . import throne_room  # noqa: F401  (no handler; imported for the lever helper)
from . import tomb  # noqa: F401
from . import treasure_trove  # noqa: F401
from . import weight_room  # noqa: F401
