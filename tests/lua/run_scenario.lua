-- Plays a scripted session through the add-on and checks its behaviour.
-- Usage: lua5.1 run_scenario.lua <addon dir> <output dir>
-- Writes <output dir>/signals.json (payload + drawn blocks per screenshot) and
-- <output dir>/ForeverNotify.lua (SavedVariables as written at final logout).

local addonDir, outDir = arg[1], arg[2]
package.path = arg[0]:gsub("[^/]+$", "") .. "?.lua;" .. package.path
local S = require("wowstub")

local failures = 0
local function check(cond, msg)
  if not cond then
    failures = failures + 1
    io.stderr:write("FAIL: " .. msg .. "\n")
  end
end

S.units.player = {
  name = "Thrall", level = 23, class = "Shaman", classFile = "SHAMAN", race = "Orc",
  player = true, health = 1500, maxHealth = 2000, guid = "Player-1-PLAYER", pvp = false,
}
S.money = 100000 -- 10g

local ns = S.LoadAddon(addonDir)

-- Capture payload text alongside each screenshot.
local payloads = {}
local encode = ns.Signal.Encode
ns.Signal.Encode = function(text)
  payloads[#payloads + 1] = text
  return encode(text)
end

local function LastPayload()
  return payloads[#payloads] or ""
end

local function Has(text, line)
  return ("\n" .. text .. "\n"):find("\n" .. line:gsub("%p", "%%%0") .. "\n") ~= nil
end

-- Login ---------------------------------------------------------------------
S.Fire("ADDON_LOADED", "ForeverNotify")
S.Fire("PLAYER_ENTERING_WORLD", true, false)
check(S.cvars.screenshotFormat == "png", "screenshot format switched to png")
S.Advance(3)
check(#S.screenshots == 0, "no signal at plain login")

-- Test command ----------------------------------------------------------------
SlashCmdList.FOREVERNOTIFY("test")
S.Advance(1)
check(#S.screenshots == 1, "test produced a screenshot")
check(Has(LastPayload(), "t=TEST"), "test payload type")
check(Has(LastPayload(), "zone=Hillsbrad Foothills"), "test payload zone")
check(Has(LastPayload(), "x=52.4"), "test payload x coordinate")
check(not ForeverNotifySignalFrame.shown, "grid hidden after screenshot")
local shot = S.screenshots[1]
check(math.abs(shot.scale - 768 / 1080) < 1e-9, "grid scaled to physical pixels")

-- Gold tracking ---------------------------------------------------------------
S.Fire("MERCHANT_SHOW"); S.money = S.money + 500; S.Fire("PLAYER_MONEY")
S.money = S.money - 2000; S.Fire("PLAYER_MONEY"); S.Fire("MERCHANT_CLOSED")
S.Advance(2)
S.Fire("LOOT_OPENED"); S.money = S.money + 1234; S.Fire("PLAYER_MONEY"); S.Fire("LOOT_CLOSED")
S.Advance(2)
S.Fire("QUEST_TURNED_IN", 123, 1000, 5000); S.money = S.money + 5000; S.Fire("PLAYER_MONEY")
S.Advance(3)
S.money = S.money - 100; S.Fire("PLAYER_MONEY")
local session = ForeverNotifyDB.sessions["Thrall-Area52"]
check(session.income.vendor == 500, "vendor income")
check(session.expense.vendor == 2000, "vendor spending")
check(session.income.loot == 1234, "loot income")
check(session.income.quest == 5000, "quest income")
check(session.expense.other == 100, "other spending")

-- PvP attack ------------------------------------------------------------------
S.units.player.health = S.SECRET -- secret values must be skipped, not crash
S.units.nameplate3 = {
  name = "Gankster", realm = "Stormrage", level = 60, class = "Rogue", classFile = "ROGUE",
  race = "Undead", guild = "Shadow Council", player = true, hostile = true, target = "player",
}
S.units.nameplate4 = { name = "Lookout", level = 58, class = "Hunter", race = "Troll", player = true, hostile = true }
S.inCombat = true
local before = #S.screenshots
S.Fire("PLAYER_REGEN_DISABLED")
S.Advance(1)
check(#S.screenshots == before + 1, "PvP alert screenshot")
local pvp = LastPayload()
check(Has(pvp, "t=PVP"), "pvp payload type")
check(Has(pvp, "a1=Gankster|Stormrage|60|Rogue|Undead|Shadow Council"), "pvp attacker summary: " .. pvp)
check(Has(pvp, "near=2"), "two hostile players nearby")
check(not pvp:find("hp="), "secret health omitted")
check(Has(pvp, "pvp=contested"), "zone pvp type")

S.Advance(5)
check(#S.screenshots == before + 1, "no repeat alert for the same attacker")

-- Death to the attacker ---------------------------------------------------------
S.Fire("PLAYER_DEAD")
S.Advance(1)
local death = LastPayload()
check(Has(death, "t=DEATH"), "death payload type")
check(Has(death, "k=Gankster|Stormrage|60|Rogue|Undead|Shadow Council"), "death killer: " .. death)
check(Has(death, "kpvp=1"), "death marked pvp")
S.inCombat = false
S.units.nameplate3, S.units.nameplate4 = nil, nil
S.units.player.health = 2000

-- Death to an NPC seen via the combat log ----------------------------------------
S.Advance(30)
S.cleu = { 0, "SWING_DAMAGE", false, "Creature-0-1", "Hillsbrad Farmer", 0x0A48, 0, "Player-1-PLAYER", "Thrall", 0x511, 0 }
S.Fire("COMBAT_LOG_EVENT_UNFILTERED")
S.Fire("PLAYER_DEAD")
S.Advance(1)
death = LastPayload()
check(Has(death, "k=Hillsbrad Farmer"), "npc killer from combat log: " .. death)
check(Has(death, "kpvp=0"), "npc death not pvp")

-- Death to an NPC seen only via its nameplate (no combat-log data) ----------------
S.Advance(30)
S.units.nameplate5 = { name = "Murloc Forager", level = 22, hostile = true, target = "player" }
S.inCombat = true
S.Fire("PLAYER_REGEN_DISABLED")
S.Advance(2)
S.Fire("PLAYER_DEAD")
S.Advance(1)
death = LastPayload()
check(Has(death, "k=Murloc Forager"), "npc killer from nameplate scan: " .. death)
check(Has(death, "kpvp=0"), "nameplate npc death not pvp")
S.inCombat = false
S.units.nameplate5 = nil
S.Advance(2)

-- Combat-log PvP (attacker with no nameplate) ---------------------------------------
S.Advance(30)
S.inCombat = true
S.guidInfo["Player-2-ROGUE"] = { "Rogue", "ROGUE", "Night Elf", "NightElf", 3, "Sneaky", "Stormrage" }
S.cleu = { 0, "SPELL_DAMAGE", false, "Player-2-ROGUE", "Sneaky-Stormrage", 0x0548, 0, "Player-1-PLAYER", "Thrall", 0x511, 0 }
before = #S.screenshots
S.Fire("COMBAT_LOG_EVENT_UNFILTERED")
S.Advance(1)
check(#S.screenshots == before + 1, "combat-log PvP alert")
check(Has(LastPayload(), "a1=Sneaky|Stormrage||Rogue|Night Elf|"), "combat-log attacker: " .. LastPayload())
S.inCombat = false
S.Advance(2)

-- Level up ---------------------------------------------------------------------
S.units.player.level = 24
S.Fire("PLAYER_LEVEL_UP", 24)
S.Advance(1)
check(Has(LastPayload(), "t=LEVEL"), "level payload type")
check(Has(LastPayload(), "new=24"), "new level")

-- Reload keeps the session and signals the companion --------------------------------
local sessionId = session.id
S.Fire("PLAYER_LOGOUT")
check(ForeverNotifyDB.lastSummary ~= nil, "summary written on logout/reload")
S.Fire("PLAYER_ENTERING_WORLD", false, true)
S.Advance(3)
check(Has(LastPayload(), "t=RELOAD"), "reload signal sent")
check(ForeverNotifyDB.sessions["Thrall-Area52"].id == sessionId, "session survives reload")
check(ForeverNotifyDB.sessions["Thrall-Area52"].reloads == 1, "reload counted")

-- Zoning is not a reload ----------------------------------------------------------
local count = #S.screenshots
S.Fire("PLAYER_ENTERING_WORLD", false, false)
S.Advance(3)
check(#S.screenshots == count, "zoning sends nothing")

-- Final logout ---------------------------------------------------------------------
ForeverNotifyDB.chars["Jaina-Area52"] = { name = "Jaina", realm = "Area52", money = 2500000 }
S.Advance(600)
S.Fire("PLAYER_LOGOUT")
local summary = ForeverNotifyDB.lastSummary
check(summary.startMoney == 100000, "summary start money")
check(summary.endMoney == S.money, "summary end money")
check(summary.deaths == 3, "summary deaths")
check(summary.accountMoney == S.money + 2500000, "account total")
check(summary.accountChars == 2, "account character count")
check(summary.startLevel == 23 and summary.endLevel == 24, "summary levels")

-- Blocked combat log must not break loading ------------------------------------------
check(ns.PvP.CombatLogAvailable(), "combat log reported available")

-- Outputs -----------------------------------------------------------------------
local records = {}
for i, s in ipairs(S.screenshots) do
  records[i] = { payload = payloads[i], blocks = s.blocks }
end
local out = assert(io.open(outDir .. "/signals.json", "w"))
out:write(S.Json(records))
out:close()
out = assert(io.open(outDir .. "/ForeverNotify.lua", "w"))
out:write(S.SavedVariablesText("ForeverNotifyDB"))
out:close()

if failures > 0 then
  io.stderr:write(failures .. " check(s) failed\n")
  os.exit(1)
end
io.write("all add-on checks passed (" .. #S.screenshots .. " signals)\n")
