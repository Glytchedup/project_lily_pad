import pytest

from lilypad.effects.animals import AnimalCrossing
from lilypad.effects.layout import layout_for


def test_classic_preserves_original_crossings_and_dino_ring():
    layout = layout_for("drawn")
    assert layout.name == "classic"
    assert layout.ground == 0.94            # animals.py:354
    assert layout.fly_band == (0.16, 0.46)  # animals.py:359
    assert layout.swim_band == (0.48, 0.74)  # animals.py:360
    assert layout.swim_height == AnimalCrossing._SIZE["swim"]
    assert layout.shockwave == 0.92         # registry.py:122
    assert layout.sky is None
    assert layout.far_shore is None
    assert layout.water is None


def test_painted_pond_bands():
    layout = layout_for("painted")
    assert layout.name == "pond"
    assert layout.sky == (0.00, 0.52)
    assert layout.fly_band == (0.10, 0.40)
    assert layout.far_shore == (0.52, 0.62)
    assert layout.shockwave == layout.ground == 0.66
    assert layout.water == (0.66, 0.88)
    assert layout.swim_band == (0.74, 0.84)
    assert layout.swim_height == 0.22


def test_pip_foreground_and_peekaboo_edge_are_shared():
    classic, pond = layout_for("drawn"), layout_for("painted")
    assert classic.foreground == pond.foreground == (0.80, 1.00)
    assert classic.peekaboo_edge == pond.peekaboo_edge == 1.00  # animals.py:235


def test_unknown_world_rejected():
    with pytest.raises(ValueError, match="scene.world"):
        layout_for("forest")
