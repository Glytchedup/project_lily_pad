import base64
from io import BytesIO
import json

import pytest

pytest.importorskip("PIL")
np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
from PIL import Image, ImageDraw

from tools.art import judge, qa_sprite as qa


def sprite():
    im = Image.new("RGBA", (112, 80))
    ImageDraw.Draw(im).ellipse((10, 10, 101, 69), fill="orange", outline="#281E29", width=5)
    return im


def test_clean_halo_fringe_keyline_and_value():
    clean = sprite()
    def issues(image):
        return qa.measure(image, extension=".png", file_bytes=100, traced_aspect=92/60)["issues"]
    assert issues(clean) == []
    halo = clean.copy()
    ImageDraw.Draw(halo).ellipse((8, 8, 103, 71), outline=(255,255,255,150), width=2)
    assert "halo" in issues(halo)
    stray = clean.copy()
    ImageDraw.Draw(stray).rectangle((2, 3, 4, 6), fill="white")
    assert issues(stray) == ["fringe"]
    pale = clean.copy()
    ImageDraw.Draw(pale).ellipse((10, 10, 101, 69), fill="white")
    assert "keyline" in issues(pale)
    dark = clean.copy()
    ImageDraw.Draw(dark).ellipse((10, 10, 101, 69), fill="#171616")
    assert "value" in issues(dark)
    dark.putpixel((0, 1), (1,2,3,255))
    metrics = qa.measure(dark, file_bytes=700_000, extension=".png", traced_aspect=4)
    assert {"canvas_edge", "file_size", "proportion"} <= set(metrics["issues"])
    assert qa.traced_aspect("giraffe") > 0 and qa.traced_aspect("pig") is None


def manifest(root, name="xrayfish"):
    root.mkdir()
    im = sprite()
    im.save(root / "idle.png")
    im.putpixel((84, 30), (0, 0, 0, 255))
    im.save(root / "blink.png")
    im = sprite()
    im.putpixel((54, 61), (0, 0, 0, 255))
    im.save(root / "step.png")
    (root/"manifest.toml").write_text(
        f'schema=1\n[animals.{name}]\nview="side"\neye_at=[0.75, 0.375]\n'
        'frames={idle="idle.png", blink="blink.png", step="step.png"}\n', encoding="utf-8")


def test_review_writes_board_and_exact_change_counts(tmp_path):
    root, out = tmp_path/"painted", tmp_path/"review"
    manifest(root, "fixture")
    assert qa.review(root, out)
    with Image.open(out/"contact-sheet.png") as im:
        assert im.getpixel((0,0)) == (14,26,44) and im.getpixel((220,0)) == (128,128,128)
    with Image.open(root/"blink.png") as im:
        changed = im.convert("RGBA")
    changed.putpixel((40, 40), (11, 15, 21, 255))
    changed.save(root/"blink.png")
    assert not qa.review(root, out)
    entry = json.loads((out/"qa.json").read_text())["entries"]["fixture"]
    assert entry["identity"]["blink"]["changed_outside"] == 1
    assert entry["identity"]["step"]["changed_outside"] == 0
    mask = Image.new("L", changed.size)
    ImageDraw.Draw(mask).point([(40,40), (84,30)], fill=255)
    mask.save(tmp_path/"mask.png")
    assert qa.review(root, out, "fixture", {"blink":tmp_path/"mask.png"})


def test_paid_judge_uses_blind_images_all_pairs_and_persists_answers(tmp_path, monkeypatch):
    root, out = tmp_path/"painted", tmp_path/"review"
    manifest(root)
    qa.review(root, out)
    calls = []
    def chat(model, messages, est, **kwargs):
        parts = messages[0]["content"]
        prompt = parts[0]["text"]
        assert model == "google/gemini-3.8-flash" and est > 0 and "fish" not in prompt
        for part in parts[1:]:
            with Image.open(BytesIO(base64.b64decode(part["image_url"]["url"].split(",")[1]))) as im:
                if not calls:
                    assert im.size == (120, 120) and len(im.getcolors()) == 2
                else:
                    assert im.size == (150, 150)
        answer = "Fish." if "One word" in prompt else "yes" if "same" in prompt else "no"
        calls.append(prompt)
        return {"choices":[{"message":{"content":answer}}]}
    monkeypatch.setattr(judge.orc, "chat", chat)
    assert judge.judge(root, out)
    assert judge.judge(root, out)
    assert len(calls) == 2 + 3 + 3
    data = json.loads((out/"qa.json").read_text())["entries"]["xrayfish"]
    assert data["judge"]["pass"] and "frames" in data
    # A replacement frame invalidates previous recognition and friendliness results.
    with Image.open(root/"step.png") as im:
        new = im.convert("RGBA")
    new.putpixel((5,5), (255,0,0,255))
    new.save(root/"step.png")
    monkeypatch.setattr(judge.orc, "chat", lambda *a, **kw: {"choices":[{"message":{"content":"yesterday"}}]})
    assert not judge.judge(root, out)
    assert "metrics_pass" not in json.loads((out/"qa.json").read_text())["entries"]["xrayfish"]
