"""Headless pygame for effect tests (SDL dummy driver, tiny hidden display)."""

import os
import sys
from pathlib import Path

# Test *this* checkout. `pip install -e` records one absolute path, so inside a
# git worktree `import lilypad` otherwise resolves to the main checkout and the
# whole suite silently validates code you are not editing — passing or failing
# for reasons invisible in the diff.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pygame  # noqa: E402
import pytest  # noqa: E402

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


@pytest.fixture(scope="session", autouse=True)
def _pygame_headless():
    pygame.init()
    pygame.display.set_mode((320, 240))  # enables convert_alpha()
    yield
    pygame.quit()
