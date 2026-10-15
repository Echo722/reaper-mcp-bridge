# reaper-mcp-bridge

[English](README.md)

让 AI agent——Claude(Desktop / Code)、Codex 或任何支持 MCP 的客户端——用自然语言操控 [REAPER](https://www.reaper.fm/):建工程、管轨道、录音编辑、MIDI 编曲、混音渲染、批量命名/导出。

```
Claude / Codex / 任何 MCP 客户端
        │  MCP (stdio, JSON-RPC) —— agent 把 server 作为子进程拉起
        ▼
Python MCP server(本包)
        │  文件 IPC:写 <id>.req.json / 读 <id>.res.json
        ▼
Lua 桥脚本(经 reaper.defer 常驻 REAPER 内)
        │  ReaScript API
        ▼
REAPER
```

设计要点:

- **零额外组件**——不用 reapy、不开端口、不碰防火墙,Python 与 REAPER 之间靠目录里的 JSON 文件通信。
- **双层工具**:~50 个有类型、好发现、可撤销的高层工具(轨道/编辑/MIDI/混音/渲染/批量),加上 `reaper_eval` 万能逃生口(agent 可直接在 REAPER 里跑任意 Lua)。
- **可撤销**——所有写操作包在单个 REAPER undo block 里,随时 Ctrl+Z,工具名出现在撤销历史中。

## 快速开始

前置:

- REAPER
- [uv](https://docs.astral.sh/uv/)(`winget install astral-sh.uv` / `brew install uv`)。uv 会自己准备合适的 Python 和依赖,不用另装 Python。
- [Git](https://git-scm.com/downloads),uv 用它从 GitHub 下载本仓库。没有 Git?见[不用 Git 安装](#不用-git-安装)。

### 1. 安装(一次性)

```sh
uv tool install git+https://github.com/Echo722/reaper-mcp-bridge
```

装好后会多出一个 `reaper-mcp-bridge` 命令。agent 在本机直接运行它,之后断网也能用。如果提示找不到命令,运行 `uv tool update-shell` 后重新打开终端。

### 2. 把 Lua 桥装进 REAPER(一次性)

```sh
reaper-mcp-bridge install-bridge --autostart
```

自动探测 REAPER 安装位置(便携版加 `--reaper-dir "D:\REAPER"`),把桥脚本拷进 `Scripts/` 并设置开机自动加载。重启 REAPER,控制台应显示:

```
[MCP] bridge listening @ <...>/Scripts/reaper_mcp_bridge_data
```

验证链路:

```sh
reaper-mcp-bridge doctor
```

### 3. 在 agent 里注册(每个客户端一次)

**Claude Code**

```sh
claude mcp add --scope user reaper -- reaper-mcp-bridge
```

**Claude Desktop**——把 [examples/claude_desktop_config.example.json](examples/claude_desktop_config.example.json) 合并进你的 `claude_desktop_config.json`,完全退出再重启 Desktop。

**Codex CLI**——在 `~/.codex/config.toml` 里加(见 [examples/codex_config.example.toml](examples/codex_config.example.toml)):

```toml
[mcp_servers.reaper]
command = "reaper-mcp-bridge"
```

其他支持 stdio 的 MCP 客户端同理:命令 `reaper-mcp-bridge`,不需要参数。客户端找不到命令时就填完整路径,`uv tool dir --bin` 会打印它所在的文件夹。

### 4. 开始用

打开 REAPER,对 agent 说:

- "看一下当前工程:列出所有轨道,告诉我大致结构。"
- "新建一条叫 Drums 的轨道,颜色设成暗红色。"
- "在轨道 0 插一段 4 小节的 C–Am–F–G 进行,每个和弦一小节。"
- "把所有 region 重命名成 `Take_$num` 格式,从 01 开始。"
- "把所有 region 导出到 `D:\bounces\session1\`,文件名用 region 名字。"

## 更新

```sh
uv tool upgrade reaper-mcp-bridge
```

然后重启 agent(或重连 `reaper` 服务),让它启动新版本。

## 不用 Git 安装

改用 GitHub 上 `main` 分支的 zip 下载地址安装:

```sh
uv tool install https://github.com/Echo722/reaper-mcp-bridge/archive/refs/heads/main.zip
```

更新时在同一条命令后面加上 `--reinstall`。其余步骤和[快速开始](#快速开始)一样。

## 工具速览

| 模块 | 工具 |
|------|------|
| 诊断 | `ping`, `bridge_status`, `reaper_eval` |
| 工程 | `get_project_info`, `list_tracks`, `list_regions`, `list_markers`, `new_project`, `save_project_as` |
| 轨道 | `add_track`, `delete_track`, `rename_track`, `set_track_volume_db`, `set_track_pan`, `set_track_mute`, `set_track_solo`, `set_track_record_arm`, `set_track_color`, `set_track_folder_depth`, `select_tracks` |
| 录音/编辑 | `play`, `stop`, `record`, `set_cursor`, `set_time_selection`, `clear_time_selection`, `split_items_at_time`, `move_selected_items`, `set_selected_item_fades`, `glue_selected_items`, `set_record_input`, `select_items_on_track` |
| MIDI | `insert_midi_item`, `insert_midi_notes`, `create_chord_progression`, `quantize_midi_item` |
| 混音 | `add_fx`, `remove_fx`, `list_fx`, `set_fx_param`, `set_fx_enabled`, `set_master_volume_db` |
| 渲染 | `render_with_current_settings`, `render`, `get_render_settings` |
| 批量 | `batch_rename_items`, `batch_rename_regions`, `batch_export_regions`, `normalize_loudness`, `apply_template` |

其余 ReaScript 操作由 `reaper_eval` 兜底,参考 [ReaScript API](https://www.reaper.fm/sdk/reascript/reascripthelp.html)。

## 安全

**`reaper_eval` 等于在你机器上执行任意代码。** REAPER 内的 Lua 环境可以访问 `os`、`io` 等——任何被允许调用本 server 的 agent 原则上都能以你的身份运行任意命令。这是设计使然(逃生口让工具集保持完备),在预期用法下没有问题:你自己操作的、可信的本机 agent。**不要**把本 server 暴露给不可信的客户端;如果希望 `reaper_eval` 有人工把关,请在 agent 的工具权限里设置。

## 并发

可以同时给多个 agent 注册(甚至同时连接)——每个 agent 拉起自己的 server 进程,请求靠唯一 ID 互不冲突。但工具**不做跨 agent 协调**:两个 agent 同时改同一个工程会导致 undo 历史交错、选区互踩。建议同一时间只让一个 agent 干活。

## 自定义桥目录

桥数据目录默认在 `<REAPER resource path>/Scripts/reaper_mcp_bridge_data`,`install-bridge` 会记录实际位置,Python 端自动找到它(解析顺序:env `REAPER_MCP_BRIDGE_DIR` > locator 文件 > 平台默认)。要挪位置,就在 REAPER 启动环境和 MCP 客户端配置的 `env` 块里同时设 `REAPER_MCP_BRIDGE_DIR`。

## 故障排查

- **"timeout waiting for bridge response"**——REAPER 没开或桥脚本没跑。执行 `reaper-mcp-bridge doctor`。
- **REAPER 控制台没有 `[MCP] bridge listening`**——重跑 `reaper-mcp-bridge install-bridge --autostart` 并重启 REAPER,或在 Actions 列表手动加载 `Scripts/reaper_mcp_bridge.lua`。
- **REAPER 开着但桥一直不启动**——启动时的对话框(如 "Choose Project" / 崩溃恢复)会阻塞 `__startup.lua`,关掉对话框后桥立即加载。
- **doctor 显示目录存在但 ping 失败**——核对 REAPER 控制台打印的目录与 doctor 打印的目录是否一致。

## 开发

```sh
git clone https://github.com/Echo722/reaper-mcp-bridge && cd reaper-mcp-bridge
uv run reaper-mcp-bridge doctor      # 首次运行 uv 自动建环境
uv run --with pytest pytest          # 单元测试(不需要 REAPER)
uv run python tests/e2e_ping.py      # 端到端(需 REAPER + 桥在跑)
```

## 许可

MIT。`server/bridge_lua/json.lua` 来自 [rxi/json.lua](https://github.com/rxi/json.lua)(MIT,版权头保留在文件内)。
