# Analysis: WoW Forever → Discord event notifications

**Status:** Draft for review — no code has been written yet.
**Date:** 6 October 2026

## 1. Goal

Send notifications for selected in-game events (e.g. queue pop, ready check,
whisper, death, level-up) from the World of Warcraft: Forever client to a
Discord channel, so they reach your phone via the Discord app.

## 2. Key finding: an add-on alone cannot do this

WoW add-ons run in a sandboxed Lua environment:

- No network access (no sockets, no HTTP).
- No arbitrary file I/O. The only disk writes an add-on controls are its
  SavedVariables, which the client writes on `/reload` or logout.

So any WoW → Discord solution has two halves:

```
┌────────────────────────┐   local signal    ┌──────────────────────┐   HTTPS POST   ┌──────────────┐
│ In-game add-on (Lua)   │ ────────────────► │ PC companion app     │ ─────────────► │ Discord      │
│ listens for WoW events │  (file on disk)   │ watches + decodes    │   (webhook)    │ channel/phone│
└────────────────────────┘                   └──────────────────────┘                └──────────────┘
```

The companion makes a single outbound HTTPS request per notification to a
Discord webhook URL. It opens no inbound ports and needs no bot account.

Existing published add-ons already use this pattern, which shows it is
workable and tolerated:

