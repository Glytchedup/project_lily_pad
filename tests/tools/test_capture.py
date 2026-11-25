import hashlib

import pytest

pytest.importorskip("PIL")
from PIL import Image

from tools.art import capture


def test_full_headless_capture_is_repeatable_with_assets_and_overrides(tmp_path):
    # Solid colour patches are easy to locate after the normal runtime blits.
    art = tmp_path/"assets"
    painted = art/"painted"
    painted.mkdir(parents=True)
    for pose, color in (("idle","#ff00c9"), ("blink","#f300c9"), ("step","#f800c9")):
        im = Image.new("RGBA", (24,40))
        im.paste(color, (3, 5, 20, 37))
        im.save(painted/(pose+".png"))
    (painted/"manifest.toml").write_text(
        'schema=1\n[animals.giraffe]\nview="side"\nnative_height=40\nanchor=[0.5,0.9]\n'
        'eye_at=[0.8,0.2]\nback_at=[0.5,0.3]\nframes={idle="idle.png",blink="blink.png",step="step.png"}\n')
    world = tmp_path/"world"
    world.mkdir()
    for layer, size, color in (("plate",(16,9),"#152334"), ("far_shore",(16,3),"#233415"),
                               ("near_water",(16,2),"#341523")):
        Image.new("RGB", size, color).save(world/(layer+".png"))
    frog = tmp_path/"trial-pip.png"
    Image.new("RGBA",(5,7),"#fcab12").save(frog)
    cfg = tmp_path/"trial.toml"
    cfg.write_text('[effects]\nanimal_art="painted"\ntrails=false\n')
    def run(name):
        out = tmp_path/name
        capture.main(["--all", "--size", "1280x720", "--config", str(cfg), "--art-dir", str(art),
                      "--world-override", str(world), "--pip-override", str(frog), "--out", str(out)])
        return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in out.rglob("*.png")}
    first = run("one")
    assert run("two") == first
    scenes = {"walk-0.3", "walk-1.7", "walk-3.0", "hop-landing", "two-crossing", "peekaboo-mid-jump",
              "fireworks-trails", "party-pip", "count-five"}
    assert all(f"{scene}.png" in first for scene in scenes)
    assert first["walk-0.3.png"] != first["walk-1.7.png"] != first["walk-3.0.png"]
    assert len([key for key in first if key.startswith("strips/")]) == 30
    assert "cast.png" in first and "pip.png" in first
    with Image.open(tmp_path/"one/walk-1.7.png") as im:
        assert im.size == (1280,720)
        assert [im.getpixel((8,y))[:3] for y in (20,350,680)] == [(21,35,52),(35,52,21),(52,21,35)]
        colors = {c[:3] for _,c in im.getcolors(im.width*im.height)}
        assert (255,0,201) in colors and (252,171,18) in colors
    with Image.open(tmp_path/"one/strips/giraffe.png") as im:
        assert im.getpixel((0,0))[:3] == (14,26,44)
        colors = {c[:3] for _,c in im.getcolors(im.width*im.height)}
        assert {(255,0,201), (243,0,201), (248,0,201)} <= colors


def test_src_subprocess_loads_requested_checkout(tmp_path):
    # A distinguishable frog proves the child selected --src over the editable install.
    src = tmp_path/"old"/"src"
    pkg = src/"lilypad"
    effects = pkg/"effects"
    effects.mkdir(parents=True)
    for path in (pkg/"__init__.py", effects/"__init__.py", effects/"animal_art.py"):
        path.touch()
    (pkg/"config.py").write_text("def load(path): return None\n")
    (effects/"critter.py").write_text(
        'import pygame\ndef frog_sprite(r):\n    assert r == 160\n'
        '    s = pygame.Surface((17, 8), pygame.SRCALPHA)\n    s.set_at((2,3), (36,47,59,255))\n    return s\n')
    out = tmp_path/"output"
    capture.main(["--src", str(src), "--pip", "--out", str(out)])
    with Image.open(out/"pip.png") as im:
        assert im.size == (17,8)
        assert im.getpixel((0,0))[:3] == (255,255,255)
        assert im.getpixel((2,3))[:3] == (36,47,59)
