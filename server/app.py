"""
REAPER MCP server — entry point.

Exposes REAPER (via the in-DAW Lua bridge) to Claude as an MCP server over
stdio. Tools are organized by domain in `server.tools.*`; each module exposes a
`register(mcp)` function that hangs its tools off the shared FastMCP instance.

Run directly for stdio:
    python -m server.app
or:
    python server/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Allow `python server/app.py` (no -m) — add repo root to sys.path.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from server.bridge_client import (  # noqa: E402
    BridgeError,
    eval_lua,
    ping as bridge_ping,
    resolve_bridge_dir,
)
from server.tools import (  # noqa: E402
    batch,
    editing,
    midi,
    mixing,
    project,
    render,
    tracks,
)


INSTRUCTIONS = """\
This server controls REAPER, a digital audio workstation, via an in-REAPER Lua
bridge. REAPER must be open AND the bridge script (reaper_mcp_bridge.lua) must
be loaded and running. The README documents one-time setup.

How to use the tools:
- Start by calling `get_project_info` and `list_tracks` to understand the
  current project before making changes.
- All mutating tools wrap their work in a single REAPER undo step, so the user
  can Ctrl+Z. Tool names appear in REAPER's undo history.
- `reaper_eval` is an escape hatch: send arbitrary Lua. The `reaper` global is
  available; values you `return` are JSON-encoded back. Prefer the typed tools
  when one fits — they are easier on tokens and produce cleaner undo entries.
- Track / item / region indices are 0-based unless a tool's docstring says
  otherwise.

If a tool errors with "timeout waiting for bridge response", the bridge is not
running — ask the user to launch REAPER and load the bridge script.
"""


mcp = FastMCP("reaper", instructions=INSTRUCTIONS)


# ----------------------------------------------------------------------------
# Core / diagnostic tools
# ----------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Health check: confirm the REAPER bridge is running. "
        "Returns {pong: true, time: <reaper time>} on success."
    )
)
async def ping() -> dict:
    return await bridge_ping()


@mcp.tool(
    description=(
        "Execute arbitrary Lua inside REAPER. The `reaper` global is available; "
        "values you `return` are sent back as JSON. Use this for anything not "
        "covered by a typed tool. Example: `return reaper.GetNumTracks()`. "
        "If you pass `args`, it is exposed in the chunk as the variable `args`."
    )
)
async def reaper_eval(
    code: str,
    label: str = "eval",
    undo: bool = True,
    args: Any = None,
) -> Any:
    return await eval_lua(code, args=args, label=label, undo=undo)


@mcp.tool(
    description=(
        "Print the bridge directory the Python side is using. Useful when "
        "diagnosing setup issues (it must match the Lua side)."
    )
)
async def bridge_status() -> dict:
    d, source = resolve_bridge_dir()
    try:
        info = await bridge_ping(timeout=2.0)
        running = True
    except BridgeError as e:
        info = {"error": str(e)}
        running = False
    return {
        "bridge_dir": str(d),
        "bridge_dir_source": source,
        "bridge_dir_exists": d.exists(),
        "bridge_running": running,
        "ping": info,
    }


# ----------------------------------------------------------------------------
# Domain tool registration
# ----------------------------------------------------------------------------

project.register(mcp)
tracks.register(mcp)
editing.register(mcp)
midi.register(mcp)
mixing.register(mcp)
render.register(mcp)
batch.register(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
