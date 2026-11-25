"""Pack cut RGBA panels in pose order into one painted manifest entry.

Example: pack.py giraffe cuts/item{0,1,2}.png --gait walk --source sheet.png --credits
--root is the painted directory containing manifest.toml. --eye uses final canvas fractions.
"""

import argparse
from datetime import date, datetime, time, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
from tempfile import gettempdir
import tomllib

import numpy as np
from PIL import Image
from scipy import ndimage

if __package__:
    from . import orc, splice
else:
    import orc
    import splice

ROOT = Path(__file__).resolve().parents[2] / "src/lilypad/assets/painted"
HEIGHTS = dict(walk=367, hop=345, fly=259, swim=302, float=259, front=432,
               pip=150, minis=160, pad=60)
MAX_WIDTH = 1152


def register_panels(images):
    """Return aligned panels, tightly cropped to their union, and edit-to-idle shifts."""
    idle = images[0]
    shifts = [(0, 0)] + [splice.register(idle, image)[0] for image in images[1:]]
    boxes = []
    for image, (dx, dy) in zip(images, shifts):
        box = image.getchannel("A").getbbox()
        if box is None:
            raise ValueError("Empty panel")
        x, y, right, bottom = box
        boxes.append((x + dx, y + dy, right + dx, bottom + dy))
    left, top, right, bottom = (fn(vals) for fn, vals in zip(
        (min, min, max, max), zip(*boxes)))
    aligned = [im.crop((left-dx, top-dy, right-dx, bottom-dy)) for im, (dx, dy) in zip(images, shifts)]
    return aligned, shifts


def scale_canvas(images, height):
    # Reserve transparent pixels at the *final* resolution, including after the width cap.
    w, h = images[0].size
    scale = min((height - 4) / h, (MAX_WIDTH - 4) / w)
    size = max(1, round(w * scale)), max(1, round(h * scale))
    frames = []
    for image in images:
        frame = Image.new("RGBA", (size[0]+4, size[1]+4))
        frame.paste(image.resize(size, Image.Resampling.LANCZOS), (2, 2))
        frames.append(frame)
    return frames


def measure_eye(idle, blink, front):
    """Centroid of the largest strong colour change inside the registered, opaque head."""
    x, y, r, b = idle.getchannel("A").getbbox()
    w, h = r-x, b-y
    left, right = (x, x + (w+1)//2) if front else (x + int(.60*w), r)
    box = (left, y, right, max(y+1, y+round(.45*h)))
    a, z = (np.asarray(im.crop(box), dtype=np.int16) for im in (idle, blink))
    body = (a[:,:,3] >= 128) & (z[:,:,3] >= 128)
    delta = np.max(np.abs(a[:,:,:3] - z[:,:,:3]), axis=2)
    threshold = max(12, .35 * delta[body].max()) if body.any() else 12
    labels, count = ndimage.label(body & (delta >= threshold), np.ones((3, 3)))
    if not count:
        raise ValueError("No measurable idle/blink eye change. Supply --eye x,y in canvas fractions.")
    biggest = np.bincount(labels.ravel())[1:].argmax() + 1
    yy, xx = np.nonzero(labels == biggest)
    return [(left + xx.mean() + .5) / idle.width, (y + yy.mean() + .5) / idle.height]


def landmarks(idle, eye):
    if len(eye) != 2 or not all(0 <= n <= 1 for n in eye):
        raise ValueError("--eye requires two fractions in [0, 1]")
    alpha = np.asarray(idle)[:,:,3]
    left, right = int(.4*idle.width), max(int(.4*idle.width)+1, int(.6*idle.width))
    yy, xx = np.nonzero(alpha[:,left:right])
    if not len(xx):
        raise ValueError("Idle body has no back in the middle fifth of the canvas")
    top = yy.min()
    top_columns = left + xx[yy == top]
    seat = (top_columns[np.argmin(abs(top_columns - idle.width/2))] + .5) / idle.width
    bottom = idle.getchannel("A").getbbox()[3] - 1
    return dict(anchor=[.5, bottom / idle.height], eye_at=list(eye),
                back_at=[seat, top / idle.height])


def _key(key):
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def _literal(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_literal(value[k])}" for k in sorted(value)) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(map(_literal, value)) + "]"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float):
        return repr(float(value))
    return json.dumps(value, ensure_ascii=False)


