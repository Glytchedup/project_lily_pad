"""Effect engine: owns live effects, the frog, the pond scene, trails,
hold-comets, milestones, idle/chaos state, and the frame budget with
graceful degradation."""

from __future__ import annotations

import random
import time

import pygame

from ..input.mapper import Action
from .ambient import AttractMode, CelebrationPulse, ChaosOverlay
from .base import Effect, EffectContext
from .bubbles import BubbleField
from .comet import Comet
from .critter import Frog
from .particles import Rings, burst
from .registry import celebration, effects_for
from .scenery import PondBackground

BACKGROUND = (6, 8, 12)  # near-black; pure black feels "off", this glows

TRAIL_ALPHA = 80         # veil strength; lower = longer comet tails
GHOSTBUST_EVERY = 4      # frames between SUB/MAX anti-ghost passes (see draw)
TRAILS_OFF_BELOW = 0.4   # degradation ladder sheds trails below this scale...
TRAILS_ON_ABOVE = 0.6    # ...and restores them above this one (hysteresis)
CELEBRATION_COOLDOWN = 10.0  # s between milestone parties (mash-proofing)
RIPPLE_COLOR = (150, 200, 255)
ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Action kinds that represent an actual keypress (milestone counting) —
# synthetic companions (chord, mash_*, hold_*) ride along with a base press.
_PRESS_KINDS = {"letter", "number", "space", "enter", "special", "sparkle", "arrow"}


class EffectEngine:
    def __init__(self, size: tuple[int, int], max_particles: int = 900,
                 idle_timeout: float = 60.0, fps: int = 60,
                 rng: random.Random | None = None,
                 trails: bool = True, milestone_every: int = 50) -> None:
        self.size = size
        self.max_particles = max_particles
        self.idle_timeout = idle_timeout
        self.frame_budget = 1.0 / max(1, fps)
        self.ctx = EffectContext(size=size, rng=rng or random.Random())
        self.effects: list[Effect] = []
        self.frog = Frog(size)
        self.pond = PondBackground(self.ctx)
        self.trails = trails
        self.milestone_every = milestone_every
        self.chaos: ChaosOverlay | None = None
        self.attract: AttractMode | None = None
        self.comets: dict[str, Comet] = {}
        self.press_count = 0
        self.letters_seen: set[str] = set()
        self.last_action_time = time.monotonic()
        self._scene = pygame.Surface(size)
        self._celebration_pending = False
        self._last_celebration = float("-inf")
        self._trails_live = trails
        self._frame_no = 0
        self._frame_ema = self.frame_budget
        self._chaos_spawn_accum = 0.0

    # ------------------------------------------------------------------ input

    def spawn(self, action: Action, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.last_action_time = now
        if self.attract is not None:      # any key kills attract mode instantly
            self.attract = None

        if action.kind in _PRESS_KINDS:
            self._note_press(action, now)

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
            self.effects.extend(effects_for(self.ctx, action))

    def _note_press(self, action: Action, now: float) -> None:
        """Milestone bookkeeping: every Nth press parties, and completing the
        alphabet parties harder (VISUAL_REVIEW.md #10)."""
        self.press_count += 1
        if action.kind == "letter" and action.letter in ALPHABET:
            self.letters_seen.add(action.letter)
            if self.letters_seen >= ALPHABET:
                self.letters_seen.clear()
                self._celebrate(big=True, now=now)
                return
        if self.milestone_every and self.press_count % self.milestone_every == 0:
            self._celebrate(big=False, now=now)

    def _celebrate(self, big: bool, now: float) -> None:
        # Cooldown: under a mash storm the 50-press milestone recurs every
        # couple of seconds, which would make the mega-party the steady state
        # (and stack full-screen pulse overlays). One party at a time.
        if now - self._last_celebration < CELEBRATION_COOLDOWN:
            return
        self._last_celebration = now
        # Respect the same budget gate as every other spawn path; the frog
        # and the fanfare still party even when the screen is saturated.
        if self.particle_count() < self.max_particles * 1.5:
            self.effects.extend(celebration(self.ctx, big=big))
            self.effects.append(CelebrationPulse(self.ctx, duration=2.5))
        self.frog.celebrate()
        self._celebration_pending = True

    def consume_celebration(self) -> bool:
        """Main loop polls this to fire the celebration audio cue."""
        pending, self._celebration_pending = self._celebration_pending, False
        return pending

    # ------------------------------------------------------------------ frame

    def particle_count(self) -> int:
        n = sum(len(e) for e in self.effects if hasattr(e, "__len__"))
        if self.chaos is not None:
            n += len(self.chaos)   # engine-owned, but its wash isn't free
        return n

    def update(self, dt: float, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.pond.update(dt)
        self.frog.update(dt)
        # Frog splash-down → water ripples at his feet.
        if self.frog.just_bounced and self.frog.y >= self.frog.h - self.frog.r - 1:
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

        self.effects = [e for e in self.effects if e.update(dt)]
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

        if (self.attract is None and self.chaos is None
                and now - self.last_action_time >= self.idle_timeout):
            self.attract = AttractMode(self.ctx)
        if self.attract is not None:
            self.attract.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        # The pond composites onto a scratch surface; blitting it translucent
        # instead of opaque is what leaves motion trails (VISUAL_REVIEW.md #4):
        # last frame's lights linger and fade INTO the scene over ~10 frames.
        self._frame_no += 1
        self.pond.draw(self._scene)
        # The veil is a fixed cost the particle ladder can't shrink, so the
        # ladder sheds it directly: trails drop out when degradation is deep
        # and come back once the frame budget recovers (with hysteresis).
        if self.trails:
            if self._trails_live and self.ctx.scale <= TRAILS_OFF_BELOW:
                self._trails_live = False
            elif not self._trails_live and self.ctx.scale >= TRAILS_ON_ABOVE:
                self._trails_live = True
        if self.trails and self._trails_live:
            self._scene.set_alpha(TRAIL_ALPHA)
            surface.blit(self._scene, (0, 0))
            # Integer alpha-blending truncates, so the veil alone stalls a few
            # levels away from the scene and leaves permanent ghost silhouettes.
            # A small subtract breaks the floor for bright residue, and a MAX
            # blit of the scene snaps anything that fell below it back exactly.
            # Running this pass every few frames (instead of every frame) cuts
            # its ~2 ms cost to ~0.5 ms; residue just fades a beat slower.
            if self._frame_no % GHOSTBUST_EVERY == 0:
                surface.fill((6, 6, 6), special_flags=pygame.BLEND_RGB_SUB)
                self._scene.set_alpha(None)
                surface.blit(self._scene, (0, 0),
                             special_flags=pygame.BLEND_RGB_MAX)
        else:
            self._scene.set_alpha(None)
            surface.blit(self._scene, (0, 0))
        if self.attract is not None:
            self.attract.draw(surface)
        for effect in self.effects:
            effect.draw(surface)
        self.frog.draw(surface)
        if self.chaos is not None:
            self.chaos.draw(surface)

    # ----------------------------------------------------- graceful degrade

    def note_frame_time(self, seconds: float) -> None:
        """Feed measured frame time; shrink particle scale when over budget,
        recover slowly when comfortably under."""
        self._frame_ema = 0.9 * self._frame_ema + 0.1 * seconds
        if self._frame_ema > self.frame_budget * 1.05:
            self.ctx.scale = max(0.25, self.ctx.scale * 0.9)
        elif self._frame_ema < self.frame_budget * 0.75:
            self.ctx.scale = min(1.0, self.ctx.scale * 1.02)
