"""Shared effect types and the toddler-bright palette."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

import pygame

# Saturated, high-contrast colors that pop on a black canvas.
BRIGHT_PALETTE: list[tuple[int, int, int]] = [
    (255, 59, 48),    # red
    (255, 149, 0),    # orange
    (255, 214, 10),   # yellow
    (52, 199, 89),    # green
    (0, 199, 190),    # teal
    (10, 132, 255),   # blue
    (94, 92, 230),    # indigo
    (255, 55, 95),    # pink
    (191, 90, 242),   # purple
    (255, 255, 255),  # white
]


def random_bright(rng: random.Random | None = None) -> tuple[int, int, int]:
    return (rng or random).choice(BRIGHT_PALETTE)


class Effect(Protocol):
    def update(self, dt: float) -> bool:
        """Advance by dt seconds; return False when finished."""

    def draw(self, surface: pygame.Surface) -> None: ...


@dataclass
class EffectContext:
    """Everything an effect factory needs to build effects."""
    size: tuple[int, int]          # screen size
    rng: random.Random
    scale: float = 1.0             # degradation factor 0.25..1.0 (particle counts)

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]

    def random_pos(self, margin: float = 0.15) -> tuple[float, float]:
        mx, my = self.width * margin, self.height * margin
        return (self.rng.uniform(mx, self.width - mx),
                self.rng.uniform(my, self.height - my))
