"""MIDI: insert items, insert notes, quantize. Uses PPQ <-> seconds helpers
from the ReaScript API. Note positions/lengths are accepted in quarter notes
relative to the item start, which is the most musical unit."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from server.bridge_client import eval_lua


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        description=(
            "Insert an empty MIDI item on a track, spanning [start_sec, end_sec]. "
            "Returns the item index on the track."
        )
    )
    async def insert_midi_item(track_index: int, start_sec: float, end_sec: float) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            local item = reaper.CreateNewMIDIItemInProj(tr, args[2], args[3], false)
            -- find this item's index on the track
            local n = reaper.CountTrackMediaItems(tr)
            local idx = -1
            for i = 0, n - 1 do
                if reaper.GetTrackMediaItem(tr, i) == item then idx = i; break end
            end
            return { track = args[1], item_index = idx,
                     start_sec = args[2], end_sec = args[3] }
        """
        return await eval_lua(
            code,
            args=[track_index, start_sec, end_sec],
            label="insert_midi_item",
        )

    @mcp.tool(
        description=(
            "Insert MIDI notes into an existing MIDI item. Each note: "
            "{pitch: 0..127, start_qn: float, length_qn: float, "
            "velocity?: 1..127 (default 96), channel?: 0..15 (default 0)}. "
            "Positions are quarter-notes relative to the item start."
        )
    )
    async def insert_midi_notes(
        track_index: int,
        item_index: int,
        notes: list[dict],
    ) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end
            local item = reaper.GetTrackMediaItem(tr, args[2])
            if not item then error("no item " .. args[2] .. " on track " .. args[1]) end
            local take = reaper.GetActiveTake(item)
            if not take or not reaper.TakeIsMIDI(take) then error("active take is not MIDI") end

            local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
            local item_start_qn = reaper.TimeMap2_timeToQN(0, item_pos)

            local inserted = 0
            for _, n in ipairs(args[3]) do
                local start_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, item_start_qn + n.start_qn)
                local end_ppq   = reaper.MIDI_GetPPQPosFromProjQN(take, item_start_qn + n.start_qn + n.length_qn)
                local vel = n.velocity or 96
                local ch  = n.channel or 0
                reaper.MIDI_InsertNote(take, false, false, start_ppq, end_ppq, ch, n.pitch, vel, true)
                inserted = inserted + 1
            end
            reaper.MIDI_Sort(take)
            return { inserted = inserted }
        """
        return await eval_lua(
            code,
            args=[track_index, item_index, notes],
            label=f"insert_midi_notes ({len(notes)})",
        )

    @mcp.tool(
        description=(
            "Convenience: build a chord progression on a track from scratch. "
            "Creates a MIDI item and writes one chord per entry. "
            "`chords`: [{root: 0..11 (C=0), type: 'maj'|'min'|'7'|'maj7'|'min7'|'dim'|'aug', "
            "duration_qn: float, octave?: int (default 4)}]. "
            "Notes are placed back-to-back starting at item start (start_sec)."
        )
    )
    async def create_chord_progression(
        track_index: int,
        start_sec: float,
        chords: list[dict],
    ) -> dict:
        code = r"""
            local CHORD_INTERVALS = {
                maj   = {0, 4, 7},
                min   = {0, 3, 7},
                ["7"] = {0, 4, 7, 10},
                maj7  = {0, 4, 7, 11},
                min7  = {0, 3, 7, 10},
                dim   = {0, 3, 6},
                aug   = {0, 4, 8},
            }
            local tr = reaper.GetTrack(0, args[1])
            if not tr then error("no track at " .. args[1]) end

            local total_qn = 0
            for _, c in ipairs(args[3]) do total_qn = total_qn + c.duration_qn end
            local start = args[2]
            local end_sec = reaper.TimeMap2_QNToTime(0, reaper.TimeMap2_timeToQN(0, start) + total_qn)

            local item = reaper.CreateNewMIDIItemInProj(tr, start, end_sec, false)
            local take = reaper.GetActiveTake(item)
            local item_start_qn = reaper.TimeMap2_timeToQN(0, start)

            local cursor_qn = 0
            local total_notes = 0
            for _, c in ipairs(args[3]) do
                local intervals = CHORD_INTERVALS[c.type]
                if not intervals then error("unknown chord type: " .. tostring(c.type)) end
                local octave = c.octave or 4
                local base = 12 * (octave + 1) + c.root  -- midi note: C-1 = 0
                for _, iv in ipairs(intervals) do
                    local sp = reaper.MIDI_GetPPQPosFromProjQN(take, item_start_qn + cursor_qn)
                    local ep = reaper.MIDI_GetPPQPosFromProjQN(take, item_start_qn + cursor_qn + c.duration_qn)
                    reaper.MIDI_InsertNote(take, false, false, sp, ep, 0, base + iv, 90, true)
                    total_notes = total_notes + 1
                end
                cursor_qn = cursor_qn + c.duration_qn
            end
            reaper.MIDI_Sort(take)
            return { track = args[1], chords = #args[3], notes = total_notes,
                     start_sec = start, end_sec = end_sec }
        """
        return await eval_lua(
            code,
            args=[track_index, start_sec, chords],
            label="chord_progression",
        )

    @mcp.tool(
        description=(
            "Quantize note positions in the active MIDI take of the item at "
            "(track_index, item_index) to `grid_qn` quarter notes. "
            "Pass 0.25 for 16th-note grid, 0.5 for 8ths, 1.0 for quarters."
        )
    )
    async def quantize_midi_item(track_index: int, item_index: int, grid_qn: float) -> dict:
        code = r"""
            local tr = reaper.GetTrack(0, args[1])
            local item = reaper.GetTrackMediaItem(tr, args[2])
            local take = reaper.GetActiveTake(item)
            if not take or not reaper.TakeIsMIDI(take) then error("not a MIDI item") end

            local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
            local item_start_qn = reaper.TimeMap2_timeToQN(0, item_pos)
            local grid = args[3]

            local _, n_notes = reaper.MIDI_CountEvts(take)
            local moved = 0
            for i = 0, n_notes - 1 do
                local _, _, _, sp, ep, ch, pitch, vel = reaper.MIDI_GetNote(take, i)
                local sqn = reaper.MIDI_GetProjQNFromPPQPos(take, sp) - item_start_qn
                local len_qn = reaper.MIDI_GetProjQNFromPPQPos(take, ep) - reaper.MIDI_GetProjQNFromPPQPos(take, sp)
                local snapped = math.floor(sqn / grid + 0.5) * grid
                if math.abs(snapped - sqn) > 1e-9 then
                    local new_sp = reaper.MIDI_GetPPQPosFromProjQN(take, item_start_qn + snapped)
                    local new_ep = reaper.MIDI_GetPPQPosFromProjQN(take, item_start_qn + snapped + len_qn)
                    reaper.MIDI_SetNote(take, i, nil, nil, new_sp, new_ep, ch, pitch, vel, true)
                    moved = moved + 1
                end
            end
            reaper.MIDI_Sort(take)
            return { quantized = moved, of = n_notes, grid = grid }
        """
        return await eval_lua(
            code,
            args=[track_index, item_index, grid_qn],
            label=f"quantize 1/{int(round(1/grid_qn))} qn",
        )
