"""Action → effect factories. One place to see what every key does.

Each factory takes (ctx, action) and returns a list of Effect instances.
Unknown special NAMES fall back to sparkle, so every keypress produces
something. Action KINDS the engine handles itself (arrow, mash_*, hold_*)
have no factory here and effects_for returns [] for them — the engine
never routes them this far.
"""

from __future__ import annotations

from typing import Callable

from ..input.mapper import Action
from .animals import ANIMAL_LETTERS, PeekabooAnimal
from .base import BRIGHT_PALETTE, Effect, EffectContext
from .bubbles import BubbleField
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
    ring_burst,
    shaped_burst,
)

Factory = Callable[[EffectContext, Action], list[Effect]]


def _letter(ctx: EffectContext, action: Action) -> list[Effect]:
    letter = GiantLetter(ctx, action.letter)
    out: list[Effect] = [burst(ctx, letter.pos, count=45, speed=340), letter]
    # Animal letters bring their animal along ("C is for cow — moo!"),
    # and B blows bubbles. The letter still shows; the friend joins it.
    # (.upper() matches the audio engine's normalization — evdev names are
    # uppercase, but don't rely on every backend agreeing.)
    upper = action.letter.upper()
    if upper in ANIMAL_LETTERS:
        out.append(PeekabooAnimal(ctx, ANIMAL_LETTERS[upper]))
    elif upper == "B":
        out.append(BubbleField(ctx, count=8))
    return out


def celebration(ctx: EffectContext, big: bool = False) -> list[Effect]:
    """Milestone mega-party (VISUAL_REVIEW.md #10): everything at once.
    The engine adds the frog joy-hops and the rainbow border pulse itself."""
    out: list[Effect] = [
        Fireworks(ctx, rockets=6 if big else 5),
        confetti_rain(ctx, count=120),
        Balloons(ctx, 10),
    ]
    if big:  # alphabet complete — a heart in the sky
        out.append(shaped_burst(ctx, (ctx.width / 2, ctx.height * 0.35), "heart",
                                count=110, spread=300))
    return out


def _number(ctx: EffectContext, action: Action) -> list[Effect]:
    return [CountAlong(ctx, action.count)]


def _space(ctx: EffectContext, action: Action) -> list[Effect]:
    # Particle rings rather than drawn Rings: hard-edged circles redrawn
    # every frame stack into a full-screen bullseye under the trail veil.
    center = (ctx.width / 2, ctx.height / 2)
    return [confetti_rain(ctx),
            ring_burst(ctx, center, speed=520),
            ring_burst(ctx, center, speed=340)]


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
