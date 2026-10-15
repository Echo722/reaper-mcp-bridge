"""Rendering / bouncing. Configures project render settings via
GetSetProjectInfo and triggers REAPER's render action (42230, render via most
recent settings) — i.e. no dialog popup."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from server.bridge_client import eval_lua


# REAPER RENDER_BOUNDSFLAG values:
#   0 = custom time bounds, 1 = entire project, 2 = time selection,
#   3 = project regions (all), 4 = selected media items,
#   5 = selected project regions
_BOUNDS_MAP = {
    "entire_project": 1,
    "time_selection": 2,
    "all_regions":   3,
    "selected_items": 4,
    "selected_regions": 5,
}


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Trigger a render using REAPER's current render-dialog settings "
            "(non-interactive — no UI popup). Useful if the user has already "
            "configured the render dialog."
        )
    )
    async def render_with_current_settings() -> dict:
        # 42230 = File: Render project, using the most recent render settings
        code = r"""
            reaper.Main_OnCommand(42230, 0)
            return { ok = true }
        """
        return await eval_lua(code, label="render", undo=False)

    @mcp.tool(
        description=(
            "Render to a directory with the given bounds and file pattern. "
            "`bounds` ∈ {'entire_project','time_selection','all_regions',"
            "'selected_items','selected_regions'}. "
            "`file_name_pattern` uses REAPER's wildcards: e.g. '$project', "
            "'$region', '$track', '$item'. Extension comes from current render "
            "format (configure via REAPER once, or call `render_with_current_settings`)."
        )
    )
    async def render(
        output_dir: str,
        bounds: str = "entire_project",
        file_name_pattern: str = "$project",
        sample_rate: int = 0,
    ) -> dict:
        flag = _BOUNDS_MAP.get(bounds)
        if flag is None:
            raise ValueError(
                f"bounds must be one of {sorted(_BOUNDS_MAP)} (got {bounds!r})"
            )
        code = r"""
            local out_dir  = args[1]
            local flag     = args[2]
            local pattern  = args[3]
            local sr       = args[4]

            reaper.RecursiveCreateDirectory(out_dir, 0)
            reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", flag, true)
            reaper.GetSetProjectInfo_String(0, "RENDER_FILE", out_dir, true)
            reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", pattern, true)
            if sr > 0 then
                reaper.GetSetProjectInfo(0, "RENDER_SRATE", sr, true)
            end
            -- Render through last-used format (RENDER_FORMAT cfg blob is kept).
            reaper.Main_OnCommand(42230, 0)
            return { output_dir = out_dir, bounds = args[5], pattern = pattern, sr = sr }
        """
        return await eval_lua(
            code,
            args=[output_dir, flag, file_name_pattern, sample_rate, bounds],
            label=f"render → {output_dir}",
            undo=False,
            timeout=300.0,  # rendering can take a while
        )

    @mcp.tool(
        description=(
            "Get the current render settings: bounds flag, output file/dir, "
            "pattern, sample rate, channels."
        )
    )
    async def get_render_settings() -> dict:
        code = r"""
            local _, file = reaper.GetSetProjectInfo_String(0, "RENDER_FILE", "", false)
            local _, pat  = reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", "", false)
            return {
                bounds_flag = reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, false),
                file = file,
                pattern = pat,
                sample_rate = reaper.GetSetProjectInfo(0, "RENDER_SRATE", 0, false),
                channels = reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", 0, false),
            }
        """
        return await eval_lua(code, label="get_render_settings", undo=False)
