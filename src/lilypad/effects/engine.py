"""Effect engine: owns live effects, the frog, the pond scene, trails,
hold-comets, milestones, idle/chaos state, and the frame budget with
graceful degradation."""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict
from functools import partial
from pathlib import Path

import pygame

from ..audio.tracks import BeatClock
from ..config import Config, SceneConfig
from ..input.mapper import Action
from ..lighting.keymap import COLS, ROWS, position
from ..lighting.show import PartyShow, parade_chase
from . import animals, critter, painted
from .album import create_album
from .ambient import AttractMode, CelebrationPulse, ChaosOverlay
from .animals import AnimalCrossing, PeekabooAnimal
from .base import Effect, EffectContext
from .bubbles import BubbleField
from .comet import Comet
from .critter import Frog
from .ecosystem import AnimalView, Director
from .letters import GiantLetter
from .layout import CLASSIC, layout_for
from .lily import load_lily
from .numbers import CountAlong
from .parade import GrandParade
from .particles import Balloons, Fireworks, ParticleSystem, Rings, SpiralBurst, burst, shaped_burst
from .reflection import ReflectionCache
from .registry import celebration, effects_for
from .scenery import PondBackground
from .storybook import Storybook

BACKGROUND = (6, 8, 12)  # near-black; pure black feels "off", this glows

TRAIL_ALPHA = 80         # veil strength; lower = longer comet tails
GHOSTBUST_EVERY = 4      # frames between SUB/MAX anti-ghost passes (see draw)
TRAILS_OFF_BELOW = 0.4   # degradation ladder sheds trails below this scale...
TRAILS_ON_ABOVE = 0.6    # ...and restores them above this one (hysteresis)
log = logging.getLogger(__name__)

CELEBRATION_COOLDOWN = 10.0  # s between milestone parties (mash-proofing)
PARTY_PULSE = 4.0        # s of rainbow border when a reward track is earned
MAX_ANIMALS = 5          # concurrent creatures; see the note in spawn()
ANIMAL_TYPES = (PeekabooAnimal, AnimalCrossing)
#: Concurrent giant letters / count-alongs. Each one is screen-sized, so a
#: two-handed run along the keyboard used to stack a dozen of them into an
#: unreadable pile — the opposite of "this key made THAT happen". Over the cap
#: the OLDEST glyph is retired into its fade rather than the newest dropped:
#: every key must still visibly do something, and the thing it does has to be
#: the thing you can see.
MAX_GLYPHS = 6
GLYPH_TYPES = (GiantLetter, CountAlong)
RIPPLE_COLOR = (150, 200, 255)
ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Action kinds that represent an actual keypress (milestone counting) —
# synthetic companions (chord, mash_*, hold_*) ride along with a base press.
_PRESS_KINDS = {"letter", "number", "space", "enter", "special", "sparkle", "arrow"}

# Each row names its destination and its painters in back-to-front order.
# New layers (for example reflections before flyers) belong in this table.
_CLEAN_PASSES = (
    ("scene", ("pond",)),
    ("fx", ("backdrop", "particles", "comets", "bubbles", "rings", "attract")),
    ("screen", ("present",)),
    ("screen", ("reflections", "lily", "flyers", "ground", "swimmers", "lip",
                "frog", "peekaboo", "glyphs", "parade", "rider")),
    ("screen", ("pulses", "chaos")),
)
_CROSSING_LAYERS = {"fly": "flyers", "swim": "swimmers"}
_EFFECT_LAYERS = (
    (PeekabooAnimal, "peekaboo"), (GLYPH_TYPES, "glyphs"), (CelebrationPulse, "pulses"),
    (Comet, "comets"), (BubbleField, "bubbles"), (Rings, "rings"),
)


def _layer(effect: Effect) -> str:
    if isinstance(effect, AnimalCrossing):
        return _CROSSING_LAYERS.get(effect.gait, "ground")
    for types, layer in _EFFECT_LAYERS:
        if isinstance(effect, types):
            return layer
    return "particles"


def _gaze_position(effect):
    if isinstance(effect, AnimalCrossing):
        return effect.x, effect.y if effect.airborne else effect.y - effect.height / 2
    if isinstance(effect, PeekabooAnimal):
        return effect.x, effect.y - effect.jump + effect.height / 2
    if isinstance(effect, Comet):
        return effect.x, effect.y
    if isinstance(effect, CountAlong):
        return effect.digit.pos
    if isinstance(effect, Fireworks):
        rocket = next((r for r in effect.rockets if not r.exploded), None)
        if rocket is not None:
            return rocket.x, rocket.y
        return effect.bursts[-1].origin if effect.bursts else None
    elif isinstance(effect, ParticleSystem):
        points = effect.particles
    elif isinstance(effect, BubbleField):
        points = effect.bubbles
    elif isinstance(effect, Balloons):
        points = effect.parts
    elif isinstance(effect, SpiralBurst):
        points = effect.sys.particles
    else:
        return getattr(effect, "pos", None)
    if points:
        return points[0].x, points[0].y
    return None


