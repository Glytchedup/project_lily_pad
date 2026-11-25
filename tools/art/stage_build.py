"""Cut, splice and pack the painted cast (animals, Pip) from AI pose sheets. Offline: no paid calls.

    python tools/art/stage_build.py [name ...] --sheets work/prod/sheets --trial work/trial --root OUT/painted

Why not plain ``cutout_sprite.py --split`` then ``pack.py``?  ``splice.register`` rejects any panel whose upper 55%
differs from idle by more than 2% of the height.  The image model redraws heads slightly between idle and blink, and
the hop and fly step panels (leap, wings down) change the upper body by design, so about two thirds of real sheets
fail that gate.  This script builds the frames the way the README describes instead:

1. **cut**      ``cutout_sprite.cutout`` splits the sheet into one RGBA panel per pose.
2. **blink**    idle with only the eye disc(s) replaced by the blink panel's pixels, so nothing else can drift.
                Eyes are found by differencing idle and blink (the open iris is dark, the closed lid is light);
                the disc radius is the larger of the diff blob and the measured iris.  Side views with two visible
                eyes (3/4 heads) get both discs, front views get the left and right eye.
3. **step**     walk gait: ``splice.splice(..., "step")``, idle's upper 55% plus the step panel's lower 45%.  When
                the strict gate fails, ``seam_register`` picks the offset that makes the join seamless.  Hop/fly:
                the raw step panel, centroid aligned, because the whole pose changes.  A walker whose step panel
                still shows a seam (``RAW_STEP``: bear) also uses the raw panel, aligned on its feet.  Pip's cheer
                is aligned on its base too (he sits on a pad).
4. **pack**     ``pack.pack`` registers, scales to the gait height and writes WebP, the manifest and CREDITS.
                Two ``pack`` hooks are replaced for the run: ``measure_eye`` (whole-body diff centroid, so eyes lower
                than 45% of the body work) and ``scale_canvas`` (see margins).

Margins: every canvas gets a transparent margin of ``--margin`` (6%) of its height on all four sides, so nothing
touches the canvas edge.  Sides grow to at least 7.5% of the figure width so the runtime squash (x1.14 wide) never
clips.  The bottom margin lifts feet, the peekaboo cut and Pip's seat by that much; the runtime anchors on the canvas
bottom, so compensate there if the lift shows.

Folding this into ``pack.py`` (``measure_eye``, ``scale_canvas`` margins, the loose registration) is the intended
follow-up; the functions here are deliberately small and self-contained.
"""

import argparse
import json
import shutil
import sys
from math import ceil, pi, sqrt
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cutout_sprite  # noqa: E402
import pack  # noqa: E402
import splice  # noqa: E402

# name -> gait.  walk/hop/fly have idle, blink, step panels; swim/float/front have idle, blink.
GAIT = {
    "alligator": "walk", "bear": "walk", "brachiosaurus": "walk", "elephant": "walk", "fox": "walk",
    "giraffe": "walk", "horse": "walk", "iguana": "walk", "koala": "walk", "lion": "walk",
    "stegosaurus": "walk", "triceratops": "walk", "unicorn": "walk", "yak": "walk", "zebra": "walk",
    "monkey": "hop", "rabbit": "hop", "trex": "hop", "velociraptor": "hop",
    "owl": "fly", "pterodactyl": "fly", "quail": "fly",
    "jellyfish": "float", "narwhal": "swim", "whale": "swim", "xrayfish": "swim",
    "cow": "front", "duck": "front", "pig": "front", "sheep": "front",
}
PANELS = {"walk": 3, "hop": 3, "fly": 3, "swim": 2, "float": 2, "front": 2}
TRIAL = ("giraffe", "bear")          # approved trial sheets live in trial/M_<name>_sheet.png
RAW_STEP = {"bear"}                  # walkers whose step panel cannot be joined to idle without a visible seam
EYES: dict[str, list] = {}           # manual override: name -> [(x, y, iris_radius), ...] in cut-panel pixels

MARGIN = 0.06
SQUASH_SIDE = 0.075                  # runtime squash is x1.14 wide, so each side needs about 7% of the figure width


