"""Batch operations: rename items/regions, batch-export regions, LUFS
normalize, apply a track template."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from server.bridge_client import eval_lua
from server.tools._helpers import lua_color


# Loudness target codes accepted by reaper.CalculateNormalization (REAPER 6.40+):
#   0 = LUFS-I, 1 = RMS-I, 2 = Peak, 3 = True Peak, 4 = LUFS-M max, 5 = LUFS-S max
_NORM_KIND = {
    "LUFS-I":     0,
    "RMS-I":      1,
    "peak":       2,
    "true_peak":  3,
    "LUFS-M_max": 4,
    "LUFS-S_max": 5,
}


def register(mcp: FastMCP) -> None:

    # ------------------------------------------------------------------
    # Renaming
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Rename items on a track in order. `pattern` supports tokens: "
            "$num (1-based, zero-padded to pad_width), $idx (1-based, no padding), "
            "$name (original active-take name), $track (track name). "
            "If track_index = -1, applies across ALL tracks in track-then-position order. "
            "Returns the list of renames applied."
        )
    )
    async def batch_rename_items(
        pattern: str,
        track_index: int = -1,
        start_num: int = 1,
        pad_width: int = 2,
    ) -> dict:
        code = r"""
            local pat   = args[1]
            local ti    = args[2]
            local start = args[3]
            local pad   = args[4]

            local function format_num(n)
                local s = tostring(n)
                while #s < pad do s = "0" .. s end
                return s
            end

            local renames = {}
            local function rename_track_items(tr, t_idx)
                local _, tr_name = reaper.GetTrackName(tr)
                local n = reaper.CountTrackMediaItems(tr)
                for i = 0, n - 1 do
                    local item = reaper.GetTrackMediaItem(tr, i)
                    local take = reaper.GetActiveTake(item)
                    if take then
                        local orig = reaper.GetTakeName(take)
                        local idx = #renames + 1
                        local num = start + idx - 1
                        local new = pat
                            :gsub("%$num",  format_num(num))
                            :gsub("%$idx",  tostring(idx))
                            :gsub("%$name", orig)
                            :gsub("%$track", tr_name)
                        reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", new, true)
                        renames[idx] = { track = t_idx, item = i, from = orig, to = new }
                    end
                end
            end

            if ti < 0 then
                local n = reaper.CountTracks(0)
                for ti2 = 0, n - 1 do
                    rename_track_items(reaper.GetTrack(0, ti2), ti2)
                end
            else
                local tr = reaper.GetTrack(0, ti)
                if not tr then error("no track at " .. ti) end
                rename_track_items(tr, ti)
            end
            reaper.UpdateArrange()
            return { count = #renames, renames = renames }
        """
        return await eval_lua(
            code,
            args=[pattern, track_index, start_num, pad_width],
            label="batch_rename_items",
        )

    @mcp.tool(
        description=(
            "Rename ALL regions in the project in time order. Pattern tokens: "
            "$num (1-based, zero-padded to pad_width), $idx, $name (original name)."
        )
    )
    async def batch_rename_regions(
        pattern: str,
        start_num: int = 1,
        pad_width: int = 2,
    ) -> dict:
        code = r"""
            local pat   = args[1]
            local start = args[2]
            local pad   = args[3]

            local function format_num(n)
                local s = tostring(n)
                while #s < pad do s = "0" .. s end
                return s
            end

            -- collect regions in time order
            local regions = {}
            local _, nm, nr = reaper.CountProjectMarkers(0)
            for i = 0, nm + nr - 1 do
                local _, is_rgn, pos, rgnend, name, idx, color = reaper.EnumProjectMarkers3(0, i)
                if is_rgn then
                    regions[#regions + 1] = {
                        enum_index = i, region_index = idx, pos = pos,
                        rgnend = rgnend, name = name, color = color,
                    }
                end
            end
            table.sort(regions, function(a, b) return a.pos < b.pos end)

            local renames = {}
            for k, r in ipairs(regions) do
                local num = start + k - 1
                local new = pat
                    :gsub("%$num",  format_num(num))
                    :gsub("%$idx",  tostring(k))
                    :gsub("%$name", r.name)
                reaper.SetProjectMarker3(
                    0, r.region_index, true, r.pos, r.rgnend, new, r.color
                )
                renames[k] = { region_index = r.region_index, from = r.name, to = new }
            end
            return { count = #renames, renames = renames }
        """
        return await eval_lua(
            code, args=[pattern, start_num, pad_width],
            label="batch_rename_regions",
        )

    # ------------------------------------------------------------------
    # Batch export regions
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Render every region in the project to its own file. Uses the "
            "project's currently-configured render FORMAT (configure it once "
            "in REAPER's Render dialog, then this just changes bounds + "
            "output dir + pattern). `file_name_pattern` supports REAPER "
            "wildcards: default '$region' = filename equals region name."
        )
    )
    async def batch_export_regions(
        output_dir: str,
        file_name_pattern: str = "$region",
        only_matching: str = "",
    ) -> dict:
        # bounds=3 = all project regions; if a non-empty `only_matching` is
        # given, REAPER's "region matches" wildcard support is via the render
        # dialog only — easiest cross-version path is to render all and let
        # the user filter, or to render selected regions. We expose only-all.
        code = r"""
            local out_dir = args[1]
            local pattern = args[2]
            reaper.RecursiveCreateDirectory(out_dir, 0)
            reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 3, true)  -- all regions
            reaper.GetSetProjectInfo_String(0, "RENDER_FILE", out_dir, true)
            reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", pattern, true)
            reaper.Main_OnCommand(42230, 0)  -- render via last settings
            return { output_dir = out_dir, pattern = pattern }
        """
        if only_matching:
            # Documented but not implemented — surface clearly.
            raise NotImplementedError(
                "only_matching filtering isn't supported by REAPER's render-pattern "
                "API in a portable way. Rename matching regions first, or use "
                "selected_regions bounds via render() after a manual selection."
            )
        return await eval_lua(
            code, args=[output_dir, file_name_pattern],
            label=f"export regions → {output_dir}",
            undo=False, timeout=600.0,
        )

    # ------------------------------------------------------------------
    # LUFS normalization
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Normalize the perceived loudness of items by adjusting each item's "
            "volume (D_VOL). Doesn't modify audio data. "
            "`target_db`: e.g. -14 for streaming, -23 for broadcast EBU R128. "
            "`kind`: 'LUFS-I' (default), 'RMS-I', 'peak', 'true_peak', "
            "'LUFS-M_max', 'LUFS-S_max'. "
            "`selected_only`: true = only currently selected items; "
            "false = every item in the project. Requires REAPER 6.40+."
        )
    )
    async def normalize_loudness(
        target_db: float = -14.0,
        kind: str = "LUFS-I",
        selected_only: bool = False,
    ) -> dict:
        kind_code = _NORM_KIND.get(kind)
        if kind_code is None:
            raise ValueError(f"kind must be one of {sorted(_NORM_KIND)} (got {kind!r})")
        code = r"""
            local target   = args[1]   -- dB
            local kind     = args[2]
            local sel_only = args[3]

            local items = {}
            if sel_only then
                local n = reaper.CountSelectedMediaItems(0)
                for i = 0, n - 1 do items[#items + 1] = reaper.GetSelectedMediaItem(0, i) end
            else
                local n_tracks = reaper.CountTracks(0)
                for ti = 0, n_tracks - 1 do
                    local tr = reaper.GetTrack(0, ti)
                    for ii = 0, reaper.CountTrackMediaItems(tr) - 1 do
                        items[#items + 1] = reaper.GetTrackMediaItem(tr, ii)
                    end
                end
            end

            if not reaper.CalculateNormalization then
                error("reaper.CalculateNormalization unavailable — REAPER 6.40+ required")
            end

            local results = {}
            for k, it in ipairs(items) do
                local gain = reaper.CalculateNormalization(it, kind, target, 0, 0)
                -- 0 means analysis failed (silent item / no audio source)
                if gain and gain > 0 then
                    reaper.SetMediaItemInfo_Value(it, "D_VOL", gain)
                    results[#results + 1] = { ok = true, gain = gain }
                else
                    results[#results + 1] = { ok = false }
                end
            end
            reaper.UpdateArrange()
            local succ = 0
            for _, r in ipairs(results) do if r.ok then succ = succ + 1 end end
            return { processed = #results, successful = succ,
                     target_db = target, kind_code = kind }
        """
        return await eval_lua(
            code,
            args=[target_db, kind_code, selected_only],
            label=f"normalize {target_db} {kind}",
            timeout=120.0,
        )

    # ------------------------------------------------------------------
    # Template projects
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Build a track layout from a template. `tracks` is a list, processed "
            "in order. Each entry may contain: "
            "{name, color:[r,g,b]?, volume_db?, pan?, folder_start?:bool, "
            " folder_end?:int (1=close one, 2=close two, ...), record_armed?:bool, "
            " record_input?:int, fx?:[name,name,...]}. "
            "Appends to the current project; does not clear existing tracks. "
            "Returns the indices and names of the new tracks."
        )
    )
    async def apply_template(tracks: list[dict]) -> dict:
        # Pre-process colors here so Lua doesn't have to.
        prepared: list[dict[str, Any]] = []
        for t in tracks:
            t2 = dict(t)
            c = t2.get("color")
            if c and len(c) == 3:
                t2["color_native"] = lua_color(*c)
            prepared.append(t2)

        code = r"""
            local specs = args[1]
            local created = {}
            local base = reaper.CountTracks(0)
            for i, spec in ipairs(specs) do
                local pos = base + i - 1
                reaper.InsertTrackAtIndex(pos, true)
                local tr = reaper.GetTrack(0, pos)
                if spec.name then
                    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", spec.name, true)
                end
                if spec.color_native then
                    reaper.SetTrackColor(tr, spec.color_native)
                end
                if spec.volume_db then
                    local db = spec.volume_db
                    local amp = (db <= -150) and 0 or (10 ^ (db / 20))
                    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", amp)
                end
                if spec.pan then
                    reaper.SetMediaTrackInfo_Value(tr, "D_PAN",
                        math.max(-1, math.min(1, spec.pan)))
                end
                if spec.record_armed then
                    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
                end
                if spec.record_input ~= nil then
                    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", spec.record_input)
                end
                if spec.folder_start then
                    reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", 1)
                elseif spec.folder_end then
                    reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", -spec.folder_end)
                end
                if spec.fx then
                    for _, name in ipairs(spec.fx) do
                        reaper.TrackFX_AddByName(tr, name, false, -1)
                    end
                end
                created[#created + 1] = { index = pos, name = spec.name or "" }
            end
            reaper.UpdateArrange()
            return { added = #created, tracks = created }
        """
        return await eval_lua(
            code, args=[prepared], label=f"apply_template ({len(prepared)} tracks)",
        )
