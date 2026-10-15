"""Cross-platform installer for the in-REAPER Lua bridge.

Copies the bundled Lua files (server/bridge_lua/) into REAPER's Scripts
folder, optionally wires up auto-start via Scripts/__startup.lua, and writes a
locator file so the Python side can find the bridge data dir without env vars
— including for portable REAPER installs.
"""

from __future__ import annotations

import re
import sys
from importlib import resources
from pathlib import Path

from server.bridge_client import (
    BRIDGE_DATA_DIRNAME,
    default_resource_dir,
    read_locator,
    write_locator,
)

LUA_FILES = ("json.lua", "reaper_mcp_bridge.lua")
STARTUP_LINE = (
    'dofile(reaper.GetResourcePath() .. "/Scripts/reaper_mcp_bridge.lua")'
    "  -- reaper-mcp-bridge"
)


class InstallError(RuntimeError):
    pass


def find_resource_dir(
    reaper_dir: str | None = None,
    resource_dir: str | None = None,
) -> Path:
    """Locate REAPER's resource directory (where Scripts/ and reaper.ini live).

    Priority: explicit --resource-dir > --reaper-dir (portable detection) >
    platform default. Portable installs keep reaper.ini next to the program.
    """
    if resource_dir:
        return Path(resource_dir)

    if reaper_dir:
        d = Path(reaper_dir)
        if not d.is_dir():
            raise InstallError(f"--reaper-dir does not exist: {d}")
        if (d / "reaper.ini").exists():
            return d  # portable install: resources sit next to the program
        default = default_resource_dir()
        if default.exists():
            print(
                f"note: no reaper.ini in {d} (not a portable install); "
                f"using standard resource dir {default}"
            )
            return default
        raise InstallError(
            f"no reaper.ini in {d} and no standard resource dir at {default}. "
            "Launch REAPER once, or pass --resource-dir explicitly."
        )

    # A previous install recorded where the bridge lives — stick to it. This
    # matters when a stale standard-install dir (%APPDATA%\REAPER) coexists
    # with the portable install actually in use.
    prior = read_locator()
    if prior is not None:
        res = prior.parent.parent  # <resource>/Scripts/<data dir>
        if (res / "Scripts").is_dir():
            print(f"note: reusing resource dir from previous install: {res}")
            return res

    default = default_resource_dir()
    if default.exists():
        return default
    raise InstallError(
        f"REAPER resource dir not found at {default}. If REAPER is a portable "
        "install, pass --reaper-dir <folder containing reaper.exe>; otherwise "
        "launch REAPER once so it creates its config, then retry."
    )


def _ensure_autostart(scripts_dir: Path) -> str:
    startup = scripts_dir / "__startup.lua"
    if startup.exists():
        existing = startup.read_text(encoding="utf-8")
        if re.search(r"reaper_mcp_bridge\.lua", existing):
            return f"auto-start already configured in {startup}"
        with startup.open("a", encoding="utf-8", newline="") as f:
            f.write("\r\n" if sys.platform == "win32" else "\n")
            f.write(STARTUP_LINE + ("\r\n" if sys.platform == "win32" else "\n"))
        return f"appended bridge loader to {startup}"
    startup.write_text(STARTUP_LINE + "\n", encoding="utf-8")
    return f"created {startup} with bridge loader"


def install_bridge(
    reaper_dir: str | None = None,
    resource_dir: str | None = None,
    autostart: bool = False,
) -> Path:
    """Install the Lua bridge. Returns the bridge data dir. Prints progress."""
    res = find_resource_dir(reaper_dir, resource_dir)
    print(f"REAPER resource dir: {res}")

    scripts_dir = res / "Scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    lua_root = resources.files("server").joinpath("bridge_lua")
    for name in LUA_FILES:
        src = lua_root.joinpath(name)
        dst = scripts_dir / name
        dst.write_bytes(src.read_bytes())
        print(f"copied : {name} -> {dst}")

    if autostart:
        print(_ensure_autostart(scripts_dir))

    data_dir = scripts_dir / BRIDGE_DATA_DIRNAME
    data_dir.mkdir(parents=True, exist_ok=True)
    locator = write_locator(data_dir)
    print(f"bridge data dir    : {data_dir}")
    print(f"locator written    : {locator}")

    print()
    print("Done. Next steps:")
    if autostart:
        print("  1. Restart REAPER - the bridge loads automatically.")
    else:
        print("  1. In REAPER: Actions -> Show action list -> Load ReaScript ->")
        print(f"     {scripts_dir / 'reaper_mcp_bridge.lua'} -> Run")
        print("     (re-run `install-bridge --autostart` to make this automatic)")
    print("  2. Verify with: reaper-mcp-bridge doctor")
    return data_dir
