"""Paid visual review of a packed entry. Run qa_sprite.py with the same root and --out.

Each completed answer is saved immediately. Repeating the command resumes the
same review as long as the encoded frames are unchanged.
"""

import argparse
import base64
from io import BytesIO
from itertools import combinations
from pathlib import Path
import re

from PIL import Image, ImageOps

if __package__:
    from . import orc, qa_sprite as qa
else:
    import orc
    import qa_sprite as qa

MODEL = "google/gemini-3.8-flash"
SYNONYMS = {
    "alligator": ("gator", "crocodilian"), "rabbit": ("bunny", "bunny rabbit"),
    "cow": ("calf",), "pig": ("piglet",), "sheep": ("lamb",), "duck": ("duckling",),
    "trex": ("tyrannosaurus", "tyrannosaurus rex", "dinosaur"),
    "xrayfish": ("fish", "x-ray tetra", "tetra"), "pip": ("frog", "tree frog"),
    "pterodactyl": ("pterosaur",), "velociraptor": ("raptor",),
    "brachiosaurus": ("sauropod",), "whale": ("humpback", "humpback whale"),
}


def _image(frame, size, silhouette=False):
    image = ImageOps.contain(frame, (size, size), Image.Resampling.LANCZOS)
    if silhouette:
        mask = image.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        image = Image.new("RGBA", image.size, "black")
        image.putalpha(mask)
    canvas = Image.new("RGB", (size, size), "white")
    canvas.paste(image, ((size-image.width)//2, (size-image.height)//2), image.getchannel("A"))
    data = BytesIO()
    canvas.save(data, "PNG")
    url = "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": url}}


def _token(s):
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def judge(root, out, name=None):
    with orc._lock(out / "qa.json"):
        return _judge(root, out, name)


def _judge(root, out, name):
    selected = qa.entries(root, name)
    if name is None:
        selected = {k: v for k, v in selected.items() if "frames" in v}
    report = qa.read_report(out)
    passed = True
    for key, entry in sorted(selected.items()):
        paths = qa.frame_paths(root, entry)
        digest = qa.fingerprint(paths)
        item = report["entries"].setdefault(key, {})
        if item.get("fingerprint") != digest:
            item.clear()
            item["fingerprint"] = digest
        result = item.setdefault("judge", {"model": MODEL, "answers": {}})
        result.pop("pass", None)
        answers = result["answers"]
        def ask(test, prompt, images, accepted):
            if test not in answers:
                content = [{"type": "text", "text": prompt}, *images]
                response = orc.chat(MODEL, [{"role": "user", "content": content}], est=.003,
                                    temperature=0, max_tokens=32, _note=f"{key}/{test}")
                answer = response["choices"][0]["message"]["content"].strip()
                answers[test] = {"answer": answer, "pass": _token(answer) in accepted}
                qa.write_report(out, report)

        frames = {}
        for pose, path in paths.items():
            with Image.open(path) as source:
                frames[pose] = source.convert("RGBA")
        animal = key.split("/")[-1]
        names = {_token(s) for s in (animal, *SYNONYMS.get(animal, ()))}
        prompt = "One word: what animal is this?"
        ask("silhouette_120", prompt, [_image(frames["idle"], 120, True)], names)
        sprites = {p: _image(im, 150) for p, im in frames.items()}
        ask("sprite_150", prompt, [sprites["idle"]], names)
        for p, q in combinations(sorted(frames), 2):
            ask(f"same/{p}/{q}", "Are these the same character in two poses? Answer yes or no.",
                [sprites[p], sprites[q]], {"yes"})
        for pose, sprite in sprites.items():
            ask(f"friendly/{pose}", "Any visible teeth, claws or scary expression? Answer yes or no.",
                [sprite], {"no"})
        result["pass"] = all(a["pass"] for a in answers.values())
        passed &= result["pass"]
        qa.write_report(out, report)
    return passed


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path, nargs="?", default=qa.ROOT)
    p.add_argument("--name")
    p.add_argument("--out", type=Path, default=Path("work/qa"))
    args = p.parse_args(argv)
    return 0 if judge(args.root, args.out, args.name) else 1


if __name__ == "__main__":
    raise SystemExit(main())
