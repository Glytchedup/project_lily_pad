"""Measure packed frames against the Fable art gates and render the two-background review sheet.

qa_sprite.py [PAINTED_ROOT] [--name giraffe] [--out REVIEW_DIR]
Use --mask POSE=PNG for an exact splice mask (white permits change in final canvas coordinates).
"""

import argparse
import hashlib
import json
from pathlib import Path
import tomllib

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

if __package__:
    from . import orc, sheet
else:
    import orc
    import sheet

ROOT = Path(__file__).resolve().parents[2] / "src/lilypad/assets/painted"
POND = np.array([14, 26, 44]) / 255


def entries(root, name=None):
    data = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))
    if type(data.get("schema")) is not int or data["schema"] != 1:
        raise ValueError("Expected painted manifest schema 1")
    result = dict(data.get("animals", {}))
    for key in ("pip", "pad"):
        if key in data:
            result[key] = data[key]
    result.update({f"minis/{k}": v for k, v in data.get("minis", {}).items()})
    if name is not None:
        result = {name: result[name]}
    if not result:
        raise ValueError("No entries to review")
    return result


def frame_paths(root, entry):
    frames = entry.get("frames")
    if frames is None:
        frames = {"idle": entry["file"]}
    elif not {"idle", "blink"} <= frames.keys():
        raise ValueError("Manifest entry needs idle and blink")
    paths = {pose: (root / path).resolve() for pose, path in frames.items()}
    if any(not path.is_relative_to(root.resolve()) for path in paths.values()):
        raise ValueError("Frame path outside the painted root")
    return paths


