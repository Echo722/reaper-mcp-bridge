# reaper-mcp-bridge

[中文文档](README.zh-CN.md)

Control [REAPER](https://www.reaper.fm/) from AI agents — Claude (Desktop / Code), Codex, or any MCP-capable client. Build projects, manage tracks, record and edit, write MIDI, mix, render, batch-rename/export — by talking to your agent in plain language.

```
Claude / Codex / any MCP client
        │  MCP (stdio, JSON-RPC) — agent spawns the server as a subprocess
        ▼
Python MCP server  (this package)
        │  file IPC: writes <id>.req.json / reads <id>.res.json
        ▼
Lua bridge script  (resident inside REAPER via reaper.defer)
        │  ReaScript API
        ▼
REAPER
```

Design highlights:

- **No extra moving parts** — no reapy, no network ports, no firewall prompts. The Python server and REAPER talk through JSON files in a directory.
- **Two layers of tools**:
  - ~50 typed, discoverable, undo-friendly tools (tracks / editing / MIDI / mixing / rendering / batch);
  - `reaper_eval` as an escape hatch — the agent can run arbitrary Lua inside REAPER for anything not covered.
- **Undoable** — every mutating tool is wrapped in a single REAPER undo block. Ctrl+Z works, and tool names show up in REAPER's undo history.

## Quick start

Prerequisites:

- REAPER
- [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv` / `brew install uv`). uv fetches a suitable Python and the dependencies on its own, so no separate Python install is needed.
- [Git](https://git-scm.com/downloads), which uv uses to download this repository. No Git? See [Install without Git](#install-without-git).

Every command below runs the package straight from this GitHub repository.

### 1. Install the Lua bridge into REAPER (once)

```sh
uvx --from git+https://github.com/Echo722/reaper-mcp-bridge reaper-mcp-bridge install-bridge --autostart
```

This auto-detects your REAPER install (portable installs: add `--reaper-dir "D:\REAPER"`), copies the bridge script into REAPER's `Scripts/` folder, and wires it to load on startup. Restart REAPER; its console should show:

```
[MCP] bridge listening @ <...>/Scripts/reaper_mcp_bridge_data
```

Verify end-to-end:

```sh
uvx --from git+https://github.com/Echo722/reaper-mcp-bridge reaper-mcp-bridge doctor
```

### 2. Register the server with your agent (once per client)

**Claude Code**

```sh
claude mcp add --scope user reaper -- uvx --from git+https://github.com/Echo722/reaper-mcp-bridge reaper-mcp-bridge
```

**Claude Desktop** — merge [examples/claude_desktop_config.example.json](examples/claude_desktop_config.example.json) into your `claude_desktop_config.json`, then fully quit and relaunch Claude Desktop.

**Codex CLI** — add to `~/.codex/config.toml` (see [examples/codex_config.example.toml](examples/codex_config.example.toml)):

```toml
[mcp_servers.reaper]
command = "uvx"
args = ["--from", "git+https://github.com/Echo722/reaper-mcp-bridge", "reaper-mcp-bridge"]
```

Any other MCP client that supports stdio servers works the same way: the command is `uvx`, the arguments are `--from git+https://github.com/Echo722/reaper-mcp-bridge reaper-mcp-bridge`.

### 3. Use it

Open REAPER, then ask your agent things like:

- "Look at the current project: list all tracks and describe the structure."
- "Create a track called Drums and color it dark red."
- "Insert a 4-bar C–Am–F–G progression on track 0, one chord per bar."
- "Rename all regions to `Take_$num` starting from 01."
- "Export every region to `D:\bounces\session1\`, named after the region."

## Updating

uv caches the package after the first run. To pick up the latest version from GitHub, refresh it once, then restart your agent (or reconnect the `reaper` server) so it starts the new version:

```sh
uvx --refresh --from git+https://github.com/Echo722/reaper-mcp-bridge reaper-mcp-bridge doctor
```

## Install without Git

Replace the `git+https://...` source with GitHub's zip download of the `main` branch in every command above, for example:

```sh
uvx --from https://github.com/Echo722/reaper-mcp-bridge/archive/refs/heads/main.zip reaper-mcp-bridge install-bridge --autostart
```

## Tool overview

| Domain | Tools |
|--------|-------|
| Diagnostics | `ping`, `bridge_status`, `reaper_eval` |
| Project | `get_project_info`, `list_tracks`, `list_regions`, `list_markers`, `new_project`, `save_project_as` |
| Tracks | `add_track`, `delete_track`, `rename_track`, `set_track_volume_db`, `set_track_pan`, `set_track_mute`, `set_track_solo`, `set_track_record_arm`, `set_track_color`, `set_track_folder_depth`, `select_tracks` |
| Record / edit | `play`, `stop`, `record`, `set_cursor`, `set_time_selection`, `clear_time_selection`, `split_items_at_time`, `move_selected_items`, `set_selected_item_fades`, `glue_selected_items`, `set_record_input`, `select_items_on_track` |
| MIDI | `insert_midi_item`, `insert_midi_notes`, `create_chord_progression`, `quantize_midi_item` |
| Mixing | `add_fx`, `remove_fx`, `list_fx`, `set_fx_param`, `set_fx_enabled`, `set_master_volume_db` |
| Render | `render_with_current_settings`, `render`, `get_render_settings` |
| Batch | `batch_rename_items`, `batch_rename_regions`, `batch_export_regions`, `normalize_loudness`, `apply_template` |

`reaper_eval` covers anything else via the [ReaScript API](https://www.reaper.fm/sdk/reascript/reascripthelp.html).

## Security

**`reaper_eval` is arbitrary code execution on your machine.** The Lua environment inside REAPER has full access to `os`, `io`, etc. — any agent allowed to call this server can, in principle, run any command as you. This is by design (it is the escape hatch that makes the tool set complete), and it is fine for the intended use: a trusted, local agent you operate yourself. Do **not** expose this server to untrusted clients, and review your agent's tool-permission settings if you want a human in the loop for `reaper_eval`.

## Concurrency

Multiple agents can be registered (and even connected) at the same time — each spawns its own server process, and requests never collide thanks to per-request IDs. However, the tools are **not** coordinated across agents: two agents editing the same project simultaneously will interleave undo entries and stomp on each other's selections. Recommended usage: let one agent work at a time.

## Custom bridge directory

By default the bridge data dir lives at `<REAPER resource path>/Scripts/reaper_mcp_bridge_data`, and `install-bridge` records its location so the Python side finds it automatically (env `REAPER_MCP_BRIDGE_DIR` > locator file > platform default). To relocate it, set `REAPER_MCP_BRIDGE_DIR` in both the environment REAPER starts from and the `env` block of your MCP client config.

## Troubleshooting

- **"timeout waiting for bridge response"** — REAPER isn't open, or the bridge script isn't running. Run the `doctor` command from [Quick start](#1-install-the-lua-bridge-into-reaper-once).
- **No `[MCP] bridge listening` line in REAPER's console** — re-run `install-bridge --autostart` and restart REAPER, or load `Scripts/reaper_mcp_bridge.lua` manually via the Actions list.
- **REAPER is open but the bridge never starts** — a startup dialog (e.g. "Choose Project" / crash recovery) blocks `__startup.lua` until dismissed. Close the dialog; the bridge loads right after.
- **Doctor says the dir exists but ping fails** — make sure the dir REAPER prints in its console matches the one doctor prints.

## Development

```sh
git clone https://github.com/Echo722/reaper-mcp-bridge && cd reaper-mcp-bridge
uv run reaper-mcp-bridge doctor      # uv creates the env on first run
uv run --with pytest pytest          # unit tests (no REAPER needed)
uv run python tests/e2e_ping.py      # end-to-end (REAPER + bridge running)
```

Repo layout:

```
server/
  app.py            # FastMCP entry point (tool registration)
  cli.py            # console entry: serve / install-bridge / doctor
  installer.py      # cross-platform Lua bridge installer
  bridge_client.py  # file IPC client + bridge dir resolution
  bridge_lua/       # the Lua side (shipped as package data)
  tools/            # typed tools by domain
examples/           # MCP client config templates
tests/
```

## License

MIT. `server/bridge_lua/json.lua` is [rxi/json.lua](https://github.com/rxi/json.lua) (MIT, copyright header retained in file).
