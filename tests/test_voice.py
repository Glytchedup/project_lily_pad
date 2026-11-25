"""Short synthetic speech files and one-channel timing without wall-clock waits."""

import wave

import pygame
import pytest

from lilypad.audio.voice import NarratorPolicy, VoiceLoader
from lilypad.effects.numbers import CountAlong


def write_clip(path, milliseconds):
    path.parent.mkdir(exist_ok=True, parents=True)
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 10000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * (10 * milliseconds))


@pytest.fixture
def clips(tmp_path):
    already_open = pygame.mixer.get_init()
    if not already_open:
        pygame.mixer.init()
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    yield packaged, tmp_path / "sounds" / "voice"
    if not already_open:
        pygame.mixer.quit()


def test_resolves_each_entry_independently_and_falls_back_to_espeak(clips):
    packaged, espeak = clips
    (packaged / "manifest.toml").write_text(
        '[letters.G]\nfile="gee.wav"\n[letters.B]\nfile="missing.ogg"\n'
        '[phrases.G]\nfile="bad.ogg"\n[animals.giraffe]\nfile="animal.wav"\n'
        '[praise.party_start]\nfile="party.wav"\n[numbers.3]\nfile="three.wav"\n',
        encoding="utf-8",
    )
    for name, ms in [("gee", 50), ("animal", 70), ("party", 90), ("three", 110)]:
        write_clip(packaged / f"{name}.wav", ms)
    (packaged / "bad.ogg").write_bytes(b"broken")
    for name in ("G", "B", "3", "10"):
        write_clip(espeak / f"{name}.wav", 30)

    loader = VoiceLoader(packaged, espeak)
    for group, key, ms in [
        ("letters", "g", 50), ("letters", "B", 30), ("phrases", "G", 30),
        ("animals", "giraffe", 70), ("praise", "party_start", 90),
        ("numbers", 3, 110), ("numbers", 10, 30), ("endings", 3, 30),
    ]:
        assert loader.get(group, key).get_length() == pytest.approx(ms / 1000, abs=0.001)
    assert loader.get("letters", "A") is None
    assert loader.get("animals", "unknown") is None
    assert loader.get("praise", "G") is None


def test_missing_or_unreadable_manifest_still_uses_espeak(clips):
    packaged, espeak = clips
    write_clip(espeak / "G.wav", 30)
    assert VoiceLoader(packaged, espeak).get("letters", "G") is not None
    (packaged / "manifest.toml").write_bytes(b"[broken")
    assert VoiceLoader(packaged, espeak).get("letters", "G") is not None


def test_cache_holds_48_decoded_sounds_and_evicts_least_recently_used(clips):
    packaged, espeak = clips
    rows = []
    for i in range(49):
        write_clip(packaged / f"{i}.wav", 10)
        rows.append(f'[praise.take{i}]\nfile="{i}.wav"\n')
    (packaged / "manifest.toml").write_text("".join(rows), encoding="utf-8")
    loader = VoiceLoader(packaged, espeak)
    sounds = [loader.get("praise", f"take{i}") for i in range(48)]
    assert all(isinstance(sound, pygame.mixer.Sound) for sound in sounds)
    assert loader.get("praise", "take0") is sounds[0]  # take1 becomes the oldest
    assert loader.get("praise", "take48") is not None
    for key in ("A", "B", "C"):
        assert loader.get("letters", key) is None
    assert loader.get("praise", "take0") is sounds[0]
    assert loader.get("praise", "take1") is not sounds[1]
    assert len(loader._cache) == 48


def test_letters_interrupt_and_phrase_wait_starts_at_actual_replacement_end():
    policy = NarratorPolicy(party_duck=0.37)
    assert policy.request("praise", now=1.0, duration=6.0)
    assert policy.request("letters", now=2.0, duration=0.1)
    assert not policy.request("phrases", now=2.89, duration=4)
    assert policy.request("phrases", now=2.1 + 0.8, duration=4)
    assert not policy.request("animals", now=3.0, duration=0.1)
    assert policy.request("letters", now=3.0, duration=0.1)
    assert policy.gain(party_playing=True) == 0.37
    assert policy.gain(party_playing=False) == 1


def test_silent_letter_still_suppresses_phrases_for_six_tenths():
    policy = NarratorPolicy(party_duck=0.25, now=5.0)
    assert not policy.request("phrases", now=5.79, duration=1)
    assert not policy.request("letters", now=6.0, duration=0)
    assert not policy.request("phrases", now=6.59, duration=1)
    assert policy.request("phrases", now=6.6, duration=1)


def test_ten_letters_per_second_always_sound_and_no_phrase_slips_through():
    policy = NarratorPolicy(party_duck=0.1)
    for press in range(30):
        now = 5 + press / 10
        assert policy.request("letters", now=now, duration=0.18)
        assert not policy.request("phrases", now=now + 0.09, duration=2)
    assert policy.request("phrases", now=9.0, duration=2)


def test_count_schedule_follows_visual_pops(monkeypatch):
    # Change the visual constant so a second, copied timing literal cannot pass.
    monkeypatch.setattr(CountAlong, "POP_INTERVAL", 0.375)
    policy = NarratorPolicy(party_duck=1)
    policy.schedule_count(10, now=20)
    for index in range(10):
        born = 20 + index * CountAlong.POP_INTERVAL
        assert policy.due_count(born - 0.001) is None
        assert policy.due_count(born) == index + 1
        assert policy.due_count(born) is None
    assert policy.due_count(100) is None


def test_new_count_replaces_old_letter_cancels_and_late_frame_does_not_burst():
    policy = NarratorPolicy(party_duck=0.25)
    policy.schedule_count(10, now=1)
    policy.schedule_count(4, now=2)
    assert policy.due_count(2) == 1
    assert policy.due_count(2 + 2 * CountAlong.POP_INTERVAL) == 3
    assert policy.request("letters", now=2.8, duration=0.3)
    assert policy.due_count(5) is None


def test_get_packaged_never_uses_the_espeak_stand_in(clips):
    packaged, espeak = clips
    write_clip(packaged / "gee.wav", 50)
    write_clip(espeak / "G.wav", 30)
    write_clip(espeak / "B.wav", 30)
    (packaged / "manifest.toml").write_text('[letters.G]\nfile="gee.wav"\n', encoding="utf-8")
    loader = VoiceLoader(packaged, espeak)
    assert loader.get_packaged("letters", "g").get_length() == pytest.approx(0.05, abs=0.001)
    assert loader.get_packaged("letters", "B") is None
    assert loader.get_packaged("phrases", "G") is None
    assert loader.get("phrases", "G") is not None      # get() keeps its fallback


def test_an_ending_replaces_a_count_number_that_is_still_sounding():
    policy = NarratorPolicy(party_duck=0.5)
    assert policy.request("numbers", now=1.0, duration=0.5)
    assert not policy.request("numbers", now=1.2, duration=0.5)
    assert policy.request("endings", now=1.2, duration=0.5)
    assert not policy.request("numbers", now=1.6, duration=0.5)
