"""FX (add / remove / list / set param), master volume."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from server.bridge_client import eval_lua


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Add an FX plugin to a track. `fx_name` is matched the way REAPER's "
            "FX browser matches: e.g. 'ReaEQ', 'VST:Pro-Q 3', 'ReaComp'. "
            "Returns the new FX index on that track, or -1 if not found."
        )
    )
    async def add_fx(track_index: int, fx_name: str) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            local idx = reaper.TrackFX_AddByName(tr, args[2], false, -1)
            return { track = args[1], fx_index = idx, requested = args[2] }
        """
        return await eval_lua(
            code, args=[track_index, fx_name], label=f"add_fx {fx_name}"
        )

    @mcp.tool(description="Remove an FX from a track by FX index.")
    async def remove_fx(track_index: int, fx_index: int) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            local ok = reaper.TrackFX_Delete(tr, args[2])
            return { ok = ok, track = args[1], fx_index = args[2] }
        """
        return await eval_lua(code, args=[track_index, fx_index], label="remove_fx")

    @mcp.tool(
        description=(
            "List FX on a track with their parameters. "
            "Each entry: {index, name, enabled, num_params, params: [{index, name, value, value_normalized, min, max}]}. "
            "Set `include_params=false` to skip parameter details (faster)."
        )
    )
    async def list_fx(track_index: int, include_params: bool = True) -> list[dict]:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            local inc = args[2]
            local out = {}
            local n = reaper.TrackFX_GetCount(tr)
            for i = 0, n - 1 do
                local _, name = reaper.TrackFX_GetFXName(tr, i, "")
                local enabled = reaper.TrackFX_GetEnabled(tr, i)
                local np = reaper.TrackFX_GetNumParams(tr, i)
                local params = nil
                if inc then
                    params = {}
                    for p = 0, np - 1 do
                        local _, pname = reaper.TrackFX_GetParamName(tr, i, p, "")
                        local val, mn, mx = reaper.TrackFX_GetParam(tr, i, p)
                        local norm = reaper.TrackFX_GetParamNormalized(tr, i, p)
                        params[p + 1] = {
                            index = p, name = pname,
                            value = val, value_normalized = norm,
                            min = mn, max = mx,
                        }
                    end
                end
                out[i + 1] = { index = i, name = name, enabled = enabled,
                                num_params = np, params = params }
            end
            return out
        """
        return await eval_lua(
            code, args=[track_index, include_params],
            label="list_fx", undo=False,
        )

    @mcp.tool(
        description=(
            "Set an FX parameter. `normalized=true` (default) means `value` is in "
            "0..1. Set normalized=false to use the plugin's native units."
        )
    )
    async def set_fx_param(
        track_index: int,
        fx_index: int,
        param_index: int,
        value: float,
        normalized: bool = True,
    ) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            local ok
            if args[5] then
                ok = reaper.TrackFX_SetParamNormalized(tr, args[2], args[3], args[4])
            else
                ok = reaper.TrackFX_SetParam(tr, args[2], args[3], args[4])
            end
            local _, pname = reaper.TrackFX_GetParamName(tr, args[2], args[3], "")
            return { ok = ok, param = pname, set_to = args[4], normalized = args[5] }
        """
        return await eval_lua(
            code,
            args=[track_index, fx_index, param_index, value, normalized],
            label=f"set_fx_param {param_index}",
        )

    @mcp.tool(description="Bypass / enable an FX on a track.")
    async def set_fx_enabled(track_index: int, fx_index: int, enabled: bool) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            reaper.TrackFX_SetEnabled(tr, args[2], args[3])
            return { fx_index = args[2], enabled = args[3] }
        """
        return await eval_lua(
            code, args=[track_index, fx_index, enabled], label="set_fx_enabled",
        )

    @mcp.tool(description="Set master track volume in dB. 0 = unity.")
    async def set_master_volume_db(db: float) -> dict:
        code = r"""
            local m = reaper.GetMasterTrack(0)
            local amp = (args[1] <= -150) and 0 or (10 ^ (args[1] / 20))
            reaper.SetMediaTrackInfo_Value(m, "D_VOL", amp)
            return { master_db = args[1], amp = amp }
        """
        return await eval_lua(code, args=[db], label=f"master {db}dB")
