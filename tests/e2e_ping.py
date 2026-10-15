r"""End-to-end smoke test for the REAPER MCP bridge — does NOT go through Claude.

What it does:
  1. Reports which bridge dir the Python side is using.
  2. Sends a `ping` to the in-REAPER Lua bridge.
  3. Runs a tiny eval that returns reaper.GetNumTracks() and the project length.

Run AFTER you have REAPER open with reaper_mcp_bridge.lua loaded.

Usage:
    uv run python tests/e2e_ping.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

# Make `server.*` importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.bridge_client import BridgeError, bridge_dir, eval_lua, ping


async def main() -> int:
    d = bridge_dir()
    print(f"bridge dir : {d}")
    print(f"exists     : {d.exists()}")
    if not d.exists():
        print("  (will be created on first request; that's fine)")

    print("\n[1/2] ping ...")
    try:
        info = await ping(timeout=5.0)
        print(f"     ok: {info}")
    except BridgeError as e:
        print(f"     FAILED: {e}")
        print("     -> Is REAPER running with reaper_mcp_bridge.lua loaded?")
        return 1

    print("\n[2/2] eval reaper.GetNumTracks() + project length ...")
    try:
        result = await eval_lua(
            r"return { tracks = reaper.GetNumTracks(), length = reaper.GetProjectLength(0) }",
            label="test_ping",
            undo=False,
        )
        print(f"     ok: {result}")
    except BridgeError as e:
        print(f"     FAILED: {e}")
        return 1

    print("\n[OK] bridge round trip works end-to-end")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(2)
