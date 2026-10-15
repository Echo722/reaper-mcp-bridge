--[[
  reaper_mcp_bridge.lua

  In-REAPER service that talks to the external Python MCP server via JSON files
  exchanged in a "bridge directory". Polls each defer tick (~30Hz) for
  *.req.json, dispatches, and writes *.res.json atomically.

  Protocol:
    request  : { id, kind = "eval" | "ping", code?, args?, label?, undo? }
    response : { id, ok, result, error, console }
    `args` (any JSON-encodable table) is exposed inside the eval env as `args`.

  Bridge dir resolution (first match wins):
    1. env REAPER_MCP_BRIDGE_DIR
    2. <REAPER resource path>/Scripts/reaper_mcp_bridge_data
]]

------------------------------------------------------------------------------
-- Locate this script's directory so we can load json.lua sitting next to it.
------------------------------------------------------------------------------
local function script_dir()
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then src = src:sub(2) end
  return src:match("^(.*[\\/])") or "./"
end

package.path = script_dir() .. "?.lua;" .. package.path
local ok_json, json = pcall(require, "json")
if not ok_json then
  reaper.ShowConsoleMsg("[MCP] failed to load json.lua: " .. tostring(json) .. "\n")
  return
end

------------------------------------------------------------------------------
-- Bridge directory
------------------------------------------------------------------------------
local function path_sep()
  return package.config:sub(1, 1)
end

local function join(a, b)
  local sep = path_sep()
  if a:sub(-1) == "/" or a:sub(-1) == "\\" then return a .. b end
  return a .. sep .. b
end

local bridge_dir = os.getenv("REAPER_MCP_BRIDGE_DIR")
if not bridge_dir or bridge_dir == "" then
  bridge_dir = join(reaper.GetResourcePath(), "Scripts" .. path_sep() .. "reaper_mcp_bridge_data")
end
-- normalize: drop trailing slash
if bridge_dir:sub(-1) == "/" or bridge_dir:sub(-1) == "\\" then
  bridge_dir = bridge_dir:sub(1, -2)
end

reaper.RecursiveCreateDirectory(bridge_dir, 0)

------------------------------------------------------------------------------
-- File helpers
------------------------------------------------------------------------------
local function read_file(path)
  local f, err = io.open(path, "rb")
  if not f then return nil, err end
  local data = f:read("*a")
  f:close()
  return data
end

local function atomic_write(path, data)
  local tmp = path .. ".tmp"
  local f, err = io.open(tmp, "wb")
  if not f then return false, err end
  f:write(data)
  f:close()
  -- os.rename on Windows fails if dst exists; remove first.
  os.remove(path)
  local ok, rerr = os.rename(tmp, path)
  if not ok then return false, rerr end
  return true
end

------------------------------------------------------------------------------
-- Eval: run Lua code in a sandboxed-ish env that has `reaper` available,
-- captures `print` output, and serializes the return value.
------------------------------------------------------------------------------
local function safe_jsonable(v, depth)
  depth = depth or 0
  if depth > 6 then return tostring(v) end
  local t = type(v)
  if t == "nil" or t == "boolean" or t == "string" then return v end
  if t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return tostring(v) end
    return v
  end
  if t == "table" then
    -- detect array vs map
    local out
    local n = 0
    local is_array = true
    for k, _ in pairs(v) do
      n = n + 1
      if type(k) ~= "number" then is_array = false; break end
    end
    if is_array and n == #v then
      out = {}
      for i, x in ipairs(v) do out[i] = safe_jsonable(x, depth + 1) end
    else
      out = {}
      for k, x in pairs(v) do
        out[tostring(k)] = safe_jsonable(x, depth + 1)
      end
    end
    return out
  end
  -- userdata / function / thread → stringify
  return tostring(v)
end