# ---------------------------------------------------------------------------------------------- image helpers
def luma(im):
    a = np.asarray(im.convert("RGBA"), dtype=np.float32)
    return a[:, :, :3] @ np.array([.2126, .7152, .0722], np.float32), a[:, :, 3] > 128


def centroid(im):
    yy, xx = np.nonzero(np.asarray(im.getchannel("A")) > 128)
    return xx.mean(), yy.mean()


def centroid_offset(master, edit):
    mx, my = centroid(master)
    ex, ey = centroid(edit)
    return round(mx - ex), round(my - ey)


def base_offset(master, edit):
    """Align a sitting pose on its base: x from the lower 40% mass, y from the bottom row."""
    def base(im):
        a = np.asarray(im.getchannel("A")) > 128
        rows = np.flatnonzero(a.any(axis=1))
        top, bottom = rows[0], rows[-1]
        low = a[bottom - round(.4 * (bottom - top)):]
        return np.nonzero(low)[1].mean(), bottom
    (mx, mb), (ex, eb) = base(master), base(edit)
    return round(mx - ex), mb - eb


def shifted(edit, off, size):
    dx, dy = off
    return edit.crop((-dx, -dy, size[0] - dx, size[1] - dy))


# ---------------------------------------------------------------------------------------------- eyes
def detect_eyes(idle, blink, front):
    """Return [(x, y, radius)] of the eye(s) that change between idle and blink, in idle pixels."""
    b = shifted(blink, centroid_offset(idle, blink), idle.size)
    la, ma = luma(idle)
    lb, mb = luma(b)
    both = ma & mb
    d = lb - la                                   # an open iris is dark, so the blink is lighter there
    mask = both & (d > max(25, .45 * np.percentile(d[both], 99.7)))
    lab = None
    for r in (max(2, round(.006 * idle.height)), max(2, round(.004 * idle.height)), 2, 1):
        yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
        opened = ndi.binary_opening(mask, structure=(xx ** 2 + yy ** 2) <= r * r)
        lab, n = ndi.label(opened)
        if n:
            break
    if not n:
        raise ValueError("no eye blob")
    area = np.bincount(lab.ravel())
    area[0] = 0
    centres = ndi.center_of_mass(opened, lab, range(1, n + 1))     # (y, x) per label
    comps = []

    def add(k):
        comps.append((centres[k - 1][1] + .5, centres[k - 1][0] + .5, sqrt(area[k] / pi)))

    if front:
        box = splice._box(idle)
        cut = (box[0] + box[2]) / 2
        right = max((k for k in range(1, n + 1) if centres[k - 1][1] >= cut), key=lambda q: area[q], default=None)
        ry = centres[right - 1][0] if right else None
        left_all = [k for k in range(1, n + 1) if centres[k - 1][1] < cut]
        near = [k for k in left_all if ry is not None and abs(centres[k - 1][0] - ry) < .12 * idle.height]
        left = max(near or left_all, key=lambda q: area[q], default=None)
        for k in (left, right):
            if k:
                add(k)
    else:
        k = int(np.argmax(area))
        add(k)
        rp = comps[0][2]
        for j in np.argsort(area)[::-1]:              # a second eye on a 3/4 head
            if j == k or area[j] < .2 * area[k]:
                continue
            dist = np.hypot(centres[j - 1][1] + .5 - comps[0][0], centres[j - 1][0] + .5 - comps[0][1])
            if 3 * rp <= dist <= 10 * rp and abs(centres[j - 1][0] + .5 - comps[0][1]) <= 4 * rp:
                add(j)
                break
    comps.sort()
    return comps


def local_blink(master, edit, eye, radius):
    """Lenient blink when the strict gate fails: register on a window around the eye only."""
    g = centroid_offset(master, edit)
    box = splice._box(master)
    half = round(.22 * (box[3] - box[1]))
    ex, ey = round(eye[0]), round(eye[1])
    ref = splice._signal(master.crop((ex - half, ey - half, ex + half, ey + half)))
    cand = splice._signal(edit.crop((ex - g[0] - half, ey - g[1] - half, ex - g[0] + half, ey - g[1] + half)))
    tx, ty = splice._translation(ref, cand)
    aligned = shifted(edit, (g[0] + tx, g[1] + ty), master.size)
    yy, xx = np.ogrid[:master.height, :master.width]
    inside = (xx - eye[0]) ** 2 + (yy - eye[1]) ** 2 <= (1.6 * radius) ** 2
    return Image.composite(aligned, master, Image.fromarray(inside))


