"""Track create / delete / rename / mix-properties / color / folder structure."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from server.bridge_client import eval_lua
from server.tools._helpers import lua_color


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Add a new track. `name` is optional. `position` is the 0-based "
            "index where to insert; -1 (default) appends at the end. "
            "Returns {index, name}."
        )
    )
    async def add_track(name: str = "", position: int = -1) -> dict:
        code = r"""
            local name = args[1]
            local pos  = args[2]
            local n = reaper.CountTracks(0)
            if pos < 0 or pos > n then pos = n end
            reaper.InsertTrackAtIndex(pos, true)
            local tr = reaper.GetTrack(0, pos)
            if name ~= "" then
                reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", name, true)
            end
            local _, final_name = reaper.GetTrackName(tr)
            return { index = pos, name = final_name }
        """
        return await eval_lua(code, args=[name, position], label=f"add_track {name}".strip())

    @mcp.tool(description="Delete a track by 0-based index.")
    async def delete_track(index: int) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            reaper.DeleteTrack(tr)
            return { deleted = args[1] }
        """
        return await eval_lua(code, args=[index], label=f"delete_track {index}")

    @mcp.tool(description="Rename a track.")
    async def rename_track(index: int, name: str) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", args[2], true)
            return { index = args[1], name = args[2] }
        """
        return await eval_lua(code, args=[index, name], label=f"rename_track -> {name}")

    @mcp.tool(
        description=(
            "Set track volume in dB. Use -150 for -inf (silent). 0 = unity. "
            "Typical mix range: -60..+12."
        )
    )
    async def set_track_volume_db(index: int, db: float) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            local db = args[2]
            local amp = (db <= -150) and 0 or (10 ^ (db / 20))
            reaper.SetMediaTrackInfo_Value(tr, "D_VOL", amp)
            return { index = args[1], db = db, amp = amp }
        """
        return await eval_lua(code, args=[index, db], label=f"set_track_volume {db}dB")

    @mcp.tool(description="Set track pan. -1.0 = full left, 0 = center, 1.0 = full right.")
    async def set_track_pan(index: int, pan: float) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            local p = math.max(-1, math.min(1, args[2]))
            reaper.SetMediaTrackInfo_Value(tr, "D_PAN", p)
            return { index = args[1], pan = p }
        """
        return await eval_lua(code, args=[index, pan], label=f"set_track_pan {pan}")

    @mcp.tool(description="Mute or unmute a track.")
    async def set_track_mute(index: int, muted: bool) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", args[2] and 1 or 0)
            return { index = args[1], muted = args[2] }
        """
        return await eval_lua(code, args=[index, muted], label="mute" if muted else "unmute")

    @mcp.tool(description="Solo or unsolo a track.")
    async def set_track_solo(index: int, soloed: bool) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", args[2] and 2 or 0)
            return { index = args[1], soloed = args[2] }
        """
        return await eval_lua(code, args=[index, soloed], label="solo" if soloed else "unsolo")

    @mcp.tool(description="Arm or disarm a track for recording.")
    async def set_track_record_arm(index: int, armed: bool) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", args[2] and 1 or 0)
            return { index = args[1], armed = args[2] }
        """
        return await eval_lua(code, args=[index, armed], label="arm" if armed else "unarm")

    @mcp.tool(
        description=(
            "Set track color. r/g/b each 0..255. Use r=g=b=0 to clear (revert to default)."
        )
    )
    async def set_track_color(index: int, r: int, g: int, b: int) -> dict:
        if r == 0 and g == 0 and b == 0:
            color = 0
        else:
            color = lua_color(r, g, b)
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            reaper.SetTrackColor(tr, args[2])
            return { index = args[1], color = args[2] }
        """
        return await eval_lua(code, args=[index, color], label="set_track_color")

    @mcp.tool(
        description=(
            "Set folder structure depth for a track. "
            "1 = this track starts a folder, "
            "0 = normal (default), "
            "-1 = end of one folder, -2 = end of two folders, etc. "
            "Use this to group tracks: e.g. set depth=1 on a 'Drums' track and "
            "depth=-1 on the last child."
        )
    )
    async def set_track_folder_depth(index: int, depth: int) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at index " .. args[1]) end
            reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", args[2])
            return { index = args[1], folder_depth = args[2] }
        """
        return await eval_lua(code, args=[index, depth], label=f"folder_depth={depth}")

    @mcp.tool(
        description=(
            "Select tracks by index list (replacing any previous selection). "
            "Pass [] to clear selection."
        )
    )
    async def select_tracks(indices: list[int]) -> dict:
        code = r"""
            -- clear selection
            local n = reaper.CountTracks(0)
            for i = 0, n - 1 do
                reaper.SetTrackSelected(reaper.GetTrack(0, i), false)
            end
            for _, idx in ipairs(args[1]) do
                local tr = reaper.GetTrack(0, idx)
                if tr then reaper.SetTrackSelected(tr, true) end
            end
            return { selected = args[1] }
        """
        return await eval_lua(code, args=[indices], label="select_tracks")
