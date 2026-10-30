local ADDON, ns = ...

-- Time played at the current level, for "time on previous level" in level-up
-- posts. The server's count (the "this level" line of /played) is asked for at
-- login and /reload, and counted forward from there. If the server never
-- answers, the add-on's own count is used, but only when it has covered the
-- whole level (it saw the level start), so a partial count is never posted.

local Played = {}
ns.Played = Played

local SYNC_INTERVAL = 60  -- seconds between saves of the running count (a crash loses at most this)
local HIDE_FOR = 10       -- seconds to keep the chat windows' /played lines hidden after our request

local key                 -- character the count belongs to: ns.SessionKey() from login
local mark                -- GetTime() up to which the count has been added
local hiddenFrames = {}   -- chat frames we stopped listening for TIME_PLAYED_MSG

-- Per-character record in SavedVariables: { level, secs, complete }.
local function Record()
  local char = ns.db and key and ns.db.chars[key]
  if not char then return end
  char.played = char.played or {}
  return char.played
end

-- Adds the time since the last mark to the count.
local function Flush()
  local rec, now = Record(), GetTime()
  if rec and mark then rec.secs = (rec.secs or 0) + (now - mark) end
  mark = now
end

-- Our request would print "Total time played: ..." in chat; the chat windows
-- stop listening until the answer arrives or HIDE_FOR passes, so only a
-- /played the player types shows up.
local function RestoreChat()
  for frame in pairs(hiddenFrames) do
    pcall(frame.RegisterEvent, frame, "TIME_PLAYED_MSG")
  end
  hiddenFrames = {}
end

local function HideChat()
  for i = 1, (tonumber(NUM_CHAT_WINDOWS) or 10) do
    local frame = _G["ChatFrame" .. i]
    if frame and frame.IsEventRegistered and ns.call(frame.IsEventRegistered, frame, "TIME_PLAYED_MSG") then
      if pcall(frame.UnregisterEvent, frame, "TIME_PLAYED_MSG") then hiddenFrames[frame] = true end
    end
  end
  C_Timer.After(HIDE_FOR, RestoreChat)
end

-- Called on initial login and on /reload.
function Played.Begin()
  key = ns.SessionKey()
  mark = GetTime()
  local rec, level = Record(), ns.call(UnitLevel, "player")
  -- Levels gained without the add-on: start over, incomplete until the server answers.
  if rec and level and level > 0 and rec.level ~= level then
    rec.level, rec.secs, rec.complete = level, 0, false
  end
  if type(RequestTimePlayed) == "function" then
    HideChat()
    if not pcall(RequestTimePlayed) then RestoreChat() end
  end
end

ns.On("TIME_PLAYED_MSG", function(_, atLevel)
  -- Re-register on the next frame, not while this event is still being delivered.
  if next(hiddenFrames) then C_Timer.After(0, RestoreChat) end
  atLevel = ns.safe(atLevel)
  local rec = Record()
  if not rec or type(atLevel) ~= "number" then return end
  rec.secs, rec.complete = atLevel, true
  mark = GetTime()
end)

-- Seconds played at the level just finished (nil if unknown), and starts
-- counting the new one.
function Played.LevelUp(level)
  Flush()
  local rec = Record()
  if not rec then return end
  local secs = rec.complete and rec.secs or nil
  rec.level, rec.secs, rec.complete = level, 0, true
  return secs
end

ns.On("PLAYER_LOGOUT", Flush)
C_Timer.NewTicker(SYNC_INTERVAL, Flush)
