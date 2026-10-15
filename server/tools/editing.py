"""Time selection, transport, item move/split/glue/fade, record input."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from server.bridge_client import eval_lua


def register(mcp: FastMCP) -> None:

    # --- transport -----------------------------------------------------------

    @mcp.tool(description="Start playback from the edit cursor.")
    async def play() -> dict:
        return await eval_lua(
            "reaper.OnPlayButton(); return { ok = true }",
            label="play", undo=False,
        )

    @mcp.tool(description="Stop playback or recording.")
    async def stop() -> dict:
        return await eval_lua(
            "reaper.OnStopButton(); return { ok = true }",
            label="stop", undo=False,
        )

    @mcp.tool(description="Start recording on all armed tracks.")
    async def record() -> dict:
        return await eval_lua(
            "reaper.CSurf_OnRecord(); return { ok = true }",
            label="record", undo=False,
        )

    @mcp.tool(description="Move the edit cursor to `time_sec`.")
    async def set_cursor(time_sec: float) -> dict:
        code = r"""
            reaper.SetEditCurPos(args[1], true, false)
            return { cursor = args[1] }
        """
        return await eval_lua(code, args=[time_sec], label="set_cursor", undo=False)

    # --- time selection ------------------------------------------------------

    @mcp.tool(description="Set the time selection (loop range) in seconds.")
    async def set_time_selection(start_sec: float, end_sec: float) -> dict:
        code = r"""
            reaper.GetSet_LoopTimeRange(true, false, args[1], args[2], false)
            return { start = args[1], ["end"] = args[2] }
        """
        return await eval_lua(code, args=[start_sec, end_sec], label="set_time_selection")

    @mcp.tool(description="Clear the time selection.")
    async def clear_time_selection() -> dict:
        code = "reaper.GetSet_LoopTimeRange(true, false, 0, 0, false); return { cleared = true }"
        return await eval_lua(code, label="clear_time_selection")

    # --- items ---------------------------------------------------------------

    @mcp.tool(
        description=(
            "Split every item that crosses `time_sec` at that time. If "
            "`selected_only` is true, only split currently-selected items. "
            "Returns count of items created."
        )
    )
    async def split_items_at_time(time_sec: float, selected_only: bool = False) -> dict:
        code = r"""
            local t = args[1]
            local sel_only = args[2]
            local created = 0
            local n_tracks = reaper.CountTracks(0)
            for ti = 0, n_tracks - 1 do
                local tr = reaper.GetTrack(0, ti)
                local n_items = reaper.CountTrackMediaItems(tr)
                for ii = n_items - 1, 0, -1 do  -- reverse so SplitMediaItem indices remain valid
                    local item = reaper.GetTrackMediaItem(tr, ii)
                    if (not sel_only) or reaper.IsMediaItemSelected(item) then
                        local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
                        local len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
                        if pos < t and (pos + len) > t then
                            reaper.SplitMediaItem(item, t)
                            created = created + 1
                        end
                    end
                end
            end
            return { split_count = created, at = t }
        """
        return await eval_lua(code, args=[time_sec, selected_only], label="split_at_cursor")

    @mcp.tool(description="Shift the position of all currently selected items by `delta_sec` seconds.")
    async def move_selected_items(delta_sec: float) -> dict:
        code = r"""
            local d = args[1]
            local n = reaper.CountSelectedMediaItems(0)
            for i = 0, n - 1 do
                local item = reaper.GetSelectedMediaItem(0, i)
                local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
                reaper.SetMediaItemInfo_Value(item, "D_POSITION", pos + d)
            end
            return { moved = n, delta = d }
        """
        return await eval_lua(code, args=[delta_sec], label=f"move_selected {delta_sec}s")

    @mcp.tool(
        description=(
            "Set fade-in and fade-out (seconds) on every selected media item. "
            "Pass -1 for either to leave it unchanged."
        )
    )
    async def set_selected_item_fades(fade_in_sec: float = -1, fade_out_sec: float = -1) -> dict:
        code = r"""
            local fi, fo = args[1], args[2]
            local n = reaper.CountSelectedMediaItems(0)
            for i = 0, n - 1 do
                local item = reaper.GetSelectedMediaItem(0, i)
                if fi >= 0 then
                    reaper.SetMediaItemInfo_Value(item, "D_FADEINLEN", fi)
                end
                if fo >= 0 then
                    reaper.SetMediaItemInfo_Value(item, "D_FADEOUTLEN", fo)
                end
            end
            return { affected = n }
        """
        return await eval_lua(code, args=[fade_in_sec, fade_out_sec], label="set_fades")

    @mcp.tool(
        description=(
            "Glue (consolidate) currently selected items. Each contiguous group "
            "on a track becomes one item. Useful after a lot of editing."
        )
    )
    async def glue_selected_items() -> dict:
        # 41588 = Item: Glue items
        code = r"""
            reaper.Main_OnCommand(41588, 0)
            return { ok = true, selected_count = reaper.CountSelectedMediaItems(0) }
        """
        return await eval_lua(code, label="glue_items")

    @mcp.tool(
        description=(
            "Set the record input for a track. `input` is REAPER's input index: "
            "0..N-1 for mono inputs, or use 1024+ch for stereo pair starting at ch. "
            "Pass -1 to set to MIDI all-channels-all-devices."
        )
    )
    async def set_record_input(track_index: int, input: int) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", args[2])
            return { track = args[1], input = args[2] }
        """
        return await eval_lua(code, args=[track_index, input], label="set_record_input")

    @mcp.tool(
        description=(
            "Select items on a track by index range. Pass start=-1, end=-1 to "
            "select all items on the track. `replace` = clear other selections first."
        )
    )
    async def select_items_on_track(
        track_index: int,
        start_item: int = -1,
        end_item: int = -1,
        replace: bool = True,
    ) -> dict:
        code = r"""
            local ti, s, e, rep = args[1], args[2], args[3], args[4]
            local tr = reaper.GetTrack(0, ti)
            if not tr then error("no track at " .. ti) end
            if rep then
                reaper.SelectAllMediaItems(0, false)
            end
            local n = reaper.CountTrackMediaItems(tr)
            if s < 0 then s = 0 end
            if e < 0 or e >= n then e = n - 1 end
            for i = s, e do
                reaper.SetMediaItemSelected(reaper.GetTrackMediaItem(tr, i), true)
            end
            return { selected_range = { s, e }, total_on_track = n }
        """
        return await eval_lua(
            code,
            args=[track_index, start_item, end_item, replace],
            label="select_items",
        )