| Add-on | Signal method | Delivery |
|---|---|---|
| [QueuePing](https://www.curseforge.com/wow/addons/queueping) | Add-on + desktop app | ntfy or Discord webhook |
| [Queue Ringer / BenTools](https://www.curseforge.com/wow/addons/bentools) | Add-on + Windows companion | Discord webhook, phone |
| [Summoning Stone](https://www.curseforge.com/wow/addons/summoning-stone) | Takes screenshots on events | Desktop app → ntfy |
| [Queue Pop Notifier](https://www.curseforge.com/wow/addons/queue-pop-notifier) | Flashes an 8-colour on-screen signal | Companion reads screen → Pushover |

## 3. What WoW Forever changes

- **It's an official Blizzard product, not a private server.** It has its own
  client, selected from the Battle.net version dropdown.
- **Dates:** the beta runs 17 Sep – 21 Oct 2026, capped at level 30. Launch is
  **4 Nov 2026**, and raids unlock 9 Dec.
- **Add-ons are supported**, on the **modern (Midnight 12.x) UI/API**, not the
  legacy Classic API. Midnight's "add-on disarmament" is active, including
  **secret values**:
  - Combat state such as unit health, and possibly unit names and some
    booleans, comes back as a *secret value*. Add-ons can display these but
    cannot compare them, branch on them or do maths with them.
  - In boss encounters and Mythic+, combat-log data is secret, and add-ons
    cannot parse chat or add-on comms channels.
  - Open-world combat is reportedly not restricted.

**Implications for this project**

| Feasible (expected) | Not feasible |
|---|---|
| Queue/LFG proposal shown | "Boss below 20%" or other combat-math alerts |
| Ready check / role check | Parsing raid chat during an encounter |
| Whisper received (outside encounters) | Anything that automates combat decisions |
| Player died / released / resurrected | |
| Level up, achievement earned | |
| AFK/disconnect-ish signals, logout | |
| Mail / auction sold (if events exposed) | |

The "expected" column is based on Midnight rules. It must be confirmed in the
Forever beta, because event payloads may be secret in places we don't expect.
The add-on will guard every value with `issecretvalue()`.

## 4. Signal-channel options (add-on → companion)

| # | Method | Realtime | Data capacity | ToS posture | Verdict |
|---|---|---|---|---|---|
| A | **Screenshot trigger + coded strip**: the add-on draws a small coloured block strip encoding the event, calls `Screenshot()`, then hides the strip. The companion watches `_retail_/Screenshots` (path TBC for Forever), decodes the strip from the file, and posts to Discord with optional image. | Yes (~1 s) | Small (event id + a few bytes), plus the image itself | Read-only use of files the game writes; no input injection | **Recommended** |
| B | SavedVariables file | No (only on `/reload` or logout) | Large (full Lua table) | Clean | **Use for session recap on logout** |
| C | `/chatlog` → `Logs/WoWChatLog.txt` tail | Unreliable (buffered, possibly until logout) | Medium | Clean | Rejected |
| D | Live screen-pixel reading | Yes | Small | Grey area; same technique bots use | Rejected for an official realm |
| E | Client DLL / memory hooks | Yes | Unlimited | **Bannable** | Rejected |

### Why option A

- `Screenshot()` is a normal, sanctioned client feature, and Summoning Stone
  depends on it.
- The companion never touches the game process, never reads screen memory,
  and never sends keystrokes.
- Screenshots must be **PNG/TGA, not JPEG** (`screenshotFormat` CVar), or
  compression will corrupt the colour strip. The add-on can check this CVar
  and warn the user.
- Bonus: the screenshot can be attached to the Discord message, for example
  showing the queue-pop dialog.

### Encoding sketch (option A)

- Strip of N solid squares (e.g. 8 × 24 px) in a fixed screen corner, rendered
  above all UI at full alpha for one frame.
- First and last squares are fixed sync colours (e.g. pure magenta) so the
  companion can find and validate the strip.
- Middle squares hold data using 8 well-separated colours (3 bits per square):
  event id, plus a short checksum.
- Screenshots that have no valid strip are your own manual shots. The
  companion can ignore them, or optionally forward them to a "#screenshots"
  channel.

## 5. Proposed deliverables

1. **`addon/ForeverNotify/`**: the WoW add-on.
   - TOC with the Forever interface number. TBC: run
     `/dump select(4, GetBuildInfo())` in the beta client.
   - Event list toggled by slash command (`/fnotify`) and saved per
     character.
   - `issecretvalue()` guards on all event payloads.
   - `/fnotify test` fires a sample notification.
   - Writes a session summary to SavedVariables for the logout recap.
2. **`companion/`**: PC companion in Python 3.
   - Watches the Screenshots folder for new files and decodes the strip.
   - Posts a Discord embed with character, realm, event, time and optional
     image.
   - Optionally reads SavedVariables after logout and posts a recap.
   - Config file holds the webhook URL, folder paths and which events attach
     images.
   - Unit-tested here against synthetic screenshots. Optionally packaged as a
     Windows `.exe` (PyInstaller).
3. **`README.md`**: install and setup guide, including creating a Discord
   webhook.

## 6. Security and privacy

- The Discord webhook URL is a secret. Anyone with it can post to your
  channel. It lives only in the companion's local config file, which is
  git-ignored, and never in the add-on or the repo.
- Traffic is outbound HTTPS to `discord.com` only. Nothing listens on the
  network.
- The companion respects Discord rate limits: it backs off on HTTP 429 and
  coalesces bursts.
- Screenshots may contain chat or other players' names. Image attachment is
  per-event opt-in.

## 7. Risks and unknowns

| Risk | Impact | Mitigation |
|---|---|---|
| `Screenshot()` restricted/protected in Forever | Option A fails | Test first in beta. Fallback: option B for recap only, or reconsider option D with your explicit OK |
| Event payloads unexpectedly secret | Fewer usable events | Guard with `issecretvalue()`; drop affected events |
| Forever screenshot folder/format differs | Companion misses files | Configurable path; add-on warns if format is JPEG |
| UI scale/resolution affects strip size | Decode errors | Add-on sizes the strip in physical pixels; companion searches for sync colours |
| Blizzard policy change | Add-on disallowed | Design never automates gameplay; easy to disable |
| I can't run WoW in the cloud session | In-game behaviour untested by me | You run a short beta test checklist; I fix from your feedback/logs |

## 8. Open questions for you

1. Which events matter most? (Suggested v1: queue pop, ready check, whisper,
   death, level-up, achievement.)
2. Companion runtime: a Python script, or a packaged Windows `.exe`?
3. Attach screenshots to notifications by default, or text-only?
4. Do you have Forever beta access, so we can validate before the 4 Nov
   launch?
5. One Discord channel for everything, or separate channels or webhooks per
   event type?

## 9. Suggested validation plan (before full build)

1. **Spike (≈1 evening of your time):** a minimal add-on that calls
   `Screenshot()` on `/fnotify test` and on `READY_CHECK`. Confirm a file
   appears and note the folder path, format and interface number.
2. If the spike passes, build the full add-on and companion with unit tests.
3. Beta test run against the checklist, then tag v0.1.

## Sources

- [Shacknews: WoW Forever release date and beta](https://shacknews.com/article/150712/world-of-warcraft-forever-classic-release-date-beta-sign-up)
- [PCGH: Forever launch 4 Nov, beta from 17 Sep](https://www.pcgameshardware.de/World-of-Warcraft-Spiel-42971/News/Forever-Classic-Plus-Release-Systemanforderungen-1553608/)
- [Icy Veins: Addons in WoW Forever, devs address the question](https://www.icy-veins.com/wow-forever/news/addons-in-wow-forever-blizzard-devs-just-addressed-the-big-question/)
- [wowforeverclassic.com: Addons, what works and what is blocked](https://wowforeverclassic.com/guides/addons)
- [wowforeverbuilds: What the Forever beta breaks for addons](https://wowforeverbuilds.com/news/what-the-wow-forever-beta-breaks-for-addons-secret-health-values-dead-secure-sni)
- [Icy Veins: Combat addon restrictions eased in Midnight](https://www.icy-veins.com/wow/news/combat-addon-restrictions-eased-in-midnight/)
- [warcraft.wiki.gg: /chatlog](https://warcraft.wiki.gg/wiki/MACRO_chatlog)
- [Blizzard UI Add-On Development Policy](https://us.forums.blizzard.com/en/wow/t/ui-add-on-development-policy/24534)
- Prior-art add-ons are linked in section 2.

> Caveat: several sources are community sites summarising a beta that is
> still in progress. The cloud environment blocked direct fetches of most
> pages, so some details come from search summaries. Treat the API details as
> "to be confirmed in the beta spike" (section 9).