local function run_eval(code, label, want_undo, args)
  local console_buf = {}
  local env = setmetatable({
    reaper = reaper,
    args = args or {},
    print = function(...)
      local parts = {}
      for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
      console_buf[#console_buf + 1] = table.concat(parts, "\t")
    end,
  }, { __index = _G })

  local chunk, cerr = load(code, "=mcp_eval", "t", env)
  if not chunk then
    return false, nil, "compile error: " .. tostring(cerr), table.concat(console_buf, "\n")
  end

  if want_undo then reaper.Undo_BeginBlock() end
  local results = { pcall(chunk) }
  if want_undo then
    reaper.Undo_EndBlock("MCP: " .. (label or "eval"), -1)
  end

  local ok = table.remove(results, 1)
  if not ok then
    return false, nil, tostring(results[1]), table.concat(console_buf, "\n")
  end

  -- Pack results: single value → that value; multiple → array
  local result
  if #results == 0 then result = nil
  elseif #results == 1 then result = safe_jsonable(results[1])
  else
    result = {}
    for i, v in ipairs(results) do result[i] = safe_jsonable(v) end
  end
  return true, result, nil, table.concat(console_buf, "\n")
end

------------------------------------------------------------------------------
-- Dispatch
------------------------------------------------------------------------------
local function dispatch(req)
  if req.kind == "ping" then
    return true, { pong = true, time = reaper.time_precise() }, nil, ""
  end
  if req.kind == "eval" then
    return run_eval(req.code or "", req.label, req.undo ~= false, req.args)
  end
  return false, nil, "unknown kind: " .. tostring(req.kind), ""
end

-- Responses whose requester died (e.g. Python timed out and cleaned up its
-- request) are never consumed. Track every response we write and reap any
-- still on disk after RES_TTL seconds.
local pending_res = {}  -- res file path -> os.time() when written
local RES_TTL = 600
local CLEANUP_INTERVAL = 60
local last_cleanup = os.time()

local function cleanup_orphans(now)
  for path, written in pairs(pending_res) do
    if now - written > RES_TTL then
      os.remove(path)  -- no-op if the requester already consumed it
      pending_res[path] = nil
    end
  end
end

-- On startup, sweep leftovers from a previous session: any res/tmp file
-- predates this bridge instance, so its requester is gone.
local function sweep_previous_session()
  local names = {}
  local i = 0
  while true do
    local name = reaper.EnumerateFiles(bridge_dir, i)
    if not name then break end
    if name:sub(-9) == ".res.json" or name:sub(-4) == ".tmp" then
      names[#names + 1] = name
    end
    i = i + 1
  end
  for _, name in ipairs(names) do
    os.remove(join(bridge_dir, name))
  end
  if #names > 0 then
    reaper.ShowConsoleMsg("[MCP] swept " .. #names .. " stale file(s)\n")
  end
end

local function respond(id, ok, result, err, console)
  local payload = { id = id, ok = ok, result = result, error = err, console = console }
  local encoded
  local ok_enc, enc_err = pcall(function() encoded = json.encode(payload) end)
  if not ok_enc then
    -- Result wasn't encodable; coerce to string and retry once.
    payload.result = tostring(payload.result)
    payload.error = (payload.error or "") .. " | encode err: " .. tostring(enc_err)
    payload.ok = false
    encoded = json.encode(payload)
  end
  local out = join(bridge_dir, id .. ".res.json")
  atomic_write(out, encoded)
  pending_res[out] = os.time()
end

------------------------------------------------------------------------------
-- Polling loop
------------------------------------------------------------------------------
local function list_reqs()
  local reqs = {}
  local i = 0
  while true do
    local name = reaper.EnumerateFiles(bridge_dir, i)
    if not name then break end
    -- Match *.req.json but NOT *.req.json.tmp
    if name:sub(-9) == ".req.json" then
      reqs[#reqs + 1] = name
    end
    i = i + 1
  end
  table.sort(reqs) -- stable processing order
  return reqs
end

local function process_one(name)
  local path = join(bridge_dir, name)
  local data, rerr = read_file(path)
  if not data then return end -- vanished mid-tick

  -- id = filename without ".req.json"
  local id = name:sub(1, -10)

  local req
  local ok_dec, dec_err = pcall(function() req = json.decode(data) end)
  if not ok_dec then
    respond(id, false, nil, "invalid json: " .. tostring(dec_err), "")
    os.remove(path)
    return
  end
  -- prefer id from payload if present (defense-in-depth)
  id = req.id or id

  local ok, result, err, console = dispatch(req)
  respond(id, ok, result, err, console or "")
  os.remove(path)
end

local function tick()
  local ok_iter, items = pcall(list_reqs)
  if ok_iter and items then
    for _, name in ipairs(items) do
      local ok_proc, perr = pcall(process_one, name)
      if not ok_proc then
        reaper.ShowConsoleMsg("[MCP] process_one error: " .. tostring(perr) .. "\n")
      end
    end
  end
  local now = os.time()
  if now - last_cleanup >= CLEANUP_INTERVAL then
    last_cleanup = now
    pcall(cleanup_orphans, now)
  end
  reaper.defer(tick)
end

pcall(sweep_previous_session)
reaper.ShowConsoleMsg("[MCP] bridge listening @ " .. bridge_dir .. "\n")
reaper.atexit(function()
  reaper.ShowConsoleMsg("[MCP] bridge stopped\n")
end)
tick()
