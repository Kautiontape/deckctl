#!/usr/bin/env python3
"""Exercise the non-device parts of the daemon.

Loads the example configs, builds widget instances, renders each key to a
PIL image, walks the page stack, and parses an action — all without
touching the Stream Deck. Renders are saved to /tmp/deckctl-smoke/ for
visual inspection.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

# Run from the repo root.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from deckctl.actions import ActionContext, execute  # noqa: E402
from deckctl.config import load_deck_config, load_pages, load_secrets  # noqa: E402
from deckctl.pages import ActivePage, PageStack, make_widget_deps  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

OUT = Path("/tmp/deckctl-smoke")


def main() -> int:
    # Stage example configs into a temp dir so paths resolve.
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    config_dir = OUT / "config"
    config_dir.mkdir()
    (config_dir / "pages").mkdir()

    # Copy example config but rename .toml.example -> .toml.
    src_cfg = REPO / "config"
    shutil.copyfile(src_cfg / "deck.toml.example", config_dir / "deck.toml")
    for ex in (src_cfg / "pages").iterdir():
        if ex.name.endswith(".toml.example"):
            shutil.copyfile(ex, config_dir / "pages" / ex.name.removesuffix(".example"))

    cfg = load_deck_config(config_dir / "deck.toml")
    cfg.config_dir = config_dir
    pages = load_pages(config_dir / "pages")
    secrets = load_secrets(cfg.secrets_path)

    print(f"loaded {len(pages)} page(s): {sorted(pages)}")
    print(f"icon dirs ({len(cfg.icon_dirs)}): {[str(p) for p in cfg.icon_dirs]}")
    print(f"secrets: {len(secrets)} key(s)")

    DECK_COLS, DECK_ROWS, KEY_SIZE = 5, 3, (72, 72)
    deps = make_widget_deps(cfg, KEY_SIZE)

    # Track pages visited by the on_change callback.
    visited: list[str] = []

    def on_change(page):
        visited.append(page.name)
        active = ActivePage(
            page,
            deck_cols=DECK_COLS,
            deck_rows=DECK_ROWS,
            deps=deps,
        )
        # Render and save composited grid for this page.
        rendered = active.render()
        from PIL import Image

        grid = Image.new("RGB", (KEY_SIZE[0] * DECK_COLS, KEY_SIZE[1] * DECK_ROWS), (40, 40, 40))
        for idx, img in rendered.items():
            row, col = divmod(idx, DECK_COLS)
            grid.paste(img, (col * KEY_SIZE[0], row * KEY_SIZE[1]))  # type: ignore[arg-type]
        out_path = OUT / f"{page.name}.png"
        grid.save(out_path)
        print(f"  rendered {page.name}: {len(rendered)} key(s) → {out_path}")

    stack = PageStack(pages, cfg, on_change=on_change)
    print(f"\ninitial page: {stack.current.name}")

    # Walk a navigation: main → ha → back → main → power → back
    print("\nnav: push 'ha'")
    stack.push("ha")
    print(f"  current: {stack.current.name}")
    print("nav: push 'feishin'")
    stack.push("feishin")
    print(f"  current: {stack.current.name}")
    print("nav: back")
    stack.back()
    print(f"  current: {stack.current.name}")
    print("nav: back (to main)")
    stack.back()
    print(f"  current: {stack.current.name}")
    print("nav: back at main (no history) → stays on main")
    stack.back()
    print(f"  current: {stack.current.name}")

    # Action parser smoke
    print("\naction parsing:")
    ctx = ActionContext(page_stack=stack, secrets=secrets)
    for s in ["page:sway", "back", "command:echo hi", "echo bare"]:
        # Don't actually fire shells; just check it doesn't blow up.
        if s.startswith("page:") or s == "back":
            execute(s, ctx)
            print(f"  {s!r} → current={stack.current.name}")
        else:
            print(f"  {s!r} would shell out to /bin/sh (skipping in smoke)")

    print(f"\npages visited (in render order): {visited}")
    print(f"\nrenders saved to {OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
