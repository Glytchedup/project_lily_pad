"""Integration tests for the upgraded EffectEngine: pond, trails, comets,
bubbles, ripples, milestones, and the new registry wiring."""

import random
from unittest.mock import Mock

import pygame
import pytest

from lilypad.__main__ import PlaygroundAudio, _mirror_frame
from lilypad.audio.engine import AudioEngine
from lilypad.audio.tracks import BeatClock, BeatMap
from lilypad.config import SceneConfig
from lilypad.effects import animals
from lilypad.effects.animals import PeekabooAnimal
from lilypad.effects.base import EffectContext
from lilypad.effects.bubbles import BubbleField
from lilypad.effects.comet import Comet
from lilypad.effects.engine import EffectEngine
from lilypad.effects.registry import celebration, effects_for
from lilypad.input.mapper import Action, classify

SIZE = (640, 480)


def make_engine(**kw):
    return EffectEngine(SIZE, rng=random.Random(99), **kw)


def surf():
    return pygame.Surface(SIZE)


def run(engine, seconds, dt=1 / 60):
    steps = int(seconds / dt)
    s = surf()
    for _ in range(steps):
        engine.update(dt, now=0.0)
        engine.draw(s)
    return s


# ---------------------------------------------------------------- registry

def test_animal_letters_spawn_peekaboo():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    effects = effects_for(ctx, Action(kind="letter", letter="C"))
    assert any(isinstance(e, PeekabooAnimal) for e in effects)


def test_plain_letter_spawns_no_animal():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    effects = effects_for(ctx, Action(kind="letter", letter="Q"))
    assert not any(isinstance(e, PeekabooAnimal) for e in effects)
    assert not any(isinstance(e, BubbleField) for e in effects)


def test_letter_b_spawns_bubbles():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    effects = effects_for(ctx, Action(kind="letter", letter="B"))
    assert any(isinstance(e, BubbleField) for e in effects)


def test_celebration_factory_returns_effects():
    ctx = EffectContext(size=SIZE, rng=random.Random(1))
    assert len(celebration(ctx, big=False)) >= 3
    assert len(celebration(ctx, big=True)) >= 4


# ------------------------------------------------------------------ comets

def test_hold_start_creates_comet_hold_end_releases():
    e = make_engine()
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    assert "A" in e.comets
    comet = e.comets["A"]
    assert comet in e.effects
    e.spawn(Action(kind="hold_end", key="A"), now=1.0)
    assert "A" not in e.comets
    run(e, 3.0)  # burst + trail expire
    assert comet not in e.effects


def test_hold_end_without_start_is_harmless():
    e = make_engine()
    e.spawn(Action(kind="hold_end", key="Z"), now=0.0)
    assert e.comets == {}


def test_replacing_a_comet_releases_the_old_one():
    e = make_engine()
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    old = e.comets["A"]
    e.spawn(Action(kind="hold_start", key="A"), now=1.0)
    assert e.comets["A"] is not old
    assert old.released


# -------------------------------------------------------------- milestones

def test_milestone_triggers_celebration():
    e = make_engine(milestone_every=5)
    for i in range(5):
        e.spawn(Action(kind="sparkle", key=f"K{i}"), now=0.0)
    assert e.consume_celebration() is True
    assert e.consume_celebration() is False  # one-shot


def test_milestone_disabled_when_zero():
    e = make_engine(milestone_every=0)
    for i in range(60):
        e.spawn(Action(kind="sparkle", key=f"K{i}"), now=0.0)
    assert e.consume_celebration() is False


def test_alphabet_completion_celebrates_and_resets():
    e = make_engine(milestone_every=0)
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        e.spawn(Action(kind="letter", key=ch, letter=ch), now=0.0)
    assert e.consume_celebration() is True
    assert e.letters_seen == set()


def test_synthetic_actions_do_not_count_as_presses():
    e = make_engine(milestone_every=2)
    e.spawn(Action(kind="chord", keys=("A", "B")), now=0.0)
    e.spawn(Action(kind="mash_start"), now=0.0)
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    assert e.press_count == 0


