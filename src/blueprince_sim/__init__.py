"""Blue Prince room-drafting simulator."""

from .config import GameConfig
from .engine import Game, Phase, RedrawKind, Registry

__version__ = "0.1.0"
__all__ = ["GameConfig", "Game", "Phase", "RedrawKind", "Registry", "make_env"]


def make_env(cfg: GameConfig | None = None, **kwargs):
    """Create a Gymnasium BluePrinceEnv (imports gymnasium lazily)."""
    from .env.blueprince_env import BluePrinceEnv

    return BluePrinceEnv(cfg=cfg, **kwargs)
