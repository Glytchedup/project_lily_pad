import hashlib
import json
from pathlib import Path
import tomllib

import pytest

pytest.importorskip("PIL")
np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
from PIL import Image, ImageDraw

from tools.art import pack


def panels(folder):
    idle = Image.new("RGBA", (150, 120))
    draw = ImageDraw.Draw(idle)
    draw.ellipse((20, 43, 105, 89), fill="tan", outline="black", width=3)
    draw.rounded_rectangle((80, 14, 127, 76), radius=11, fill="orange", outline="black", width=3)
    draw.rectangle((39, 78, 49, 104), fill="tan")
    draw.ellipse((104, 25, 112, 33), fill="navy")
    blink = idle.copy()
    draw = ImageDraw.Draw(blink)
    draw.ellipse((104, 25, 112, 33), fill="orange")
    draw.line((104, 29, 112, 29), fill="black")
    step = idle.copy()
    ImageDraw.Draw(step).rectangle((15, 96, 49, 108), fill="tan")  # changes the union
    paths = []
    for i, (im, shift) in enumerate(zip((idle, blink, step), ((0, 0), (6, -3), (-4, 7)))):
        shifted = Image.new("RGBA", idle.size)
        shifted.paste(im, shift)
        path = folder / f"panel{i}.png"
        shifted.save(path)
        paths.append(path)
    return paths


@pytest.mark.parametrize("png", [True, False])
def test_pack_registration_landmarks_schema_upsert_and_credits(tmp_path, png):
    files = panels(tmp_path)
    root = tmp_path / "painted"
    root.mkdir()
    manifest = root / "manifest.toml"
    manifest.write_text('# painted manifest\nschema=1\n[animals.zebra]\nother=[1, 2] # keep this note\n')
    source = tmp_path / "sheet.png"
    Image.new("RGBA", (450, 120), "white").save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    Path(str(source) + ".json").write_text(json.dumps(dict(model="fixture/model", date="2026-11-25",
                                                           prompt_sha256="fixture-prompt-sha")))
    entry, shifts = pack.pack("giraffe", files, root=root, gait="walk", source=source, credits=True, png=png)
    assert np.max(np.abs(np.asarray(shifts) - [[0,0], [-6,3], [4,-7]])) <= 1
    assert entry["native_height"] == 367 and entry["view"] == "side"
    assert entry["source_hash"] == "sha256:" + sha and entry["prompt_id"] == "sheet-side-v1"
    assert set(entry["frames"]) == {"idle", "step", "blink"}
    sizes = set()
    for file in entry["frames"].values():
        with Image.open(root / file) as im:
            assert im.format == ("PNG" if png else "WEBP")
            if png:
                assert im.mode == "P" and len(im.getcolors()) <= 256
            sizes.add(im.size)
    assert len(sizes) == 1
    w, h = sizes.pop()
    # Planted eye (108,29); aligned union before scaling is (15,14)..(128,109).
    expected = [(2+(108.5-15)*(w-4)/113)/w, (2+(29.5-14)*(h-4)/95)/h]
    assert np.allclose(entry["eye_at"], expected, atol=.03)
    with Image.open(root / entry["frames"]["idle"]) as im:
        alpha = np.asarray(im.convert("RGBA"))[:,:,3]
        assert entry["anchor"][0] == .5
        assert abs(entry["anchor"][1]*h - np.nonzero(alpha)[0].max()) <= 2
        x, y = entry["back_at"]
        assert .4 <= x <= .6 and abs(y*h - np.nonzero(alpha[:,int(.4*w):int(.6*w)])[0].min()) <= 2
    doc = tomllib.loads(manifest.read_text())
    assert "other=[1, 2] # keep this note" in manifest.read_text()
    assert doc["schema"] == 1 and doc["style"] == "A"
    assert list(doc["animals"]) == ["giraffe", "zebra"]
    assert doc["animals"] == {"giraffe":entry, "zebra":{"other":[1,2]}}
    row = (root / "CREDITS.md").read_text()
    assert all(row.count(f"`{file}`") == 1 for file in entry["frames"].values())
    assert "fixture/model | 2026-11-25 | A | fixture-prompt-sha" in row
    pack.pack("giraffe", files, root=root, gait="walk", source=source, credits=True, png=png, eye=(.3,.2))
    doc = tomllib.loads(manifest.read_text())
    assert doc["animals"]["giraffe"]["eye_at"] == [.3, .2]
    assert doc["animals"]["zebra"] == {"other":[1,2]}
    assert (root / "CREDITS.md").read_text() == row
    from lilypad.effects import painted, assets
    try:
        painted.configure(tmp_path)
        assert painted.has("giraffe") and painted.eye_at("giraffe") == (.3, .2)
        assert painted.build("giraffe", h, "step").get_size() == (w, h)
    finally:
        painted.configure(assets.asset_root(kiosk=True))


def test_single_frame_and_pip_schema_and_width_cap(tmp_path):
    files = panels(tmp_path)
    root = tmp_path / "painted"
    pad = tmp_path / "pad.png"
    Image.new("RGBA", (500, 5), "green").save(pad)
    row, _ = pack.pack("pad", [pad], gait="pad", root=root)
    assert row["file"] == "pip/pad.webp"
    with Image.open(root / row["file"]) as im:
        assert im.width == 1152 and im.height == row["native_height"] < 60
    mini, _ = pack.pack("duck", files[:1], gait="minis", root=root)
    assert mini == {"file":"minis/duck.webp", "native_height":160}
    pip, _ = pack.pack("pip", [files[0], files[1], files[0], files[1]], gait="pip", root=root, eye=(.33,.22))
    doc = tomllib.loads((root/"manifest.toml").read_text())
    assert doc["pip"] == pip and pip["native_height"] == 150 and pip["eye_at"] == [.33,.22]
    assert set(pip["frames"]) == {"idle", "blink", "cheer", "eyes_white"}
    assert doc["minis"]["duck"] == mini and doc["pad"] == row


def test_failed_pack_preserves_previous_manifest_and_frames(tmp_path):
    files = panels(tmp_path)
    root = tmp_path / "painted"
    pack.pack("bear", files, gait="walk", root=root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="eye"):
        pack.pack("bear", [files[0]]*3, gait="walk", root=root)
    assert {p:p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
