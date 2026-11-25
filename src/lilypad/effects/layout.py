"""Vertical scene bands, measured downwards from the top in screen heights."""

from dataclasses import dataclass

Band = tuple[float, float]


@dataclass(frozen=True)
class Layout:
    name: str
    sky: Band | None          # the classic gradient has no painted bands
    far_shore: Band | None
    water: Band | None        # water available for walker reflections
    ground: float             # walkers' feet, landings and dust
    shockwave: float          # origin of the dinosaur's ring
    fly_band: Band            # range for the centre of the flight path
    swim_band: Band
    swim_height: float        # sprite height before the width cap
    foreground: Band = (0.80, 1.00)
    peekaboo_edge: float = 1.00


# Median far-bank/water boundary across the four 1920x1080 plates.
_POND_BANK = 774 / 1080

POND = Layout(
    name="pond",
    sky=(0.00, 0.52),
    far_shore=(0.52, 0.62),
    water=(_POND_BANK, 0.93),
    ground=_POND_BANK,
    shockwave=_POND_BANK,
    fly_band=(0.10, 0.40),
    swim_band=(0.79, 0.86),
    swim_height=0.22,
)

CLASSIC = Layout(
    name="classic",
    sky=None,
    far_shore=None,
    water=None,
    ground=0.94,
    shockwave=0.92,
    fly_band=(0.16, 0.46),
    swim_band=(0.48, 0.74),
    swim_height=0.28,
)


def layout_for(world: str) -> Layout:
    """Return the preset selected by scene.world."""
    if world == "painted":
        return POND
    if world == "drawn":
        return CLASSIC
    raise ValueError(f"scene.world must be 'painted' or 'drawn', got {world!r}")
