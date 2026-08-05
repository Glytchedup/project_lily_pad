"""Action → effect factories. One place to see what every key does.

Each factory takes (ctx, action) and returns a list of Effect instances.
Unknown special names and unknown action kinds both fall back to sparkle —
the registry, like the mapper, is total: every action produces something.
"""

from __future__ import annotations

from typing import Callable

from ..input.mapper import Action
from .base import BRIGHT_PALETTE, Effect, EffectContext
from .letters import GiantLetter
from .numbers import CountAlong
from .particles import (
    Balloons,
    Fireworks,
    Rings,
    SpiralBurst,
    Vacuum,
    burst,
    confetti_rain,
)

Factory = Callable[[EffectContext, Action], list[Effect]]


def _letter(ctx: EffectContext, action: Action) -> list[Effect]:
    letter = GiantLetter(ctx, action.letter)
    return [burst(ctx, letter.pos, count=45, speed=340), letter]


def _number(ctx: EffectContext, action: Action) -> list[Effect]:
    return [CountAlong(ctx, action.count)]


def _space(ctx: EffectContext, action: Action) -> list[Effect]:
    center = (ctx.width / 2, ctx.height / 2)
    return [confetti_rain(ctx), Rings(ctx, center, count=4, life=1.1)]


def _enter(ctx: EffectContext, action: Action) -> list[Effect]:
    return [Fireworks(ctx, rockets=3)]


def _chord(ctx: EffectContext, action: Action) -> list[Effect]:
    """Two-key chord: twin bursts + a white shockwave — a mini supernova."""
    rng = ctx.rng
    p1, p2 = ctx.random_pos(0.25), ctx.random_pos(0.25)
    c1, c2 = rng.choice(BRIGHT_PALETTE), rng.choice(BRIGHT_PALETTE)
    center = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    return [
        burst(ctx, p1, count=70, colors=[c1], speed=460),
        burst(ctx, p2, count=70, colors=[c2], speed=460),
        Rings(ctx, center, color=(255, 255, 255), count=2, life=0.8),
    ]


def _sparkle(ctx: EffectContext, action: Action) -> list[Effect]:
    return [burst(ctx, ctx.random_pos(), count=28, speed=260, size=5, life=0.9)]


_SPECIAL_FACTORIES: dict[str, Factory] = {
    "swirl": lambda ctx, a: [SpiralBurst(ctx, ctx.random_pos(), clockwise=True)],
    "spiral": lambda ctx, a: [SpiralBurst(ctx, ctx.random_pos(), clockwise=False)],
    "zigzag": lambda ctx, a: [
        burst(ctx, (ctx.width * 0.3, ctx.height * 0.4), count=30, speed=300),
        burst(ctx, (ctx.width * 0.5, ctx.height * 0.6), count=30, speed=300),
        burst(ctx, (ctx.width * 0.7, ctx.height * 0.4), count=30, speed=300),
    ],
    "colorwave": lambda ctx, a: [
        Rings(ctx, (0, ctx.height / 2), count=4, life=1.2),
        Rings(ctx, (ctx.width, ctx.height / 2), count=4, life=1.2),
    ],
    "shimmer": lambda ctx, a: [confetti_rain(ctx, count=60)],
    "bounce": lambda ctx, a: [burst(ctx, ctx.random_pos(), count=40,
                                    gravity=700, speed=380, life=1.6)],
    "pinwheel": lambda ctx, a: [SpiralBurst(ctx, (ctx.width / 2, ctx.height / 2),
                                            count=70, clockwise=True)],
    "vacuum": lambda ctx, a: [Vacuum(ctx, ctx.random_pos(0.3))],
    "balloon": lambda ctx, a: [Balloons(ctx, 8)],
    "drum": lambda ctx, a: [Rings(ctx, ctx.random_pos(0.25), count=3)],
}


def _special(ctx: EffectContext, action: Action) -> list[Effect]:
    factory = _SPECIAL_FACTORIES.get(action.letter, _sparkle)
    return factory(ctx, action)


_KIND_FACTORIES: dict[str, Factory] = {
    "letter": _letter,
    "number": _number,
    "space": _space,
    "enter": _enter,
    "chord": _chord,
    "sparkle": _sparkle,
    "special": _special,
    # "arrow", "mash_start", "mash_end" are handled by the engine itself
    # (critter shove / chaos overlay) and spawn no registry effects.
}


def effects_for(ctx: EffectContext, action: Action) -> list[Effect]:
    factory = _KIND_FACTORIES.get(action.kind)
    if factory is None:
        return []
    return factory(ctx, action)


def registered_kinds() -> set[str]:
    return set(_KIND_FACTORIES)
