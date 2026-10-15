"""Project-level read tools and project file management."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from server.bridge_client import eval_lua


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Get an overview of the current REAPER project: file path, sample "
            "rate, length in seconds, play state, track count, region count, "
            "marker count, time selection. Call this first to orient yourself."
        )
    )
    async def get_project_info() -> dict:
        code = r"""
            local proj = 0  -- current project
            local _, path = reaper.EnumProjects(-1, "")
            local sr = reaper.GetSetProjectInfo(proj, "PROJECT_SRATE", 0, false)
            local length = reaper.GetProjectLength(proj)
            local play_state = reaper.GetPlayState()  -- bitfield
            local ts_start, ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
            local _, num_markers, num_regions = reaper.CountProjectMarkers(proj)
            return {
                project_path = path,
                sample_rate = sr,
                length_sec = length,
                num_tracks = reaper.CountTracks(proj),
                num_markers = num_markers,
                num_regions = num_regions,
                play_state = play_state,
                playing = (play_state & 1) == 1,
                recording = (play_state & 4) == 4,
                paused = (play_state & 2) == 2,
                time_selection = { start = ts_start, ["end"] = ts_end },
                cursor_pos = reaper.GetCursorPosition(),
            }
        """
        return await eval_lua(code, label="get_project_info", undo=False)

    @mcp.tool(
        description=(
            "List all tracks with index, name, volume (dB), pan (-1..1), mute, "
            "solo, record arm, color (RGB or 0 if none), item count, FX names."
        )
    )
    async def list_tracks() -> list[dict]:
        code = r"""
            local out = {}
            local n = reaper.CountTracks(0)
            for i = 0, n - 1 do
                local tr = reaper.GetTrack(0, i)
                local _, name = reaper.GetTrackName(tr)
                local vol = reaper.GetMediaTrackInfo_Value(tr, "D_VOL")
                local pan = reaper.GetMediaTrackInfo_Value(tr, "D_PAN")
                local mute = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") == 1
                local solo = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO") > 0
                local arm = reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") == 1
                local color = reaper.GetTrackColor(tr)
                local r, g, b = reaper.ColorFromNative(color)
                local n_items = reaper.CountTrackMediaItems(tr)
                local n_fx = reaper.TrackFX_GetCount(tr)
                local fx = {}
                for j = 0, n_fx - 1 do
                    local _, fxname = reaper.TrackFX_GetFXName(tr, j, "")
                    fx[j + 1] = fxname
                end
                local depth = reaper.GetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH")
                out[i + 1] = {
                    index = i,
                    name = name,
                    volume_db = (vol > 0) and (20 * math.log(vol) / math.log(10)) or -150,
                    pan = pan,
                    muted = mute,
                    soloed = solo,
                    record_armed = arm,
                    color_rgb = (color ~= 0) and { r, g, b } or nil,
                    num_items = n_items,
                    fx = fx,
                    folder_depth = depth,  -- 1 = folder start, -1/-2... = end
                }
            end
            return out
        """
        return await eval_lua(code, label="list_tracks", undo=False)

    @mcp.tool(
        description="List all regions in the project: {index, name, start_sec, end_sec, color_rgb}."
    )
    async def list_regions() -> list[dict]:
        code = r"""
            local out = {}
            local _, num_markers, num_regions = reaper.CountProjectMarkers(0)
            local total = num_markers + num_regions
            local k = 1
            for i = 0, total - 1 do
                local _, is_rgn, pos, rgnend, name, idx, color = reaper.EnumProjectMarkers3(0, i)
                if is_rgn then
                    local r, g, b = reaper.ColorFromNative(color)
                    out[k] = {
                        enum_index = i,
                        index = idx,
                        name = name,
                        start_sec = pos,
                        end_sec = rgnend,
                        color_rgb = (color ~= 0) and { r, g, b } or nil,
                    }
                    k = k + 1
                end
            end
            return out
        """
        return await eval_lua(code, label="list_regions", undo=False)

    @mcp.tool(
        description="List all markers (not regions): {enum_index, index, name, time_sec, color_rgb}."
    )
    async def list_markers() -> list[dict]:
        code = r"""
            local out = {}
            local _, num_markers, num_regions = reaper.CountProjectMarkers(0)
            local total = num_markers + num_regions
            local k = 1
            for i = 0, total - 1 do
                local _, is_rgn, pos, _, name, idx, color = reaper.EnumProjectMarkers3(0, i)
                if not is_rgn then
                    local r, g, b = reaper.ColorFromNative(color)
                    out[k] = {
                        enum_index = i, index = idx, name = name,
                        time_sec = pos,
                        color_rgb = (color ~= 0) and { r, g, b } or nil,
                    }
                    k = k + 1
                end
            end
            return out
        """
        return await eval_lua(code, label="list_markers", undo=False)

    @mcp.tool(
        description="Save the current project to a specific path (.rpp). Creates parent dirs if needed."
    )
    async def save_project_as(path: str) -> dict:
        code = r"""
            local p = args[1]
            -- Make sure directory exists
            local dir = p:match("^(.*)[/\\][^/\\]+$")
            if dir then reaper.RecursiveCreateDirectory(dir, 0) end
            reaper.Main_SaveProjectEx(0, p, 0)
            return { saved_to = p }
        """
        return await eval_lua(code, args=[path], label="save_project_as")

    @mcp.tool(
        description=(
            "Create a brand-new empty project in a new tab and switch to it. "
            "Does NOT save the previous project."
        )
    )
    async def new_project() -> dict:
        code = r"""
            -- 40859 = New project tab
            reaper.Main_OnCommand(40859, 0)
            return { ok = true, num_tracks = reaper.CountTracks(0) }
        """
        return await eval_lua(code, label="new_project")
