"""Prewarm water reflections once per registered animal frame and facing."""

from collections import OrderedDict
from collections.abc import Hashable, Iterable

import pygame


class ReflectionCache:
    """Bounded LRU owned by the scene. Pass scene.reflections as enabled.

    Prewarm (key, surface) pairs before play. The draw pass only calls get().
    A key identifies the animal, pose, facing, size and resolved art mode.
    """

    def __init__(self, enabled: bool, *, capacity: int = 76) -> None:
        # 19 walkers/hoppers x two frames x two facings. A large animal must
        # not silently displace other prewarmed animals during startup.
        if capacity < 1:
            raise ValueError("reflection cache capacity must be positive")
        self.enabled = enabled
        self.capacity = capacity
        self.bytes_used = 0
        self._frames: OrderedDict[Hashable, pygame.Surface] = OrderedDict()

    def __len__(self) -> int:
        return len(self._frames)

    def get(self, key: Hashable) -> pygame.Surface | None:
        if not self.enabled:
            return None
        sprite = self._frames.get(key)
        if sprite is not None:
            self._frames.move_to_end(key)
        return sprite

    def prewarm(self, frames: Iterable[tuple[Hashable, pygame.Surface]]) -> None:
        if not self.enabled:
            return
        for key, frame in frames:
            if self.get(key) is not None:
                continue
            width = frame.get_width()
            height = max(1, round(frame.get_height() * 0.55))
            sprite = _reflect(frame, width, height)
            if len(self) == self.capacity:
                _, oldest = self._frames.popitem(last=False)
                self.bytes_used -= oldest.get_pitch() * oldest.get_height()
            self._frames[key] = sprite
            self.bytes_used += sprite.get_pitch() * height


def _reflect(frame: pygame.Surface, width: int, height: int) -> pygame.Surface:
    if frame.get_bitsize() < 24 or frame.get_colorkey() is not None:
        frame = frame.convert_alpha()
    flipped = pygame.transform.flip(frame, False, True)
    scaled = pygame.transform.smoothscale(flipped, (width, height))
    # Darken by 55%. Per-pixel transparency survives the three band blits.
    scaled.fill((115, 115, 115), special_flags=pygame.BLEND_RGB_MULT)
    sprite = pygame.Surface((width, height), pygame.SRCALPHA, 32)
    ripple = min(3, (width - 1) // 2, max(1, width // 120)) if height >= 3 else 0
    for band, offset in enumerate((0, ripple, -ripple)):
        top = band * height // 3
        bottom = (band + 1) * height // 3
        sprite.blit(scaled, (offset, top), (0, top, width, bottom - top))
    sprite.set_alpha(90)
    return sprite
