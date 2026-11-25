"""Build Pip, his lily pad, the count-along minis and Lily from their AI sheets. Offline: no paid calls.

    python tools/art/build_extras.py --prod work/prod --root OUT/painted --work OUT/work

* Pip      3 panels (idle, blink, cheer) -> ``[pip]``.  Blink is idle with both eye discs from the blink panel;
           ``eyes_white`` is idle with each iris and pupil painted in the sclera cream (the runtime draws
           moving pupils over it); ``eye_at`` is the left eye.  Built by ``stage_build.build_pip``.
* pad      one lily pad -> ``[pad]`` (60 px tall).
* minis    the sheet has two rows: a crisp bottom row of seven and a soft extra flower and star on top.
           The two top-row items are dropped; the seven kept are named left to right.
* Lily     ``kid/lily_a.png`` (sit, sit_blink, wave; front view) and ``kid/lily_b.png`` (tummy, point, cheer).
           Sheet B has a soft ground shadow under every pose; it is removed (pale, unsaturated pixels that connect
           to the outside without crossing the dark keyline).  Each pose is scaled so ``heights`` (fractions of
           ``native_height``) keep her one size across poses.
"""

import argparse
import hashlib
import os
import shutil
import sys
import tomllib
from pathlib import Path
from tempfile import gettempdir

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cutout_sprite  # noqa: E402
import orc  # noqa: E402
import pack  # noqa: E402
import stage_build as sb  # noqa: E402

MINIS = ("duck", "apple", "frog", "flower", "star", "stegosaurus", "triceratops")
LILY_NATIVE = 300
LILY_HEIGHTS = {"sit": .78, "sit_blink": .78, "wave": 1.0, "tummy": .55, "point": 1.0, "cheer": 1.0}


def cut_with_centres(sheet, count, tol=24):
    """Like ``cutout_sprite.cutout`` but also returns each sprite's vertical centre (fraction of the sheet)."""
    with Image.open(sheet) as src:
        rgba = np.asarray(src.convert("RGBA"))
        mask, green = cutout_sprite._foreground(rgba, count, tol)
        out = []
        for region, member in cutout_sprite._parts(mask, count):
            out.append(((region[0].start + region[0].stop) / 2 / rgba.shape[0],
                        cutout_sprite._finish(rgba[region], member, green)))
    return out


def remove_ground_shadow(im):
    """Clear the pale, unsaturated ground shadow outside the keyline."""
    a = np.asarray(im.convert("RGBA")).copy()
    rgb = a[:, :, :3].astype(int)
    lum = rgb @ np.array([.2126, .7152, .0722])
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    candidate = (a[:, :, 3] > 0) & (sat <= 48) & (lum > 150)
    exterior = a[:, :, 3] == 0
    grown = ndi.binary_propagation(exterior, mask=exterior | candidate)
    shadow = grown & candidate
    shadow = ndi.binary_dilation(shadow, iterations=2) & (a[:, :, 3] > 0) & (lum > 140) & (sat <= 55)
    a[shadow, 3] = 0
    # drop hairline leftovers of the shadow's textured edge
    solid = ndi.binary_opening(a[:, :, 3] > 0, structure=np.ones((3, 3)))
    a[~ndi.binary_dilation(solid, iterations=1), 3] = 0
    # keep only the figure: the largest component and anything of real size attached to it
    lab, n = ndi.label(a[:, :, 3] > 0, np.ones((3, 3)))
    area = np.bincount(lab.ravel())
    area[0] = 0
    keep = area >= .02 * area.max()
    a[~keep[lab], 3] = 0
    out = Image.fromarray(a)
    left, top, right, bottom = out.getchannel("A").getbbox()
    return out.crop((left - 2, top - 2, right + 2, bottom + 2)) if min(left, top) >= 2 else out.crop((left, top, right, bottom))


def tight(im, pad=2):
    left, top, right, bottom = im.getchannel("A").getbbox()
    out = Image.new("RGBA", (right - left + 2 * pad, bottom - top + 2 * pad))
    out.paste(im.crop((left, top, right, bottom)), (pad, pad))
    return out


def sha(*paths):
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return "sha256:" + h.hexdigest()