def seam_register(master, edit, reach=(150, 60), band=18):
    """Offset that makes the step panel join idle without a visible step at the 55% seam.

    The upper-body gate fails when the head tilts or the body sits lower in the step panel, and phase correlation
    then lands on a bad offset.  What the splice shows is the join, so search for the (dx, dy) that minimises the
    colour and alpha difference in a band of rows either side of the seam, over the pixels where either is solid.
    """
    box = splice._box(master)
    seam = box[1] + round(.55 * (box[3] - box[1]))
    rows = slice(seam - band, seam + band)
    a = np.asarray(master.convert("RGBA")).astype(np.float32)[rows]
    pad = np.pad(np.asarray(edit.convert("RGBA")).astype(np.float32), ((reach[1] + band,) * 2, (reach[0],) * 2, (0, 0)))
    w = a.shape[1]
    best = (1e18, (0, 0))

    def cost(dx, dy):
        # edit pixel (x, y) lands at (x + dx, y + dy); read the edit rows/cols that land on the master band
        y0 = seam - band - dy + reach[1] + band
        x0 = -dx + reach[0]
        if y0 < 0 or x0 < 0 or y0 + 2 * band > pad.shape[0] or x0 + w > pad.shape[1]:
            return 1e18
        b = pad[y0:y0 + 2 * band, x0:x0 + w]
        solid = (a[:, :, 3] > 128) | (b[:, :, 3] > 128)
        if solid.sum() < 50:
            return 1e18
        d = np.abs(a[:, :, :3] - b[:, :, :3]).mean(axis=2)
        d = np.where((a[:, :, 3] > 128) & (b[:, :, 3] > 128), d, 255.0)
        return d[solid].mean()

    for dx in range(-reach[0], reach[0] + 1, 4):
        for dy in range(-reach[1], reach[1] + 1, 4):
            c = cost(dx, dy)
            if c < best[0]:
                best = (c, (dx, dy))
    cx, cy = best[1]
    for dx in range(cx - 3, cx + 4):
        for dy in range(cy - 3, cy + 4):
            c = cost(dx, dy)
            if c < best[0]:
                best = (c, (dx, dy))
    return best[1]


def splice_eyes(idle, blink, eyes, info):
    """Paste each eye disc from ``blink`` onto idle."""
    res, modes, radii = idle, [], []
    for ex, ey, er in eyes:
        try:
            ri = splice._eye_radius(idle, ex, ey)
        except ValueError:
            ri = 0
        radii.append([round(er, 1), round(ri, 1)])
        er = max(1.4 * er, 1.15 * ri, .01 * idle.height)
        try:
            res, _, resid, _ = splice.splice(res, blink, "blink", (ex, ey), er)
            modes.append(f"strict res={resid:.1f}")
        except ValueError:
            res = local_blink(res, blink, (ex, ey), er)
            modes.append("LENIENT-local")
    info["eye_r"], info["blink"] = radii, modes
    return res


def eyes_white(idle, eyes):
    """Pip's idle with the iris and pupil of each eye painted in the sclera colour (cream)."""
    out = np.asarray(idle.convert("RGBA")).copy()
    lum, solid = luma(idle)
    for ex, ey, er in eyes:
        reach = round(2.0 * er)
        yy, xx = np.ogrid[:idle.height, :idle.width]
        zone = (xx - ex) ** 2 + (yy - ey) ** 2 <= reach ** 2
        white = zone & (lum > 225) & solid
        cream = np.median(out[white][:, :3], axis=0).astype(np.uint8) if white.any() else np.array([255, 248, 235], np.uint8)
        dark, _ = ndi.label(zone & (lum < 110) & solid)
        k = dark[min(idle.height - 1, round(ey)), min(idle.width - 1, round(ex))]
        if not k:       # the centre may be a catchlight; take the largest dark blob in the zone
            sizes = np.bincount(dark.ravel())
            sizes[0] = 0
            k = int(np.argmax(sizes))
        iris = ndi.binary_fill_holes(dark == k)
        iris = ndi.binary_dilation(iris, iterations=2)
        out[iris, :3] = cream
    return Image.fromarray(out)