def _foot_margin(row: dict, idle: pygame.Surface) -> int:
    """Pixels below the registered foot. Old manifests put 1.0 at the canvas edge."""
    h = idle.get_height()
    anchor = row.get("anchor")
    y = anchor[1] if isinstance(anchor, (list, tuple)) and len(anchor) == 2 else 1
    if not isinstance(y, (float, int)) or not 0 <= y <= 1:
        y = 1
    if y == 1:
        return h - idle.get_bounding_rect().bottom
    # pack.py stores the last visible pixel, whereas Rect.bottom is exclusive.
    return max(0, h - 1 - round(y * h))


class EffectEngine:
    @classmethod
    def from_config(cls, size, cfg: Config, *, root, rng=None, lily_seed=None):
        """Use the same scene and feature switches in the app, benchmark and captures."""
        fx = cfg.effects
        return cls(size, rng=rng, root=root, lily_seed=lily_seed, scene=cfg.scene,
                   max_particles=fx.max_particles, trails=fx.trails, clean_sprites=fx.clean_sprites,
                   milestone_every=fx.milestone_every, fps=cfg.display.fps,
                   idle_timeout=cfg.display.idle_timeout, sleep_timeout=cfg.display.sleep_timeout,
                   mirror_animals=cfg.lighting.mirror_animals, ecosystem=fx.ecosystem,
                   storybook=fx.storybook, parade=fx.parade, album=fx.album,
                   party_show=cfg.music.party_show)

    def __init__(self, size: tuple[int, int], max_particles: int = 900,
                 idle_timeout: float = 60.0, fps: int = 60,
                 rng: random.Random | None = None,
                 trails: bool = True, milestone_every: int = 50,
                 sleep_timeout: float = 300.0, clean_sprites: bool = False,
                 *, scene: SceneConfig | None = None, root: Path | None = None,
                 lily_seed: int | None = None, mirror_animals: bool = False,
                 ecosystem: bool = False, storybook: str = "off", parade: bool = False,
                 party_show: bool = False, album: bool = False) -> None:
        self.size = size
        self.max_particles = max_particles
        self.idle_timeout = idle_timeout
        self.sleep_timeout = sleep_timeout
        self.asleep = False
        self.frame_budget = 1.0 / max(1, fps)
        self.ctx = EffectContext(size=size, rng=rng or random.Random())
        self.effects: list[Effect] = []
        self.frog = Frog(size)
        if critter.painted_pip_active():
            # The pad and physics already have their waterline. Register Pip's
            # draw origin against that line after his display-size poses load.
            self.frog._feet += _foot_margin(critter._manifest()["pip"],
                                            critter.frog_sprite(self.frog.r))
        self.pond = PondBackground(self.ctx, scene, root=root)
        self.painted = self.pond.painted
        self.layout = layout_for(scene.world) if scene else CLASSIC
        self.lily = None
        if self.painted and scene.lily:
            self.lily = load_lily(root, size, self.layout, move_seconds=scene.lily_move_seconds,
                                 seed=time.time_ns() if lily_seed is None else lily_seed)
            if self.lily is not None:
                self._register_lily_feet()
        self.beat_clock = None
        self.director = Director(self.ctx) if ecosystem else None
        self.storybook = Storybook(size, storybook, pond=self.pond, root=root) if storybook != "off" else None
        self.album = create_album(album, size, root)
        if self.album is not None:
            self.album.prewarm(animals.animal_names())
        self.on_animal = None
        self.parade_enabled = parade
        self.parade = self.trio = None
        self._parade_boarded = False
        self._parade_finale = False
        self._moon_glow = None
        self._rider_sprite = None
        self.party_show_enabled = party_show
        self.show = None
        self._free_clock = None
        self._party_elapsed = 0.0
        self._last_drop = self._last_trio_bar = -1
        self.reflections = ReflectionCache(bool(self.painted and scene.reflections))
        self._foot_margins = {}
        if scene is not None:
            self._prepare_cast()
        self.mirror_animals = mirror_animals
        self.blooms = []
        self.praise = None
        self.trails = trails
        self.clean_sprites = clean_sprites
        self._fx: pygame.Surface | None = None
        self.milestone_every = milestone_every
        self.chaos: ChaosOverlay | None = None
        self.party = False       # reward dance party (see start_party)
        self.attract: AttractMode | None = None
        self.comets: dict[str, Comet] = {}
        self.press_count = 0
        self.letters_seen: set[str] = set()
        self.last_action_time = time.monotonic()
        self._scene = pygame.Surface(size)
        try:
            self._scene = self._scene.convert()  # match display pixel format
        except pygame.error:
            pass  # no display (bare unit tests); purely a blit-speed nicety
        self._celebration_pending = False
        self._last_celebration = float("-inf")
        self._trails_live = trails
        self._frame_no = 0
        self._frame_ema = self.frame_budget
        self._chaos_spawn_accum = 0.0

    def _register_lily_feet(self) -> None:
        # A flush canvas anchor on an older Lily pack means "use idle alpha".
        # Each spot already holds the final display-size surfaces and origins.
        for spot in self.lily.spots:
            idle, (_, top) = spot.poses[spot.base]
            if top + idle.get_height() != spot.feet:
                continue
            margin = _foot_margin({}, idle) / idle.get_height()
            if margin:
                for pose, (art, (x, y)) in spot.poses.items():
                    spot.poses[pose] = art, (x, y + round(margin * art.get_height()))

    def _prepare_cast(self) -> None:
        """Measure idle feet and prepare reflection poses at actual spawn sizes."""
        for name in animals.animal_names():
            peek = name in animals.PEEKABOO_CAST
            gait = "peekaboo" if peek else animals.GAITS.get(name, "walk")
            if gait not in ("walk", "hop", "peekaboo"):
                continue
            painted_cast = animals.resolved_mode(name) == "painted"
            if not painted_cast and not self.reflections.enabled:
                continue
            height = animals._sprite_height(name, self.size, gait)
            width = self.size[0]
            if painted_cast:
                idle = animals._scene_sprite(name, height, "idle", False, width)
                self._foot_margins[name] = _foot_margin(painted._rows()[name], idle)
            if self.reflections.enabled and not peek:
                self.reflections.prewarm(
                    ((name, pose, left), animals._scene_sprite(name, height, pose, left, width))
                    for pose in ("idle", "step") for left in (False, True)
                )

    def tracked(self):
        """Keyboard patches follow the centre and width of each crossing canvas."""
        w, h = self.size
        for e in self.effects:
            if isinstance(e, AnimalCrossing):
                y = e.y if e.airborne else e.y + self._foot_margins.get(e.name, 0) - e.height / 2
                yield e, e.name, e.x / w, y / h, e._sprite_w / w

    def attract_key(self, key: str) -> None:
        if self.painted:
            row, col = position(key)
            self.pond.attract((col + 0.5) * self.ctx.width / COLS,
                              (row + 0.5) * self.ctx.height / ROWS)

    # ------------------------------------------------------------------ input

    def wake(self, now: float | None = None) -> bool:
        """Any key touches this: reset the idle clock and end sleep.

        Called from the raw event loop rather than from ``spawn`` alone,
        because keys that produce no Action still mean somebody is there —
        holding the parent escape combo in front of a black screen should
        light it back up, not look broken.

        Returns whether the screen had actually been asleep.
        """
        self.last_action_time = time.monotonic() if now is None else now
        was_asleep, self.asleep = self.asleep, False
        if was_asleep:
            if self.lily:
                self.lily.wake()
            log.info("screen woken by a keypress")
        return was_asleep

    def spawn(self, action: Action, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.wake(now)
        if self.attract is not None:      # any key kills attract mode instantly
            self.attract = None

        if action.kind in _PRESS_KINDS:
            self._note_press(action, now)
        elif action.kind == "chord" and self.storybook is not None:
            self.storybook.press(None, now, party_active=self.party)

        if action.kind == "arrow":
            self.frog.shove(action.direction)
            self.effects.append(burst(
                self.ctx, (self.frog.x, self.frog.y), count=18, speed=220, life=0.6,
            ))
            return
        if action.kind == "mash_start":
            if self.chaos is None:
                self.chaos = ChaosOverlay(self.ctx)
            else:
                self.chaos.ending = False
            return
        if action.kind == "mash_end":
            if self.chaos is not None:
                self.chaos.stop()
            return
        if action.kind == "hold_start":
            # A held key becomes a wandering rainbow comet until release.
            old = self.comets.pop(action.key, None)
            if old is not None:
                old.release()
            comet = Comet(self.ctx)
            self.comets[action.key] = comet
            self.effects.append(comet)
            return
        if action.kind == "hold_end":
            comet = self.comets.pop(action.key, None)
            if comet is not None:
                comet.release()
            return

        if self.particle_count() < self.max_particles * 1.5:
            spawned = effects_for(self.ctx, action, self.layout)
            self._cap_glyphs(spawned)
            if self.animal_count() >= MAX_ANIMALS:
                # Every letter has its own creature now, so a two-handed run
                # along the keyboard used to put a dozen big sprites on screen
                # at once. Each one is a full-height alpha blit every frame —
                # cheap here, several times dearer on the Pi's software path —
                # and a dozen animals is visual noise to a 2-year-old anyway.
                # The letter and its burst still fire: only the surplus animal
                # is dropped, so the key still visibly does something.
                spawned = [e for e in spawned if not isinstance(e, ANIMAL_TYPES)]
            for effect in spawned:
                if isinstance(effect, ANIMAL_TYPES):
                    if self.album is not None:
                        self.album.note_animal(effect.name, (effect.x, effect.y))
                    if self.on_animal is not None:
                        self.on_animal(effect.name, now)
                    if self.lily:
                        self.lily.on_animal_start()
                    if isinstance(effect, PeekabooAnimal) and effect.name in self._foot_margins:
                        # The painted farm portraits end in a straight cut. Keep
                        # a quarter below the edge at rest so the 22% jump and
                        # 2.2% bob can never expose the bottom of the painting.
                        effect._y_rest = (self.ctx.height - 0.75 * effect.height
                                          + self._foot_margins[effect.name])
            if self.painted and action.kind == "special" and action.letter == "dino":
                # The shockwave still fires when all crossing slots are occupied.
                self.pond.shake(6, 0.35)
            self.effects.extend(spawned)
        else:
            # The product invariant is that EVERY key visibly does something.
            # Sustained fast play can saturate the budget with ordinary
            # spawns (measured 28% silently-dead space presses at 6/s), so
            # when the full effect is too expensive, spawn a small burst
            # that always fits instead of nothing.
            self.effects.append(burst(self.ctx, self.ctx.random_pos(),
                                      count=14, speed=280, size=5, life=0.6))

    def _cap_glyphs(self, incoming: list[Effect]) -> None:
        """Retire the oldest glyphs so at most MAX_GLYPHS are on screen."""
        new = sum(1 for e in incoming if isinstance(e, GLYPH_TYPES))
        if not new:
            return
        live = [e for e in self.effects
                if isinstance(e, GLYPH_TYPES) and not self._retired(e)]
        for glyph in live[:max(0, len(live) + new - MAX_GLYPHS)]:
            glyph.retire()

    @staticmethod
    def _retired(glyph) -> bool:
        return glyph.age >= glyph.total - glyph.FADE_TIME

    def glyph_count(self) -> int:
        return sum(1 for e in self.effects if isinstance(e, GLYPH_TYPES))

    # ------------------------------------------------------- reward party

    def start_party(self, now: float | None = None, beat_clock=None) -> None:
        """The reward track has been earned: fireworks, then Pip dances.

        Driven by the audio engine's meter (it owns the music, so it owns
        when the music is due). Deliberately bypasses the celebration
        cooldown and the particle-budget gate — this one is *earned*, and a
        busy screen is not a reason to withhold it.
        """
        now = time.monotonic() if now is None else now
        self.party = True
        self._party_elapsed = 0.0
        self._last_drop = self._last_trio_bar = -1
        if self.party_show_enabled:
            self._free_clock = BeatClock()
            self.show = PartyShow()
        if self.storybook is not None:
            self.storybook.clear()
            self.storybook.press(None, now)
        self.wake(now)
        self.attract = None
        self._last_celebration = now
        self.effects.extend(celebration(self.ctx, big=True))
        if not self.painted:
            self.effects.append(CelebrationPulse(self.ctx, duration=PARTY_PULSE))
        self.set_party_clock(beat_clock)
        self._celebration_pending = True

    def end_party(self, now: float) -> None:
        """The track finished. Restart the idle clocks from *here*.

        Nobody presses a key while watching the frog dance, so
        ``last_action_time`` is still sitting at the moment the party began.
        Without this the attract animation fires the same frame the music
        stops — and on a five-minute track the screen goes straight to black,
        turning a celebration into a blackout.
        """
        self.party = False
        self.last_action_time = now
        self.show = self.trio = self._free_clock = None
        self.set_party_clock(None)

    def set_party_clock(self, clock) -> None:
        self.beat_clock = clock or self._free_clock
        if self.show is not None:
            self.show.beat_clock = self.beat_clock
            self._last_drop = self._last_trio_bar = -1
        self.frog.dance(self.party, beat_clock=self.beat_clock)
        if self.lily:
            self.lily.set_party(self.party, self.beat_clock)

    def _note_press(self, action: Action, now: float) -> None:
        """Milestone bookkeeping: every Nth press parties, and completing the
        alphabet parties harder (VISUAL_REVIEW.md #10)."""
        self.press_count += 1
        if self.storybook is not None:
            key = action.letter if action.kind == "letter" and not self.party else None
            self.storybook.press(key, now, party_active=self.party)
        if action.kind == "letter" and action.letter in ALPHABET:
            self.letters_seen.add(action.letter)
            if self.letters_seen >= ALPHABET:
                # Clear ONLY if the party actually fires — an earlier version
                # cleared unconditionally, and a cooldown-suppressed party
                # silently destroyed the child's 26-letter progress (97% of
                # completions were eaten at mash speeds).
                if self._celebrate(big=True, now=now):
                    self.letters_seen.clear()
                return
        if self.milestone_every and self.press_count % self.milestone_every == 0:
            self._celebrate(big=False, now=now)

    def _celebrate(self, big: bool, now: float) -> bool:
        """Fire a party; returns whether it actually fired.

        Ordinary milestones respect a cooldown (under a mash storm the
        50-press milestone recurs every ~2 s, which made the mega-party the
        steady state) and the particle-budget gate. The alphabet party is a
        once-per-alphabet earned reward, so it bypasses both.
        """
        if not big:
            if self.party:
                # The dance party already IS the celebration; stacking a
                # milestone party on top of it is just noise.
                return False
            if now - self._last_celebration < CELEBRATION_COOLDOWN:
                return False
            if self.particle_count() >= self.max_particles * 1.5:
                # Screen saturated: skip, and do NOT arm the cooldown — the
                # next affordable milestone should party at full strength.
                return False
        self._last_celebration = now
        if big and self.parade_enabled:
            parade = GrandParade.create(self.ctx, layout=self.layout, frog=self.frog,
                                        on_finish=self._finish_parade)
            if parade is not None:
                self.trio = None
                self.parade = parade
                self._parade_boarded = False
                self.frog.cancel_ride()
                self._moon_glow = self._parade_moon()
                # The procession is on the far bank. Match J22's rider scale
                # and register the visible soles directly on the moving head.
                rider = critter.frog_sprite(self.frog.r, "cheer")
                height = max(1, round(self.ctx.height * .095))
                rider = pygame.transform.smoothscale_by(rider, height / rider.get_height())
                self._rider_sprite = rider.subsurface(rider.get_bounding_rect())
                if self.lily:
                    self.lily.cheer(parade.duration)
                self.praise = "alphabet_complete"
                return True
        self.effects.extend(celebration(self.ctx, big=big))
        if not self.painted:
            self.effects.append(CelebrationPulse(self.ctx, duration=2.5))
        self.frog.celebrate()
        if self.lily:
            self.lily.cheer(2.5)
        self.praise = "alphabet_complete" if big else "lily_great"
        self._celebration_pending = True
        return True

    def _parade_moon(self):
        # Plates have different moon positions. Locate the brightest patch of
        # sky once when the parade starts, without scanning display-size pixels.
        if self.painted:
            plate = self.pond._painted.current.plate
            sky = plate.subsurface((0, 0, plate.get_width(), max(1, plate.get_height() // 2)))
            sample = pygame.transform.smoothscale(sky, (48, 16))
            x, y = max(((x, y) for y in range(16) for x in range(48)),
                       key=lambda xy: sum(sample.get_at(xy)[:3]))
            center = (round((x + .5) * sky.get_width() / 48),
                      round((y + .5) * sky.get_height() / 16))
        else:
            plate = self.pond._variants[self.pond._index]
            center = self.pond._sky["moon"][:2]
        radius = max(8, round(self.ctx.height * .09))
        rect = pygame.Rect(0, 0, 2 * radius, 2 * radius)
        rect.center = center
        rect = rect.clip(plate.get_rect())
        # Add back only the already-bright paint, preserving the crescent's
        # exact outline and keeping the surrounding night sky dark.
        glow = plate.subsurface(rect).copy()
        glow.fill((60, 60, 60), special_flags=pygame.BLEND_RGB_SUB)
        glow.fill((130, 130, 120), special_flags=pygame.BLEND_RGB_MULT)
        return id(plate), glow, rect

    def _finish_parade(self):
        self._parade_finale = True

    def _draw_rider(self, screen):
        anchor = self.parade.pip_anchor()
        if anchor is not None:
            screen.blit(self._rider_sprite, self._rider_sprite.get_rect(midbottom=anchor))

    def _riding_in_parade(self):
        return self.parade is not None and self.frog._anchor == self.parade.pip_anchor

    def lighting_frame(self):
        """Choreography below the normal key flashes, ripples and animal coats."""
        procession = self.parade or self.trio
        lead = procession.lead_x_frac() if procession is not None else None
        if self.show is not None:
            if self.beat_clock.is_drop:
                lead = None  # a drop lights even a keyboard following a trio
            return self.show.frame(self._party_elapsed, lead_x_frac=lead)
        if self.parade is not None:
            t = self.parade.age
            return parade_chase(t, (2 * t) % 1, int(t / 2), False, x_frac=lead)
        return None

    def consume_celebration(self) -> bool:
        """Main loop polls this to fire the celebration audio cue."""
        pending, self._celebration_pending = self._celebration_pending, False
        return pending

    # ------------------------------------------------------------------ frame

    def animal_count(self) -> int:
        return (3 if self.trio is not None else 0) + sum(
            1 for e in self.effects if isinstance(e, ANIMAL_TYPES))

    def particle_count(self) -> int:
        # The engine-owned mash overlay deliberately does NOT count here:
        # taxing the budget with its (real) draw cost starved mash mode of
        # the very bursts that make it fun — measured 72% fewer at default
        # config, and zero below max_particles=250. Its cost is handled by
        # the degradation ladder instead (particle scale + trail shedding).
        # CelebrationPulse instances live in self.effects and do count.
        return (sum(len(e) for e in self.effects if hasattr(e, "__len__"))
                + len(self.pond))

    def _fall_asleep(self) -> None:
        """Drop everything and go dark.

        Attract mode is lovely for a minute and wrong at bedtime: after
        ``sleep_timeout`` with nobody in the room the screen should be black,
        the music should stop (which follows from clearing ``attract``) and the
        keyboard lights should go out. Live effects are dropped rather than
        left to finish so a sleeping app costs almost nothing.
        """
        if self.asleep:
            return
        # A black screen is indistinguishable from a crashed app from the
        # outside. Say so in the journal, so a parent who SSHes in wondering
        # why the playground is dark gets the answer in one line.
        log.info("screen asleep after %.0fs with no keypresses — any key wakes it",
                 self.sleep_timeout)
        self.asleep = True
        if self.storybook is not None:
            self.storybook.clear()
            self.storybook.press(None, self.last_action_time)
        self.parade = self.trio = self._moon_glow = self._rider_sprite = None
        if self.lily:
            self.lily.sleep()
        self.blooms.clear()
        self._fx = None  # waking begins with the current pond, free of old trails
        self.attract = None
        self.chaos = None
        self.effects.clear()
        self.comets.clear()

    def close(self):
        if self.storybook is not None:
            self.storybook.close()

    def _update_show(self, dt):
        self._party_elapsed += dt
        clock = self.beat_clock
        if clock is self._free_clock:
            clock.advance(dt)
        if clock.is_drop and clock.beat_index > self._last_drop:
            self._last_drop = clock.beat_index
            self.effects.append(shaped_burst(self.ctx, self.ctx.random_pos(.25), "star"))
        bar = clock.bar
        if bar > 0 and bar % 8 == 0 and bar > self._last_trio_bar:
            self._last_trio_bar = bar
            if self.parade is None and self.animal_count() <= MAX_ANIMALS - 3:
                # J22 indexes trios by groups of eight bars. Randomize the
                # group on each eligible downbeat, keeping its three gaits.
                group = self.ctx.rng.randrange(1, 27)
                self.trio = GrandParade.create(self.ctx, layout=self.layout, party_bar=group * 8)

    def _encounters(self, dt):
        live = {id(e): e for e in self.effects if isinstance(e, AnimalCrossing)}
        views = (AnimalView.from_crossing(a) for a in live.values())
        for intent in self.director.tick(dt, views, self.frog):
            animal = live[intent.animal_id]
            if intent.kind == "greet":
                for partner in (animal, live[intent.other_id]):
                    partner.pause(AnimalCrossing.GREET_DURATION)
                    partner.greet_bounce()
            elif intent.kind == "pip_duck":
                self.frog.duck((animal.width + 2 * self.frog.r) / animal.speed)
            elif intent.kind == "pip_jump":
                self.frog.jump_over()
            elif intent.kind == "pip_wave":
                self.frog.wave()
            elif intent.kind == "pip_ride":
                def anchor(a=animal):
                    if a in self.effects:
                        return a.back_anchor(ground_margin=self._foot_margins.get(a.name))
                    return None
                direction = -1 if animal.going_left else 1
                to_middle = (self.ctx.width / 2 - animal.x) * direction / animal.speed
                self.frog.ride(anchor, self.frog.age + max(.6, to_middle))
        for effect in reversed(self.effects):
            pos = _gaze_position(effect)
            if pos is not None:
                self.frog.look_at(*pos)
                break

    def update(self, dt: float, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        # A dance party keeps the room awake: nobody presses a key while
        # watching the frog dance, and a 3-minute track is far longer than
        # either the attract or the sleep timeout.
        if (self.sleep_timeout > 0 and not self.party
                and now - self.last_action_time >= self.sleep_timeout):
            self._fall_asleep()
            return
        self.pond.update(dt)
        if self.show is not None:
            self._update_show(dt)
        # Filter expired crossings before the Director or a mount samples
        # them. The original update order remains intact in classic mode.
        encounters = self.director is not None and self.ctx.scale >= .5
        if encounters:
            self.effects = [e for e in self.effects if not isinstance(e, AnimalCrossing) or e.update(dt)]
            self._encounters(dt)
        if self.trio is not None and not self.trio.update(dt):
            self.trio = None
        if self.parade is not None:
            if not self.parade.update(dt):
                self.parade = self._moon_glow = self._rider_sprite = None
            elif not self._parade_boarded:
                anchor = self.parade.pip_anchor()
                if anchor is not None and self.frog.r <= anchor[0] <= self.ctx.width - self.frog.r:
                    self.frog.cancel_ride()
                    self.frog.ride(self.parade.pip_anchor, self.frog.age + 8.)
                    self._parade_boarded = True
        if self.lily:
            self.lily.update(dt)
        self.frog.update(dt)
        # Frog splash-down → water ripples where he lands on his pad. Asks the
        # frog where its floor is rather than assuming the bottom of the screen:
        # he now rests high enough for the lily pad under him to be visible.
        if self.frog.just_bounced and self.frog.y >= self.frog.floor_y - 1:
            self.effects.append(Rings(
                self.ctx, (self.frog.x, self.frog.y + self.frog.r * 0.8),
                color=RIPPLE_COLOR, count=2, life=0.6,
                max_r=self.frog.r * 4.0,
            ))
        # Frog pops any bubble he touches.
        splashes: list[tuple[float, float]] = []
        for e in self.effects:
            if isinstance(e, BubbleField):
                for (x, y, _color) in e.pop_near(
                        (self.frog.x, self.frog.y), self.frog.r * 1.2):
                    splashes.append((x, y))
        for pos in splashes:
            self.effects.append(burst(self.ctx, pos, count=8, speed=160,
                                      size=4, life=0.5))

        if self.mirror_animals:
            rockets = [r for effect in self.effects if isinstance(effect, Fireworks)
                       for r in effect.rockets if not r.exploded]
        self.effects = [e for e in self.effects
                        if (encounters and isinstance(e, AnimalCrossing)) or e.update(dt)]
        if self._parade_finale:
            self._parade_finale = False
            self.effects.append(shaped_burst(self.ctx, (self.ctx.width / 2, self.ctx.height * .35),
                                             "heart", count=110, spread=300))
            self._celebration_pending = True
        if self.mirror_animals:
            self.blooms = [(r.x / self.ctx.width, r.y / self.ctx.height, r.color)
                           for r in rockets if r.exploded]
        # Drop bookkeeping for comets that finished dying on their own.
        if self.comets:
            live = set(id(e) for e in self.effects)
            self.comets = {k: c for k, c in self.comets.items() if id(c) in live}

        if self.chaos is not None:
            if not self.chaos.update(dt):
                self.chaos = None
            else:
                # Chaos mode keeps popping random bursts on its own.
                self._chaos_spawn_accum += dt
                if self._chaos_spawn_accum >= 0.15 and not self.chaos.ending:
                    self._chaos_spawn_accum = 0.0
                    if self.particle_count() < self.max_particles:
                        self.effects.append(burst(
                            self.ctx, self.ctx.random_pos(0.05),
                            count=35, speed=380,
                        ))

        # A held key emits exactly one action (hold_start), so a live comet
        # means the child is actively pressing — that's not "idle" even
        # though no new actions arrive.
        if (self.attract is None and self.chaos is None and not self.comets
                and not self.party and self.parade is None
                and now - self.last_action_time >= self.idle_timeout):
            self.attract = AttractMode(self.ctx)
        if self.attract is not None:
            self.attract.update(dt)
        if self.storybook is not None:
            self.storybook.update(dt, party_active=self.party, attract_active=self.attract is not None)
        if self.album is not None:
            self.album.set_attract(self.attract is not None)
            self.album.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        if self.asleep:
            # Pure black, not the pond's near-black: the point is a dark room.
            surface.fill((0, 0, 0))
            return
        # The pond composites onto a scratch surface; blitting it translucent
        # instead of opaque is what leaves motion trails (VISUAL_REVIEW.md #4):
        # last frame's lights linger and fade INTO the scene over ~10 frames.
        self._frame_no += 1
        # The veil is a fixed cost the particle ladder can't shrink, so the
        # ladder sheds it directly: trails drop out when degradation is deep
        # and come back once the frame budget recovers (with hysteresis).
        if self.trails:
            if self._trails_live and self.ctx.scale <= TRAILS_OFF_BELOW:
                self._trails_live = False
            elif not self._trails_live and self.ctx.scale >= TRAILS_ON_ABOVE:
                self._trails_live = True
        # Trails also pause while the mash chaos overlay is live: the veil
        # re-blends the full-screen hue wash every frame, compounding it into
        # a solid saturated screen that swallows the pond and every effect.
        trails_live = self.trails and self._trails_live
        if self.painted or (self.clean_sprites and trails_live):
            self._draw_clean(surface, trails_live)
            return

        self._fx = None
        self.pond.draw(self._scene)
        self._draw_pond_extras(self._scene)
        if trails_live and self.chaos is None:
            self._draw_veil(surface)
        else:
            self._draw_opaque_scene(surface)
        if self.attract is not None:
            self.attract.draw(surface)
        # Full-screen pulses draw above the frog, same depth as the mash
        # overlay they subclass — a border that vanishes behind the frog at
        # one call site and covers him at the other reads as a glitch.
        pulses = []
        for effect in self.effects:
            if isinstance(effect, CelebrationPulse):
                pulses.append(effect)
            elif (isinstance(effect, AnimalCrossing) and not effect.airborne
                  and effect.name in self._foot_margins):
                self._draw_ground(effect, surface)
            else:
                effect.draw(surface)
        rider = self._riding_in_parade()
        (self.frog.pad.draw if rider else self.frog.draw)(surface)
        if procession := self.parade or self.trio:
            procession.draw(surface)
        if rider:
            self._draw_rider(surface)
        for pulse in pulses:
            pulse.draw(surface)
        if self.chaos is not None:
            self.chaos.draw(surface)

    def _draw_opaque_scene(self, surface: pygame.Surface) -> None:
        self._scene.set_alpha(None)
        surface.blit(self._scene, (0, 0))

    def _draw_veil(self, surface: pygame.Surface) -> None:
        self._scene.set_alpha(TRAIL_ALPHA)
        surface.blit(self._scene, (0, 0))
        # Integer alpha blending stalls a few levels away from the scene.
        # Subtract to break that floor, then snap dim pixels back to the pond.
        if self._frame_no % GHOSTBUST_EVERY == 0:
            surface.fill((9, 9, 9), special_flags=pygame.BLEND_RGB_SUB)
            self._scene.set_alpha(None)
            surface.blit(self._scene, (0, 0), special_flags=pygame.BLEND_RGB_MAX)

    def _present_fx(self, screen: pygame.Surface) -> None:
        screen.blit(self._fx, (0, 0))

    def _draw_reflections(self, screen: pygame.Surface) -> None:
        bank = round(self.layout.ground * self.ctx.height)
        for e in self.effects:
            if not isinstance(e, AnimalCrossing) or e.airborne:
                continue
            pose = "step" if e.pose == "step" else "idle"
            image = self.reflections.get((e.name, pose, e.going_left))
            if image is not None:
                # Mirror the lift of the feet across the bank, then remove
                # the transparent bottom margin now at the top of the mirror.
                y = bank + round((bank - e.y - self._foot_margins.get(e.name, 0)) * 0.55)
                rect = image.get_rect(midtop=(int(e.x), y))
                water_end = round(self.layout.water[1] * self.ctx.height)
                top = max(0, bank - y)
                height = min(rect.bottom, water_end) - (y + top)
                if height > 0:
                    screen.blit(image, (rect.x, y + top), (0, top, rect.width, height))

    def _draw_ground(self, animal, screen):
        animal._dust.draw(screen)
        sprite = animal._sprites[animal.pose]
        bottom = round(animal.y) + self._foot_margins[animal.name]
        screen.blit(sprite, sprite.get_rect(midbottom=(int(animal.x), bottom)))

    def _draw_lip(self, screen):
        # P0 already contains the water. Reapply it only where swimmers cover it.
        previous = screen.get_clip()
        areas = []
        for e in self.effects:
            if isinstance(e, AnimalCrossing) and e.gait == "swim":
                rect = e._sprites[e.pose].get_rect(center=(int(e.x), int(e.y))).clip(previous)
                if rect:
                    areas.append(rect)
        if areas:
            screen.set_clip(areas[0].unionall(areas[1:]))
            try:
                self.pond.draw_near_water(screen)
            finally:
                screen.set_clip(previous)

    def _draw_beat(self, target):
        clock = self.beat_clock
        flies = self.pond._flies
        if flies and clock.beat_index >= 0 and clock.beat_phase < 0.18:
            glow = flies.frames[1]
            dx = self.pond._painted.shake_x
            for x, y in flies.positions:
                target.blit(glow, glow.get_rect(center=(int(x) + dx, int(y))),
                            special_flags=pygame.BLEND_ADD)

    def _draw_pond_extras(self, target):
        if self.parade is not None and self._moon_glow is not None:
            world = self.pond._painted
            # During the sky dip or a storybook page, the normal moon can
            # be completely hidden. Never stamp it back onto that sky.
            if world is None or (world.card is None and world.elapsed <= world.period):
                if world is not None and id(world.current.plate) != self._moon_glow[0]:
                    self._moon_glow = self._parade_moon()
                _, image, rect = self._moon_glow
                dest = rect.move(world.shake_x, 0) if world is not None and world.shake_x else rect
                target.blit(image, dest, special_flags=pygame.BLEND_RGB_ADD)
        if self.storybook is not None:
            self.storybook.draw(target)

    def _draw_clean(self, screen: pygame.Surface, trails_live: bool) -> None:
        backdrop = self._draw_veil if trails_live and self.chaos is None else self._draw_opaque_scene
        buffered = self.clean_sprites and trails_live
        if not buffered:
            self._fx = None
        elif self._fx is None:
            self._fx = pygame.Surface(self.size).convert()
            backdrop = self._draw_opaque_scene

        targets = {"scene": self._scene, "fx": self._fx if buffered else screen, "screen": screen}
        painters = defaultdict(list)
        painters["pond"].append(self.pond.draw)
        if self.painted and self.party and self.beat_clock is not None:
            painters["pond"].append(self._draw_beat)
        painters["pond"].append(self._draw_pond_extras)
        painters["backdrop"].append(backdrop)
        if buffered:
            painters["present"].append(self._present_fx)
        if self.reflections.enabled and self.ctx.scale >= 0.6:
            painters["reflections"].append(self._draw_reflections)
        if self.lily:
            painters["lily"].append(self.lily.draw)
        rider = self._riding_in_parade()
        painters["frog"].append(self.frog.pad.draw if rider else self.frog.draw)
        if rider:
            painters["rider"].append(self._draw_rider)
        if procession := self.parade or self.trio:
            painters["parade"].append(procession.draw)
        if self.attract is not None:
            painters["attract"].append(self.attract.draw)
        if self.chaos is not None:
            painters["chaos"].append(self.chaos.draw)
        for effect in self.effects:
            layer = _layer(effect)
            if layer == "ground" and self._foot_margins and effect.name in self._foot_margins:
                painters[layer].append(partial(self._draw_ground, effect))
            else:
                painters[layer].append(effect.draw)
        if self.painted and painters["swimmers"] and self.ctx.scale >= 0.6:
            painters["lip"].append(self._draw_lip)

        for target, layers in _CLEAN_PASSES:
            for layer in layers:
                for paint in painters[layer]:
                    paint(targets[target])

    # ----------------------------------------------------- graceful degrade

    def note_frame_time(self, seconds: float) -> None:
        """Feed measured frame time; shrink particle scale when over budget,
        recover slowly when comfortably under."""
        self._frame_ema = 0.9 * self._frame_ema + 0.1 * seconds
        if self._frame_ema > self.frame_budget * 1.05:
            self.ctx.scale = max(0.25, self.ctx.scale * 0.9)
        elif self._frame_ema < self.frame_budget * 0.75:
            self.ctx.scale = min(1.0, self.ctx.scale * 1.02)
