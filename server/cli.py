"""Console entry point for reaper-mcp-bridge.

Subcommands:
    serve           Run the MCP server over stdio (default when no args, so
                    MCP client configs don't need a subcommand).
    install-bridge  Copy the Lua bridge into REAPER and (optionally) auto-start it.
    doctor          Diagnose bridge connectivity.
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _cmd_serve(_args: argparse.Namespace) -> int:
    from server.app import main as serve_main

    serve_main()
    return 0


def _cmd_install_bridge(args: argparse.Namespace) -> int:
    from server.installer import InstallError, install_bridge

    try:
        install_bridge(
            reaper_dir=args.reaper_dir,
            resource_dir=args.resource_dir,
            autostart=args.autostart,
        )
    except InstallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_doctor(_args: argparse.Namespace) -> int:
    from server.bridge_client import BridgeError, ping, resolve_bridge_dir

    d, source = resolve_bridge_dir()
    print(f"bridge data dir : {d}")
    print(f"resolved via    : {source}")
    print(f"dir exists      : {d.exists()}")

    try:
        info = asyncio.run(ping(timeout=3.0))
    except BridgeError as e:
        print("bridge running  : NO")
        print(f"  {e}")
        print()
        print("Checklist:")
        print("  - Is REAPER open?")
        print("  - Did you run `reaper-mcp-bridge install-bridge --autostart` and restart REAPER?")
        print("  - REAPER's console should show: [MCP] bridge listening @ <dir>")
        print("  - That <dir> must match the bridge data dir above.")
        return 1
    print(f"bridge running  : YES (pong, reaper time {info.get('time')})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="reaper-mcp-bridge",
        description="MCP server for controlling the REAPER DAW.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="run the MCP server over stdio (default)")

    p_install = sub.add_parser(
        "install-bridge", help="install the Lua bridge into REAPER"
    )
    p_install.add_argument(
        "--reaper-dir",
        help="REAPER program folder (portable installs: where reaper.exe and reaper.ini live)",
    )
    p_install.add_argument(
        "--resource-dir",
        help="REAPER resource folder, overrides detection (where Scripts/ lives)",
    )
    p_install.add_argument(
        "--autostart",
        action="store_true",
        help="load the bridge automatically on REAPER startup (via Scripts/__startup.lua)",
    )

    sub.add_parser("doctor", help="diagnose bridge connectivity")

    args = parser.parse_args()
    command = args.command or "serve"
    handler = {
        "serve": _cmd_serve,
        "install-bridge": _cmd_install_bridge,
        "doctor": _cmd_doctor,
    }[command]
    sys.exit(handler(args))


if __name__ == "__main__":
    main()