# ---------------------------------------------------------------------------------------------- pack hooks
def my_measure_eye(idle, blink, front):
    """Whole-body diff centroid of the largest changed blob (the left eye for front views)."""
    a, b = (np.asarray(im, dtype=np.int16) for im in (idle, blink))
    body = (a[:, :, 3] >= 128) & (b[:, :, 3] >= 128)
    delta = np.max(np.abs(a[:, :, :3] - b[:, :, :3]), axis=2)
    lab, n = ndi.label(body & (delta >= (max(12, .35 * delta[body].max()) if body.any() else 12)), np.ones((3, 3)))
    if not n:
        raise ValueError("No measurable idle/blink eye change.")
    area = np.bincount(lab.ravel())[1:]
    pts = []
    for k in np.argsort(area)[::-1][:2 if front else 1]:
        y, x = np.nonzero(lab == k + 1)
        pts.append(((x.mean() + .5) / idle.width, (y.mean() + .5) / idle.height))
    return list(sorted(pts)[0])


def margin_canvas(margin):
    """A ``pack.scale_canvas`` replacement: fixed canvas height, transparent margins around the figure."""
    def scale_canvas(images, height):
        w, h = images[0].size
        top = round(margin * height)
        bottom = top
        scale = (height - top - bottom) / h
        for _ in range(3):
            cw = w * scale
            side = max(round(margin * height), ceil(SQUASH_SIDE * cw))
            if cw + 2 * side <= pack.MAX_WIDTH:
                break
            scale *= (pack.MAX_WIDTH - 2 * side) / cw
        size = max(1, round(w * scale)), max(1, round(h * scale))
        frames = []
        for image in images:
            frame = Image.new("RGBA", (size[0] + 2 * side, height))
            frame.paste(image.resize(size, Image.Resampling.LANCZOS), (side, top))
            frames.append(frame)
        return frames
    return scale_canvas


pack.measure_eye = my_measure_eye
_orig_register = splice.register
FALLBACK = {"hit": False, "offset": centroid_offset}


def _register(master, edit, eye=None):
    """pack's registration, falling back to a plain alignment for panels the gate cannot judge."""
    try:
        return _orig_register(master, edit, eye)
    except ValueError:
        FALLBACK["hit"] = True
        if edit.size == master.size:            # spliced blink: built on a copy of idle, the shift is zero
            return (0, 0), -1.0
        return FALLBACK["offset"](master, edit), -1.0


# ---------------------------------------------------------------------------------------------- build
def green_panels(src, count):
    """A sheet whose panels are green rectangles on a white page: re-lay them on one green canvas.

    The cutout keys the page border (white), so green panels would survive as solid rectangles and a white
    figure on them would be cleared as an enclosed hole.  Cropping each rectangle and joining them on green first
    lets the normal green-key cut work.
    """
    a = np.asarray(src.convert("RGB")).astype(int)
    green = (a[:, :, 1] > a[:, :, 0] + 60) & (a[:, :, 1] > a[:, :, 2] + 60)
    lab, n = ndi.label(ndi.binary_opening(green, iterations=3))
    boxes = ndi.find_objects(lab)
    keep = sorted(np.argsort(np.bincount(lab.ravel())[1:])[::-1][:count])
    crops = sorted((boxes[k] for k in keep), key=lambda b: b[1].start)
    inset = 4
    tiles = [src.convert("RGB").crop((b[1].start + inset, b[0].start + inset, b[1].stop - inset, b[0].stop - inset))
             for b in crops]
    gap = 80
    canvas = Image.new("RGB", (sum(t.width for t in tiles) + gap * (count + 1), max(t.height for t in tiles) + 2 * gap),
                       tuple(int(v) for v in np.median(a[green], axis=0)))
    x = gap
    for t in tiles:
        canvas.paste(t, (x, gap))
        x += t.width + gap
    return canvas


