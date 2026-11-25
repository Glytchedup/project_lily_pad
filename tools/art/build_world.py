"""Build the painted pond moods (plate, near-water strip, empty far-shore strip). Offline: no paid calls.

    python tools/art/build_world.py --prod work/prod --world src/lilypad/assets/world

Per mood (``world/manifest.toml`` schema, written by J11):

* plate       ``<mood>_plate.png`` centre-cropped to 16:9 and scaled to 1920x1080, saved as JPEG q88.  World layers
              keep their max channel at or below 70 except the brightest 0.5% of pixels (moon, stars, glints), so the
              plate is darkened with one uniform gamma, the smallest that passes the check on the *decoded JPEG*.
* near_water  1997x238 RGBA (``ceil(1920 * 1.04)`` by ``0.22 * 1080``), bottom flush: the eight props of
              ``world/props_sheet.png`` composed as cattail clumps toward both ends and lily-pad groups and grass
              tufts between, darkened to sit under the animals, with a light per-mood tint.
* far_shore   the plates already carry the shore, but the loader requires the key, so every mood points at one fully
              transparent 1997x324 strip.
"""

import argparse
import io
from math import ceil
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cutout_sprite  # noqa: E402

MOODS = ("starry", "twilight", "aurora", "mist")     # playback order
W, H = 1920, 1080
STRIP_W = ceil(W * 1.04)
NEAR_H = round(H * .22)
FAR_H = round(H * .30)
BUDGET = .0045                                       # share of pixels allowed above 70
TINT = {"starry": (0.92, 1.00, 1.06), "twilight": (1.06, 0.92, 1.12), "aurora": (0.90, 1.08, 1.04),
        "mist": (0.96, 1.02, 1.04)}
DARKEN = .34                                          # props are painted mid-value; the foreground must sit low


def over_budget(arr):
    return (arr.max(axis=2) > 70).mean()


def encode(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


def build_plate(src, out):
    """Return (gamma, over70 fraction after JPEG, bytes written)."""
    im = Image.open(src).convert("RGB")
    h = round(im.width * 9 / 16)
    top = (im.height - h) // 2
    im = im.crop((0, top, im.width, top + h)).resize((W, H), Image.Resampling.LANCZOS)
    base = np.asarray(im).astype(np.float32) / 255
    gamma = 1.0
    while True:
        arr = np.rint(255 * base ** gamma).astype(np.uint8)
        data = encode(arr)
        decoded = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
        frac = over_budget(decoded)
        if frac <= BUDGET:
            break
        gamma += .02
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return round(gamma, 2), frac, len(data)


def cut_props(sheet, want=8):
    """The sheet's props, merging close pieces (the pad groups) until exactly ``want`` remain, left to right."""
    with Image.open(sheet) as src:
        rgba = np.asarray(src.convert("RGBA"))
    mask, green = cutout_sprite._foreground(rgba, 1, 24)
    for radius in range(4, 80, 2):
        lab, n = ndi.label(ndi.binary_dilation(mask, iterations=radius))
        area = np.bincount(lab.ravel())[1:]
        big = [k + 1 for k in range(n) if area[k] > .004 * mask.size]
        if len(big) == want:
            break
    else:
        raise RuntimeError(f"could not find {want} props (found {len(big)})")
    props = []
    for k, box in ((k, ndi.find_objects(lab)[k - 1]) for k in big):
        member = mask[box] & (lab[box] == k)
        props.append((box[1].start, cutout_sprite._finish(rgba[box], member, green)))
    return [im for _, im in sorted(props, key=lambda p: p[0])]


def shade(im, tint):
    a = np.asarray(im).astype(np.float32)
    a[:, :, :3] = np.clip(a[:, :, :3] * DARKEN * np.array(tint), 0, 255)
    return Image.fromarray(a.astype(np.uint8))


def place(strip, im, x, height=None, width=None, flip=False):
    if flip:
        im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if height:
        im = im.resize((round(im.width * height / im.height), height), Image.Resampling.LANCZOS)
    elif width:
        im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
    x = max(0, min(STRIP_W - im.width, x))
    strip.alpha_composite(im, (x, NEAR_H - im.height))     # bottom edge flush
    return x + im.width


def build_strip(props, tint):
    """props, left to right on the sheet: cattail A, reeds, tuft, 3 pads, lotus pad, 2 pads, cattail B, cattail C."""
    cat_a, reeds, tuft, pads3, lotus, pads2, cat_b, cat_c = (shade(p, tint) for p in props)
    s = Image.new("RGBA", (STRIP_W, NEAR_H))
    # left end: cattail clumps, then reeds
    place(s, cat_a, 6, height=NEAR_H - 6)
    place(s, cat_c, 84, height=NEAR_H - 28)
    place(s, reeds, 150, height=120)
    # between: lily-pad groups, tufts, the lotus
    place(s, pads3, 330, width=190)
    place(s, tuft, 560, height=70)
    place(s, lotus, 700, width=170)
    place(s, reeds, 930, height=96, flip=True)
    place(s, pads2, 1090, width=200)
    place(s, tuft, 1360, height=84, flip=True)
    place(s, pads3, 1480, width=170, flip=True)
    # right end: cattail clumps
    place(s, reeds, 1690, height=110)
    place(s, cat_b, 1770, height=NEAR_H - 10)
    place(s, cat_a, STRIP_W - 6, height=NEAR_H - 18, flip=True)
    place(s, cat_c, STRIP_W - 4, height=NEAR_H - 40, flip=True)
    return s


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prod", type=Path, required=True)
    p.add_argument("--world", type=Path, required=True, help="src/lilypad/assets/world")
    args = p.parse_args(argv)
    world = args.world
    props = cut_props(args.prod / "world/props_sheet.png")
    rows, credits = [], []
    (world / "shared").mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (STRIP_W, FAR_H)).save(world / "shared" / "clear.png", optimize=True)
    for order, mood in enumerate(MOODS):
        gamma, frac, size = build_plate(args.prod / f"world/{mood}_plate.png", world / mood / "plate.jpg")
        build_strip(props, TINT[mood]).save(world / mood / "water.png", optimize=True)
        rows.append((mood, order))
        credits += [f"{mood}/plate.jpg", f"{mood}/water.png"]
        print(f"{mood}: gamma {gamma}, {frac * 100:.3f}% over 70 after JPEG, plate {size} bytes")
    manifest = world / "manifest.toml"
    head = [l for l in manifest.read_text(encoding="utf-8").splitlines() if l.startswith("#") or not l.strip()]
    body = []
    for mood, order in rows:
        body += [f"[moods.{mood}]", f'plate = "{mood}/plate.jpg"', 'far_shore = "shared/clear.png"',
                 f'near_water = "{mood}/water.png"', f"order = {order}", ""]
    manifest.write_text("\n".join(head + body).rstrip() + "\n", encoding="utf-8")
    path = world / "CREDITS.md"
    lines = ["# World credits", "", "| File | Model | Date | Style ID | Prompt SHA | AI-generated original; no reference to "
             "existing characters |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| `{f}` | google/gemini-3-pro-image | 2026-11-25 | A | unknown | "
              f"AI-generated original; no reference to existing characters |" for f in credits]
    lines.append("| `shared/clear.png` | none | 2026-11-25 | A | none | Generated locally: a fully transparent strip |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
