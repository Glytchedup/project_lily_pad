"""Lighting package: backend factory with auto-fallback."""

from __future__ import annotations

import logging

from .base import LightingBackend, LightingEngine

log = logging.getLogger(__name__)

__all__ = ["LightingBackend", "LightingEngine", "make_backend"]


def make_backend(preference: str = "auto") -> LightingBackend:
    """Backend selection chain: explicit choice, or auto-fallback
    razer_hid → openrazer → mock. Never raises — the show must go on."""
    from .mock import MockLightingBackend

    def _try(name: str) -> LightingBackend | None:
        try:
            if name == "razer_hid":
                from .razer_hid import RazerHidBackend
                return RazerHidBackend()
            if name == "openrazer":
                from .openrazer_backend import OpenRazerBackend
                return OpenRazerBackend()
            if name == "mock":
                return MockLightingBackend()
        except Exception as exc:              # noqa: BLE001 — fall through the chain
            log.warning("lighting backend %s unavailable: %s", name, exc)
        return None

    order = ["razer_hid", "openrazer", "mock"] if preference == "auto" else [preference]
    for name in order:
        backend = _try(name)
        if backend is not None:
            log.info("lighting backend: %s", backend.name)
            return backend
    log.warning("falling back to mock lighting backend")
    return MockLightingBackend()
