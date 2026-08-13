import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
# tests/ itself, so shared test-only helpers (e.g. luck_utils.py) are a plain
# `import luck_utils` from any test file, including tests/rooms/*.py -- pytest's
# rootdir insertion only adds each test file's OWN directory (neither tests/ nor
# tests/rooms/ has an __init__.py), so tests/rooms/*.py cannot see tests/*.py otherwise.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from blueprince_sim.config import GameConfig
from blueprince_sim.engine.model import Registry


@pytest.fixture(scope="session")
def registry() -> Registry:
    """Room/weights/locks Registry parsed once from data/*.json (immutable, shareable)."""
    return Registry.load()


@pytest.fixture()
def cfg() -> GameConfig:
    """A default GameConfig: no unlocks, upgrades, or item-gated conditions."""
    return GameConfig()
