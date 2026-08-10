"""Who is in the show: one data row per creature.

Separated from ``animal_art`` on purpose — this file is the cast list, and
swapping "R is for Rabbit" to "R is for Raptor" should never mean reading a
line of drawing code. ``animal_art`` turns a row here into a sprite.

Every creature is drawn side-on facing **right**, so it can walk, hop, fly or
swim across the screen and be flipped for the other direction. The four
original farm animals (cow, duck, pig, sheep) are drawn front-on by bespoke
code in ``animal_art`` and deliberately have no row here — they keep their
peekaboo entrance.

Field notes:

``build``     which body plan the drawer assembles
``aspect``    sprite width as a multiple of its height
``neck``      0 = head sits on the shoulders, 1+ = giraffe
``head``      head size multiplier
``chunk``     body fatness multiplier
``leg``       leg length as a fraction of sprite height
``features``  extra parts the drawer knows how to add; unknown names are
              ignored, so a typo costs a feature, never a crash
"""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]

BUILDS = ("quadruped", "biped", "bird", "swimmer", "floater", "flyer")

#: Ear shapes the drawer implements.
EARS = ("none", "round", "pointy", "floppy", "long", "tuft", "tiny", "fan")

#: Head-front shapes.
MUZZLES = ("none", "snout", "round", "long", "jaws", "beak", "bill", "trunk")

#: Tail shapes.
TAILS = ("none", "short", "long", "puff", "curl", "club", "tuft", "fluke",
         "thick", "spiked")

#: Coat patterns, clipped to the body silhouette.
PATTERNS = ("none", "spots", "stripes", "patch", "shaggy", "speckle")


@dataclass(frozen=True)
class StencilSpec:
    """The extra data a traced outline needs on top of its ``AnimalSpec``.

    Deliberately a separate table rather than more fields on ``AnimalSpec``:
    this is a trial covering three creatures, and keeping it separate means
    both "convert the rest of the cast" and "delete the whole idea" are small,
    obvious changes.

    ``eye_at``      where the eye goes, as a fraction of the sprite box. The
                    one number per animal that has to be found by looking.
    ``faces_left``  true if the source art points left; the loader flips it, so
                    every animal in the app still faces right.
    ``eye``         eye radius as a fraction of sprite height — much larger
                    than life, on purpose (see ``animal_stencil._eye``).
    ``belly``       height fraction given a lighter underside, 0 for none.
    """

    file: str
    eye_at: tuple[float, float]
    faces_left: bool = True
    eye: float = 0.055
    belly: float = 0.0


#: Creatures drawn from a traced outline instead of primitives. Anything not
#: listed here is built the original way; both routes come out of
#: ``animal_art.animal_sprite`` looking the same to everything downstream.
STENCILS: dict[str, StencilSpec] = {
    "giraffe": StencilSpec(
        file="giraffe.svg", eye_at=(0.815, 0.080), eye=0.042,
    ),
    "triceratops": StencilSpec(
        # Behind the brow horns, not on the frill — the frill is the big flat
        # area that reads as "head" at a glance and is the easy place to get
        # this wrong.
        file="triceratops.svg", eye_at=(0.845, 0.400), eye=0.048,
    ),
    "whale": StencilSpec(
        file="whale.svg", eye_at=(0.900, 0.470), eye=0.050, belly=0.38,
    ),
}


@dataclass(frozen=True)
class AnimalSpec:
    build: str
    body: RGB
    shade: RGB
    accent: RGB = (255, 255, 255)
    aspect: float = 1.5
    ears: str = "none"
    muzzle: str = "snout"
    tail: str = "none"
    pattern: str = "none"
    features: tuple[str, ...] = ()
    neck: float = 0.0
    head: float = 1.0
    chunk: float = 1.0
    leg: float = 0.28
    eye: float = 0.050