def fingerprint(paths):
    digest = hashlib.sha256()
    for pose, path in sorted(paths.items()):
        digest.update(pose.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def read_report(out):
    path = out / "qa.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"entries": {}}


def write_report(out, report):
    out.mkdir(parents=True, exist_ok=True)
    orc.atomic_write(out / "qa.json", (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def luminance(rgb):
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055)**2.4)
    return linear @ np.array([.2126, .7152, .0722])


def measure(image, *, file_bytes, extension, traced_aspect=None):
    image = image.convert("RGBA")
    rgba = np.asarray(image) / 255.
    rgb, alpha = rgba[:,:,:3], rgba[:,:,3]
    solid = alpha >= .5
    labels, n = ndi.label(solid, np.ones((3, 3)))
    if not n:
        return {"issues": ["empty"]}
    main = labels == (np.bincount(labels.ravel())[1:].argmax() + 1)
    filled = ndi.binary_fill_holes(main)
    outer = filled & ~ndi.binary_erosion(filled, structure=np.ones((3, 3)))
    luma = luminance(rgb)
    lightness = np.where(luma > (6/29)**3, 116 * np.cbrt(luma) - 16, (29/3)**3*luma)
    keyline = outer & (lightness < 30)
    key_luma = float(np.median(luma[keyline])) if keyline.any() else 0.
    translucent = (alpha > .1) & (alpha < .9)
    halo = 0.
    if translucent.any():
        a = alpha[translucent, None]
        halo = float(luminance(rgb[translucent]*a + POND*(1-a)).mean())
    distance = ndi.distance_transform_edt(~main)
    fringe = int((solid & (distance > 2)).sum())
    yy, xx = np.nonzero(main)
    height = int(np.ptp(yy)) + 1
    aspect = (int(np.ptp(xx))+1) / height
    body = main & ~outer
    mean = float(lightness[body if body.any() else main].mean())
    # Sample the top silhouette once per occupied column. The art bible puts
    # the rim inside a keyline up to 3.5% of figure height.
    cols = np.flatnonzero(main.any(axis=0))
    top = main[:,cols].argmax(axis=0)
    bright = body & (lightness >= 65)
    if bright.any():
        rim = float((ndi.distance_transform_edt(~bright)[top,cols] <= max(2, .05*height)).mean())
    else:
        rim = 0.
    box = image.getchannel("A").getbbox()
    touches = box[0] == 0 or box[1] == 0 or box[2] == image.width or box[3] == image.height
    key_share = float(keyline.sum()/outer.sum())
    checks = dict(halo=halo <= key_luma + .08, fringe=fringe == 0, keyline=key_share >= .85,
                  value=mean >= 45 or rim >= .30, canvas_edge=not touches,
                  file_size=file_bytes <= (200_000 if extension.lower() == ".webp" else 600_000))
    if traced_aspect is not None:
        checks["proportion"] = abs(aspect/traced_aspect - 1) <= .25
    return dict(halo_luminance=halo, keyline_luminance=key_luma, fringe_pixels=fringe,
                dark_contour_fraction=key_share, aspect=aspect, traced_aspect=traced_aspect,
                mean_body_L=mean, rim_fraction=rim, touches_edge=touches, file_bytes=file_bytes,
                issues=[key for key, passed in checks.items() if not passed])


def traced_aspect(name):
    from lilypad.effects import animal_stencil
    if animal_stencil.has(name):
        # The SVG can include blank margins. The runtime stencil uses a tight crop.
        w, h = animal_stencil._shape(name, 256).get_size()
        return w / h
    return None  # front cast, Pip, pad and minis have no traced reference


def identity(idle, frame, pose, entry, mask_path=None):
    if frame.size != idle.size:
        return {"issues": ["canvas_size"]}
    w, h = idle.size
    yy, xx = np.ogrid[:h, :w]
    box = idle.getchannel("A").getbbox()
    if box is None:
        return {"issues": ["empty"]}
    if mask_path is not None:
        with Image.open(mask_path) as mask:
            if mask.size != idle.size:
                raise ValueError(f"Mask {mask_path} must match the packed canvas")
            allowed = np.asarray(mask.convert("L")) > 0
        region = str(mask_path)
    elif pose in ("blink", "eyes_white"):
        x, y = entry["eye_at"]
        # Conservative fallback for sheets without a supplied splice disc.
        radius = max(2, .10 * (box[3]-box[1]))
        allowed = (xx + .5 - x*w)**2 + (yy + .5 - y*h)**2 <= radius**2
        if entry.get("view", "front") == "front":
            allowed |= allowed[:,::-1].copy()
        region = "eye disc(s), radius 10% of body height"
    elif pose == "step":
        seam = box[1] + round(.55 * (box[3]-box[1]))
        allowed = yy >= seam
        region = "lower 45% of body"
    else:
        return {"issues": ["change_mask_required"]}
    a, b = np.asarray(idle), np.asarray(frame)
    visible = (a[:,:,3] > 0) | (b[:,:,3] > 0)
    count = int(np.count_nonzero(visible & ~allowed & (a != b).any(axis=2)))
    return dict(region=region, changed_outside=count, issues=["identity"] if count else [])


def review(root, out, name=None, masks=None):
    # The numerical and paid reviewers update different fields of the same file.
    with orc._lock(out / "qa.json"):
        return _review(root, out, name, masks)


def _review(root, out, name, masks):
    selected = entries(root, name)
    report = read_report(out)
    if name is None:
        report["entries"] = {k:v for k,v in report["entries"].items() if k in selected}
    photos, captions = [], []
    for key, entry in sorted(selected.items()):
        paths = frame_paths(root, entry)
        digest = fingerprint(paths)
        old = report["entries"].get(key, {})
        result = {"fingerprint": digest, "frames": {}, "identity": {}}
        if old.get("fingerprint") == digest and "judge" in old:
            result["judge"] = old["judge"]
        reference = traced_aspect(key)
        with Image.open(paths["idle"]) as source:
            idle = source.convert("RGBA")
        for pose, path in paths.items():
            with Image.open(path) as source:
                frame = source.convert("RGBA")
            result["frames"][pose] = measure(frame, file_bytes=path.stat().st_size,
                                             extension=path.suffix, traced_aspect=reference)
            if pose != "idle":
                result["identity"][pose] = identity(idle, frame, pose, entry, (masks or {}).get(pose))
            photos.append(path)
            captions.append(f"{key} / {pose}")
        result["metrics_pass"] = not any(row["issues"] for group in ("frames", "identity")
                                         for row in result[group].values())
        report["entries"][key] = result
    width, cols = 220, 3
    board = sheet.contact_sheet(photos, columns=cols, width=width)
    draw = ImageDraw.Draw(board)
    for i, caption in enumerate(captions):
        x = (i % cols) * width * 2
        y = (i // cols) * (width*9//16+22) + width*9//16
        draw.rectangle((x, y, x+2*width-1, y+21), fill="black")
        draw.text((x+5, y+4), caption, fill="white")
    out.mkdir(parents=True, exist_ok=True)
    board.save(out / "contact-sheet.png")
    write_report(out, report)
    return all(report["entries"][k]["metrics_pass"] for k in selected)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path, nargs="?", default=ROOT)
    p.add_argument("--name")
    p.add_argument("--out", type=Path, default=Path("work/qa"))
    p.add_argument("--mask", action="append", default=[], metavar="POSE=PNG")
    args = p.parse_args(argv)
    if args.mask and not args.name:
        p.error("--mask needs --name to identify the entry")
    masks = dict(item.split("=", 1) for item in args.mask)
    return 0 if review(args.root, args.out, args.name, masks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
