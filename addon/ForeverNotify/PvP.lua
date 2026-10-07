local ADDON, ns = ...

-- Detects hostile players attacking you. Two sources:
--   1. Unit scan: while you are in combat, any hostile player among your
--      target/focus/mouseover/nameplates who is targeting you.
--   2. Combat log: if the client still lets add-ons read it outside encounters,
--      damage to you from a hostile player (catches attackers without a
--      visible nameplate). Midnight-era clients may block or hide this.

local PvP = {}
ns.PvP = PvP

local ATTACKER_TTL = 10     -- seconds an attacker counts as "active"
local REPORT_AGAIN = 120    -- seconds before the same attacker triggers a new alert
local KILLER_WINDOW = 20    -- seconds before death within which an attacker counts as the killer
local NPC_KILLER_WINDOW = 10
local MAX_LISTED = 3

local attackers = {}        -- name -> { summary, lastSeen, source }
local reported = {}         -- name -> GetTime() of last alert
local lastAlert = -math.huge
local lastNpcAttacker       -- { name, at } from the combat log
local ticker
local wasFlagged

local COMBATLOG_PLAYER = 0x400
local COMBATLOG_NPC = 0x800
local COMBATLOG_HOSTILE = 0x40

local function InCombat()
  return ns.call(UnitAffectingCombat, "player") and true or false
end

local function IsHostilePlayer(unit)
  if not ns.call(UnitExists, unit) or not ns.call(UnitIsPlayer, unit) then return false end
  return (ns.call(UnitCanAttack, "player", unit) or ns.call(UnitIsEnemy, "player", unit)) and true or false
end

local function IsHostileNPC(unit)
  if not ns.call(UnitExists, unit) or ns.call(UnitIsPlayer, unit) then return false end
  return ns.call(UnitCanAttack, "player", unit) and true or false
end