def _sections(text):
    """Find the schema's named stanzas, keeping original comments and spacing."""
    headers = list(re.finditer(r"(?m)^\[([\w.-]+)\][ \t]*(?:#[^\n]*)?$", text))
    prefix = text[:headers[0].start()] if headers else text
    blocks = {}
    for i, header in enumerate(headers):
        end = headers[i+1].start() if i+1 < len(headers) else len(text)
        blocks[header[1]] = text[header.start():end]
    return prefix, blocks


def manifest_bytes(doc, old, target):
    # Schema collections use named tables. Other nested values (including frames)
    # use inline tables; unknown metadata survives a read/write round trip.
    lines = []
    for line in old.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            break
        lines.append(line)
    def emit(table, path):
        children = []
        for k in sorted(table):
            value = table[k]
            if isinstance(value, dict) and (not path or path in (("animals",), ("minis",))):
                children.append((k, value))
            else:
                lines.append(f"{_key(k)} = {_literal(value)}")
        for k, child in children:
            prefix = (*path, k)
            if prefix not in (("animals",), ("minis",)) or not child:
                lines.extend(["", "[" + ".".join(map(_key, prefix)) + "]"])
            emit(child, prefix)
    emit(doc, ())
    result = "\n".join(lines) + "\n"
    prefix, blocks = _sections(result)
    _, prior = _sections(old)
    kept = []
    for key, block in blocks.items():
        if key != target and key in prior:
            block = prior[key]
        kept.append(block.rstrip("\n"))
    preserved = prefix + "\n\n".join(kept) + "\n"
    # A prior manifest can use valid but different TOML notation (e.g. a
    # separate frames subtable). Always verify semantic equality before reuse.
    try:
        if tomllib.loads(preserved) == doc:
            return preserved.encode()
    except tomllib.TOMLDecodeError:
        pass
    if tomllib.loads(result) != doc:
        raise ValueError("Cannot preserve all existing manifest data")
    return result.encode()


def _encode(image, png):
    data = BytesIO()
    if png:
        image.save(data, "PNG")
    else:
        image.save(data, "WEBP", quality=90, alpha_quality=100)
    return data.getvalue()


def _palette_frames(frames):
    # Quantize all poses together so a change in one leg cannot recolour the
    # unchanged body through an independently chosen palette.
    w, h = frames[0].size
    atlas = Image.new("RGBA", (w, h*len(frames)))
    for i, image in enumerate(frames):
        atlas.paste(image, (0, i*h))
    indexed = atlas.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
    return [indexed.crop((0, i*h, w, (i+1)*h)) for i in range(len(frames))]


def _credits(path, files, source, style):
    receipt = Path(str(source) + ".json")
    meta = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {}
    day = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).date().isoformat()
    old = path.read_text(encoding="utf-8") if path.exists() else (
        "| File | Model | Date | Style | Prompt SHA-256 | Origin |\n|---|---|---|---|---|---|\n")
    rows = old.rstrip().splitlines()
    for file in files:
        row = (f"| `{file}` | {meta.get('model', 'unknown')} | {meta.get('date', day)} | "
               f"{meta.get('style', style)} | {meta.get('prompt_sha256', 'unknown')} | "
               "AI-generated original; no reference to existing characters |")
        if row not in rows:
            rows.append(row)
    return ("\n".join(rows) + "\n").encode()


