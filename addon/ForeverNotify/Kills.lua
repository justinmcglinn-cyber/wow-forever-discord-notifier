local ADDON, ns = ...

-- Reports honorable kills of enemy-faction players.
--
-- On Forever the combat log is blocked and the honour chat message doesn't
-- name the victim ("You have been awarded 3 Honor."), so kills are counted from
-- the honourable-kill counter (PLAYER_PVP_KILLS_CHANGED + GetPVPSessionStats)
-- and matched to enemy players seen dead (PvP.RecentlyDead). Other clients'
-- "X dies, honorable kill ..." messages name the victim directly.
--
-- An honourable kill means "your group killed someone near you", so in a
-- party/raid only *your* kills are posted on their own: the victim was your
-- target while alive at death or in the TARGET_WINDOW seconds before. The rest
-- go into one battle report per fight, sent once you've been out of combat for
-- REPORT_QUIET seconds. Solo, every honourable kill is yours.
--
-- Streak (your kills since your last death; survives /reload) and multi-kills
-- (your kills within MULTI_WINDOW seconds) count only your kills.

local Kills = {}
ns.Kills = Kills

local MULTI_WINDOW = 10
local FALLBACK_DELAY = 1   -- seconds to wait for a naming chat message before using the counter
local DEAD_WINDOW = 15     -- seconds a dead enemy player can still be matched to a kill
local TARGET_WINDOW = 10   -- your target within this many seconds before their death = your kill
local HONOR_WINDOW = 3     -- an honour message this close to a kill is that kill's honour
local REPORT_QUIET = 30    -- seconds out of combat before a fight's battle report is sent
local MAX_VICTIMS_TEXT = 220

local lastKillAt = -math.huge
local multi = 0
local namedAt = -math.huge
local lastSessionKills
local lastHonor            -- { amount, at } from the latest honour message
local claimed = {}         -- name -> deadAt already credited, so one corpse is one kill
local fight                -- current battle tally, or nil
local lastActivity = -math.huge

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

-- Returns victim, rank (or nil), honour, or nil if the message doesn't name a victim.
function Kills.Parse(msg)
  if type(msg) ~= "string" then return end
  local victim, rank, honor = msg:match(WITH_RANK)
  if victim then return victim, rank, tonumber(honor) end
  victim, honor = msg:match(NO_RANK)
  if victim then return victim, nil, tonumber(honor) end
end

-- Honour from an award message such as "You have been awarded 3 Honor.".
function Kills.ParseHonor(msg)
  if type(msg) ~= "string" then return end
  return tonumber(msg:match("(%d+)%s+[Hh]onor"))
end

local function State()
  ns.db.kills = ns.db.kills or { streak = 0 }
  return ns.db.kills
end

local function SessionKills()
  return ns.call(GetPVPSessionStats)
end

local function InGroup()
  if type(IsInGroup) == "function" then return ns.call(IsInGroup) and true or false end
  return (ns.call(GetNumGroupMembers) or 0) > 0
end

local function InCombat()
  return ns.call(UnitAffectingCombat, "player") and true or false
end

local function Location(p)
  p:SetLocation(ns.Location())
  return p
end

------------------------------------------------------------------------------
-- Battle report
------------------------------------------------------------------------------

local function Fight()
  if not fight then
    fight = { start = GetTime(), total = 0, mine = 0, honor = 0, victims = {}, seenVictim = {} }
  end
  return fight
end

