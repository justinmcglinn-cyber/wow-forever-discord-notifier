-- Minimal stand-in for the WoW client API, enough to run the add-on under
-- plain Lua 5.1 and record what it draws and sends.

local S = {
  now = 1000,            -- GetTime()
  epoch = 1790000000,    -- time() at now == 1000
  frames = {},
  timers = {},
  screenshots = {},
  printed = {},
  cvars = { screenshotFormat = "jpeg" },
  units = {},
  guidInfo = {},
  blockedEvents = {},
  money = 0,
  inCombat = false,
  zone = "Hillsbrad Foothills",
  subzone = "Southshore",
  cleu = {},
}
S.SECRET = setmetatable({}, { __tostring = function() return "<secret>" end })

function issecretvalue(v) return rawequal(v, S.SECRET) end

------------------------------------------------------------------------------
-- Frames and textures
------------------------------------------------------------------------------

local Frame = {}
Frame.__index = Frame

function CreateFrame(_, name, parent)
  local f = setmetatable({ name = name, parent = parent, shown = true, scripts = {}, events = {}, textures = {} }, Frame)
  S.frames[#S.frames + 1] = f
  if name then _G[name] = f end
  return f
end

function Frame:RegisterEvent(event)
  if S.blockedEvents[event] then error("Attempt to register unknown event \"" .. event .. "\"") end
  self.events[event] = true
end
function Frame:UnregisterEvent(event) self.events[event] = nil end

-- True if any frame is registered for the event.
function S.Registered(event)
  for _, f in ipairs(S.frames) do
    if f.events[event] then return true end
  end
  return false
end
function Frame:SetScript(kind, fn) self.scripts[kind] = fn end
function Frame:GetScript(kind) return self.scripts[kind] end
function Frame:Show() self.shown = true end
function Frame:Hide() self.shown = false end
function Frame:IsShown() return self.shown end
function Frame:SetFrameStrata() end
function Frame:SetFrameLevel() end
function Frame:SetIgnoreParentScale() end
function Frame:SetIgnoreParentAlpha() end
function Frame:SetScale(s) self.scale = s end
function Frame:ClearAllPoints() self.point = nil end
function Frame:SetPoint(p, rel, relp, x, y) self.point = { p, rel, relp, x or 0, y or 0 } end
function Frame:SetSize(w, h) self.w, self.h = w, h end
function Frame:SetColorTexture(r, g, b) self.color = { r, g, b } end
function Frame:CreateTexture()
  local t = setmetatable({ shown = true }, Frame)
  self.textures[#self.textures + 1] = t
  return t
end

UIParent = CreateFrame("Frame", "UIParent")

function S.Fire(event, ...)
  for _, f in ipairs(S.frames) do
    if f.events[event] and f.scripts.OnEvent then f.scripts.OnEvent(f, event, ...) end
  end
end

------------------------------------------------------------------------------
-- Time
------------------------------------------------------------------------------

function GetTime() return S.now end
function time() return S.epoch + math.floor(S.now - 1000) end

C_Timer = {}
function C_Timer.After(delay, fn)
  S.timers[#S.timers + 1] = { at = S.now + delay, fn = fn }
end
function C_Timer.NewTicker(interval, fn)
  local ticker = { cancelled = false }
  function ticker:Cancel() self.cancelled = true end
  local function schedule()
    C_Timer.After(interval, function()
      if ticker.cancelled then return end
      fn(ticker)
      if not ticker.cancelled then schedule() end
    end)
  end
  schedule()
  return ticker
end

function S.Advance(seconds)
  local target = S.now + seconds
  while S.now < target - 1e-9 do
    S.now = math.min(target, S.now + 0.05)
    local due = {}
    for i = #S.timers, 1, -1 do
      if S.timers[i].at <= S.now + 1e-9 then
        due[#due + 1] = table.remove(S.timers, i)
      end
    end
    table.sort(due, function(a, b) return a.at < b.at end)
    for _, t in ipairs(due) do t.fn() end
    for _, f in ipairs(S.frames) do
      if f.shown and f.scripts.OnUpdate then f.scripts.OnUpdate(f, 0.05) end
    end
  end
end

------------------------------------------------------------------------------
-- Screenshots: record the shown signal-grid blocks in screen pixels
------------------------------------------------------------------------------

function Screenshot()
  local f = ForeverNotifySignalFrame
  local shot = { blocks = {}, scale = f and f.scale }
  if f and f.shown then
    for _, t in ipairs(f.textures) do
      if t.shown then
        shot.blocks[#shot.blocks + 1] = { t.point[4], -t.point[5], t.w, t.h, t.color[1], t.color[2], t.color[3] }
      end
    end
  end
  S.screenshots[#S.screenshots + 1] = shot
  C_Timer.After(0.05, function() S.Fire("SCREENSHOT_SUCCEEDED") end)
end

------------------------------------------------------------------------------
-- Units, player state and misc API
------------------------------------------------------------------------------

local function Resolve(unit)
  if S.units[unit] then return S.units[unit] end
  local base = unit:match("^(.-)target$")
  if base and base ~= "" then
    local b = Resolve(base)
    if b and b.target then return S.units[b.target] end
  end
end

function UnitExists(u) return Resolve(u) ~= nil end
function UnitIsUnit(a, b) local x = Resolve(a); return x ~= nil and x == Resolve(b) end
function UnitName(u) local r = Resolve(u); if r then return r.name, r.realm end end
function UnitLevel(u) local r = Resolve(u); return r and r.level end
function UnitClass(u) local r = Resolve(u); if r then return r.class, r.classFile end end
function UnitRace(u) local r = Resolve(u); return r and r.race end
function GetGuildInfo(u) local r = Resolve(u); return r and r.guild end
function UnitIsPlayer(u) local r = Resolve(u); return r and r.player or false end
-- Whether a can attack b: a unit's `canAttack` (default: its `hostile`) says if
-- it and the player can attack each other.
function UnitCanAttack(a, b)
  local other = Resolve(a) == S.units.player and Resolve(b) or Resolve(a)
  if not other then return false end
  if other.canAttack ~= nil then return other.canAttack end
  return other.hostile or false
end
function UnitFactionGroup(u) local r = Resolve(u); return r and r.faction end
function UnitIsEnemy(_, u) local r = Resolve(u); return r and r.hostile or false end
function UnitAffectingCombat() return S.inCombat end
function UnitHealth(u) local r = Resolve(u); return r and r.health end
function UnitHealthMax(u) local r = Resolve(u); return r and r.maxHealth end
function UnitGUID(u) local r = Resolve(u); return r and r.guid end
function UnitIsPVP(u) local r = Resolve(u); return r and r.pvp or false end
function GetPlayerInfoByGUID(guid) local i = S.guidInfo[guid]; if i then return unpack(i) end end

function GetMoney() return S.money end
function GetRealZoneText() return S.zone end
function GetSubZoneText() return S.subzone end
function GetNormalizedRealmName() return "Area52" end
function GetRealmName() return "Area 52" end
function IsInInstance() return false, "none" end
function GetPhysicalScreenSize() return 1920, 1080 end
function GetCVar(k) return S.cvars[k] end
function SetCVar(k, v) S.cvars[k] = v end
function CombatLogGetCurrentEventInfo() return unpack(S.cleu) end

C_Map = {
  GetBestMapForUnit = function() return 1424 end,
  GetPlayerMapPosition = function()
    return { GetXY = function() return 0.524, 0.4912 end }
  end,
}
C_PvP = { GetZonePVPInfo = function() return "contested" end }

bit = {
  band = function(a, b)
    local result, place = 0, 1
    while a > 0 and b > 0 do
      if a % 2 == 1 and b % 2 == 1 then result = result + place end
      a, b, place = math.floor(a / 2), math.floor(b / 2), place * 2
    end
    return result
  end,
}

SlashCmdList = {}
function print(...)
  local parts = {}
  for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
  S.printed[#S.printed + 1] = table.concat(parts, " ")
end

------------------------------------------------------------------------------
-- Loading the add-on and dumping SavedVariables the way the client does
------------------------------------------------------------------------------

function S.LoadAddon(dir)
  local ns = {}
  local toc = assert(io.open(dir .. "/ForeverNotify.toc")):read("*a")
  for file in toc:gmatch("([%w_]+%.lua)") do
    assert(loadfile(dir .. "/" .. file))("ForeverNotify", ns)
  end
  return ns
end

local function SerializeValue(v, indent)
  local t = type(v)
  if t == "string" then return (string.format("%q", v):gsub("\\\n", "\\n")) end
  if t == "number" or t == "boolean" then return tostring(v) end
  if t == "table" then
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    local out = { "{" }
    for _, k in ipairs(keys) do
      local key = type(k) == "string" and string.format("[%q]", k) or "[" .. k .. "]"
      out[#out + 1] = indent .. "\t" .. key .. " = " .. SerializeValue(v[k], indent .. "\t") .. ","
    end
    out[#out + 1] = indent .. "}"
    return table.concat(out, "\n")
  end
  return "nil"
end

function S.SavedVariablesText(name)
  return "\n" .. name .. " = " .. SerializeValue(_G[name], "") .. "\n"
end

local function Json(v)
  local t = type(v)
  if t == "table" then
    if #v > 0 or next(v) == nil then
      local parts = {}
      for i = 1, #v do parts[i] = Json(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, val in pairs(v) do parts[#parts + 1] = Json(tostring(k)) .. ":" .. Json(val) end
    return "{" .. table.concat(parts, ",") .. "}"
  elseif t == "string" then
    return '"' .. v:gsub('[%c"\\]', function(c) return string.format("\\u%04x", c:byte()) end) .. '"'
  elseif t == "nil" then
    return "null"
  end
  return tostring(v)
end
S.Json = Json

return S