def upsert(root, key, entry):
    """Add a top-level table (``lily``) to the manifest the way pack.py does: locked, sorted, comments kept."""
    manifest = root / "manifest.toml"
    lock = hashlib.sha256(os.fsencode(os.path.normcase(str(manifest)))).hexdigest()
    with orc._lock(Path(gettempdir()) / ("lilypad-pack-" + lock)):
        old = manifest.read_text(encoding="utf-8")
        doc = tomllib.loads(old)
        doc[key] = entry
        orc.atomic_write(manifest, pack.manifest_bytes(doc, old, key))


def add_credits(root, files):
    path = root / "CREDITS.md"
    rows = path.read_text(encoding="utf-8").rstrip().splitlines()
    for f in files:
        row = (f"| `{f}` | unknown | unknown | A | unknown | "
               "AI-generated original; no reference to existing characters |")
        if row not in rows:
            rows.append(row)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def build_pad(sheet, root, work):
    panel = cut_with_centres(sheet, 1)[0][1]
    (work / "cut").mkdir(parents=True, exist_ok=True)
    panel.save(work / "cut" / "pad.png")
    return pack.pack("pad", [work / "cut" / "pad.png"], gait="pad", root=root, source=sheet, credits=True)[0]


def build_minis(sheet, root, work):
    parts = cut_with_centres(sheet, 9)
    kept = [im for cy, im in parts if cy >= .35]          # the two soft top-row items sit high on the sheet
    assert len(kept) == len(MINIS), f"expected {len(MINIS)} bottom-row minis, found {len(kept)}"
    folder = work / "cut" / "minis"
    folder.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name, im in zip(MINIS, kept):                      # cutout_sprite already orders parts left to right
        path = folder / f"{name}.png"
        im.save(path)
        entries[name] = pack.pack(name, [path], gait="minis", root=root, source=sheet, credits=True)[0]
    return entries


def build_lily(sheet_a, sheet_b, root, work):
    folder = work / "cut" / "lily"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    a = [im for _, im in cut_with_centres(sheet_a, 3)]
    b = [remove_ground_shadow(im) for _, im in cut_with_centres(sheet_b, 3)]
    eyes = sb.detect_eyes(a[0], a[1], True)
    info = {}
    sit_blink = sb.splice_eyes(a[0], a[1], eyes, info)
    poses = {"sit": a[0], "sit_blink": sit_blink, "wave": a[2], "tummy": b[0], "point": b[1], "cheer": b[2]}
    files = {}
    for pose, im in poses.items():
        im = tight(im, 2)           # sit and sit_blink share an alpha box, so the pair keeps one canvas
        height = round(LILY_HEIGHTS[pose] * LILY_NATIVE)
        size = max(1, round(im.width * height / im.height)), height
        frame = im.resize(size, Image.Resampling.LANCZOS)
        rel = f"lily/{pose}.webp"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.save(path, "WEBP", quality=90, alpha_quality=100)
        files[pose] = rel
        frame.save(folder / f"{pose}.png")
    entry = dict(native_height=LILY_NATIVE, anchor=[.5, 1.0], frames=files, heights=LILY_HEIGHTS,
                 source_hash=sha(sheet_a, sheet_b), prompt_id="lily-v1")
    upsert(root, "lily", entry)
    add_credits(root, list(files.values()))
    return entry


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prod", type=Path, required=True, help="work/prod (extras/ and kid/ live under it)")
    p.add_argument("--root", type=Path, required=True, help="painted output directory")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--only", nargs="*", choices=("pip", "pad", "minis", "lily"))
    args = p.parse_args(argv)
    run = args.only or ("pip", "pad", "minis", "lily")
    prod = args.prod
    if "pip" in run:
        print("pip", sb.build_pip(prod / "extras/pip_sheet.png", args.root, args.work))
    if "pad" in run:
        print("pad", build_pad(prod / "extras/pad2.png", args.root, args.work))
    if "minis" in run:
        print("minis", build_minis(prod / "extras/minis_sheet.png", args.root, args.work))
    if "lily" in run:
        print("lily", build_lily(prod / "kid/lily_a.png", prod / "kid/lily_b.png", args.root, args.work))
    sb.fix_credits(args.root, "google/gemini-3-pro-image", "2026-11-25")


if __name__ == "__main__":
    main()
