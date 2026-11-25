"""Choose pond encounters from a frame snapshot. The caller applies the intents."""

from __future__ import annotations

import random
from collections.abc import Iterable
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from .animals import AnimalCrossing
    from .base import EffectContext
    from .critter import Frog


class CrossingGeometry(NamedTuple):
    height: int
    back_at: tuple[float, float] | None
    speed: float


class AnimalView(NamedTuple):
    """Screen pixels, signed direction (+1 right), read-only crossing geometry."""

    id: int
    name: str
    x: float
    width: int
    gait: str
    direction: int
    view: CrossingGeometry

    @classmethod
    def from_crossing(cls, animal: AnimalCrossing) -> AnimalView:
        geometry = CrossingGeometry(animal.height, animal.back_at, animal.speed)
        return cls(id(animal), animal.name, animal.x, animal.width, animal.gait,
                   -1 if animal.going_left else 1, geometry)


class Intent(NamedTuple):
    kind: str
    animal_id: int
    other_id: int | None = None


def _pip_intent(animal: AnimalView, frog: Frog) -> Intent | None:
    ahead = (frog.x - animal.x) * animal.direction
    if ahead < -frog.r:
        return None
    reach = animal.width / 2 + frog.r
    if animal.gait == "fly":
        kind = "pip_wave"
    elif animal.gait == "walk":
        # These cast gags also work with fallback art. A measured point on a
        # giraffe's neck or an alligator's snout doesn't make either a mount.
        if animal.name in ("alligator", "iguana"):
            kind = "pip_jump"
        elif animal.name == "giraffe":
            kind = "pip_duck"
        elif animal.name in ("elephant", "brachiosaurus"):
            kind = "pip_ride"
        elif animal.view.height >= 1.6 * frog.sprite_height:
            kind = "pip_ride" if animal.view.back_at is not None else "pip_duck"
        else:
            kind = "pip_jump"
        if kind == "pip_jump":
            # Put the apex over the centre of the moving walker.
            reach = animal.view.speed * frog.JUMP_APEX_SECONDS
        elif kind == "pip_ride":
            reach = min(reach, frog.r * 2.5)
    else:
        return None
    return Intent(kind, animal.id) if ahead <= reach else None


class Director:
    """One encounter per six seconds, including walker-to-walker greetings."""

    COOLDOWN = 6.0

    def __init__(self, ctx: EffectContext, *, seed: int = 0) -> None:
        self._ctx = ctx
        self._rng = random.Random(seed)
        self._cooldown = 0.0

    def tick(self, dt: float, animals: Iterable[AnimalView], frog: Frog) -> list[Intent]:
        self._cooldown = max(0.0, self._cooldown - dt)
        if self._ctx.scale < 0.5 or self._cooldown > 1e-9:
            return []
        width = self._ctx.width
        views = (a if isinstance(a, AnimalView) else AnimalView(*a) for a in animals)
        visible = [a for a in views if -a.width / 2 <= a.x <= width + a.width / 2]
        walkers = [a for a in visible if a.gait == "walk" and 0 <= a.x <= width]
        candidates = [Intent("greet", a.id, b.id)
                      for a in walkers if a.direction == 1
                      for b in walkers if b.direction == -1 and 0 <= b.x - a.x <= 0.25 * width]
        if not candidates and not frog.riding and not frog.dancing and frog.vy == 0:
            candidates = [intent for a in visible if (intent := _pip_intent(a, frog)) is not None]
        if not candidates:
            return []
        self._cooldown = self.COOLDOWN
        return [self._rng.choice(candidates)]
