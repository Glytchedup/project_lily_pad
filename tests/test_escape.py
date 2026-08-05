from lilypad.escape import EscapeHatch

COMBO = ("LEFTSHIFT", "RIGHTSHIFT", "BACKSPACE")
ALL = frozenset(COMBO)
PARTIAL = frozenset(("LEFTSHIFT", "BACKSPACE"))
NONE = frozenset()


def make():
    return EscapeHatch(combo=COMBO, hold_seconds=5.0)


def test_fires_after_full_hold():
    h = make()
    assert not h.update(ALL, 0.0)
    assert not h.update(ALL, 4.9)
    assert h.update(ALL, 5.0)


def test_broken_hold_resets_timer():
    h = make()
    h.update(ALL, 0.0)
    h.update(PARTIAL, 3.0)      # released one key at 3s — reset
    assert not h.update(ALL, 4.0)
    assert not h.update(ALL, 8.9)   # only 4.9s since re-hold
    assert h.update(ALL, 9.0)


def test_partial_combo_never_fires():
    h = make()
    assert not h.update(PARTIAL, 0.0)
    assert not h.update(PARTIAL, 100.0)


def test_extra_keys_do_not_block():
    h = make()
    held = frozenset((*COMBO, "A", "SPACE"))  # toddler leaning on keys too
    h.update(held, 0.0)
    assert h.update(held, 5.0)


def test_fires_only_once():
    h = make()
    h.update(ALL, 0.0)
    assert h.update(ALL, 5.0)
    assert not h.update(ALL, 6.0)


def test_hold_progress():
    h = make()
    assert h.hold_progress(0.0) == 0.0
    h.update(ALL, 0.0)
    assert 0.49 < h.hold_progress(2.5) < 0.51
    assert h.hold_progress(99.0) == 1.0
