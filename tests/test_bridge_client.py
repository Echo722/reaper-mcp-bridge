"""Unit tests for the file-IPC client. A background thread plays the role of
the in-REAPER Lua bridge (reads *.req.json, writes *.res.json), so no REAPER
is needed."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import bridge_client
from server.bridge_client import (
    BridgeError,
    call_sync,
    default_resource_dir,
    locator_path,
    resolve_bridge_dir,
    write_locator,
)


class FakeBridge:
    """Polls a dir like the Lua bridge does and answers every request."""

    def __init__(self, directory: Path, make_response, delay: float = 0.0):
        self.dir = directory
        self.make_response = make_response  # req dict -> res dict (sans id)
        self.delay = delay
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            for req_path in self.dir.glob("*.req.json"):
                try:
                    req = json.loads(req_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if self.delay:
                    time.sleep(self.delay)
                res = {"id": req["id"], **self.make_response(req)}
                res_path = self.dir / f"{req['id']}.res.json"
                res_path.write_text(json.dumps(res), encoding="utf-8")
                req_path.unlink(missing_ok=True)
            time.sleep(0.01)


@pytest.fixture
def bridge_dir(tmp_path, monkeypatch):
    d = tmp_path / "bridge_data"
    monkeypatch.setenv("REAPER_MCP_BRIDGE_DIR", str(d))
    return d


def test_round_trip_ok(bridge_dir):
    def respond(req):
        assert req["kind"] == "ping"
        return {"ok": True, "result": {"pong": True}}

    with FakeBridge(bridge_dir, respond):
        res = call_sync("ping", timeout=5.0)
    assert res.ok
    assert res.result == {"pong": True}
    # response file is consumed
    assert list(bridge_dir.glob("*.res.json")) == []


def test_error_response_raises_with_console(bridge_dir):
    def respond(req):
        return {"ok": False, "error": "boom", "console": "printed stuff"}

    with FakeBridge(bridge_dir, respond):
        res = call_sync("eval", timeout=5.0, code="error('boom')")
    with pytest.raises(BridgeError) as ei:
        res.raise_for_error()
    assert "boom" in str(ei.value)
    assert "printed stuff" in str(ei.value)


def test_timeout_cleans_up_request(bridge_dir):
    with pytest.raises(BridgeError, match="timeout"):
        call_sync("ping", timeout=0.3)
    # the stale request file was removed so it can't pile up
    assert list(bridge_dir.glob("*.req.json")) == []


def test_half_written_response_is_retried(bridge_dir):
    """Client must tolerate reading a response mid-write (invalid JSON) and
    pick up the complete version on a later poll."""

    def respond_eventually(req):
        res_path = bridge_dir / f"{req['id']}.res.json"
        res_path.write_text('{"ok": tr', encoding="utf-8")  # torn write
        time.sleep(0.2)  # let the client read the garbage at least once
        return {"ok": True, "result": 42}

    with FakeBridge(bridge_dir, respond_eventually):
        res = call_sync("ping", timeout=5.0)
    assert res.ok
    assert res.result == 42


def test_args_passed_through(bridge_dir):
    seen = {}

    def respond(req):
        seen.update(req)
        return {"ok": True, "result": None}

    with FakeBridge(bridge_dir, respond):
        call_sync("eval", timeout=5.0, code="return args", args=[1, "x", {"k": 2}])
    assert seen["args"] == [1, "x", {"k": 2}]
    assert seen["code"] == "return args"


# ---------------------------------------------------------------------------
# bridge dir resolution order: env > locator file > platform default
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point the locator config root at a temp dir on every platform."""
    monkeypatch.delenv("REAPER_MCP_BRIDGE_DIR", raising=False)
    monkeypatch.setattr(
        bridge_client, "_config_root", lambda: tmp_path / "config-root"
    )
    return tmp_path


def test_resolution_env_wins(isolated_config, monkeypatch):
    write_locator(isolated_config / "from-locator")
    monkeypatch.setenv("REAPER_MCP_BRIDGE_DIR", str(isolated_config / "from-env"))
    path, source = resolve_bridge_dir()
    assert path == isolated_config / "from-env"
    assert "env" in source


def test_resolution_locator_beats_default(isolated_config):
    write_locator(isolated_config / "from-locator")
    path, source = resolve_bridge_dir()
    assert path == isolated_config / "from-locator"
    assert "locator" in source


def test_resolution_falls_back_to_platform_default(isolated_config):
    path, source = resolve_bridge_dir()
    assert path == default_resource_dir() / "Scripts" / "reaper_mcp_bridge_data"
    assert source == "platform default"


def test_locator_round_trip(isolated_config):
    target = isolated_config / "somewhere" / "bridge_data"
    p = write_locator(target)
    assert p == locator_path()
    assert bridge_client.read_locator() == target


def test_corrupt_locator_is_ignored(isolated_config):
    p = locator_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json at all", encoding="utf-8")
    path, source = resolve_bridge_dir()
    assert source == "platform default"
