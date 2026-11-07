"""Key events around page changes, driven through the daemon's real key handler."""

import time

import pytest

from deckctl.__main__ import Daemon
from deckctl.config import load_deck_config, load_pages

MAIN = """
[page]
name = "main"

[[keys]]
pos = [0, 0]
type = "page"
target = "first"
label = "Open"

[[keys]]
pos = [4, 2]
type = "page"
target = "second"
label = "Hold"
on_long_press = "page:first"
long_press_ms = 10
"""

FIRST = """
[page]
name = "first"
back = "main"

[[keys]]
pos = [0, 0]
type = "command"
label = "Back"
on_press = "back"

[[keys]]
pos = [1, 0]
type = "page"
target = "second"
label = "Deeper"
"""

SECOND = """
[page]
name = "second"
back = "first"

[[keys]]
pos = [0, 0]
type = "command"
label = "Back"
on_press = "back"
"""

BACK, DEEPER, HOLD = 0, 1, 14


class FakeDeck:
    cols, rows, key_count, key_size, connected = 5, 3, 15, (72, 72), True

    def __init__(self):
        self.images = {}

    def set_key_image(self, idx, image):
        self.images[idx] = image

    def set_brightness(self, percent):
        pass


@pytest.fixture
def daemon(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "main.toml").write_text(MAIN)
    (pages / "first.toml").write_text(FIRST)
    (pages / "second.toml").write_text(SECOND)
    deck_toml = tmp_path / "deck.toml"
    deck_toml.write_text('[deck]\ndefault_page = "main"\n')

    d = Daemon(tmp_path)
    d.cfg = load_deck_config(deck_toml)
    d.pages = load_pages(pages)
    d.deck = FakeDeck()
    d._build_active_page()
    settle(d)
    return d


def settle(d):
    """Pretend the current page has been on screen for a while."""
    d._page_drawn_at = 0.0


def tap(d, idx):
    d._on_key(idx, True)
    d._on_key(idx, False)


def current(d):
    return d.page_stack.current.name


def open_second(d):
    tap(d, BACK)  # main's first key opens `first`
    settle(d)
    tap(d, DEEPER)
    settle(d)
    assert current(d) == "second"


def test_a_press_right_after_a_page_change_is_dropped(daemon):
    open_second(daemon)
    tap(daemon, BACK)
    assert current(daemon) == "first"
    tap(daemon, BACK)  # a bounce, or a press made during the redraw
    assert current(daemon) == "first"


def test_a_press_works_once_the_page_has_settled(daemon):
    open_second(daemon)
    tap(daemon, BACK)
    settle(daemon)
    tap(daemon, BACK)
    assert current(daemon) == "main"


def test_a_release_with_no_press_on_this_page_does_nothing(daemon):
    open_second(daemon)
    daemon._on_key(BACK, False)
    assert current(daemon) == "second"


def test_a_hold_that_changes_page_leaves_no_stale_image(daemon):
    daemon._on_key(HOLD, True)
    time.sleep(0.05)  # past long_press_ms, and lets the arc thread finish
    daemon._on_key(HOLD, False)
    assert current(daemon) == "first"
    assert daemon.deck.images[HOLD] is None