#: Every creature except the four front-on farm animals. Keys are the names
#: used by ``ANIMAL_LETTERS`` and the audio cue table.
SPECS: dict[str, AnimalSpec] = {
    # ---------------------------------------------------------- A–Z cast
    "alligator": AnimalSpec(
        build="quadruped", body=(86, 156, 84), shade=(58, 116, 62),
        accent=(238, 232, 200), aspect=2.0, ears="tiny", muzzle="jaws",
        tail="thick", pattern="none", features=("scutes", "teeth"),
        head=1.05, chunk=0.86, leg=0.19, eye=0.040,
    ),
    "bear": AnimalSpec(
        build="quadruped", body=(146, 100, 62), shade=(108, 72, 44),
        accent=(214, 178, 132), aspect=1.45, ears="round", muzzle="round",
        tail="short", features=("claws",), chunk=1.12, leg=0.26, eye=0.048,
    ),
    "elephant": AnimalSpec(
        build="quadruped", body=(154, 156, 168), shade=(116, 118, 132),
        accent=(238, 232, 214), aspect=1.55, ears="fan", muzzle="trunk",
        tail="tuft", features=("tusks",), chunk=1.18, leg=0.30, eye=0.038,
    ),
    "fox": AnimalSpec(
        build="quadruped", body=(232, 126, 46), shade=(190, 92, 30),
        accent=(250, 246, 238), aspect=1.65, ears="pointy", muzzle="long",
        tail="puff", features=("socks",), chunk=0.92, leg=0.26,
    ),
    "giraffe": AnimalSpec(
        build="quadruped", body=(238, 196, 108), shade=(196, 148, 70),
        accent=(140, 96, 44), aspect=1.25, ears="pointy", muzzle="snout",
        tail="tuft", pattern="patch", features=("ossicones", "mane"),
        neck=1.05, head=0.74, chunk=0.86, leg=0.34,
    ),
    "horse": AnimalSpec(
        build="quadruped", body=(160, 108, 66), shade=(120, 78, 46),
        accent=(246, 242, 232), aspect=1.55, ears="pointy", muzzle="long",
        tail="long", features=("mane", "hooves"), neck=0.28, chunk=0.96,
        leg=0.34,
    ),
    "iguana": AnimalSpec(
        build="quadruped", body=(96, 186, 128), shade=(62, 140, 92),
        accent=(246, 226, 138), aspect=2.05, ears="none", muzzle="snout",
        tail="thick", features=("spikes", "dewlap"), head=0.92, chunk=0.76,
        leg=0.18, eye=0.042,
    ),
    "jellyfish": AnimalSpec(
        build="floater", body=(196, 132, 246), shade=(150, 92, 208),
        accent=(246, 226, 255), aspect=0.95, muzzle="none",
        features=("frills",), eye=0.055,
    ),
    "koala": AnimalSpec(
        build="quadruped", body=(158, 162, 172), shade=(120, 124, 136),
        accent=(246, 244, 240), aspect=1.15, ears="round", muzzle="round",
        tail="none", features=("bignose", "fluffyears"), chunk=1.0,
        leg=0.24, eye=0.046,
    ),
    "lion": AnimalSpec(
        build="quadruped", body=(226, 174, 92), shade=(184, 132, 60),
        accent=(150, 92, 44), aspect=1.55, ears="round", muzzle="round",
        tail="tuft", features=("ruff",), chunk=1.0, leg=0.28,
    ),
    "monkey": AnimalSpec(
        build="quadruped", body=(140, 98, 66), shade=(104, 70, 46),
        accent=(226, 186, 148), aspect=1.55, ears="round", muzzle="round",
        tail="curl", features=("face",), chunk=0.88, leg=0.24, eye=0.052,
    ),
    "narwhal": AnimalSpec(
        build="swimmer", body=(126, 158, 206), shade=(90, 120, 168),
        accent=(240, 238, 228), aspect=1.85, muzzle="none", tail="fluke",
        pattern="speckle", features=("tusk", "fin"), eye=0.040,
    ),
    "owl": AnimalSpec(
        build="bird", body=(158, 118, 78), shade=(118, 86, 56),
        accent=(240, 226, 196), aspect=1.05, ears="tuft", muzzle="beak",
        tail="short", features=("wing", "bigeyes"), chunk=1.1, leg=0.14,
        eye=0.100,
    ),
    "quail": AnimalSpec(
        build="bird", body=(198, 162, 118), shade=(154, 122, 84),
        accent=(90, 74, 58), aspect=1.35, ears="none", muzzle="beak",
        tail="short", pattern="speckle", features=("wing", "plume"),
        chunk=0.95, leg=0.16, eye=0.048,
    ),
    "rabbit": AnimalSpec(
        build="quadruped", body=(238, 236, 232), shade=(200, 196, 192),
        accent=(248, 176, 194), aspect=1.30, ears="long", muzzle="round",
        tail="puff", features=("whiskers",), chunk=0.94, leg=0.22,
    ),
    "unicorn": AnimalSpec(
        build="quadruped", body=(250, 248, 250), shade=(214, 210, 224),
        accent=(255, 214, 10), aspect=1.55, ears="pointy", muzzle="long",
        tail="rainbow", features=("horn", "rainbowmane", "hooves"),
        neck=0.28, chunk=0.94, leg=0.34,
    ),
    "whale": AnimalSpec(
        build="swimmer", body=(72, 140, 196), shade=(48, 104, 154),
        accent=(226, 238, 246), aspect=1.75, muzzle="none", tail="fluke",
        features=("spout", "fin", "belly"), chunk=1.15, eye=0.042,
    ),
    "xrayfish": AnimalSpec(
        build="swimmer", body=(196, 226, 214), shade=(150, 190, 180),
        accent=(56, 66, 78), aspect=1.55, muzzle="none", tail="fantail",
        features=("bones", "fin"), chunk=0.9, eye=0.058,
    ),
    "yak": AnimalSpec(
        build="quadruped", body=(96, 76, 66), shade=(68, 54, 46),
        accent=(216, 198, 168), aspect=1.55, ears="tiny", muzzle="round",
        tail="tuft", pattern="shaggy", features=("horns", "shaggy"),
        chunk=1.18, leg=0.20,
    ),
    "zebra": AnimalSpec(
        build="quadruped", body=(246, 244, 240), shade=(210, 206, 200),
        accent=(40, 38, 44), aspect=1.55, ears="pointy", muzzle="long",
        tail="tuft", pattern="stripes", features=("mane", "hooves"),
        neck=0.24, chunk=0.96, leg=0.32,
    ),

    # ------------------------------------------------------------ dinosaurs
    "trex": AnimalSpec(
        build="biped", body=(104, 168, 96), shade=(70, 128, 72),
        accent=(226, 214, 168), aspect=1.65, muzzle="jaws", tail="thick",
        features=("teeth", "tinyarms", "scutes", "clawtoes"),
        head=1.25, chunk=1.0, eye=0.042,
    ),
    "velociraptor": AnimalSpec(
        build="biped", body=(216, 138, 78), shade=(174, 100, 54),
        accent=(92, 154, 196), aspect=1.75, muzzle="jaws", tail="long",
        features=("teeth", "feathers", "sicklefoot", "tinyarms"),
        head=0.88, chunk=0.78, eye=0.046,
    ),
    "stegosaurus": AnimalSpec(
        build="quadruped", body=(122, 176, 128), shade=(84, 136, 96),
        accent=(238, 156, 92), aspect=1.85, ears="none", muzzle="snout",
        tail="spiked", features=("plates",), head=0.62, chunk=1.05,
        leg=0.22, eye=0.036,
    ),
    "triceratops": AnimalSpec(
        build="quadruped", body=(154, 168, 118), shade=(114, 128, 84),
        accent=(238, 232, 208), aspect=1.70, ears="none", muzzle="beakjaw",
        tail="thick", features=("frill", "threehorns"), head=1.05,
        chunk=1.08, leg=0.22, eye=0.038,
    ),
    "brachiosaurus": AnimalSpec(
        build="quadruped", body=(126, 152, 190), shade=(90, 114, 152),
        accent=(214, 226, 240), aspect=1.35, ears="none", muzzle="snout",
        tail="long", features=("crest",), neck=1.30, head=0.66, chunk=0.78,
        leg=0.34, eye=0.034,
    ),
    "pterodactyl": AnimalSpec(
        build="flyer", body=(206, 146, 92), shade=(164, 108, 62),
        accent=(238, 226, 196), aspect=1.95, muzzle="beak",
        features=("crest", "membrane"), eye=0.042,
    ),
}