def drop_white_slivers(im):
    """Clear thin enclosed gaps of pure white (background seen between two legs) that the cutout keeps."""
    a = np.asarray(im).copy()
    white = (a[:, :, :3].min(axis=2) >= 240) & (a[:, :, 3] > 0)
    lab, _ = ndi.label(white)
    for k, box in enumerate(ndi.find_objects(lab), 1):
        h, w = box[0].stop - box[0].start, box[1].stop - box[1].start
        fill = (lab[box] == k).sum() / (h * w)       # a catchlight is round (about 0.78); a gap is a thin diagonal
        if max(h, w) >= 12 and (fill < .4 or max(h, w) >= 3 * min(h, w)):
            region = ndi.binary_dilation(lab == k, iterations=1)
            a[region, 3] = 0
    return Image.fromarray(a)


def foreground_keep_holes(rgba, count, tolerance):
    """``cutout_sprite._foreground`` that clears only the border-connected background.

    The stock cutout also clears every enclosed region that matches the background, which would punch Pip's
    white eyes out of his head.
    """
    border = np.concatenate((rgba[0], rgba[-1], rgba[1:-1, 0], rgba[1:-1, -1]))
    key = np.median(border[border[:, 3] != 0][:, :3], axis=0).astype(np.float32)
    delta = rgba[:, :, :3].astype(np.float32) - key
    candidate = np.einsum("ijk,ijk->ij", delta, delta) <= tolerance ** 2
    seeds = np.zeros_like(candidate)
    seeds[[0, -1], :] = candidate[[0, -1], :]
    seeds[:, [0, -1]] = candidate[:, [0, -1]]
    outside = ndi.binary_propagation(seeds, mask=candidate)
    return ~outside, bool(key[1] > max(key[0], key[2]) + 20)


GREEN_PANELS = {"sheep"}           # panels drawn as green rectangles on a white page
WHITE_SLIVERS = {"iguana"}           # a white gap between two legs that survives the cutout


def cut_sheet(sheet, count, out_dir, tol=24, name="", keep_holes=False):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    with Image.open(sheet) as src:
        if name in GREEN_PANELS:
            src = green_panels(src, count)
        stock = cutout_sprite._foreground
        if keep_holes:
            cutout_sprite._foreground = foreground_keep_holes
        try:
            panels = cutout_sprite.cutout(src, count, tol)
        finally:
            cutout_sprite._foreground = stock
    if name in WHITE_SLIVERS:
        panels = [drop_white_slivers(p) for p in panels]
    paths = []
    for i, panel in enumerate(panels):
        paths.append(out_dir / f"item{i}.png")
        panel.save(paths[-1])
    return [Image.open(p).convert("RGBA") for p in paths]


def pack_panels(name, gait, panels, spliced_dir, root, source, png, credits, margin, base_align=False):
    if spliced_dir.exists():
        shutil.rmtree(spliced_dir)
    spliced_dir.mkdir(parents=True)
    paths = []
    for i, im in enumerate(panels):
        paths.append(spliced_dir / f"item{i}.png")
        im.save(paths[-1])
    saved = pack.scale_canvas
    pack.scale_canvas = margin_canvas(margin) if margin else saved
    FALLBACK["hit"] = False
    FALLBACK["offset"] = base_offset if gait == "pip" or base_align else centroid_offset
    splice.register = _register
    try:
        return pack.pack(name, paths, gait=gait, root=root, source=source, credits=credits, png=png)[0]
    finally:
        splice.register = _orig_register
        pack.scale_canvas = saved


