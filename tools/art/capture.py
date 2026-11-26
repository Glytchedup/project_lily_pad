"""Render repeatable engine scenarios and sprite boards in an isolated, headless process.

--art-dir is a runtime asset root (contains painted/manifest.toml).
--world-override expects plate, far_shore and near_water PNGs or WebPs.
Each run at one --size writes into --out. Use separate output directories for comparisons.
"""

import argparse
from functools import lru_cache
import inspect
import math
import os
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
POND = (14, 26, 44)
FPS = 60
SEED = 319
SCENARIOS = ("walk", "hop", "crossing", "peekaboo", "fireworks", "party", "count", "letters", "eyes")


class StaticPond:
    def __init__(self, pygame, folder, size):
        def load(*names):
            for name in names:
                for ext in (".png", ".webp"):
                    path = folder / (name + ext)
                    if path.is_file():
                        return pygame.image.load(path).convert_alpha()
            raise ValueError(f"Missing {names[0]} (.png or .webp) in {folder}")
        w, h = size
        plate = load("plate", "world_plate")
        self.canvas = pygame.transform.smoothscale(plate, size).convert()
        for strip, fraction, baseline in ((load("far_shore", "far-shore", "far"), .30, .62),
                                          (load("near_water", "near-water", "near"), .22, 1.)):
            if strip.get_size() == plate.get_size():
                layer = pygame.transform.smoothscale(strip, size)
                self.canvas.blit(layer, (0, 0))
            else:
                layer = pygame.transform.smoothscale(strip, (w, round(h*fraction)))
                self.canvas.blit(layer, layer.get_rect(bottomleft=(0, round(h*baseline))))

    def draw(self, surface):
        surface.blit(self.canvas, (0, 0))

    def update(self, dt):
        return True

    def __len__(self):
        return 0


def configure_art(cfg, size, world):
    from lilypad.effects import animal_art, animals
    if hasattr(animal_art, "set_art_mode"):
        from lilypad.effects.layout import layout_for
        animal_art.set_art_mode(cfg.effects.animal_art)
        animals.prewarm(size[1], screen_width=size[0], max_sprite_width=cfg.effects.max_sprite_width,
                        layout=layout_for("painted" if world else cfg.scene.world))
    else:  # baseline checkout, before scene bands or the painted route
        animal_art.set_silhouettes(cfg.effects.silhouettes)
        animals.prewarm(size[1])


def pip_source(pygame, path):
    from lilypad.effects import critter
    original = critter.frog_sprite
    raw = pygame.image.load(path).convert_alpha()
    bounds = raw.get_bounding_rect()
    if not bounds.width or not bounds.height:
        raise ValueError("Pip override is empty")
    cut = raw.subsurface(bounds)
    @lru_cache(maxsize=8)
    def scaled(r, pose="idle"):
        height = original(r, "idle").get_bounding_rect().height
        return pygame.transform.smoothscale(cut, (max(1, round(cut.get_width()*height/cut.get_height())), height))
    critter.frog_sprite = scaled


