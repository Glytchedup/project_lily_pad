"""Key a sprite or a one-row pose sheet into padded, straight-alpha PNGs."""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi


def _foreground(rgba, count, tolerance):
    border = np.concatenate((rgba[0], rgba[-1], rgba[1:-1, 0], rgba[1:-1, -1]))
    visible = border[border[:, 3] != 0]
    transparent = rgba[:, :, 3] == 0
    if np.median(border[:, 3]) == 0:
        # An already transparent cutout has no reliable background RGB.
        return ~transparent, False
    key = np.median(visible[:, :3], axis=0).astype(np.float32)
    delta = rgba[:, :, :3].astype(np.float32) - key
    candidate = transparent | (np.einsum("ijk,ijk->ij", delta, delta) <= tolerance**2)
    seeds = np.zeros_like(candidate)
    seeds[[0, -1], :] = candidate[[0, -1], :]
    seeds[:, [0, -1]] = candidate[:, [0, -1]]
    outside = ndi.binary_propagation(seeds, mask=candidate)
    # Preserve tiny matching highlights inside the keyline, clear larger enclosed gaps.
    enclosed, _ = ndi.label(candidate & ~outside)
    holes = np.bincount(enclosed.ravel()) > 0.0015 * candidate.size / count
    holes[0] = False
    return ~(outside | holes[enclosed] | transparent), key[1] > max(key[0], key[2]) + 20


def _parts(mask, count):
    labels, n = ndi.label(mask, structure=np.ones((3, 3), dtype=bool))
    if n < count:
        raise ValueError(f"Found {n} foreground components for {count} requested sprites.")
    areas = np.bincount(labels.ravel())
    boxes = ndi.find_objects(labels)

    def center(label):
        y, x = boxes[label - 1]
        return (x.start + x.stop) / 2, (y.start + y.stop) / 2

    largest = np.argsort(areas[1:])[-count:] + 1
    anchors = sorted(largest, key=center)
    groups = {k: [k] for k in anchors}
    smallest_part = 0.02 * areas[largest].min()
    for label in range(1, n + 1):
        if label in groups or areas[label] <= smallest_part:
            continue
        x, y = center(label)
        # Detached horns and tail tips belong to the closest panel silhouette box.
        def distance(k):
            rows, cols = boxes[k - 1]
            dx = max(cols.start - x, x - cols.stop, 0)
            dy = max(rows.start - y, y - rows.stop, 0)
            return dx * dx + dy * dy

        owner = min(anchors, key=distance)
        if areas[label] > 0.02 * areas[owner]:
            groups[owner].append(label)
    for members in groups.values():
        ys, xs = zip(*(boxes[k - 1] for k in members))
        region = tuple(slice(min(s.start for s in axis), max(s.stop for s in axis))
                       for axis in (ys, xs))
        yield region, np.isin(labels[region], members)


def _finish(rgba, mask, green):
    # Pad the cutout first so components touching a crop edge get the same erosion.
    mask = np.pad(mask, 2)
    src = np.pad(rgba, ((2, 2), (2, 2), (0, 0)))
    inner = ndi.binary_erosion(mask, structure=np.ones((3, 3), dtype=bool))
    coverage = ndi.gaussian_filter(inner.astype(np.float32), sigma=0.65, radius=1)
    alpha = np.minimum(np.rint(255 * coverage).astype(np.uint8), src[:, :, 3])
    opaque = alpha == 255
    if not opaque.any():
        raise ValueError("Sprite has no opaque interior after one-pixel erosion.")
    rgb = src[:, :, :3].copy()
    if green:
        # Neutralise green spill at the opaque edge before it supplies fringe RGB.
        edge = opaque & ~ndi.binary_erosion(opaque, iterations=2)
        neutral = np.maximum(rgb[:, :, 0], rgb[:, :, 2])
        rgb[:, :, 1][edge] = np.minimum(rgb[:, :, 1][edge], neutral[edge])
    soft = (alpha > 0) & ~opaque
    nearest = ndi.distance_transform_edt(~opaque, return_distances=False, return_indices=True)
    rgb[soft] = rgb[nearest[0][soft], nearest[1][soft]]
    rgb[alpha == 0] = 0
    result = Image.fromarray(np.dstack((rgb, alpha)))
    left, top, right, bottom = result.getchannel("A").getbbox()
    return result.crop((left - 2, top - 2, right + 2, bottom + 2))


def cutout(image, count=1, tolerance=24):
    if count < 1 or not 0 <= tolerance <= 442:
        raise ValueError("Expected a positive sprite count and a colour tolerance in 0..442.")
    rgba = np.asarray(image.convert("RGBA"))
    mask, green = _foreground(rgba, count, tolerance)
    return [_finish(rgba[region], member, green) for region, member in _parts(mask, count)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path, help="PNG path, or directory with --split")
    parser.add_argument("--split", type=int, metavar="N")
    parser.add_argument("--tol", type=float, default=24, help="Euclidean RGB key tolerance")
    args = parser.parse_args(argv)
    with Image.open(args.src) as src:
        sprites = cutout(src, 1 if args.split is None else args.split, args.tol)
    if args.split is None:
        paths = [args.dst]
    else:
        paths = [args.dst / f"item{i}.png" for i in range(len(sprites))]
    for sprite, path in zip(sprites, paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        sprite.save(path, format="PNG")
        print(f"Wrote {path} ({sprite.width} x {sprite.height})")


if __name__ == "__main__":
    main()
