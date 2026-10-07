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
  if name == ADDON then InitDB() end
end)

local enteredWorld = false

ns.On("PLAYER_ENTERING_WORLD", function(isInitialLogin, isReloadingUi)
  if enteredWorld and not isInitialLogin and not isReloadingUi then return end -- zoning
  local isReload = isReloadingUi and true or false
  enteredWorld = true

  ns.Gold.Begin(isReload)
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
  local p = ns.NewPayload("DEATH"):SetLocation(ns.Location())
  ns.PvP.Scan() -- catch an attacker still targeting you, even if no combat-log data arrived
  local killer, isPlayer = ns.PvP.RecentKiller()
  if killer then
    p:Set("k", killer):Set("kpvp", isPlayer and 1 or 0)
  end
  p:Send()
end)

ns.On("PLAYER_LEVEL_UP", function(level)
  local char = ns.db.chars[ns.CharKey()]
  local previous = char and char.levelReachedAt
  if char then
    char.levelReachedAt = time()
    char.level = level
  end
  if not ns.db.settings.level then return end
  local session = ns.db.sessions[ns.CharKey()]
  ns.NewPayload("LEVEL")
    :Set("new", level)
    :Set("prev", previous and (time() - previous))
    :Set("sess", session and (time() - session.start))
    :SetLocation(ns.Location())
    :Send()
end)

ns.On("PLAYER_LOGOUT", function()
  ns.Gold.Finish()
end)

------------------------------------------------------------------------------
-- Slash commands
------------------------------------------------------------------------------

local TOGGLES = { death = "Death", level = "Level-up", pvp = "PvP attack", flag = "PvP flag", summary = "Logout gold summary" }

local function OnOff(v) return v and "|cff55ff55on|r" or "|cffff5555off|r" end

local function Status()
  local s = ns.db.settings
  ns.Print("Notifications:")
  for _, key in ipairs({ "death", "level", "pvp", "flag", "summary" }) do
    print(string.format("  %s (%s): %s", TOGGLES[key], key, OnOff(s[key])))
  end
  print("  Screenshot format: " .. tostring(ns.call(GetCVar, "screenshotFormat")))
  print("  Combat log PvP detection: " .. OnOff(ns.PvP.CombatLogAvailable()))
  print("  Queued signals: " .. ns.Signal.QueueLength())
  print("Commands: /fnotify test | /fnotify preview | /fnotify <" .. "death|level|pvp|flag|summary> | /fnotify debug")
end

SLASH_FOREVERNOTIFY1 = "/fnotify"
SlashCmdList.FOREVERNOTIFY = function(msg)
  local cmd = (msg or ""):lower():match("^%s*(%S*)")
  if cmd == "" or cmd == "status" then
    Status()
  elseif cmd == "test" then
    ns.NewPayload("TEST"):SetLocation(ns.Location()):Send()
    ns.Print("Test notification sent. Check Discord in a few seconds.")
  elseif cmd == "preview" then
    ns.Signal.Preview(ns.NewPayload("TEST"):Serialize(ns.Signal.MAX_PAYLOAD), 5)
    ns.Print("Showing the signal grid for 5 seconds (no screenshot).")
  elseif cmd == "debug" then
    ns.db.settings.debug = not ns.db.settings.debug
    ns.Print("Debug output " .. OnOff(ns.db.settings.debug))
  elseif TOGGLES[cmd] then
    ns.db.settings[cmd] = not ns.db.settings[cmd]
    ns.Print(TOGGLES[cmd] .. " notifications " .. OnOff(ns.db.settings[cmd]))
  else
    Status()
  end
end
