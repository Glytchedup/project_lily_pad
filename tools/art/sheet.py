"""Make a labelled PNG/JPEG contact sheet on one or two comparison backgrounds."""

import argparse
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageOps

POND = "#0E1A2C"
GREY = "#808080"


def contact_sheet(paths, colors=(POND, GREY), columns=4, width=480):
    if not paths or columns < 1 or width < 1 or not 1 <= len(colors) <= 2:
        raise ValueError("Supply images, a positive column count and width, and one or two backgrounds.")
    colors = [ImageColor.getrgb(c) for c in colors]
    columns = min(columns, len(paths))
    height = max(1, width * 9 // 16)
    cell = width * len(colors)
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell, rows * (height + 22)), "black")
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(paths):
        x, y = (i % columns) * cell, (i // columns) * (height + 22)
        with Image.open(path) as source:
            sprite = ImageOps.contain(source.convert("RGBA"), (width, height), Image.Resampling.LANCZOS)
        for j, color in enumerate(colors):
            left = x + j * width
            sheet.paste(color, (left, y, left + width, y + height))
            sheet.paste(sprite, (left + (width - sprite.width) // 2, y + (height - sprite.height) // 2),
                        sprite.getchannel("A"))
        draw.text((x + 6, y + height + 4), path.name, fill="white")
    return sheet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("cols", type=int, nargs="?", default=4)
    parser.add_argument("width", type=int, nargs="?", default=480, help="width per background")
    parser.add_argument("--bg", nargs="+", default=[POND, GREY], metavar="COLOR")
    args = parser.parse_args(argv)
    paths = sorted(p for p in args.directory.glob("*.png") if p.resolve() != args.out.resolve())
    try:
        sheet = contact_sheet(paths, args.bg, args.cols, args.width)
    except ValueError as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out, quality=88)


if __name__ == "__main__":
    main()