def pack(name, panels, *, gait, root=ROOT, source=None, prompt_id=None, eye=None, png=False,
         credits=False, style="A"):
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError("Use a lowercase manifest entry name")
    poses = {"pip": ("idle", "blink", "cheer", "eyes_white"), "minis": ("file",),
             "pad": ("file",)}.get(gait, ("idle", "blink", "step") if gait in ("walk", "hop", "fly")
                                  else ("idle", "blink"))
    if len(panels) != len(poses):
        raise ValueError(f"{gait} needs panels in this order: {', '.join(poses)}")
    if gait in ("pip", "pad") and name != gait:
        raise ValueError(f"Use entry name {gait!r} for this gait")
    root = Path(root).resolve()
    source = Path(source or panels[0])
    images = []
    for panel in panels:
        with Image.open(panel) as image:
            images.append(image.convert("RGBA"))
    aligned, shifts = register_panels(images)
    frames = scale_canvas(aligned, HEIGHTS[gait])
    ext = "png" if png else "webp"
    if gait == "minis":
        paths = [f"minis/{name}.{ext}"]
    elif gait == "pad":
        paths = [f"pip/pad.{ext}"]
    else:
        paths = [f"{name}/{pose}.{ext}" for pose in poses]
    to_encode = _palette_frames(frames) if png else frames
    files = {root/path: _encode(frame, png) for path, frame in zip(paths, to_encode)}
    entry = dict(native_height=frames[0].height)
    if poses == ("file",):
        entry["file"] = paths[0]
    else:
        if eye is None:
            eye = measure_eye(frames[0], frames[1], gait in ("front", "pip"))
        # Palette quantization can remove low-alpha tips. Anchor and back must
        # land on the alpha contour the runtime actually decodes.
        with Image.open(BytesIO(files[root/paths[0]])) as encoded:
            entry.update(landmarks(encoded.convert("RGBA"), eye))
        entry.update(frames=dict(zip(poses, paths)),
                     source_hash="sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
                     prompt_id=prompt_id or {"pip": "pip-v1", "front": "sheet-front-v1"}.get(gait, "sheet-side-v1"))
        if gait == "pip":
            del entry["back_at"]
        else:
            entry.update(view="front" if gait == "front" else "side", faces_left=False)
    manifest = root / "manifest.toml"
    lock_id = hashlib.sha256(os.fsencode(os.path.normcase(str(manifest)))).hexdigest()
    with orc._lock(Path(gettempdir()) / ("lilypad-pack-" + lock_id)):
        old = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
        doc = tomllib.loads(old) if old else {"schema": 1, "style": style}
        if type(doc.get("schema")) is not int or doc["schema"] != 1 or doc.get("style", style) != style:
            raise ValueError("Manifest schema or style differs from the requested pack")
        doc.setdefault("style", style)
        if gait in ("pad", "pip"):
            doc[gait] = entry
            target = gait
        else:
            group = "minis" if gait == "minis" else "animals"
            doc.setdefault(group, {})[name] = entry
            target = f"{group}.{name}"
        if credits:
            path = root / "CREDITS.md"
            files[path] = _credits(path, paths, source, style)
        files[manifest] = manifest_bytes(doc, old, target)
        before = {}
        try:
            for path, data in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                before[path] = path.read_bytes() if path.exists() else None
                orc.atomic_write(path, data)
        except OSError:
            for path, previous in reversed(before.items()):
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    orc.atomic_write(path, previous)
            raise
    return entry, shifts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("name")
    p.add_argument("panels", nargs="+", type=Path)
    p.add_argument("--gait", choices=HEIGHTS, required=True)
    p.add_argument("--root", type=Path, default=ROOT, help="painted output directory containing manifest.toml")
    p.add_argument("--source", type=Path, help="original sheet/master PNG for hash and credits (default: idle panel)")
    p.add_argument("--prompt-id")
    p.add_argument("--style", default="A")
    p.add_argument("--eye", type=splice.coordinates, help="eye centre as final canvas fractions x,y")
    p.add_argument("--credits", action="store_true")
    p.add_argument("--png", action="store_true")
    args = p.parse_args(argv)
    entry, shifts = pack(**vars(args))
    print(json.dumps(dict(entry=entry, shifts=shifts), indent=2))


if __name__ == "__main__":
    main()