# ------------------------------------------------------- frog interactions

def test_frog_bounce_spawns_ripple():
    e = make_engine()
    e.frog.vy = 500.0  # slam him into the floor
    e.frog.y = e.frog.h - e.frog.r - 1
    before = len(e.effects)
    e.update(1 / 60, now=0.0)
    assert len(e.effects) > before


def test_frog_pops_bubbles():
    e = make_engine()
    field = BubbleField(e.ctx, count=8)
    # Teleport one bubble onto the frog.
    field.bubbles[0].x, field.bubbles[0].y = e.frog.x, e.frog.y
    n = len(field.bubbles)
    e.effects.append(field)
    e.update(1 / 60, now=0.0)
    assert len(field.bubbles) < n


# ----------------------------------------------------------------- drawing

def test_draw_covers_screen_with_and_without_trails():
    for trails in (True, False):
        e = make_engine(trails=trails)
        s = surf()
        s.fill((255, 0, 255))  # sentinel
        for _ in range(30):    # veil converges over several frames
            e.update(1 / 60, now=0.0)
            e.draw(s)
        corner = s.get_at((1, 1))[:3]
        assert corner != (255, 0, 255)


def test_full_frame_with_everything_live():
    e = make_engine(milestone_every=3)
    e.spawn(Action(kind="letter", key="C", letter="C"), now=0.0)
    e.spawn(Action(kind="letter", key="B", letter="B"), now=0.0)
    e.spawn(Action(kind="number", key="3", count=3), now=0.0)
    e.spawn(Action(kind="enter", key="ENTER"), now=0.0)   # milestone fires here
    e.spawn(Action(kind="hold_start", key="Q"), now=0.0)
    e.spawn(Action(kind="mash_start"), now=0.0)
    run(e, 1.0)
    assert e.particle_count() > 0
    e.spawn(Action(kind="mash_end"), now=2.0)
    e.spawn(Action(kind="hold_end", key="Q"), now=2.0)
    run(e, 8.0)  # everything transient should drain without error


# ------------------------------------------------------- review-round fixes

def test_celebration_cooldown_limits_party_rate():
    e = make_engine(milestone_every=2)
    for i in range(20):
        e.spawn(Action(kind="sparkle", key=f"K{i}"), now=1.0)
    # 10 milestones hit, but only the first lands inside the cooldown window.
    assert e.consume_celebration() is True
    pulses = [x for x in e.effects if type(x).__name__ == "CelebrationPulse"]
    assert len(pulses) == 1
    # After the cooldown, the next milestone parties again.
    e.spawn(Action(kind="sparkle", key="L1"), now=30.0)
    e.spawn(Action(kind="sparkle", key="L2"), now=30.0)
    assert e.consume_celebration() is True


def test_comet_auto_releases_on_stuck_hold():
    from lilypad.effects.comet import _MAX_HOLD_SECONDS
    e = make_engine()
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    comet = e.comets["A"]
    for _ in range(int((_MAX_HOLD_SECONDS + 3) * 30)):
        e.update(1 / 30, now=0.0)
    assert comet.released
    assert comet not in e.effects  # fully drained and pruned


def test_comet_shed_rate_is_frame_rate_independent():
    from lilypad.effects.comet import Comet
    counts = {}
    for fps in (30, 120):
        ctx = EffectContext(size=SIZE, rng=random.Random(5))
        c = Comet(ctx)
        for _ in range(fps * 2):  # 2 simulated seconds
            c.update(1 / fps)
        counts[fps] = len(c.trail)
    assert abs(counts[30] - counts[120]) / max(counts.values()) < 0.25


def test_mash_overlay_does_not_tax_the_budget():
    """Deliberate: counting the mash overlay starved mash mode of its own
    bursts (72% fewer at default config, zero below max_particles=250)."""
    e = make_engine()
    base = e.particle_count()
    e.spawn(Action(kind="mash_start"), now=0.0)
    assert e.particle_count() == base


