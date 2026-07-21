"""Seeded RNG with named substreams.

Each named stream is an independent ``random.Random`` seeded from the episode
seed and the stream label. Features that consume randomness from their own
stream do not perturb draws made by unrelated features, which keeps golden
transcripts stable when new features are added.
"""

from __future__ import annotations

import random
import zlib


class Rng:
    __slots__ = ("seed", "_streams")

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def stream(self, label: str) -> random.Random:
        rng = self._streams.get(label)
        if rng is None:
            rng = random.Random((self.seed << 32) ^ zlib.crc32(label.encode()))
            self._streams[label] = rng
        return rng

    def roll_weighted(self, label: str, weights: tuple[float, ...]) -> int:
        """Return an index drawn proportionally to ``weights`` (need not sum to 1)."""
        total = 0.0
        for w in weights:
            total += w
        x = self.stream(label).random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if x < acc:
                return i
        return len(weights) - 1

    def chance(self, label: str, p: float) -> bool:
        return self.stream(label).random() < p

    def shuffle(self, label: str, items: list) -> None:
        self.stream(label).shuffle(items)

    def randint(self, label: str, lo: int, hi: int) -> int:
        return self.stream(label).randint(lo, hi)

    def choice(self, label: str, items: list):
        return items[self.stream(label).randrange(len(items))]
