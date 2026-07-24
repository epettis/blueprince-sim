import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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
