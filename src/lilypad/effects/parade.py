"""The alphabet conga line and the three-animal party reprise, drawn on the sprite pass."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pygame

from . import animals, critter, painted
from .animal_specs import SPECS
from .animals import AnimalCrossing, GAITS, PEEKABOO_CAST
from .base import EffectContext
from .layout import POND, Layout

_MOUNT = "brachiosaurus"
_FARM = tuple(sorted(PEEKABOO_CAST))
# The mount leads, so he keeps his place even at half density.
_LINE = (_MOUNT, *(name for name in SPECS if name != _MOUNT and name not in PEEKABOO_CAST))


@dataclass
class _Player:
    name: str
    gait: str
    size: tuple[int, int]
    source_height: int
    offset: float = 0.0       # centre measured from the first animal's nose
    foot: int = 0             # baseline in the sprite canvas


class GrandParade:
    """Use create() for a nullable celebration factory after the normal cast prewarm.

    update(dt) is called once per visual frame, independently of draw(). A positive
    multiple of eight as party_bar selects a short trio with no rider or farm chorus.
    """

    FANFARE = 3.0
    DURATION = 22.0

    @classmethod
    def create(cls, ctx: EffectContext, **kwargs) -> GrandParade | None:
        parade = cls(ctx, **kwargs)
        return None if parade.done else parade

    def __init__(self, ctx: EffectContext, *, layout: Layout = POND,
                 frog: critter.Frog | None = None, on_finish: Callable[[], None] | None = None,
                 party_bar: int | None = None) -> None:
        self._ctx = ctx
        self._layout = layout
        self._trio = party_bar is not None
        self.fanfare = 0.0 if self._trio else self.FANFARE
        self.duration = 4.0 if self._trio else self.DURATION
        self.age = 0.0
        self.done = True
        self.on_finish = on_finish
        self._line: list[_Player] = []
        self._farm: list[_Player] = []
        self._frames: dict[tuple[str, str], pygame.Surface] = {}
        self._pending: deque[tuple[_Player | None, str]] = deque()
        self._head: tuple[int, int] | None = None
        self._pip_radius = getattr(frog, "r", max(30, int(ctx.height * 0.06)))

        line = _LINE
        if party_bar is not None:
            if party_bar <= 0 or party_bar % 8:
                return
            start = (party_bar // 8 - 1) * 3
            line = tuple(_LINE[(start + i) % len(_LINE)] for i in range(3))
        farm = () if self._trio else _FARM
        if any(animals.resolved_mode(name) != "painted" for name in (*line, *farm)):
            return

        self.done = False
        # Match the ordinary painted swimmer height so its resident frames can be shared.
        height = max(1, int(ctx.height * 0.22))
        for name in (*line, *farm):
            gait = "peekaboo" if name in PEEKABOO_CAST else GAITS.get(name, "walk")
            width = max(1, round(height * painted.aspect(name)))
            # Only request the display-size source warmed by animals.prewarm().
            # Requesting a parade height there would retain both facings globally.
            source_height = animals._sprite_height(name, ctx.size, gait)
            player = _Player(name, gait, (width, height), source_height, foot=height)
            (self._farm if gait == "peekaboo" else self._line).append(player)
            self._pending.append((player, "idle"))

        # At most four slots intersect the viewport, leaving room for a rider and a cheer.
        cursor = 0.0
        for player in self._line:
            slot = max(ctx.width / 3, player.size[0] + 0.025 * ctx.width)
            player.offset = cursor + slot / 2
            cursor += slot
        first = self._line[0]
        inset = first.offset - first.size[0] / 2
        for player in self._line:
            player.offset -= inset
        last = self._line[-1]
        self._speed = (ctx.width + last.offset + last.size[0] / 2) / (self.duration - self.fanfare)

        if not self._trio and not callable(getattr(frog, "ride", None)):
            self._pending.appendleft((None, "cheer"))
        for i, player in enumerate(self._line):
            self._pending.append((player, "step"))
            if player.gait == "hop":
                self._pending.append((player, "squash"))
            # All dancers start together. Most are still offstage for both blinks.
            entry = (player.offset - player.size[0] / 2) / self._speed
            if self._gait_age(entry, i) < AnimalCrossing._BLINKS[-1][1]:
                self._pending.append((player, "blink"))

    @staticmethod
    def _gait_age(elapsed: float, index: int) -> float:
        return elapsed + index * 0.12

    def _warm_one(self, player: _Player | None, pose: str) -> None:
        if player is None:
            source = critter.frog_sprite(self._pip_radius, pose)
            height = max(1, round(self._ctx.height * 0.095))
            size = (max(1, round(height * source.get_width() / source.get_height())), height)
            rider = pygame.transform.smoothscale(source, size)
            feet = rider.get_bounding_rect().bottom or size[1]
            self._frames["pip", pose] = rider.subsurface((0, 0, size[0], feet))
            return
        left = player.gait != "peekaboo"
        source = animals.animal_sprite_facing(player.name, player.source_height, pose, left)
        sprite = source
        if source.get_size() != player.size:
            sprite = pygame.transform.smoothscale(source, player.size)
        self._frames[player.name, pose] = sprite
        if pose == "idle":
            player.foot = sprite.get_bounding_rect().bottom
            if player.name == _MOUNT and not self._trio:
                # The eye is registered on the right-facing master. Seat Pip on
                # the first opaque pixel above that eye on the mirrored canvas.
                x = round((1 - painted.eye_at(_MOUNT)[0]) * (sprite.get_width() - 1))
                column = sprite.subsurface((x, 0, 1, sprite.get_height())).get_bounding_rect()
                self._head = (x, column.top)

    def update(self, dt: float) -> bool:
        if self.done:
            return False
        self.age = min(self.duration, self.age + max(0.0, dt))
        if self.age + 1e-9 >= self.duration:
            self.age = self.duration
            self.done = True
            self._frames.clear()
            self._pending.clear()
            self._head = None
            finish, self.on_finish = self.on_finish, None
            if finish is not None:
                finish()
        else:
            # At normal frame rates the queue empties during the fanfare. A
            # stalled renderer can catch up without a bulk build or a longer show.
            for _ in range(min(2, len(self._pending))):
                self._warm_one(*self._pending.popleft())
        return not self.done

    def progress(self) -> float:
        """Elapsed fraction of the complete celebration, including the fanfare."""
        return 1.0 if self.done else self.age / self.duration

    def _visible(self) -> Iterator[tuple[_Player, int, float]]:
        elapsed = self.age - self.fanfare
        if self.done or elapsed < 0:
            return
        origin = self._ctx.width - self._speed * elapsed
        for i, player in enumerate(self._line):
            if self._ctx.scale < 0.5 and i % 2:
                continue
            x = round(origin + player.offset)
            left = x - player.size[0] // 2
            if left >= self._ctx.width:
                break
            if left + player.size[0] > 0:
                yield player, x, self._gait_age(elapsed, i)

    def lead_x_frac(self) -> float:
        """Centre of the leftmost visible dancer. Hand the chase to the next as each exits."""
        for _, x, _ in self._visible():
            return max(0.0, min(1.0, x / self._ctx.width))
        return float(not self.done and (self.age - self.fanfare) * self._speed <= self._line[0].offset)

    def _top(self, player: _Player, age: float) -> int:
        h = player.size[1]
        gait = player.gait
        if gait in ("fly", "swim"):
            band = self._layout.fly_band if gait == "fly" else self._layout.swim_band
            hz, amplitude = ((0.55, AnimalCrossing.FLY_WAVE) if gait == "fly"
                             else (0.42, AnimalCrossing.SWIM_WAVE))
            wave = h * amplitude * math.sin(age * math.tau * hz)
            return round(self._ctx.height * sum(band) / 2 - h / 2 + wave)
        if gait == "hop":
            lift = 0.42 * math.sin(math.pi * ((age / AnimalCrossing.HOP_PERIOD) % 1))
        else:
            lift = 0.035 * abs(math.sin(age * math.pi * animals.WALK_STEP_HZ))
        return round(self._ctx.height * self._layout.ground - player.foot - h * lift)

    def pip_anchor(self) -> tuple[int, int] | None:
        """Contact point for Frog.ride, in screen pixels, while the mount's head is onstage."""
        if self._head is not None:
            for player, x, age in self._visible():
                if player.name == _MOUNT:
                    px = x - player.size[0] // 2 + self._head[0]
                    if 0 <= px < self._ctx.width:
                        return px, self._top(player, age) + self._head[1]
                break  # the mount is the first dancer
        return None

    def _cheer(self, surface: pygame.Surface) -> None:
        if not self._farm:
            return
        # Each animal gets its own quarter of the procession and one fixed x.
        slot = (self.age - self.fanfare) * len(self._farm) / (self.duration - self.fanfare)
        index = int(slot)
        player = self._farm[index]
        beat = slot - index
        reveal = max(0.0, min(1.0, (beat - 0.15) * 6, (0.85 - beat) * 6))
        sprite = self._frames.get((player.name, "idle"))
        if reveal and sprite is not None:
            rise = reveal * (0.78 + 0.12 * abs(math.sin(beat * 3 * math.tau)))
            rect = sprite.get_rect(midtop=(round(self._ctx.width * (index + 0.5) / len(self._farm)),
                                           self._ctx.height - round(player.size[1] * rise)))
            if rect.colliderect(surface.get_clip()):
                surface.blit(sprite, rect)

    def draw(self, surface: pygame.Surface) -> None:
        if self.done or self.age < self.fanfare:
            return
        clip = surface.get_clip()
        for player, x, age in self._visible():
            pose = AnimalCrossing.pose_for(player.gait, age, SPECS[player.name].build == "floater")
            sprite = self._frames.get((player.name, pose))
            if sprite is None:
                sprite = self._frames.get((player.name, "idle"))
            if sprite is not None:
                rect = sprite.get_rect(midtop=(x, self._top(player, age)))
                if rect.colliderect(clip):
                    surface.blit(sprite, rect)
        pip = self._frames.get(("pip", "cheer"))
        if pip is not None:
            anchor = self.pip_anchor()
            if anchor is not None:
                rect = pip.get_rect(midbottom=anchor)
                if rect.colliderect(clip):
                    surface.blit(pip, rect)
        self._cheer(surface)
