local ADDON, ns = ...

ns.PROTOCOL_VERSION = 1

ns.DEFAULT_SETTINGS = {
  death = true,
  level = true,
  pvp = true,
  kill = true,      -- honourable kills of enemy players
  flag = false,     -- PvP flag on/off notifications (noisy in contested zones)
  summary = true,
  pvpCooldown = 10, -- minimum seconds between PvP alerts
  debug = false,
}

local issecret = issecretvalue or function() return false end

-- Returns v, or nil if it is a Midnight-style "secret value" that add-ons may
-- not inspect (comparing or branching on one raises an error).
function ns.safe(v)
  if v == nil or issecret(v) then return nil end
  return v
end

local function strip(ok, ...)
  if not ok then return end
  local n = select("#", ...)
  local out = { ... }
  for i = 1, n do out[i] = ns.safe(out[i]) end
  return unpack(out, 1, n)
end

-- Calls a WoW API defensively: missing functions, errors and secret return
-- values all come back as nil.
function ns.call(fn, ...)
  if type(fn) ~= "function" then return end
  return strip(pcall(fn, ...))
end

function ns.Print(msg)
  print("|cff33ccffForeverNotify|r: " .. tostring(msg))
end

function ns.Debug(msg)
  if ns.db and ns.db.settings.debug then ns.Print("|cff999999" .. tostring(msg) .. "|r") end
end

------------------------------------------------------------------------------
-- Event plumbing shared by every module
------------------------------------------------------------------------------

local eventFrame = CreateFrame("Frame")
local handlers = {}
ns.unavailableEvents = {}

-- Registers fn for a game event. Events the client doesn't know about (API
-- differences between builds) are recorded instead of raising an error.
function ns.On(event, fn)
  local list = handlers[event]
  if not list then
    list = {}
    handlers[event] = list
    if not pcall(eventFrame.RegisterEvent, eventFrame, event) then
      ns.unavailableEvents[event] = true
    end
  end
  list[#list + 1] = fn
end

-- Stops listening for an event and drops its handlers.
function ns.Off(event)
  handlers[event] = nil
  pcall(eventFrame.UnregisterEvent, eventFrame, event)
end

eventFrame:SetScript("OnEvent", function(_, event, ...)
  local list = handlers[event]
  if not list then return end
  for i = 1, #list do
    local ok, err = pcall(list[i], ...)
    if not ok then ns.Debug(event .. ": " .. tostring(err)) end
  end
end)

------------------------------------------------------------------------------
-- Character and location helpers
------------------------------------------------------------------------------

-- The client may hide or blank the player's name/realm at times (when quitting
-- the game, GetNormalizedRealmName() returns nil and GetRealmName() gives the
-- spaced display name), which would make CharKey() miss this character's
-- session. So keep the last real values and fall back to them.
local knownName, knownRealm

local function Real(v)
  if v == nil or v == "" or v == "Unknown" or v == UNKNOWNOBJECT then return nil end
  return v
end

function ns.PlayerName()
  knownName = Real(ns.call(UnitName, "player")) or knownName
  return knownName or "Unknown"
end

-- Normalized form ("Classic Beta PvP" -> "ClassicBetaPvP"), preferring the one
-- seen earlier over normalizing the display name ourselves.
function ns.Realm()
  local display = Real(ns.call(GetRealmName))
  knownRealm = Real(ns.call(GetNormalizedRealmName)) or knownRealm or (display and display:gsub("[%s%-]", ""))
  return knownRealm or "Unknown"
end

function ns.CharKey()
  return ns.PlayerName() .. "-" .. ns.Realm()
end

function ns.Location()
  local loc = {
    zone = ns.call(GetRealZoneText),
    subzone = ns.call(GetSubZoneText),
  }
  if C_Map then
    local mapID = ns.call(C_Map.GetBestMapForUnit, "player")
    if mapID then
      local pos = ns.call(C_Map.GetPlayerMapPosition, mapID, "player")
      if pos and pos.GetXY then
        local x, y = ns.call(pos.GetXY, pos)
        if x and y then loc.x, loc.y = x * 100, y * 100 end
      end
    end
  end
  if C_PvP and C_PvP.GetZonePVPInfo then
    loc.pvp = ns.call(C_PvP.GetZonePVPInfo)
  else
    loc.pvp = ns.call(GetZonePVPInfo)
  end
  local inInstance, instanceType = ns.call(IsInInstance)
  if inInstance then loc.instance = instanceType end
  return loc
end

-- Packs a unit's identity into "name|realm|level|class|race|guild".
function ns.UnitSummary(unit)
  local name, realm = ns.call(UnitName, unit)
  if not name then return end
  local level = ns.call(UnitLevel, unit)
  if level and level < 0 then level = "??" end
  return ns.JoinFields(name, realm, level, ns.call(UnitClass, unit), ns.call(UnitRace, unit),
    ns.call(GetGuildInfo, unit))
end

function ns.JoinFields(...)
  local parts = {}
  for i = 1, select("#", ...) do
    local v = select(i, ...)
    parts[i] = v == nil and "" or tostring(v):gsub("|", "/")
  end
  return table.concat(parts, "|")
end

------------------------------------------------------------------------------
-- Payloads: ordered "key=value" lines carried by the screenshot signal
------------------------------------------------------------------------------

local Payload = {}
Payload.__index = Payload

-- level: the player's level, when UnitLevel() would be out of date.
function ns.NewPayload(kind, level)
  local p = setmetatable({ lines = {} }, Payload)
  p:Set("t", kind)
  p:Set("c", ns.PlayerName())
  p:Set("r", ns.Realm())
  p:Set("lv", level or ns.call(UnitLevel, "player"))
  p:Set("ts", time())
  return p
end

function Payload:Set(key, value)
  if value == nil or value == "" then return self end
  if type(value) == "number" and value ~= math.floor(value) then
    value = string.format("%.1f", value)
  end
  value = tostring(value):gsub("[\r\n]", " ")
  self.lines[#self.lines + 1] = key .. "=" .. value
  return self
end

function Payload:SetLocation(loc)
  return self:Set("zone", loc.zone):Set("sz", loc.subzone):Set("x", loc.x):Set("y", loc.y)
    :Set("pvp", loc.pvp):Set("inst", loc.instance)
end

-- Serialises the payload, dropping whole trailing lines past maxBytes so the
-- most important keys (set first) always survive.
function Payload:Serialize(maxBytes)
  local out, size = {}, 0
  for i = 1, #self.lines do
    local line = self.lines[i]
    local extra = #line + (i > 1 and 1 or 0)
    if size + extra > maxBytes then break end
    out[#out + 1] = line
    size = size + extra
  end
  return table.concat(out, "\n")
end

function Payload:Send(urgent)
  ns.Signal.Send(self:Serialize(ns.Signal.MAX_PAYLOAD), urgent)
end