def test_celebration_pulse_does_count_toward_budget():
    e = make_engine(milestone_every=1)
    e.spawn(Action(kind="sparkle", key="K"), now=50.0)
    assert e.particle_count() > 250  # pulse (250) + party effects


def test_alphabet_reward_survives_cooldown():
    """A cooldown-suppressed milestone must not eat the alphabet party or
    the 26-letter progress."""
    e = make_engine(milestone_every=5)
    for i in range(5):
        e.spawn(Action(kind="sparkle", key=f"K{i}"), now=100.0)  # arms cooldown
    assert e.consume_celebration() is True
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":                       # 2 s later
        e.spawn(Action(kind="letter", key=ch, letter=ch), now=102.0)
    assert e.consume_celebration() is True    # big party fired anyway
    assert e.letters_seen == set()            # and progress was consumed by it


def test_blocked_party_does_not_arm_cooldown():
    e = make_engine(milestone_every=5)
    for _ in range(12):                        # saturate the budget
        e.effects.extend(celebration(e.ctx, big=False))
    assert e.particle_count() >= e.max_particles * 1.5
    for i in range(5):
        e.spawn(Action(kind="sparkle", key=f"B{i}"), now=100.0)
    assert e.consume_celebration() is False   # blocked by budget
    e.effects.clear()                          # screen drains
    for i in range(5):
        e.spawn(Action(kind="sparkle", key=f"C{i}"), now=101.0)
    assert e.consume_celebration() is True    # no stale cooldown in the way


def test_trails_pause_during_mash_chaos():
    e = make_engine(trails=True)
    e.spawn(Action(kind="mash_start"), now=0.0)
    s = surf()
    e.update(1 / 60, now=0.0)
    e.draw(s)
    # Veil suspended: internal scene blit ran opaque (alpha None restored).
    assert e._scene.get_alpha() in (None, 255)


def test_count_digit_outlives_the_count():
    from lilypad.effects.numbers import CountAlong
    ctx = EffectContext(size=SIZE, rng=random.Random(2))
    c = CountAlong(ctx, 10)
    assert c.digit.total >= c.total - 1e-6


def test_gated_press_still_spawns_something_visible():
    """Product invariant: every key does something visible, even with the
    particle budget saturated (28% of fast space presses went dead)."""
    e = make_engine()
    for _ in range(15):
        e.effects.extend(celebration(e.ctx, big=False))
    assert e.particle_count() >= e.max_particles * 1.5
    before = len(e.effects)
    e.spawn(Action(kind="letter", key="Q", letter="Q"), now=0.0)
    assert len(e.effects) > before


def test_no_attract_mode_while_comet_held():
    e = make_engine()
    e.idle_timeout = 1.0
    e.spawn(Action(kind="hold_start", key="A"), now=0.0)
    e.update(1 / 60, now=100.0)     # far past idle timeout, comet live
    assert e.attract is None
    e.spawn(Action(kind="hold_end", key="A"), now=100.0)
    for _ in range(240):
        e.update(1 / 60, now=200.0)  # comet drains, then truly idle
    assert e.attract is not None


def test_count_along_does_not_poison_shared_sprite():
    """set_alpha(None) on the shared cached mini sprite permanently disables
    per-pixel alpha (black squares for every later count) — the restore must
    be set_alpha(255)."""
    from lilypad.effects.numbers import CountAlong
    ctx = EffectContext(size=SIZE, rng=random.Random(4))
    s = surf()
    first = CountAlong(ctx, 3)
    while first.update(1 / 60):     # run a full lifecycle including the fade
        first.draw(s)
    sprite = first.sprite
    assert sprite.get_alpha() is not None   # per-pixel alpha still enabled
    # A later count of the same kind must blit transparent corners, not black.
    probe = surf()
    probe.fill((123, 45, 67))
    probe.blit(sprite, (0, 0))
    assert probe.get_at((0, 0))[:3] == (123, 45, 67)