def strip(pygame, name, size, out):
    from lilypad.effects import animal_art, animals
    from lilypad.effects.base import EffectContext
    ctx = EffectContext(size, rng=random.Random(SEED))
    height = animals.animal_effect(ctx, name).height
    poses = ("idle", "blink", "squash", "step")
    def sprite(pose, left):
        if hasattr(animals, "_scene_sprite"):
            return animals._scene_sprite(name, height, pose, left, size[0])
        return animal_art.animal_sprite_facing(name, height, pose, left)
    sprites = [sprite(p, left) for left in (False, True) for p in poses]
    w = max(s.get_width() for s in sprites) + 8
    h = max(s.get_height() for s in sprites) + 26
    board = pygame.Surface((4*w, 2*h))
    board.fill(POND)
    font = pygame.font.Font(None, 21)
    for i, s in enumerate(sprites):
        x, y = (i % 4)*w, (i//4)*h
        board.blit(s, s.get_rect(midbottom=(x+w//2, y+h-23)))
        label = f"{poses[i%4]} / {'left' if i >= 4 else 'right'}"
        board.blit(font.render(label, True, "white"), (x+4, y+h-20))
    folder = out / "strips"
    folder.mkdir(exist_ok=True)
    pygame.image.save(board, folder / (name + ".png"))


def cast_sheet(pygame, names, out):
    from lilypad.effects.animal_art import animal_sprite
    sprites = [animal_sprite(n, 100, "idle") for n in names]
    w = max(s.get_width() for s in sprites) + 12
    board = pygame.Surface((5*w, math.ceil(len(names)/5)*128))
    board.fill(POND)
    font = pygame.font.Font(None, 22)
    for i, (name, sprite) in enumerate(zip(names, sprites)):
        x, y = (i%5)*w, (i//5)*128
        board.blit(sprite, sprite.get_rect(midbottom=(x+w//2, y+102)))
        board.blit(font.render(name, True, "white"), (x+5, y+106))
    pygame.image.save(board, out / "cast.png")


def scene(pygame, surface, cfg, scenario, pond, out):
    from lilypad.effects.engine import EffectEngine
    size = surface.get_size()
    extra = {}
    if "clean_sprites" in inspect.signature(EffectEngine).parameters:
        extra["clean_sprites"] = cfg.effects.clean_sprites
    if hasattr(EffectEngine, "from_config") and pond is None:
        from lilypad.effects.assets import asset_root
        eng = EffectEngine.from_config(size, cfg, rng=random.Random(SEED), lily_seed=SEED,
                                       root=asset_root(kiosk=False))
        if scenario == "fireworks":
            eng.trails = eng._trails_live = True
    else:
        eng = EffectEngine(size, rng=random.Random(SEED), fps=cfg.display.fps,
                           trails=True if scenario == "fireworks" else cfg.effects.trails,
                           max_particles=cfg.effects.max_particles, milestone_every=cfg.effects.milestone_every,
                           sleep_timeout=cfg.display.sleep_timeout, idle_timeout=cfg.display.idle_timeout, **extra)
    try:
        _scene_frames(pygame, surface, eng, scenario, pond, out)
    finally:
        if hasattr(eng, "close"):
            eng.close()


def _scene_frames(pygame, surface, eng, scenario, pond, out):
    from lilypad.effects import animals
    from lilypad.input.mapper import Action
    eng.wake(0.)
    if pond is not None:
        eng.pond = pond
    surface.fill((0, 0, 0))  # the real trail veil reads the previous frame
    presses = {}
    if scenario == "walk":
        eng.effects.append(animals.animal_effect(eng.ctx, "giraffe"))
        captures = {18:"walk-0.3", 102:"walk-1.7", 180:"walk-3.0"}
    elif scenario == "hop":
        rabbit = animals.animal_effect(eng.ctx, "rabbit")
        eng.effects.append(rabbit)
        captures = {math.ceil(2*rabbit.HOP_PERIOD*FPS): "hop-landing"}
    elif scenario in ("crossing", "letters"):
        bear = animals.animal_effect(eng.ctx, "bear")
        fox = animals.animal_effect(eng.ctx, "fox")
        # Select a deterministic opposite-facing spawn using the real factory;
        # it owns mirrored poses as well as entry/exit geometry.
        while bear.going_left == fox.going_left:
            fox = animals.animal_effect(eng.ctx, "fox")
        eng.effects.extend((bear, fox))
        captures = {round(1.45*FPS): "two-crossing"}
        if scenario == "letters":
            presses = {round(.66 * FPS): "C", round(1.28 * FPS): "S"}
            captures = {round(1.21 * FPS): "crossing-letter-C",
                        round(1.84 * FPS): "crossing-letters-CS"}
    elif scenario == "eyes":
        # Three kit variants from ordinary keypresses. At 1080p this seed puts
        # B inside its own blink at tick 170. The gaze pair uses the same pond.
        presses = {1: "C", 131: "B", 261: "S"}
        captures = {38: "eyes-C", 170: "eyes-B-blink", 300: "eyes-S",
                    449: "pip-look-left", 450: "pip-look-right"}
    elif scenario == "peekaboo":
        cow = animals.animal_effect(eng.ctx, "cow")
        eng.effects.append(cow)
        apex = cow.RISE_TIME + cow._JUMPS[0] + cow._JUMP_TIME/2
        captures = {round(apex*FPS): "peekaboo-mid-jump"}
    elif scenario == "fireworks":
        eng.spawn(Action("enter"), 0.)
        captures = {round(1.1*FPS): "fireworks-trails"}
    elif scenario == "party":
        eng.start_party(0.)
        captures = {round(.8*FPS): "party-pip"}
    else:
        eng.spawn(Action("number", key="5", count=5), 0.)
        captures = {round(1.4*FPS): "count-five"}
    for tick in range(1, max(captures)+1):
        if tick in presses:
            letter = presses[tick]
            eng.spawn(Action("letter", key=letter, letter=letter), tick / FPS)
        eng.update(1/FPS, tick/FPS)
        if scenario == "eyes" and tick in (449, 450) and hasattr(eng.frog, "look"):
            eng.frog.look(-1 if tick == 449 else 1, 0)
        eng.draw(surface)
        if getattr(eng, "album", None) is not None:
            eng.album.draw(surface)
        if tick in captures:
            pygame.image.save(surface, out / (captures[tick]+".png"))


def run(args):
    # No lilypad or pygame imports before the selected source and SDL drivers.
    src = args.src.resolve()
    if not (src / "lilypad/__init__.py").is_file():
        raise ValueError(f"No lilypad package in --src {src}")
    sys.path.insert(0, str(src))
    os.environ.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    if args.art_dir:
        if not args.art_dir.is_dir():
            raise ValueError(f"Missing asset root: {args.art_dir}")
        os.environ["LILYPAD_ART_DIR"] = str(args.art_dir.resolve())
    import pygame
    from lilypad import config
    from lilypad.effects import animal_art, critter
    if Path(config.__file__).resolve().parent.parent != src:
        raise RuntimeError("Selected checkout is not the imported runtime")
    path = args.config or src.parent / "config.toml"
    if args.config and not path.is_file():
        raise ValueError(f"Missing config: {path}")
    cfg = config.load(path)
    size = tuple(map(int, args.size.split("x")))
    random.seed(SEED)
    pygame.init()
    try:
        surface = pygame.display.set_mode(size)
        args.out.mkdir(parents=True, exist_ok=True)
        if hasattr(critter, "set_pip_art"):
            from lilypad.effects import glow, letters
            from lilypad.effects.assets import asset_root
            root = asset_root(kiosk=False)
            critter.set_pip_art(cfg.effects.pip_art, root=root)
            if hasattr(letters, "set_letter_art"):
                letters.set_letter_art(cfg.effects.animal_art, root=root)
            if hasattr(letters, "set_eye_art"):
                letters.set_eye_art(cfg.effects.animal_art, root=root)
            if hasattr(glow, "set_fx_style"):
                glow.set_fx_style(cfg.effects.fx_style, root=root)
        if args.pip_override:
            pip_source(pygame, args.pip_override)
        if args.pip or args.all:
            frog = critter.frog_sprite(160)
            white = pygame.Surface(frog.get_size())
            white.fill("white")
            white.blit(frog, (0, 0))
            pygame.image.save(white, args.out / "pip.png")
        scenarios = SCENARIOS if args.all or not (args.scenario or args.pip or args.strip) else args.scenario
        if scenarios or args.strip or args.all:
            configure_art(cfg, size, args.world_override)
        if args.all:
            names = sorted(animal_art.animal_names())
            cast_sheet(pygame, names, args.out)
        else:
            names = args.strip
        for name in names:
            strip(pygame, name, size, args.out)
        pond = StaticPond(pygame, args.world_override, size) if args.world_override else None
        for scenario in scenarios:
            scene(pygame, surface, cfg, scenario, pond, args.out)
    finally:
        pygame.quit()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=ROOT / "src")
    p.add_argument("--config", type=Path)
    p.add_argument("--size", choices=("1920x1080", "1280x720"), default="1920x1080")
    p.add_argument("--art-dir", type=Path)
    p.add_argument("--world-override", type=Path)
    p.add_argument("--pip-override", type=Path)
    p.add_argument("--pip", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--strip", action="append", default=[], metavar="ANIMAL")
    p.add_argument("--scenario", action="append", default=[], choices=SCENARIOS)
    p.add_argument("--out", type=Path, default=Path("work/capture"))
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    argv = sys.argv[1:] if argv is None else argv
    args = p.parse_args(argv)
    if args._worker:
        run(args)
    else:
        env = dict(os.environ, PYTHONHASHSEED="0", PYGAME_HIDE_SUPPORT_PROMPT="1")
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--_worker", *argv], env=env, check=True)


if __name__ == "__main__":
    main()
