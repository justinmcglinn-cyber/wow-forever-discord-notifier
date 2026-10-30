local ADDON, ns = ...

local function InitDB()
  ForeverNotifyDB = ForeverNotifyDB or {}
  local db = ForeverNotifyDB
  db.settings = db.settings or {}
  for k, v in pairs(ns.DEFAULT_SETTINGS) do
    if db.settings[k] == nil then db.settings[k] = v end
  end
  db.chars = db.chars or {}
  db.sessions = db.sessions or {}
  ns.db = db
end

ns.On("ADDON_LOADED", function(name)
  if name == ADDON then
    InitDB()
    ns.PvP.SetupCombatLog()
  end
end)

local enteredWorld = false

ns.On("PLAYER_ENTERING_WORLD", function(isInitialLogin, isReloadingUi)
  if enteredWorld and not isInitialLogin and not isReloadingUi then return end -- zoning
  local isReload = isReloadingUi and true or false
  enteredWorld = true

  ns.BeginSession()
  ns.Gold.Begin(isReload)
  ns.Played.Begin()
  ns.PvP.CheckFlag()
  ns.Signal.EnsureLosslessFormat()

  C_Timer.After(2, function()
    ns.Signal.SetReady(true)
    -- Tells the companion to discard the summary written by this reload.
    if isReload then ns.NewPayload("RELOAD"):Send() end
  end)
end)

ns.On("PLAYER_DEAD", function()
  ns.Gold.AddDeath()
  if not ns.db.settings.death then return end
  local p = ns.NewPayload("DEATH"):SetLocation()
  ns.PvP.Scan() -- catch an attacker still targeting you, even if no combat-log data arrived
  local killer, isPlayer = ns.PvP.RecentKiller()
  if killer then
    p:Set("k", killer):Set("kpvp", isPlayer and 1 or 0)
  end
  p:Send()
end)

ns.On("PLAYER_LEVEL_UP", function(level)
  local char = ns.db.chars[ns.CharKey()]
  if char then char.level = level end
  local played = ns.Played.LevelUp(level)
  if not ns.db.settings.level then return end
  local session = ns.db.sessions[ns.CharKey()]
  -- The client still reports the old level while this event fires.
  ns.NewPayload("LEVEL", level)
    :Set("new", level)
    :Set("prev", played and math.floor(played))
    :Set("sess", session and (time() - session.start))
    :SetLocation()
    :Send()
end)

ns.On("PLAYER_LOGOUT", function()
  ns.Gold.Finish()
end)

-- When the game blocks one of our calls (the "blocked from an action only
-- available to the Blizzard UI" popup), say which one so it can be fixed.
local function OnBlocked(addon, func)
  if addon ~= ADDON then return end
  local inCombat = ns.call(InCombatLockdown) and true or false
  local entry = { func = tostring(func), inCombat = inCombat, at = time() }
  if ns.db then
    ns.db.blocked = ns.db.blocked or {}
    table.insert(ns.db.blocked, 1, entry)
    for i = #ns.db.blocked, 11, -1 do ns.db.blocked[i] = nil end
  end
  ns.Print("|cffff5555The game blocked|r " .. entry.func .. (inCombat and " (in combat)" or " (out of combat)")
    .. ". Please report this; click Ignore on the popup.")
end
ns.On("ADDON_ACTION_FORBIDDEN", OnBlocked)
ns.On("ADDON_ACTION_BLOCKED", OnBlocked)

------------------------------------------------------------------------------
-- Slash commands
------------------------------------------------------------------------------

-- Notifications that /fnotify <name> turns on and off, in the order /fnotify lists them.
local TOGGLE_ORDER = {
  { "death", "Death" }, { "level", "Level-up" }, { "pvp", "PvP attack" }, { "kill", "PvP kill" },
  { "flag", "PvP flag" }, { "summary", "Logout gold summary" },
}
local TOGGLES, TOGGLE_NAMES = {}, {}
for i, t in ipairs(TOGGLE_ORDER) do TOGGLES[t[1]], TOGGLE_NAMES[i] = t[2], t[1] end

local function OnOff(v) return v and "|cff55ff55on|r" or "|cffff5555off|r" end

local function Status()
  local s = ns.db.settings
  ns.Print("Notifications:")
  for _, key in ipairs(TOGGLE_NAMES) do
    print(string.format("  %s (%s): %s", TOGGLES[key], key, OnOff(s[key])))
  end
  print("  Screenshot format: " .. tostring(ns.call(GetCVar, "screenshotFormat")))
  print("  Combat log (killers/attackers you can't see): " .. OnOff(ns.PvP.CombatLogAvailable())
    .. (s.combatLog == nil and " (auto)" or ""))
  print("  Queued signals: " .. ns.Signal.QueueLength())
  for i, b in ipairs(ns.db.blocked or {}) do
    if i > 3 then break end
    print(string.format("  Blocked by the game: %s (%s, %s)", b.func, b.inCombat and "in combat" or "out of combat",
      date("%H:%M:%S", b.at)))
  end
  print("Commands: /fnotify test | /fnotify preview | /fnotify <" .. table.concat(TOGGLE_NAMES, "|")
    .. "> | /fnotify combatlog | /fnotify debug")
end

SLASH_FOREVERNOTIFY1 = "/fnotify"
SlashCmdList.FOREVERNOTIFY = function(msg)
  local cmd = (msg or ""):lower():match("^%s*(%S*)")
  if cmd == "" or cmd == "status" then
    Status()
  elseif cmd == "test" then
    ns.NewPayload("TEST"):SetLocation():Send()
    ns.Print("Test notification sent. Check Discord in a few seconds.")
  elseif cmd == "preview" then
    if ns.Signal.Preview(ns.NewPayload("TEST"):Serialize(ns.Signal.MAX_PAYLOAD), 5) then
      ns.Print("Showing the signal grid for 5 seconds (no screenshot).")
    else
      ns.Print("A notification is being sent right now; try again in a moment.")
    end
  elseif cmd == "debug" then
    ns.db.settings.debug = not ns.db.settings.debug
    ns.Print("Debug output " .. OnOff(ns.db.settings.debug))
  elseif cmd == "combatlog" then
    ns.db.settings.combatLog = not ns.PvP.CombatLogWanted()
    ns.PvP.SetupCombatLog()
    ns.Print("Combat log " .. OnOff(ns.db.settings.combatLog))
    if ns.db.settings.combatLog then
      ns.Print("If the game shows a \"blocked from an action\" popup, type /fnotify combatlog again to turn it off.")
    end
  elseif TOGGLES[cmd] then
    ns.db.settings[cmd] = not ns.db.settings[cmd]
    ns.Print(TOGGLES[cmd] .. " notifications " .. OnOff(ns.db.settings[cmd]))
  else
    Status()
  end
end
