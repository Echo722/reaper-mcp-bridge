"""Shared utilities for tool modules.

All tools push Lua snippets through `eval_lua`. Pass dynamic values via `args`
(JSON-encoded by the bridge and exposed as `args` inside the Lua chunk) rather
than f-string interpolation — keeps it safe from injection and avoids escaping
bugs.
"""

from __future__ import annotations

from typing import Any


def db_to_amp_snippet(var: str = "db") -> str:
    """Lua expression converting dB to REAPER's linear gain. REAPER uses
    10^(dB/20). Inserts via f-string: f'{db_to_amp_snippet("db")}' → '10 ^ (db / 20)'.
    """
    return f"10 ^ ({var} / 20)"


def amp_to_db_snippet(var: str = "amp") -> str:
    """Inverse of db_to_amp_snippet — REAPER returns linear gain in many getters."""
    return f"(20 * (math.log({var}) / math.log(10)))"


def lua_color(r: int, g: int, b: int) -> int:
    """Pack RGB into REAPER's native color int (with the 0x01000000 flag REAPER
    uses to mean 'custom color set'). Both Lua and Python can do this; we do it
    here so it's a single number sent in args."""
    return 0x01000000 | (b << 16) | (g << 8) | r
