"""PlayStats: pure, time-injected session counters for the parent's card."""

import builtins
import math

import pytest

from lilypad.input.mapper import Action, classify
from lilypad.stats import GAP_SECONDS, PlayStats


def letter(ch):
    return classify(ch)


def test_empty_stats_are_all_zero():
    s = PlayStats()
    assert s.time_played == 0 and s.longest_streak == 0 and s.parties == 0
    assert s.letters_found == frozenset() and s.animals_seen == frozenset()
    assert s.animal_counts == {} and s.favourite is None


def test_a_single_press_is_no_time():
    s = PlayStats()
    s.on_action(letter("a"), 5.0)
    assert s.time_played == 0 and s.longest_streak == 0


def test_time_accumulates_inside_the_gap():
    s = PlayStats()
    for t in (0, 10, 30, 90):                 # gaps 10, 20, 60: all count
        s.on_action(letter("a"), t)
    assert s.time_played == 90 and s.longest_streak == 90


def test_gap_over_sixty_seconds_is_not_play_and_splits_the_streak():
    s = PlayStats()
    for t in (0, 20, 40):                      # run of 40 s
        s.on_action(letter("a"), t)
    for t in (500, 510, 530, 560, 590):        # 90 s later: run of 90 s
        s.on_action(letter("b"), t)
    for t in (2000, 2010):                     # run of 10 s
        s.on_action(letter("c"), t)
    assert s.time_played == pytest.approx(40 + 90 + 10)
    assert s.longest_streak == pytest.approx(90)
    assert GAP_SECONDS == 60.0


def test_gap_just_over_sixty_breaks_and_exactly_sixty_does_not():
    s = PlayStats()
    s.on_action(letter("a"), 0)
    s.on_action(letter("a"), 60.0)
    s.on_action(letter("a"), 120.1)
    assert s.time_played == pytest.approx(60.0) and s.longest_streak == pytest.approx(60.0)


def test_animals_and_actions_both_tick_activity():
    s = PlayStats()
    s.on_animal("lion", 0)
    s.on_action(letter("l"), 30)
    s.on_animal("zebra", 55)
    assert s.time_played == 55


def test_party_counts_but_never_bridges_a_gap():
    s = PlayStats()
    s.on_action(letter("a"), 0)
    s.on_party(10)
    s.on_party(20)
    s.on_action(letter("b"), 200)              # silence through a party still breaks the run
    assert s.parties == 2 and s.time_played == 0 and s.longest_streak == 0


def test_only_real_letter_keys_count_as_letters_found():
    s = PlayStats()
    s.on_action(letter("g"), 1)
    s.on_action(letter("G"), 2)
    s.on_action(Action(kind="special", key="F7", letter="T"), 3)   # carries a letter field
    s.on_action(classify("5"), 4)
    s.on_action(classify("SPACE"), 5)
    s.on_action(Action(kind="letter", key="é", letter="é"), 6)
    assert s.letters_found == frozenset({"G"})


def test_release_side_actions_prove_nothing():
    s = PlayStats()
    s.on_action(letter("a"), 0)
    s.on_action(Action(kind="mash_end"), 50)
    s.on_action(Action(kind="hold_end", key="a"), 55)
    assert s.time_played == 0


def test_favourite_is_most_counted_with_first_seen_breaking_ties():
    s = PlayStats()
    for name in ("owl", "fox", "fox", "owl", "bear"):
        s.on_animal(name, 1)
    assert s.animal_counts == {"owl": 2, "fox": 2, "bear": 1}
    assert s.favourite == "owl"                # tied with fox, seen first
    s.on_animal("fox", 2)
    assert s.favourite == "fox"
    assert s.animals_seen == frozenset({"owl", "fox", "bear"})


def test_favourite_may_be_a_function_key_dinosaur():
    s = PlayStats()
    s.on_animal("stegosaurus", 1)
    assert s.favourite == "stegosaurus"


def test_time_never_runs_backwards_and_bad_times_are_ignored():
    s = PlayStats()
    s.on_action(letter("a"), 100)
    s.on_action(letter("a"), 90)               # clock hiccup
    s.on_action(letter("a"), math.nan)
    s.on_action(letter("a"), math.inf)
    s.on_action(letter("a"), None)
    s.on_action(letter("a"), 130)
    assert s.time_played == 30 and s.longest_streak == 30


def test_results_are_copies():
    s = PlayStats()
    s.on_animal("owl", 0)
    s.animal_counts["owl"] = 99
    assert s.animal_counts["owl"] == 1


def test_stats_never_touch_the_disk(monkeypatch, tmp_path):
    def forbidden(*a, **k):
        raise AssertionError("PlayStats must not open files")
    monkeypatch.setattr(builtins, "open", forbidden)
    s = PlayStats()
    for t in range(0, 300, 7):
        s.on_action(letter("a"), t)
        s.on_animal("owl", t)
    s.on_party(1)
    assert s.time_played > 0