-- Records hostile players (and, for naming killers without the combat log,
-- hostile NPCs) that are targeting you. Returns the number of hostile players
-- with visible nameplates.
local function ScanUnits()
  local units = { "target", "focus", "mouseover", "softenemy" }
  for i = 1, 40 do units[#units + 1] = "nameplate" .. i end
  local hostiles = 0
  local now = GetTime()
  for _, unit in ipairs(units) do
    if IsHostilePlayer(unit) then
      local name = ns.call(UnitName, unit)
      if unit:find("^nameplate") then hostiles = hostiles + 1 end
      if name and ns.call(UnitIsUnit, unit .. "target", "player") then
        attackers[name] = { name = name, summary = ns.UnitSummary(unit), lastSeen = now, source = "unit" }
      end
    elseif IsHostileNPC(unit) and ns.call(UnitIsUnit, unit .. "target", "player") then
      local name = ns.call(UnitName, unit)
      if name then lastNpcAttacker = { name = name, at = now } end
    end
  end
  return hostiles
end
PvP.Scan = ScanUnits

local function ActiveAttackers()
  local now, list = GetTime(), {}
  for name, a in pairs(attackers) do
    if now - a.lastSeen <= ATTACKER_TTL then
      list[#list + 1] = { name = name, info = a }
    else
      attackers[name] = nil
    end
  end
  table.sort(list, function(a, b) return a.info.lastSeen > b.info.lastSeen end)
  return list
end

-- Always tracks attackers (so deaths can name the killer); only alerts if enabled.
function PvP.Check()
  local hostiles = ScanUnits()
  local active = ActiveAttackers()
  if #active == 0 or not ns.db or not ns.db.settings.pvp then return end

  local now = GetTime()
  local fresh = false
  for _, a in ipairs(active) do
    if not reported[a.name] or now - reported[a.name] > REPORT_AGAIN then fresh = true end
  end
  if not fresh or now - lastAlert < ns.db.settings.pvpCooldown then return end
  lastAlert = now

  local p = ns.NewPayload("PVP"):SetLocation(ns.Location())
  local health, maxHealth = ns.call(UnitHealth, "player"), ns.call(UnitHealthMax, "player")
  if health and maxHealth and maxHealth > 0 then p:Set("hp", math.floor(health / maxHealth * 100 + 0.5)) end
  p:Set("near", hostiles)
  for i = 1, math.min(#active, MAX_LISTED) do
    local a = active[i]
    p:Set("a" .. i, a.info.summary or a.name)
    reported[a.name] = now
  end
  if #active > MAX_LISTED then p:Set("more", #active - MAX_LISTED) end
  p:Send()
end

-- Most recent attacker: a player seen within KILLER_WINDOW seconds or an NPC
-- within NPC_KILLER_WINDOW, whichever was seen last (a player wins a tie).
function PvP.RecentKiller()
  local now, best = GetTime(), nil
  for _, a in pairs(attackers) do
    if now - a.lastSeen <= KILLER_WINDOW and (not best or a.lastSeen > best.lastSeen) then best = a end
  end
  local npc = lastNpcAttacker
  if npc and now - npc.at <= NPC_KILLER_WINDOW and (not best or npc.at > best.lastSeen) then
    return npc.name, false
  end
  if best then return best.summary or best.name, true end
end

------------------------------------------------------------------------------
-- Unit-scan triggers
------------------------------------------------------------------------------

ns.On("PLAYER_REGEN_DISABLED", function()
  PvP.Check()
  if ticker then ticker:Cancel() end
  ticker = C_Timer.NewTicker(1, function()
    if not InCombat() then
      ticker:Cancel()
      ticker = nil
      return
    end
    PvP.Check()
  end)
end)

ns.On("UNIT_TARGET", function(unit)
  if InCombat() and unit and unit ~= "player" then PvP.Check() end
end)

------------------------------------------------------------------------------
-- Optional combat-log source
------------------------------------------------------------------------------

local band = bit and bit.band

local function OnCombatLog()
  if not band then return end
  local _, subevent, _, sourceGUID, sourceName, sourceFlags, _, destGUID = ns.call(CombatLogGetCurrentEventInfo)
  if not (subevent and sourceName and sourceFlags and destGUID) then return end
  if destGUID ~= ns.call(UnitGUID, "player") then return end
  if not (subevent:find("_DAMAGE$") or subevent:find("_MISSED$")) then return end
  if band(sourceFlags, COMBATLOG_HOSTILE) == 0 then return end

  if band(sourceFlags, COMBATLOG_PLAYER) ~= 0 then
    local name = sourceName:match("^[^-]+") or sourceName
    local existing = attackers[name]
    if existing then
      existing.lastSeen = GetTime()
    else
      local class, _, race, _, _, _, realm = ns.call(GetPlayerInfoByGUID, sourceGUID)
      attackers[name] = {
        name = name,
        summary = ns.JoinFields(name, realm, nil, class, race, nil),
        lastSeen = GetTime(),
        source = "log",
      }
    end
    PvP.Check()
  elseif band(sourceFlags, COMBATLOG_NPC) ~= 0 then
    lastNpcAttacker = { name = sourceName, at = GetTime() }
  end
end

ns.On("COMBAT_LOG_EVENT_UNFILTERED", OnCombatLog)

function PvP.CombatLogAvailable()
  return not ns.unavailableEvents.COMBAT_LOG_EVENT_UNFILTERED and type(CombatLogGetCurrentEventInfo) == "function"
end

------------------------------------------------------------------------------
-- PvP flag changes
------------------------------------------------------------------------------

local function CheckFlag()
  local flagged = ns.call(UnitIsPVP, "player") and true or false
  if wasFlagged ~= nil and flagged ~= wasFlagged and ns.db and ns.db.settings.flag then
    ns.NewPayload("FLAG"):Set("on", flagged and 1 or 0):SetLocation(ns.Location()):Send()
  end
  wasFlagged = flagged
end
PvP.CheckFlag = CheckFlag

ns.On("UNIT_FLAGS", function(unit) if unit == "player" then CheckFlag() end end)
ns.On("PLAYER_FLAGS_CHANGED", function(unit) if unit == "player" then CheckFlag() end end)
