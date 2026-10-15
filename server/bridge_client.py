"""
File-based IPC client to the in-REAPER Lua bridge.

Writes <id>.req.json into the bridge dir (atomically), polls for <id>.res.json,
returns the decoded payload. Sync impl exposed as `call_sync`; an async wrapper
`call` runs it in a thread for use from FastMCP tool handlers.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BRIDGE_DATA_DIRNAME = "reaper_mcp_bridge_data"
DEFAULT_TIMEOUT = 30.0  # seconds
POLL_INTERVAL = 0.05    # 50 ms


class BridgeError(RuntimeError):
    """Raised when the bridge returns ok=false or never responds."""


@dataclass
class BridgeResponse:
    ok: bool
    result: Any
    error: str | None
    console: str

    def raise_for_error(self) -> "BridgeResponse":
        if not self.ok:
            msg = self.error or "unknown bridge error"
            if self.console:
                msg = f"{msg}\n--- console ---\n{self.console}"
            raise BridgeError(msg)
        return self


def _config_root() -> Path:
    """Per-user config dir for this tool (locator file lives here)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "reaper-mcp-bridge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "reaper-mcp-bridge"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "reaper-mcp-bridge"


def locator_path() -> Path:
    """The locator file written by `reaper-mcp-bridge install-bridge`. It records
    which REAPER resource dir the bridge was installed into, so portable
    installs work without setting REAPER_MCP_BRIDGE_DIR by hand."""
    return _config_root() / "config.json"


def read_locator() -> Path | None:
    try:
        data = json.loads(locator_path().read_text(encoding="utf-8"))
        raw = data.get("bridge_dir")
        return Path(raw) if raw else None
    except (OSError, json.JSONDecodeError):
        return None


def write_locator(bridge_data_dir: Path) -> Path:
    p = locator_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"bridge_dir": str(bridge_data_dir)}, indent=2),
        encoding="utf-8",
    )
    return p


def default_resource_dir() -> Path:
    """REAPER's resource path for a standard (non-portable) install. Matches
    what reaper.GetResourcePath() returns on each platform."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "REAPER"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "REAPER"
    return Path.home() / ".config" / "REAPER"


def resolve_bridge_dir() -> tuple[Path, str]:
    """Resolve the bridge data dir and say where the answer came from
    (for `doctor` diagnostics). Order: env var > locator file > platform default."""
    env = os.environ.get("REAPER_MCP_BRIDGE_DIR")
    if env:
        return Path(env), "env REAPER_MCP_BRIDGE_DIR"
    loc = read_locator()
    if loc is not None:
        return loc, f"locator file {locator_path()}"
    return default_resource_dir() / "Scripts" / BRIDGE_DATA_DIRNAME, "platform default"


def bridge_dir() -> Path:
    return resolve_bridge_dir()[0]


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    # On Windows, os.replace is atomic and overwrites.
    os.replace(tmp, path)


def call_sync(
    kind: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    **fields: Any,
) -> BridgeResponse:
    """Send one request to the bridge and block until the response arrives."""
    d = bridge_dir()
    d.mkdir(parents=True, exist_ok=True)

    req_id = uuid.uuid4().hex
    payload = {"id": req_id, "kind": kind, **fields}
    req_path = d / f"{req_id}.req.json"
    res_path = d / f"{req_id}.res.json"

    _atomic_write(req_path, json.dumps(payload, ensure_ascii=False))

    deadline = time.monotonic() + timeout
    while True:
        if res_path.exists():
            try:
                raw = res_path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                # Half-written; back off one tick and retry.
                time.sleep(POLL_INTERVAL)
                continue
            try:
                res_path.unlink()
            except OSError:
                pass
            return BridgeResponse(
                ok=bool(data.get("ok")),
                result=data.get("result"),
                error=data.get("error"),
                console=data.get("console") or "",
            )

        if time.monotonic() > deadline:
            # Stale request: try to clean up so it doesn't pile up.
            try:
                req_path.unlink()
            except OSError:
                pass
            raise BridgeError(
                f"timeout after {timeout:.1f}s waiting for bridge response. "
                f"Is the Lua bridge running inside REAPER? "
                f"(bridge dir: {d})"
            )
        time.sleep(POLL_INTERVAL)


async def call(
    kind: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    **fields: Any,
) -> BridgeResponse:
    """Async wrapper that runs call_sync in a worker thread."""
    return await asyncio.to_thread(call_sync, kind, timeout=timeout, **fields)


async def eval_lua(
    code: str,
    *,
    args: Any = None,
    label: str | None = None,
    undo: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Run a chunk of Lua inside REAPER. Returns the eval result (already decoded).

    `args` (any JSON-encodable value) is exposed in the Lua chunk as the
    local-ish variable `args` — use this to pass user inputs instead of string
    interpolation.
    """
    payload: dict[str, Any] = {"code": code, "label": label, "undo": undo}
    if args is not None:
        payload["args"] = args
    res = await call("eval", timeout=timeout, **payload)
    res.raise_for_error()
    return res.result


async def ping(timeout: float = 5.0) -> dict:
    """Sanity-check the bridge."""
    res = await call("ping", timeout=timeout)
    res.raise_for_error()
    return res.result
