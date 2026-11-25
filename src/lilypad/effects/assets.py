"""Locate packaged art and load it when building the sprite cache."""

import argparse
import io
import os
from functools import cache
from pathlib import Path

import pygame


def asset_root(kiosk: bool = False) -> Path:
    """Return the package asset directory, allowing a trial directory in dev."""
    if not kiosk:
        override = os.environ.get("LILYPAD_ART_DIR")
        if override:
            return Path(override)
    return Path(__file__).resolve().parents[1] / "assets"


def load_image(path: str | Path) -> pygame.Surface:
    """Decode an image, converting for alpha blits once a display is available."""
    image = pygame.image.load(path)
    if pygame.display.get_surface() is not None:
        return image.convert_alpha()
    return image


# Lossless 1x1 RGBA WebP. Probe SDL_image itself without an encoder or display.
_WEBP_PIXEL = bytes.fromhex(
    "524946461e000000574542505650384c11000000"
    "2f0000001007d0ac9634af808188e87f0000"
)


@cache
def webp_supported() -> bool:
    """Whether this pygame build can decode the bundled WebP test pixel."""
    try:
        image = pygame.image.load(io.BytesIO(_WEBP_PIXEL), "probe.webp")
    except (pygame.error, NotImplementedError, OSError):
        return False
    return image.get_size() == (1, 1)


def budget_bytes(root: str | Path) -> int:
    """Sum the file sizes below an asset directory, including nested assets."""
    return sum(path.stat().st_size for path in Path(root).rglob("*") if path.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="report WebP support and asset root")
    if parser.parse_args().probe:
        print(f"WebP supported: {webp_supported()}")
        print(f"Asset root: {asset_root()}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
