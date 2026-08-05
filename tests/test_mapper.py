from lilypad.input.base import KeyEvent
from lilypad.input.mapper import (
    MASH_HELD_THRESHOLD,
    Action,
    KeyMapper,
    classify,
)


def press(name, ts=0.0):
    return KeyEvent(name=name, pressed=True, ts=ts)


def release(name, ts=0.0):
    return KeyEvent(name=name, pressed=False, ts=ts)


# ---------------------------------------------------------------- classify

def test_letters_classify():
    a = classify("A")
    assert a.kind == "letter" and a.letter == "A"
    assert classify("Z").kind == "letter"


def test_digits_count_along():
    assert classify("3").count == 3
    assert classify("0").count == 10          # zero counts to ten
    assert classify("KP7").count == 7         # numpad too


def test_space_arrows_enter():
    assert classify("SPACE").kind == "space"
    assert classify("LEFT").direction == (-1, 0)
    assert classify("UP").direction == (0, -1)
    assert classify("ENTER").kind == "enter"
    assert classify("KPENTER").kind == "enter"


def test_specials_never_os_actions():
    # Esc, meta/windows, media keys: all map to fun, none escape the app
    for name in ("ESC", "LEFTMETA", "PLAYPAUSE", "F5", "BACKSPACE", "MUTE"):
        assert classify(name).kind == "special"


def test_unknown_key_still_does_something():
    assert classify("MACRO1").kind == "sparkle"
    assert classify("SOMEFUTUREKEY").kind == "sparkle"


# ------------------------------------------------------------------ mapper

def collect(mapper, events):
    out = []
    for ev in events:
        out.extend(mapper.feed(ev))
    return out


def test_repeat_suppression():
    m = KeyMapper()
    actions = collect(m, [press("A", 0.0), press("A", 0.1)])  # OS repeat
    assert len(actions) == 1


def test_chord_within_window():
    m = KeyMapper(chord_window=0.15)
    actions = collect(m, [press("A", 0.0), press("B", 0.1)])
    kinds = [a.kind for a in actions]
    assert kinds == ["letter", "letter", "chord"]
    chord = actions[-1]
    assert set(chord.keys) == {"A", "B"}


def test_no_chord_outside_window():
    m = KeyMapper(chord_window=0.15)
    actions = collect(m, [press("A", 0.0), press("B", 0.5)])
    assert [a.kind for a in actions] == ["letter", "letter"]


def test_no_chord_after_release():
    m = KeyMapper(chord_window=0.15)
    actions = collect(m, [press("A", 0.0), release("A", 0.05), press("B", 0.1)])
    assert "chord" not in [a.kind for a in actions]


def test_mash_storm_by_held_count():
    m = KeyMapper()
    names = ["A", "S", "D", "F", "G"]
    assert MASH_HELD_THRESHOLD == 5
    actions = collect(m, [press(n, i * 0.3) for i, n in enumerate(names)])
    assert actions[-1].kind == "mash_start"
    assert m.in_mash

    # Releasing down to 2 held ends the storm
    end_actions = collect(m, [release("A", 2.0), release("S", 2.1), release("D", 2.2)])
    assert end_actions[-1].kind == "mash_end"
    assert not m.in_mash


def test_mash_storm_by_press_rate():
    m = KeyMapper()
    # 8 rapid press+release pairs inside one second — never 5 held at once
    events = []
    for i, name in enumerate("ASDFQWER"):
        t = i * 0.1
        events.append(press(name, t))
        events.append(release(name, t + 0.04))
    actions = collect(m, events)
    assert any(a.kind == "mash_start" for a in actions)


def test_mash_start_emitted_once():
    m = KeyMapper()
    events = [press(n, i * 0.01) for i, n in enumerate("ASDFGHJ")]
    actions = collect(m, events)
    assert sum(1 for a in actions if a.kind == "mash_start") == 1


def test_action_is_frozen():
    a = Action(kind="letter", letter="A")
    try:
        a.kind = "number"
        raised = False
    except AttributeError:
        raised = True
    assert raised