def test_comet_scales_with_resolution():
    from lilypad.effects.comet import Comet
    small = Comet(EffectContext(size=(1280, 720), rng=random.Random(5)))
    big = Comet(EffectContext(size=(3840, 2160), rng=random.Random(5)))
    assert big.radius > small.radius * 2.5
    assert big.speed > small.speed * 2.0


@pytest.fixture
def pond_engine(tmp_path, monkeypatch):
    from test_lily import make_art as make_lily
    from test_scenery import make_art as make_pond
    from lilypad.effects import painted
    from lilypad.effects.layout import POND

    make_lily(tmp_path)
    make_pond(tmp_path, count=1)
    # Prewarm a synthetic cast row at its production spawn height.
    monkeypatch.setattr(animals, "animal_names", lambda: ("giraffe",))
    monkeypatch.setattr(animals, "_layout", POND)
    monkeypatch.setattr(animals, "_max_sprite_width", 0.0)
    monkeypatch.setattr(animals, "resolved_mode", lambda name: "painted")
    monkeypatch.setattr(painted, "_rows", lambda: {"giraffe": {"anchor": [0.5, 1.0]}})

    def sprite(name, height, pose, left, width):
        art = pygame.Surface((36, height), pygame.SRCALPHA)
        art.fill((224, 64, 32), (0, 0, 36, height - 7))
        return art

    monkeypatch.setattr(animals, "_scene_sprite", sprite)
    return EffectEngine((640, 360), rng=random.Random(11), scene=SceneConfig(),
                        root=tmp_path, lily_seed=20, mirror_animals=True,
                        clean_sprites=True, trails=False)


def test_integrated_bank_places_feet_and_mirror_in_adjacent_rows(pond_engine):
    e = pond_engine
    e.spawn(classify("G"), now=0)
    animal = next(a for a in e.effects if isinstance(a, animals.AnimalCrossing))
    e.effects = [animal]
    animal.x, animal.y = 202, e.ctx.height * e.layout.ground
    bank = int(animal.y)
    screen = pygame.Surface(e.size)
    e.draw(screen)
    assert screen.get_at((202, bank - 1))[:3] == (224, 64, 32)
    assert screen.get_at((202, bank + 5)) != e._scene.get_at((202, bank + 5))
    e.ctx.scale = 0.59
    e.update(0, now=0)
    animal.x, animal.y = 202, bank
    e.draw(screen)
    assert e.pond._painted.flat
    assert screen.get_at((202, bank + 5)) == e._scene.get_at((202, bank + 5))
    e.ctx.scale = 0.6
    e.update(0, now=0)
    assert not e.pond._painted.flat


def test_pond_key_stomp_lily_and_beat_lifecycle(pond_engine):
    from lilypad.effects.ambient import CelebrationPulse
    from lilypad.effects.particles import Rings
    e = pond_engine
    e.attract_key("SPACE")
    assert e.pond._flies.remaining > 0
    assert e.pond._flies.target == (7.5 * 640 / 22, 5.5 * 360 / 6)
    e.spawn(classify("F7"), now=0)
    assert e.pond._painted.shake_left > 0
    assert next(a.pos[1] for a in e.effects if isinstance(a, Rings)) == e.ctx.height * e.layout.ground
    e._celebrate(False, 20)
    assert e.praise == "lily_great" and e.lily.cheering
    clock = BeatClock(BeatMap(120, 0, (0, .5, 1), (0,), ()))
    e.start_party(30, clock)
    assert e.lily.party and e.lily._beat is clock
    assert not any(isinstance(a, CelebrationPulse) for a in e.effects)
    screen = pygame.Surface(e.size)
    e.draw(screen)
    on_beat = pygame.image.tobytes(e._scene, "RGB")
    clock.advance(0.25)
    e.draw(screen)
    off_beat = pygame.image.tobytes(e._scene, "RGB")
    assert on_beat != off_beat
    e.set_party_clock(None)
    e.draw(screen)
    assert pygame.image.tobytes(e._scene, "RGB") == off_beat
    e.end_party(40)
    e.update(.1, now=40 + e.sleep_timeout)
    assert e.lily.asleep and e.wake(400) and not e.lily.asleep