def build_animal(name, sheet, root, work, png=False, credits=True, margin=MARGIN):
    gait = GAIT[name]
    front = gait == "front"
    ims = cut_sheet(sheet, PANELS[gait], work / "cut" / name, name=name)
    idle, info = ims[0], {"gait": gait}
    eyes = EYES.get(name) or detect_eyes(idle, ims[1], front)
    info["eyes_px"] = [[round(x, 1), round(y, 1), round(r, 1)] for x, y, r in eyes]
    out = [idle, splice_eyes(idle, ims[1], eyes, info)]
    if len(ims) == 3:
        if gait == "walk" and name not in RAW_STEP:
            try:
                step, _, resid, _ = splice.splice(idle, ims[2], "step")
                info["step"] = f"strict res={resid:.1f}"
            except ValueError as exc:
                off = seam_register(idle, ims[2])
                box = splice._box(idle)
                step, _ = splice._step(idle, ims[2], off, box[1] + round(.55 * (box[3] - box[1])))
                info["step"] = f"LENIENT-offset {off} ({str(exc)[:50]})"
        else:
            step = ims[2]
            info["step"] = "RAW panel (pose differs in the upper body by design)"
            info["step"] += "; base aligned" if gait == "walk" else ""
        out.append(step)
    entry = pack_panels(name, gait, out, work / "spliced" / name, root, sheet, png, credits, margin,
                         base_align=gait == "walk")
    info["pack_register_fallback"] = FALLBACK["hit"]
    info["entry"] = {k: entry[k] for k in ("native_height", "eye_at", "back_at", "anchor")}
    return info


def build_pip(sheet, root, work, png=False, credits=True, margin=MARGIN):
    ims = cut_sheet(sheet, 3, work / "cut" / "pip", keep_holes=True)
    idle, info = ims[0], {"gait": "pip"}
    eyes = detect_eyes(idle, ims[1], True)
    info["eyes_px"] = [[round(x, 1), round(y, 1), round(r, 1)] for x, y, r in eyes]
    blink = splice_eyes(idle, ims[1], eyes, info)
    white = eyes_white(idle, eyes)
    entry = pack_panels("pip", "pip", [idle, blink, ims[2], white], work / "spliced" / "pip",
                        root, sheet, png, credits, margin)
    info["entry"] = {k: entry[k] for k in ("native_height", "eye_at", "anchor")}
    return info


def fix_credits(root, model, date):
    """Rewrite the model, date and style columns pack derives from a missing receipt."""
    path = root / "CREDITS.md"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            cells[1:4] = [model, date, "A"]
            line = "| " + " | ".join(cells) + " |"
        rows.append(line)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("names", nargs="*", help="animals to build (default: all)")
    p.add_argument("--sheets", type=Path, required=True, help="directory of <name>.png sheets")
    p.add_argument("--trial", type=Path, help="directory with M_giraffe_sheet.png and M_bear_sheet.png")
    p.add_argument("--root", type=Path, required=True, help="painted output directory")
    p.add_argument("--work", type=Path, required=True, help="scratch directory for cut/ and spliced/ panels")
    p.add_argument("--png", action="store_true", help="lossless RGBA PNG (identity checks) instead of WebP")
    p.add_argument("--margin", type=float, default=MARGIN, help="transparent margin as a fraction of height")
    p.add_argument("--model", default="google/gemini-3-pro-image")
    p.add_argument("--date", default="2026-11-25")
    p.add_argument("--log", type=Path, help="write per-animal build notes here (merged if it exists)")
    args = p.parse_args(argv)
    if args.png:   # exact pixels for identity checks: skip pack's 256-colour dithered palette
        pack._palette_frames = lambda frames: frames
    log =json.loads(args.log.read_text()) if args.log and args.log.exists() else {}
    for name in args.names or sorted(GAIT):
        sheet = (args.trial / f"M_{name}_sheet.png") if name in TRIAL and args.trial else args.sheets / f"{name}.png"
        try:
            log[name] = build_animal(name, sheet, args.root, args.work, args.png, not args.png, args.margin)
            print(name, "ok", flush=True)
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            log[name] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            print(name, "FAIL", log[name]["error"], flush=True)
    if (args.root / "CREDITS.md").exists() and not args.png:
        fix_credits(args.root, args.model, args.date)
    if args.log:
        args.log.write_text(json.dumps(log, indent=1))


if __name__ == "__main__":
    main()
