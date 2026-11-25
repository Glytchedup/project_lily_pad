"""Generate or edit one PNG through OpenRouter using the pinned Lily Pad prompts."""

import argparse
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import tomllib

from PIL import Image

if __package__:
    from . import orc
else:
    import orc

ART = Path(__file__).resolve().parent


def hex_color(value):
    if not re.fullmatch(r"#?[a-fA-F0-9]{6}", value):
        raise argparse.ArgumentTypeError("expected a six-digit RGB hex colour")
    return "#" + value.lstrip("#")


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("prompt", nargs="?", help="subject line, cues with --animal, or raw edit text")
    parser.add_argument("--ref", type=Path, nargs="*", default=[])
    parser.add_argument("--ar", help="aspect ratio (default 1:1, or 16:9 for scenes)")
    parser.add_argument("--size", choices=("1K", "2K"), default="2K")
    parser.add_argument("--model", default="google/gemini-3-pro-image")
    parser.add_argument("--style-file", type=Path, default=ART / "styles" / "A.txt")
    parser.add_argument("--bg", type=hex_color, default="#FFFFFF")
    parser.add_argument("--animal", help="name for the subject, style reference and pose templates")
    parser.add_argument("--gait", choices=("walk", "hop", "fly"), default="walk")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--raw", action="store_true")
    modes.add_argument("--edit", type=Path, metavar="INPUT.png")
    modes.add_argument("--front", action="store_true")
    modes.add_argument("--sheet", action="store_true")
    modes.add_argument("--scene", choices=("world_plate", "far_shore", "near_water", "storybook"))
    parser.add_argument("--edit-pose", choices=("blink", "step"), help="use a pinned edit instead of typing one")
    args = parser.parse_args(argv)
    if args.edit_pose and (args.prompt is not None or not args.edit):
        parser.error("--edit-pose takes --edit and an omitted positional prompt")
    if args.scene in ("far_shore", "near_water"):
        if args.prompt is not None:
            parser.error("strip templates take no positional prompt")
    elif args.prompt is None and not args.edit_pose:
        parser.error("missing positional prompt")
    if args.scene in ("far_shore", "near_water", "storybook") and not args.ref:
        parser.error("this scene requires --ref")
    if args.scene == "storybook" and not args.animal:
        parser.error("the storybook template requires --animal")
    return args


def compose(args):
    if args.raw or (args.edit and not args.edit_pose):
        return args.prompt
    with (ART / "prompts.toml").open("rb") as source:
        templates = tomllib.load(source)
    fields = dict(animal=args.animal or "subject", cues=args.prompt, mood=args.prompt,
                  habitat=args.prompt, bg=args.bg, step=templates["steps"][args.gait])

    def render(name):
        return templates[name].format(**fields)

    if args.edit_pose:
        return render(args.edit_pose + "_edit")
    parts = [args.style_file.read_text(encoding="utf-8").strip()]
    if args.scene:
        if args.scene == "storybook":
            parts.append(render("style_ref"))
        parts.append(render(args.scene))
    else:
        parts.append(render("subject") if args.animal else args.prompt)
        if args.ref:
            parts.append(render("style_ref"))
        if args.sheet:
            parts.append(render("sheet"))
        parts.append(render("front" if args.front else "side"))
    return " ".join(parts)


def image_part(path):
    with Image.open(path) as image:
        mime = Image.MIME[image.format]
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + orc.b64file(path)}}


def main(argv=None):
    args = arguments(argv)
    prompt = compose(args)
    content = [image_part(args.edit)] if args.edit else []
    content.append({"type": "text", "text": prompt})
    content.extend(image_part(ref) for ref in args.ref)
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    response = orc.chat(
        args.model, [{"role": "user", "content": content}], est=0.15,
        modalities=["image", "text"],
        image_config={"aspect_ratio": args.ar or ("16:9" if args.scene else "1:1"),
                      "image_size": args.size},
        provider={"order": ["google-vertex", "google-ai-studio"], "allow_fallbacks": True},
        _note=out.name,
    )
    images = response["choices"][0]["message"].get("images")
    if not images:
        raise ValueError("OpenRouter returned no image.")
    header, _, payload = images[0]["image_url"]["url"].partition(",")
    if not header.startswith("data:image/") or not header.endswith(";base64"):
        raise ValueError("Expected an inline base64 image.")
    data = base64.b64decode(payload, validate=True)
    with Image.open(BytesIO(data)) as image:
        image.load()
        if image.format != "PNG":
            png = BytesIO()
            image.convert("RGBA").save(png, format="PNG")
            data = png.getvalue()
    cost = (response.get("usage") or {}).get("cost")
    metadata = {"model": args.model, "usage": {"cost": cost},
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
    # Batch resumes by image existence. Install the receipt before exposing the PNG.
    orc.atomic_write(Path(str(out) + ".json"), (json.dumps(metadata, indent=2) + "\n").encode())
    orc.atomic_write(out, data)
    print(f"Wrote {out} | cost {cost}")


if __name__ == "__main__":
    main()