def test_keyboard_mirror_keeps_tokens_and_emits_each_rocket_once():
    e = make_engine(mirror_animals=True)
    e.spawn(classify("G"), now=0)
    e.spawn(classify("ENTER"), now=0)
    lighting = Mock()
    previous = set()
    for frame in range(220):
        now = frame / 60
        e.update(1 / 60, now)
        previous = _mirror_frame(e, lighting, previous, now)
    calls = [call.args for call in lighting.track.call_args_list]
    token = calls[0][0]
    assert all(row[0] is token and row[1] == "giraffe" for row in calls)
    assert calls[1][2] != calls[0][2] and 0 < calls[0][4]
    assert not previous
    lighting.untrack.assert_called_once_with(token)
    assert lighting.bloom.call_count == 3


def test_translucent_lip_covers_the_swimmer_before_pip(pond_engine):
    e = pond_engine
    swimmer = animals.AnimalCrossing(e.ctx, "whale")
    e.effects = [swimmer]
    swimmer.x, swimmer.y = 225, 300
    screen = pygame.Surface(e.size)
    e.draw(screen)
    probe = (225, 303)
    above = (225, 275)
    assert screen.get_at(above)[:3] == (224, 64, 32)
    expected = pygame.Surface(e.size)
    swimmer.draw(expected)
    e.pond.draw_near_water(expected)
    assert screen.get_at(probe) == expected.get_at(probe)
    assert screen.get_at(probe) != screen.get_at(above)
    assert screen.get_clip() == screen.get_rect()


def test_reward_track_samples_its_own_sidecar_and_clears_clock(tmp_path, monkeypatch):
    import json
    from test_audio_engine_voice import write_clip

    song = tmp_path / "music" / "song.wav"
    write_clip(song, 2)
    song.with_suffix(".wav.beats.json").write_text(json.dumps({
        "bpm": 120, "offset": 0.0, "beats": [0, .5, 1], "downbeats": [0], "drops": [],
    }), encoding="utf8")
    audio = PlaygroundAudio(tmp_path, tunes="reward", autogen=False, background_folder=song.parent)
    try:
        audio._start_party(0)
        assert audio.beat_clock is None
        monkeypatch.setattr(pygame.mixer.music, "get_pos", lambda: 625)
        audio.tick(10)
        assert audio.beat_clock.beat_index == 1 and audio.beat_clock.beat_phase == .25
        monkeypatch.setattr(audio, "_music_playing", lambda: False)
        audio.tick(11)
        assert audio.beat_clock is None
    finally:
        audio.close()


def test_party_and_alphabet_narration_alternate_without_duplicate_events(tmp_path, monkeypatch):
    spoken = []
    monkeypatch.setattr(AudioEngine, "narrate", lambda _, event, now: spoken.append((event, now)))
    audio = PlaygroundAudio(tmp_path, mute=True, tunes="reward", voice="narrator")
    for t in (0, 10, 20, 30, 40, 50, 130, 140, 150):
        audio._start_party(t)
        audio.tick(t + 2)
    party_lines = [event for event, _ in spoken if event != "lily_wow"]
    assert party_lines == ["party_start", "lily_party"] * 4 + ["party_start"]
    assert [t for event, t in spoken if event == "lily_wow"] == [22, 152]
    audio.narrate("alphabet_complete", 200)
    audio.narrate("alphabet_complete", 250)
    assert spoken[-2:] == [("alphabet_complete", 200), ("lily_all", 250)]


@pytest.mark.parametrize("gait,floater,hz", [("fly", False, 2), ("swim", False, .8),
                                               ("fly", True, 1)])
def test_approved_painted_cycle_rates(gait, floater, hz):
    schedule = animals.AnimalCrossing.pose_for
    assert schedule(gait, .49 / hz, floater) == "idle"
    assert schedule(gait, .51 / hz, floater) == "step"
    assert schedule(gait, 1.1 / hz, floater) == "idle"
