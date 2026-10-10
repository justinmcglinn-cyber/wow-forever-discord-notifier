local ADDON, ns = ...

-- Reports honorable kills of enemy-faction players. The combat log is blocked
-- on Forever, so killing blows can't be seen; instead the honour system's chat
-- message ("X dies, honorable kill Rank: Y (Estimated Honor Points: Z)") names
-- each player you helped kill. If that message is hidden, the honourable-kill
-- counter (PLAYER_PVP_KILLS_CHANGED + GetPVPSessionStats) still reports the kill,
-- without a name. Victim details come from the unit scan (PvP.RecentlySeen).
--
-- Streak: kills since your last death (kept in SavedVariables, so it survives a
-- /reload). Multi-kill: kills within MULTI_WINDOW seconds of each other.

local Kills = {}
ns.Kills = Kills

local MULTI_WINDOW = 10
local FALLBACK_DELAY = 1  -- seconds to wait for the chat message before reporting an unnamed kill

local lastKillAt = -math.huge
local multi = 0
local namedAt = -math.huge
local lastSessionKills

-- Turns a Blizzard format string ("%s dies, ... %d)") into a Lua pattern.
local function FormatToPattern(fmt)
  local p = fmt:gsub("([%(%)%.%[%]%*%+%-%?%^%$])", "%%%1")
  p = p:gsub("%%s", "(.+)"):gsub("%%d", "(%%d+)")
  return "^" .. p .. "$"
end

local WITH_RANK = FormatToPattern(type(COMBATLOG_HONORGAIN) == "string" and COMBATLOG_HONORGAIN
  or "%s dies, honorable kill Rank: %s (Estimated Honor Points: %d)")
local NO_RANK = FormatToPattern(type(COMBATLOG_HONORGAIN_NO_RANK) == "string" and COMBATLOG_HONORGAIN_NO_RANK
  or "%s dies, honorable kill (Estimated Honor Points: %d)")

-- Returns victim, rank (or nil), honour, or nil if the message isn't an honourable kill.
function Kills.Parse(msg)
  if type(msg) ~= "string" then return end
  local victim, rank, honor = msg:match(WITH_RANK)
  if victim then return victim, rank, tonumber(honor) end
  victim, honor = msg:match(NO_RANK)
  if victim then return victim, nil, tonumber(honor) end
end

local function State()
  ns.db.kills = ns.db.kills or { streak = 0 }
  return ns.db.kills
end

local function SessionKills()
  return ns.call(GetPVPSessionStats)
end

local function Report(victim, rank, honor)
  local now = GetTime()
  multi = (now - lastKillAt <= MULTI_WINDOW) and multi + 1 or 1
  lastKillAt = now
  local state = State()
  state.streak = (state.streak or 0) + 1
  state.best = math.max(state.best or 0, state.streak)
  lastSessionKills = SessionKills() or lastSessionKills

  if not ns.db.settings.kill then return end
  local name = victim and (victim:match("^[^-]+") or victim)
  local p = ns.NewPayload("KILL")
    :Set("v", (name and ns.PvP.RecentlySeen(name)) or name)
    :Set("vr", rank)
    :Set("hon", honor)
    :Set("streak", state.streak)
    :Set("multi", multi)
    :SetLocation(ns.Location())
  local health, maxHealth = ns.call(UnitHealth, "player"), ns.call(UnitHealthMax, "player")
  if health and maxHealth and maxHealth > 0 then p:Set("hp", math.floor(health / maxHealth * 100 + 0.5)) end
  p:Send()
end

local DEAD_WINDOW = 15     -- seconds a dead enemy player can still be credited as a counter-only kill
local claimed = {}         -- name -> deadAt already credited, so one corpse is one kill

-- Diagnostic kept in SavedVariables: the last few honour messages as received.
local function NoteHonorMessage(msg, parsed)
  local secret = issecretvalue and issecretvalue(msg) or false
  local log = ns.db.killDebug or {}
  ns.db.killDebug = log
  log.messages = log.messages or {}
  table.insert(log.messages, 1, { at = time(), secret = secret, parsed = parsed,
                                  text = secret and "<secret>" or tostring(msg) })
  for i = #log.messages, 6, -1 do log.messages[i] = nil end
end

ns.On("CHAT_MSG_COMBAT_HONOR_GAIN", function(msg)
  local victim, rank, honor = Kills.Parse(ns.safe(msg))
  NoteHonorMessage(msg, victim ~= nil)
  if not victim then return end
  namedAt = GetTime()
  ns.PvP.Scan() -- refresh victim details if they're still targeted or have a nameplate
  local name = victim:match("^[^-]+") or victim
  for _, d in ipairs(ns.PvP.RecentlyDead(DEAD_WINDOW)) do
    if d.name == name then claimed[name] = d.deadAt end -- their corpse is this kill
  end
  Report(victim, rank, honor)
end)

-- Fallback when the chat message is hidden: report kills the counter shows but
-- the chat message didn't name, naming the newest enemy player seen dead
-- (usually your target's corpse) who hasn't been credited yet.
ns.On("PLAYER_PVP_KILLS_CHANGED", function()
  local changedAt = GetTime()
  ns.PvP.Scan() -- catch the corpse while it's still targeted
  C_Timer.After(FALLBACK_DELAY, function()
    local kills = SessionKills()
    local log = ns.db.killDebug or {}
    ns.db.killDebug = log
    log.counterEvents = (log.counterEvents or 0) + 1
    log.honorEventRegistered = not ns.unavailableEvents.CHAT_MSG_COMBAT_HONOR_GAIN
    if not kills then return end
    local missed = lastSessionKills and (kills - lastSessionKills) or 0
    lastSessionKills = kills
    if namedAt >= changedAt - FALLBACK_DELAY then return end -- the chat message covered it
    ns.PvP.Scan()
    local dead = ns.PvP.RecentlyDead(DEAD_WINDOW)
    for _ = 1, missed do
      local victim
      for _, d in ipairs(dead) do
        if claimed[d.name] ~= d.deadAt then
          victim = d
          claimed[d.name] = d.deadAt
          break
        end
      end
      Report(victim and victim.name, nil, nil)
    end
  end)
end)

ns.On("PLAYER_ENTERING_WORLD", function()
  lastSessionKills = SessionKills() or lastSessionKills
end)

ns.On("PLAYER_DEAD", function()
  if ns.db then State().streak = 0 end
end)