local function AddVictim(name)
  local f = Fight()
  if name and not f.seenVictim[name] then
    f.seenVictim[name] = true
    f.victims[#f.victims + 1] = name
  end
end

local function SendReport()
  local f = fight
  fight = nil
  -- Only worth a post when the group got kills you weren't credited with;
  -- your own kills were already posted one by one.
  if not f or f.total <= f.mine or not ns.db.settings.kill then return end
  local names, shown = {}, 0
  for _, name in ipairs(f.victims) do
    local text = table.concat(names, ", ")
    if #text + #name + 2 > MAX_VICTIMS_TEXT then break end
    names[#names + 1] = name
    shown = shown + 1
  end
  Location(ns.NewPayload("BATTLE")
    :Set("k", f.total)
    :Set("mine", f.mine)
    :Set("hon", f.honor > 0 and f.honor or nil)
    :Set("dur", math.floor(GetTime() - f.start + 0.5))
    :Set("streak", State().streak)
    :Set("v", #names > 0 and table.concat(names, ", ") or nil)
    :Set("more", #f.victims > shown and (#f.victims - shown) or nil)):Send()
end

-- Send the battle report once there's been no kill, honour or combat for
-- REPORT_QUIET seconds. One timer at a time, re-armed until things go quiet.
local reportPending = false

local function ScheduleReport()
  if reportPending then return end
  reportPending = true
  local wait = math.max(0.1, REPORT_QUIET - (GetTime() - lastActivity))
  C_Timer.After(wait, function()
    reportPending = false
    if not fight then return end
    if InCombat() then
      lastActivity = GetTime()
      ScheduleReport()
    elseif GetTime() - lastActivity < REPORT_QUIET - 0.05 then
      ScheduleReport()
    else
      SendReport()
    end
  end)
end

local function Activity()
  lastActivity = GetTime()
  ScheduleReport()
end

------------------------------------------------------------------------------
-- Kills
------------------------------------------------------------------------------

local function HonorNear()
  if lastHonor and GetTime() - lastHonor.at <= HONOR_WINDOW then
    local amount = lastHonor.amount
    lastHonor = nil -- one kill per award
    return amount
  end
end

-- Posts one of your kills.
local function ReportMine(victim, rank, honor)
  local now = GetTime()
  multi = (now - lastKillAt <= MULTI_WINDOW) and multi + 1 or 1
  lastKillAt = now
  local state = State()
  state.streak = (state.streak or 0) + 1
  state.best = math.max(state.best or 0, state.streak)
  local f = Fight()
  f.total, f.mine = f.total + 1, f.mine + 1
  AddVictim(victim)
  Activity()

  if not ns.db.settings.kill then return end
  local p = Location(ns.NewPayload("KILL")
    :Set("v", (victim and ns.PvP.RecentlySeen(victim)) or victim)
    :Set("vr", rank)
    :Set("hon", honor)
    :Set("streak", state.streak)
    :Set("multi", multi))
  local health, maxHealth = ns.call(UnitHealth, "player"), ns.call(UnitHealthMax, "player")
  if health and maxHealth and maxHealth > 0 then p:Set("hp", math.floor(health / maxHealth * 100 + 0.5)) end
  p:Send()
end

-- A kill your group got without you: only counted for the battle report.
local function CountAssist(victim)
  local f = Fight()
  f.total = f.total + 1
  AddVictim(victim)
  Activity()
end

-- Was `name` your target while alive at, or shortly before, `deadAt`?
local function WasMine(name, deadAt)
  local at = ns.PvP.TargetedAliveAt(name)
  return at ~= nil and at >= deadAt - TARGET_WINDOW
end

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
  local text = ns.safe(msg)
  local victim, rank, honor = Kills.Parse(text)
  honor = honor or Kills.ParseHonor(text)
  NoteHonorMessage(msg, victim ~= nil)
  if honor then
    Fight().honor = Fight().honor + honor
    Activity()
  end
  if not victim then
    if honor then lastHonor = { amount = honor, at = GetTime() } end
    return
  end
  -- A client that names the victim (not Forever).
  namedAt = GetTime()
  ns.PvP.Scan() -- refresh victim details if they're still targeted or have a nameplate
  local name = victim:match("^[^-]+") or victim
  local deadAt = GetTime()
  for _, d in ipairs(ns.PvP.RecentlyDead(DEAD_WINDOW)) do
    if d.name == name then claimed[name], deadAt = d.deadAt, d.deadAt end -- their corpse is this kill
  end
  if not InGroup() or WasMine(name, deadAt) then
    ReportMine(name, rank, honor)
  else
    CountAssist(name)
  end
end)

-- The counter: each new honourable kill is matched to an unclaimed enemy seen
-- dead, preferring one you'd been targeting.
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
    if namedAt >= changedAt - FALLBACK_DELAY then return end -- a naming chat message covered it
    ns.PvP.Scan()
    local solo = not InGroup()
    for _ = 1, missed do
      local mine, newest
      for _, d in ipairs(ns.PvP.RecentlyDead(DEAD_WINDOW)) do
        if claimed[d.name] ~= d.deadAt then
          newest = newest or d
          if WasMine(d.name, d.deadAt) then mine = d break end
        end
      end
      local victim = mine or newest
      if victim then claimed[victim.name] = victim.deadAt end
      if mine or solo then
        ReportMine(victim and victim.name, nil, HonorNear())
      else
        CountAssist(victim and victim.name)
      end
    end
  end)
end)

ns.On("PLAYER_REGEN_ENABLED", function()
  if fight then Activity() end
end)

ns.On("PLAYER_ENTERING_WORLD", function()
  lastSessionKills = SessionKills() or lastSessionKills
end)

ns.On("PLAYER_DEAD", function()
  if ns.db then State().streak = 0 end
end)
