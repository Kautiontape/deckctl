"""Action parsing and dispatch.

An `action` is a string a key invokes when pressed (short or long). Forms:

  back                                 pop the page stack
  page:<name>                          push a page
  command:<shell>                      run shell via sh -c
  <anything else>                      treated as command:<that>
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pages import PageStack

log = logging.getLogger(__name__)


@dataclass
class ActionContext:
    page_stack: "PageStack"
    secrets: dict[str, str]


def execute(action: str | None, ctx: ActionContext) -> None:
    """Best-effort: log and continue on failure. Never raises out of here."""
    if not action:
        return

    try:
        if action == "back":
            ctx.page_stack.back()
            return

        if action.startswith("page:"):
            target = action.removeprefix("page:").strip()
            ctx.page_stack.push(target)
            return

        if action.startswith("command:"):
            shell = action.removeprefix("command:")
        else:
            shell = action

        _spawn_shell(shell, ctx.secrets)
    except Exception:
        log.exception("action failed: %r", action)


def _spawn_shell(cmd: str, env_extra: dict[str, str]) -> None:
    """Fire-and-forget shell execution. Inherits user's env plus secrets."""
    import os

    env = os.environ.copy()
    env.update(env_extra)
    log.info("exec: %s", cmd)
    subprocess.Popen(
        ["sh", "-c", cmd],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def shell_quote(s: str) -> str:
    """Helper for widgets composing shell strings."""
    return shlex.quote(s)
