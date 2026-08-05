"""Headless pygame for effect tests (SDL dummy driver, tiny hidden display)."""

import os

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


@pytest.fixture(scope="session", autouse=True)
def _pygame_headless():
    pygame.init()
    pygame.display.set_mode((320, 240))  # enables convert_alpha()
    yield
    pygame.quit()
