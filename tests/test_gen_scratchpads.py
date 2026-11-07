"""The Apps page generator, including hand-written extra keys."""

import tomllib

from deckctl.tools.gen_scratchpads import build

INI = """
[one]
label = One

[two]
label = Two
"""

EXTRA = """
[[keys]]
pos = [1, 0]
type = "page"
target = "elsewhere"
label = "Pinned"
"""


def keys_by_pos(rendered):
    return {tuple(k["pos"]): k for k in tomllib.loads(rendered)["keys"]}


def test_without_extras_entries_fill_in_order(tmp_path):
    ini = tmp_path / "pads.ini"
    ini.write_text(INI)
    keys = keys_by_pos(build(ini))
    assert keys[(1, 0)]["label"] == "One"
    assert keys[(2, 0)]["label"] == "Two"


def test_extra_keys_keep_their_slot_and_entries_skip_it(tmp_path):
    ini = tmp_path / "pads.ini"
    ini.write_text(INI)
    keys = keys_by_pos(build(ini, EXTRA))
    assert keys[(1, 0)]["label"] == "Pinned"
    assert keys[(1, 0)]["target"] == "elsewhere"
    assert keys[(2, 0)]["label"] == "One"
    assert keys[(3, 0)]["label"] == "Two"
