import pygame

from lilypad.effects.reflection import ReflectionCache


def animal():
    sprite = pygame.Surface((12, 20), pygame.SRCALPHA)
    sprite.fill((200, 0, 0, 255), (4, 0, 4, 10))
    sprite.fill((0, 200, 0, 128), (4, 10, 4, 10))
    return sprite


def test_reflected_geometry_value_alpha_and_ripple():
    frame = animal()
    before = pygame.image.tobytes(frame, "RGBA")
    cache = ReflectionCache(enabled=True)
    key = ("fox", "idle", "left", 20, "painted")
    cache.prewarm([(key, frame)])
    reflected = cache.get(key)
    assert reflected.get_size() == (12, 11)
    assert reflected.get_alpha() == 90
    top = reflected.get_at((4, 0))
    assert top.r == 0 and 88 <= top.g <= 91 and 126 <= top.a <= 128
    bottom = reflected.get_at((3, 10))
    assert 88 <= bottom.r <= 91 and bottom.g == 0 and bottom.a >= 254
    # Transparent outline moves right then left across the three horizontal bands.
    assert reflected.get_at((4, 4)).a == 0
    assert reflected.get_at((5, 4)).a > 0
    assert reflected.get_at((7, 10)).a == 0
    assert pygame.image.tobytes(frame, "RGBA") == before
    cache.prewarm([(key, frame)])
    assert cache.get(key) is reflected


def test_cache_misses_never_build_and_lru_eviction_updates_resident_bytes():
    frame = animal()
    nbytes = 12 * 11 * 4
    cache = ReflectionCache(True, capacity=2)
    cache.prewarm([("idle/right", frame), ("idle/left", frame)])
    right = cache.get("idle/right")
    assert right is not cache.get("idle/left")
    assert cache.get("idle/right") is right
    cache.prewarm([("step/right", frame)])
    assert cache.get("idle/left") is None
    assert cache.get("idle/right") is right
    assert len(cache) == 2 and cache.bytes_used == 2 * nbytes


def test_disabled_does_not_even_request_the_animal_frame():
    def frames():
        raise AssertionError("disabled prewarm requested a frame")
        yield

    cache = ReflectionCache(False)
    cache.prewarm(frames())
    assert cache.get("fox") is None
    assert len(cache) == cache.bytes_used == 0


def test_smallest_frame_survives_ripple():
    frame = pygame.Surface((1, 1), pygame.SRCALPHA)
    frame.fill((100, 120, 140, 150))
    cache = ReflectionCache(True)
    cache.prewarm([("small", frame)])
    sprite = cache.get("small")
    assert sprite.get_size() == (1, 1) and sprite.get_at((0, 0)).a == 150
