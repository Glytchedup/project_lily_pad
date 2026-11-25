"""Register a pose to its master and splice only the eye or the moving legs."""

import argparse
from math import ceil, hypot, isfinite, pi, sqrt
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi


def _box(image):
    box = image.getchannel("A").getbbox()
    if box is None:
        raise ValueError("A registration image is completely transparent.")
    return box


def _signal(image):
    rgba = np.asarray(image, dtype=np.float32) / 255
    luma = rgba[:, :, :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return (0.30 + 0.70 * luma) * rgba[:, :, 3]


def _upper(image, box, size):
    x, y = box[:2]
    # Include real top/side contour features even for a uniformly painted rectangle.
    return _signal(image.crop((x - 2, y - 2, x + size[0] + 2, y + size[1])))


def _translation(ref, candidate):
    cross = np.fft.rfft2(ref) * np.fft.rfft2(candidate).conj()
    magnitude = np.abs(cross)
    if not np.ptp(ref) or not np.ptp(candidate):
        raise ValueError("Upper body has no registration features.")
    phase = cross / np.maximum(magnitude, 1e-7 * magnitude.max())
    peak = np.unravel_index(np.argmax(np.fft.irfft2(phase, s=ref.shape, axes=(0, 1))), ref.shape)
    dy, dx = (int((v + n // 2) % n - n // 2) for v, n in zip(peak, ref.shape))
    return dx, dy


def _edges(signal):
    gradient = np.hypot(ndi.sobel(signal, axis=0), ndi.sobel(signal, axis=1))
    return gradient > max(0.10, 0.10 * gradient.max())


def _residual(master, aligned, eye):
    # Symmetric 95th-percentile distance between strong upper-body edges.
    # Computing edges before masking avoids measuring a synthetic seam or eye circle.
    a, b = (_edges(_signal(im))[:-1] for im in (master, aligned))
    if eye is not None:
        x, y, radius = eye
        yy, xx = np.ogrid[:a.shape[0], :a.shape[1]]
        valid = (xx - x)**2 + (yy - y)**2 > (1.6 * radius + 1)**2
        a, b = a & valid, b & valid
    if not a.any() or not b.any():
        raise ValueError("Upper body has no comparable edges.")
    return max(float(np.percentile(ndi.distance_transform_edt(~target)[source], 95))
               for source, target in ((a, b), (b, a)))


def register(master, edit, eye=None):
    """Return the integer edit-to-master (dx, dy) and post-alignment residual in pixels."""
    m, e = _box(master), _box(edit)
    for image, box in ((master, m), (edit, e)):
        if box == (0, 0, *image.size) and all(lo == hi for lo, hi in image.getextrema()):
            raise ValueError("Upper body has no registration features.")
    height = m[3] - m[1]
    upper = max(1, round(0.55 * height))
    size = max(m[2] - m[0], e[2] - e[0]), upper
    dx, dy = _translation(_upper(master, m, size), _upper(edit, e, size))
    dx += m[0] - e[0]
    dy += m[1] - e[1]
    # Include both silhouettes, even if a malformed edit extends outside the master.
    x0, y0 = min(m[0], e[0] + dx) - 2, min(m[1], e[1] + dy) - 2
    x1, y1 = max(m[2], e[2] + dx) + 2, m[1] + upper + 1
    region = (x0, y0, x1, y1)
    reference = master.crop(region)
    candidate = edit.crop((x0 - dx, y0 - dy, x1 - dx, y1 - dy))
    relative_eye = (eye[0] - x0, eye[1] - y0, eye[2]) if eye else None
    residual = _residual(reference, candidate, relative_eye)
    if residual > 0.02 * height:
        raise ValueError(f"Upper-body residual {residual:.2f} px exceeds 2% of height ({0.02 * height:.2f} px).")
    return (dx, dy), residual


def _eye_radius(master, x, y):
    # Find the dark iris nearest the supplied centre, including a white catchlight.
    box = _box(master)
    reach = max(4, ceil((box[3] - box[1]) * 0.12))
    cx, cy = round(x), round(y)
    patch = master.crop((cx - reach, cy - reach, cx + reach + 1, cy + reach + 1))
    luma = np.asarray(patch.convert("L"))
    solid = np.asarray(patch.getchannel("A")) >= 128
    if solid.any():
        lo, hi = np.percentile(luma[solid], [2, 85])
        labels, _ = ndi.label(solid & (luma <= lo + 0.3 * (hi - lo)))
        yy, xx = np.nonzero(labels)
        if len(xx):
            i = np.argmin((xx - reach)**2 + (yy - reach)**2)
            iris = labels == labels[yy[i], xx[i]]
            if (hypot(xx[i] - reach, yy[i] - reach) <= reach / 2 and
                    not (iris[0].any() or iris[-1].any() or iris[:, 0].any() or iris[:, -1].any())):
                return sqrt(iris.sum() / pi)
    raise ValueError("Cannot measure the eye in the master. Supply --eye-r in pixels.")


def _step(master, edit, offset, seam):
    dx, dy = offset
    # Trimmed panels can have a wider stride. Preserve the full lower pose and
    # report the master's origin if that requires a larger output canvas.
    lower = edit.getchannel("A").crop((0, max(0, min(edit.height, seam - dy)), edit.width, edit.height))
    extent = lower.getbbox()
    left, right, bottom = 0, master.width, master.height
    if extent:
        left = min(0, dx + extent[0])
        right = max(right, dx + extent[2])
        bottom = max(bottom, max(seam, dy) + extent[3])
    result = Image.new("RGBA", (right - left, bottom))
    result.paste(master, (-left, 0))
    aligned = Image.new("RGBA", result.size)
    aligned.paste(edit, (dx - left, dy))
    stop = min(seam + 12, bottom)
    band = (0, seam, result.width, stop)
    if stop > seam:
        weights = np.broadcast_to(np.rint(np.arange(stop - seam) * 255 / 12)[:, None],
                                  (stop - seam, result.width)).astype(np.uint8)
        # Interpolate premultiplied colour only inside the feather band.
        mixed = Image.composite(aligned.crop(band).convert("RGBa"), result.crop(band).convert("RGBa"),
                                Image.fromarray(weights)).convert("RGBA")
        if stop > seam + 1:
            result.paste(mixed.crop((0, 1, result.width, mixed.height)), (0, seam + 1))
    result.paste(aligned.crop((0, stop, result.width, bottom)), (0, stop))
    return result, (-left, 0)


def splice(master, edit, mode, eye=None, eye_r=None):
    master, edit = master.convert("RGBA"), edit.convert("RGBA")
    disc = None
    if mode == "blink":
        if eye is None or not (0 <= eye[0] < master.width and 0 <= eye[1] < master.height):
            raise ValueError("Blink needs --eye x,y inside the master.")
        radius = _eye_radius(master, *eye) if eye_r is None else eye_r
        if not isfinite(radius) or radius <= 0:
            raise ValueError("Eye radius must be positive and finite.")
        disc = (*eye, radius)
    elif mode != "step":
        raise ValueError("Expected blink or step mode.")
    offset, residual = register(master, edit, disc)
    if mode == "blink":
        dx, dy = offset
        aligned = edit.crop((-dx, -dy, master.width - dx, master.height - dy))
        yy, xx = np.ogrid[:master.height, :master.width]
        inside = (xx - eye[0])**2 + (yy - eye[1])**2 <= (1.6 * radius)**2
        result = Image.composite(aligned, master, Image.fromarray(inside))
        origin = (0, 0)
    else:
        box = _box(master)
        result, origin = _step(master, edit, offset, box[1] + round(0.55 * (box[3] - box[1])))
    return result, offset, residual, origin


def coordinates(value):
    try:
        x, y = map(float, value.split(","))
        return x, y
    except ValueError:
        raise argparse.ArgumentTypeError("expected x,y in master pixels") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("edit", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--mode", choices=("blink", "step"), required=True)
    parser.add_argument("--eye", type=coordinates)
    parser.add_argument("--eye-r", type=float, help="measured eye radius in master pixels")
    args = parser.parse_args(argv)
    with Image.open(args.master) as master, Image.open(args.edit) as edit:
        try:
            result, offset, residual, origin = splice(master, edit, args.mode, args.eye, args.eye_r)
        except ValueError as exc:
            parser.exit(1, f"Rejected: {exc}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.out, format="PNG")
    print(f"Wrote {args.out} | edit shift {offset} | residual {residual:.2f} px | master origin {origin}")


if __name__ == "__main__":
    main()
