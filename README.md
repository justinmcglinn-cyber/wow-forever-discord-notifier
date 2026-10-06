# wow-forever-discord-notifier

Sends World of Warcraft: Forever events to a Discord channel as text messages:

- 💀 **Death**: where you died, and who killed you (player or NPC) when known
- ⬆️ **Level up**: new level, location, time spent on the previous level
- ⚔️ **PvP attack**: your location (zone, subzone, coordinates, zone type), attacker name, level, race, class and guild, your health, and the number of hostile players nearby
- 💰 **Logout gold summary**: session length, net gold change and gold/hour, income and spending by source (loot, quests, vendor, AH, mail…), deaths, levels gained, and total gold across all your characters

## How it works

WoW add-ons can't access the internet, so this has two parts:

1. **`addon/ForeverNotify`**: when an event happens, the add-on draws a tiny coded colour grid in the top-left corner for a single frame and takes a screenshot.
2. **`companion/`**: a small Python app on your PC. It watches the Screenshots folder, decodes the grid, posts a text message to your Discord webhook and deletes the signal screenshot. The gold summary is read from the add-on's saved data, which the game writes when you log out.

The companion only reads files the game writes. It never touches the game process and never sends keystrokes. Your own screenshots are never changed or uploaded.

## Setup

### 1. Discord webhook
In your Discord server, go to **Server Settings → Integrations → Webhooks → New Webhook**, pick the channel, then click **Copy Webhook URL**. Keep this URL private, because anyone with it can post to the channel.

### 2. Add-on
Copy `addon/ForeverNotify` into `<WoW Forever folder>\Interface\AddOns\`. If the character screen says it's out of date, tick **Load out of date AddOns**.

The add-on switches the screenshot format to PNG on login, because JPEG compression can corrupt the signal grid.

### 3. Companion (Windows)
1. Install Python 3.11+ from python.org (tick "Add to PATH").
2. In `companion\`, run `py -m pip install -r requirements.txt`.
3. Copy `config.example.toml` to `config.toml`. Paste your webhook URL and set `wow_dir` to your Forever install folder (the one containing `Screenshots` and `WTF`).
4. Run `py -m forever_notify test-webhook`. A test message should appear in Discord.
5. Start the companion with `run.bat`, or `py -m forever_notify run`, and leave it running while you play.

### 4. Check it end to end
In game, type `/fnotify test`. Within about a second you should get a ✅ message in Discord.

## In-game commands

| Command | Effect |
|---|---|
| `/fnotify` | Show status and which notifications are on |
| `/fnotify test` | Send a test notification |
| `/fnotify death` / `level` / `pvp` / `summary` / `flag` | Toggle that notification (`flag` = PvP flag on/off, off by default) |
| `/fnotify preview` | Show the signal grid for 5 seconds without taking a screenshot |
| `/fnotify debug` | Toggle debug output in chat |

Companion options live in `config.toml`: per-event on/off, separate webhooks per event (e.g. a `#pvp` channel), and a Discord @mention on PvP alerts so your phone pings.

## Limits

- **Forever uses Midnight's add-on restrictions ("secret values").** The add-on checks every value before using it, so restricted values are skipped rather than causing errors. During boss encounters and Mythic+, some details (e.g. health) may be missing.
- **PvP detection** needs the attacker to have a visible nameplate or be your target, or the game must let add-ons read the combat log outside encounters. A stealthed attacker you never see may only show up as "under attack" once they're visible, or as the killer if the combat log is available.
- **The gold summary is posted about 30 seconds after logout.** The delay lets the companion tell a real logout from a `/reload`. If the game crashes, the session isn't saved and no summary is sent.

## First beta session checklist

None of this has been run in the real client yet. On first use:

1. Run `/fnotify test` and confirm a Discord message arrives and the signal screenshot is deleted.
2. Run `/fnotify` and note whether "Combat log PvP detection" is on.
3. Die once, level once and log out once, and check each message.
4. If anything fails, turn on `/fnotify debug`, run the companion with `py -m forever_notify -v run`, and share the output.

## Development

```
lua5.1 tests/lua/run_scenario.lua addon/ForeverNotify /tmp/out   # add-on under a stubbed WoW API
cd companion && python -m unittest discover -s tests -t .           # decoder, formatting, watcher, end-to-end
```
