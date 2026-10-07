local ADDON, ns = ...

-- Add-ons have no network or file access, so events reach the companion app
-- through screenshots: a small grid of solid-colour blocks is drawn in the
-- top-left corner for one frame, Screenshot() is called, and the companion
-- decodes the grid from the saved file.
--
-- Grid layout (must match companion/forever_notify/signal_decode.py):
--   row 0      calibration: COLUMNS blocks alternating white/black
--   rows 1..n  data, 3 bits per block (red=4, green=2, blue=1), row-major
-- Data bytes: "F" "N" version lenHi lenLo payload... fletcher16Hi fletcher16Lo
-- (checksum covers version through payload).

local Signal = {}
ns.Signal = Signal

Signal.COLUMNS = 64
Signal.BLOCK_PX = 6
Signal.MAX_PAYLOAD = 480

local MAGIC = { 70, 78 } -- "FN"
local floor, ceil = math.floor, math.ceil

function Signal.Checksum(bytes, first, last)
  local s1, s2 = 0, 0
  for i = first, last do
    s1 = (s1 + bytes[i]) % 255
    s2 = (s2 + s1) % 255
  end
  return s2, s1
end

-- Returns the data-area colour indices (0-7) for a payload string.
function Signal.Encode(payload)
  if #payload > Signal.MAX_PAYLOAD then payload = payload:sub(1, Signal.MAX_PAYLOAD) end
  local bytes = { MAGIC[1], MAGIC[2], ns.PROTOCOL_VERSION, floor(#payload / 256), #payload % 256 }
  for i = 1, #payload do bytes[#bytes + 1] = payload:byte(i) end
  local hi, lo = Signal.Checksum(bytes, 3, #bytes)
  bytes[#bytes + 1] = hi
  bytes[#bytes + 1] = lo

  local colors, acc, nbits = {}, 0, 0
  for _, b in ipairs(bytes) do
    for shift = 7, 0, -1 do
      acc = acc * 2 + floor(b / 2 ^ shift) % 2
      nbits = nbits + 1
      if nbits == 3 then
        colors[#colors + 1] = acc
        acc, nbits = 0, 0
      end
    end
  end
  if nbits > 0 then colors[#colors + 1] = acc * 2 ^ (3 - nbits) end
  return colors
end

------------------------------------------------------------------------------
-- Drawing
------------------------------------------------------------------------------

local frame
local textures = {}

local function EnsureFrame()
  if frame then return frame end
  frame = CreateFrame("Frame", "ForeverNotifySignalFrame", UIParent)
  frame:SetFrameStrata("TOOLTIP")
  frame:SetFrameLevel(10000)
  -- Work in physical pixels regardless of UI scale or UI alpha.
  if frame.SetIgnoreParentScale then frame:SetIgnoreParentScale(true) end
  if frame.SetIgnoreParentAlpha then frame:SetIgnoreParentAlpha(true) end
  frame:Hide()
  return frame
end

local function Draw(colors)
  local f = EnsureFrame()
  local _, physicalHeight = GetPhysicalScreenSize()
  f:SetScale(768 / physicalHeight) -- 1 frame unit == 1 screen pixel

  local B, W = Signal.BLOCK_PX, Signal.COLUMNS
  local rows = 1 + ceil(#colors / W)
  f:ClearAllPoints()
  f:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)
  f:SetSize(W * B, rows * B)

  local n = 0
  local function Block(index, color)
    n = n + 1
    local t = textures[n]
    if not t then
      t = f:CreateTexture(nil, "OVERLAY")
      textures[n] = t
    end
    local col, row = index % W, floor(index / W)
    t:ClearAllPoints()
    t:SetPoint("TOPLEFT", f, "TOPLEFT", col * B, -row * B)
    t:SetSize(B, B)
    t:SetColorTexture(floor(color / 4) % 2, floor(color / 2) % 2, color % 2, 1)
    t:Show()
  end

  for col = 0, W - 1 do Block(col, col % 2 == 0 and 7 or 0) end
  for i, color in ipairs(colors) do Block(W + i - 1, color) end
  for i = n + 1, #textures do textures[i]:Hide() end
end

------------------------------------------------------------------------------
-- Screenshot queue
------------------------------------------------------------------------------

local queue = {}
local ready, busy = false, false
local token = 0 -- identifies the in-flight screenshot so stale timeouts are ignored
local awaiting

local function Finish()
  awaiting = nil
  if frame then frame:Hide() end
  busy = false
  C_Timer.After(0.5, Signal.Pump)
end

function Signal.Pump()
  if busy or not ready or #queue == 0 then return end
  busy = true
  token = token + 1
  local myToken = token
  Draw(Signal.Encode(table.remove(queue, 1)))
  frame:Show()
  local framesShown = 0
  frame:SetScript("OnUpdate", function(self)
    framesShown = framesShown + 1
    if framesShown < 2 then return end -- let the grid render for a full frame first
    self:SetScript("OnUpdate", nil)
    awaiting = myToken
    Screenshot()
    C_Timer.After(3, function()
      if awaiting == myToken then Finish() end
    end)
  end)
end

-- urgent payloads (PvP alerts) go ahead of anything already waiting.
function Signal.Send(payload, urgent)
  table.insert(queue, urgent and 1 or #queue + 1, payload)
  ns.Debug((urgent and "queued (urgent): " or "queued: ") .. payload:gsub("\n", " ; "))
  Signal.Pump()
end

function Signal.SetReady(value)
  ready = value
  Signal.Pump()
end

function Signal.QueueLength()
  return #queue
end

local function OnScreenshotDone()
  if awaiting then Finish() end
end
ns.On("SCREENSHOT_SUCCEEDED", OnScreenshotDone)
ns.On("SCREENSHOT_FAILED", OnScreenshotDone)

-- JPEG compression smears neighbouring blocks together, so switch screenshots
-- to a lossless format.
function Signal.EnsureLosslessFormat()
  local current = ns.call(GetCVar, "screenshotFormat")
  if current == "png" or current == "tga" then return current end
  for _, fmt in ipairs({ "png", "tga" }) do
    pcall(SetCVar, "screenshotFormat", fmt)
    if ns.call(GetCVar, "screenshotFormat") == fmt then
      ns.Print("Screenshot format changed from " .. tostring(current) .. " to " .. fmt
        .. " so the companion app can read notifications.")
      return fmt
    end
  end
  ns.Print("|cffff5555Could not switch screenshots to PNG/TGA. Notifications may fail to decode.|r")
  return current
end

-- Shows the grid for a few seconds without taking a screenshot (debugging).
function Signal.Preview(payload, seconds)
  Draw(Signal.Encode(payload))
  frame:Show()
  C_Timer.After(seconds or 5, function()
    if not busy then frame:Hide() end
  end)
end
