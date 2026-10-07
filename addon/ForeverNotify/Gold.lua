local ADDON, ns = ...

-- Tracks gold in and out per session, categorised by what was open when the
-- money changed, and writes a summary to SavedVariables at logout. The game
-- only writes SavedVariables on logout or /reload, which is when the companion
-- picks the summary up.

local Gold = {}
ns.Gold = Gold

local open = {}           -- category -> true while that UI/context is active
local windowUntil = {}    -- category -> GetTime() deadline for short-lived contexts

-- Checked in order; the first active context wins.
local PRIORITY = { "quest", "auction", "mail", "vendor", "trainer", "flight", "trade", "guildbank", "loot" }

local CONTEXT_EVENTS = {
  MERCHANT_SHOW = { "vendor", true },        MERCHANT_CLOSED = { "vendor", false },
  MAIL_SHOW = { "mail", true },              MAIL_CLOSED = { "mail", false },
  AUCTION_HOUSE_SHOW = { "auction", true },  AUCTION_HOUSE_CLOSED = { "auction", false },
  TRAINER_SHOW = { "trainer", true },        TRAINER_CLOSED = { "trainer", false },
  TAXIMAP_OPENED = { "flight", true },       TAXIMAP_CLOSED = { "flight", false },
  TRADE_SHOW = { "trade", true },            TRADE_CLOSED = { "trade", false },
  GUILDBANKFRAME_OPENED = { "guildbank", true }, GUILDBANKFRAME_CLOSED = { "guildbank", false },
  LOOT_OPENED = { "loot", true },            LOOT_CLOSED = { "loot", false },
  QUEST_COMPLETE = { "quest", true },        QUEST_FINISHED = { "quest", false },
}

for event, spec in pairs(CONTEXT_EVENTS) do
  local category, isOpen = spec[1], spec[2]
  ns.On(event, function()
    open[category] = isOpen or nil
    -- Money from closing a window (e.g. quest reward) can land just after it closes.
    if not isOpen then windowUntil[category] = GetTime() + 1 end
  end)
end

ns.On("QUEST_TURNED_IN", function() windowUntil.quest = GetTime() + 2 end)
ns.On("CHAT_MSG_MONEY", function() windowUntil.loot = GetTime() + 1 end)

function Gold.Category()
  local now = GetTime()
  for _, category in ipairs(PRIORITY) do
    if open[category] or (windowUntil[category] or 0) > now then return category end
  end
  return "other"
end

local function Session()
  return ns.db and ns.db.sessions[ns.CharKey()]
end

local function Record(session, delta, category)
  if delta == 0 then return end
  local bucket = delta > 0 and session.income or session.expense
  bucket[category] = (bucket[category] or 0) + math.abs(delta)
end

local function UpdateCharacter()
  local key = ns.CharKey()
  local char = ns.db.chars[key] or {}
  ns.db.chars[key] = char
  char.name = ns.PlayerName()
  char.realm = ns.Realm()
  char.money = ns.call(GetMoney) or char.money
  char.level = ns.call(UnitLevel, "player") or char.level
  local _, classFile = ns.call(UnitClass, "player")
  char.class = classFile or char.class
  char.seen = time()
  return char
end
Gold.UpdateCharacter = UpdateCharacter

-- Called on initial login (new session) and on /reload (session continues).
function Gold.Begin(isReload)
  local key = ns.CharKey()
  local money = ns.call(GetMoney) or 0
  local session = ns.db.sessions[key]
  if isReload and session then
    session.reloads = (session.reloads or 0) + 1
    Record(session, money - session.lastMoney, "other")
  else
    session = {
      id = key .. ":" .. time(),
      start = time(),
      startMoney = money,
      startLevel = ns.call(UnitLevel, "player"),
      income = {},
      expense = {},
      deaths = 0,
      reloads = 0,
    }
    ns.db.sessions[key] = session
  end
  session.lastMoney = money
  UpdateCharacter()
end

ns.On("PLAYER_MONEY", function()
  local session = Session()
  if not session then return end
  local money = ns.call(GetMoney)
  if not money then return end
  Record(session, money - session.lastMoney, Gold.Category())
  session.lastMoney = money
  UpdateCharacter()
end)

function Gold.AddDeath()
  local session = Session()
  if session then session.deaths = session.deaths + 1 end
end

-- PLAYER_LOGOUT also fires on /reload; the companion discards the summary if
-- the add-on reports a reload shortly afterwards.
function Gold.Finish()
  local session = Session()
  -- Diagnostic kept in SavedVariables: what the client reported at logout.
  ns.db.lastLogout = {
    at = time(),
    rawName = tostring(ns.call(UnitName, "player")),
    key = ns.CharKey(),
    sessionFound = session ~= nil,
  }
  if not session then return end
  local char = UpdateCharacter()

  local total, count = 0, 0
  for _, c in pairs(ns.db.chars) do
    total = total + (c.money or 0)
    count = count + 1
  end

  ns.db.lastSummary = {
    id = session.id,
    char = char.name,
    realm = char.realm,
    class = char.class,
    start = session.start,
    stop = time(),
    startMoney = session.startMoney,
    endMoney = char.money,
    startLevel = session.startLevel,
    endLevel = char.level,
    income = session.income,
    expense = session.expense,
    deaths = session.deaths,
    reloads = session.reloads,
    accountMoney = total,
    accountChars = count,
    zone = ns.call(GetRealZoneText),
    enabled = ns.db.settings.summary,
  }
end
