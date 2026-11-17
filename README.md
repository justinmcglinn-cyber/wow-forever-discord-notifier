# ForeverNotify

**World of Warcraft: Forever → Discord.** An add-on plus a small Windows app that posts your deaths, level-ups, PvP fights and kills, and a gold summary when you log out, to your guild's Discord channels as text, as they happen.

It's built for guilds where everyone runs it: each player's events land in the shared channels, test messages tidy themselves away, and the app updates itself.

**[Download ForeverNotify.exe](https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases/latest/download/ForeverNotify.exe)** · [All releases](https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases)

## Quick start (joining a guild that already uses it)

Have your guild's **team code** ready: it's in the pinned message of your guild's members-only Discord channel.

1. Download **[ForeverNotify.exe](https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases/latest/download/ForeverNotify.exe)** (direct link: https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases/latest/download/ForeverNotify.exe).
2. Run it. If Windows SmartScreen says it protected your PC (the app isn't code-signed), click **More info**, then **Run anyway**.
3. When it asks, paste the team code (copy it with the copy button on the code block in Discord; right-click pastes into the window). There's nothing else to answer.

It then does the rest by itself: installs itself in `%LOCALAPPDATA%\ForeverNotify` (with a Start menu shortcut; you can delete the downloaded file), finds your WoW Forever folder, installs the add-on, posts a test message to each channel (they delete themselves after about a minute) and turns on **start with Windows**. It finishes with a short summary (`All set:` with the channels, WoW folder, add-on, start with Windows and test messages), minimises its window and keeps watching. If WoW Forever was already running, it tells you to type `/reload` in game.

To change anything later, press **Space** in the ForeverNotify window, then **C** (Discord channels, e.g. a new team code), **W** (WoW Forever folder) or **A** (start with Windows on/off). If it can't find your WoW folder by itself, it asks.

Already running ForeverNotify? Don't download it again: it updates itself, and nothing changes for you. Using your own Discord channels instead? See [Your own channels](#your-own-channels).


## What it posts

- 💀 **Death**: where you died, and who killed you (player or NPC) when known
- ⬆️ **Level up**: new level, location, time played at the previous level (as in `/played`, so offline time doesn't count)
- ⚔️ **PvP attack**: your location (zone, subzone, coordinates, zone type), attacker name, level, race, class and guild, your health, and the number of hostile players nearby
- 🗡️ **PvP kill**: each enemy-faction player *you* killed (in a group: your target when they died), with their level, class, race and guild when they were your target or had a nameplate, honor earned, your kill streak since your last death, and DOUBLE / TRIPLE / MULTI-KILL and KILLING SPREE → LEGENDARY callouts. Solo, every honorable kill is yours
- ⚔️ **Battle report**: one post per group fight (after 30 s out of combat) with your kills, the group's kills, honor, fight length and the enemies seen dying, instead of a post for every kill your group got
- 💰 **Logout gold summary**: session length, net gold change and gold/hour, income and spending by source (loot, quests, vendor, AH, mail…), deaths, levels gained, and total gold across all your characters


## Your own channels

Not joining a guild with a team code? At the first question press **Enter** for the other options: one Discord channel for everything, or a separate channel per kind of message (deaths, level-ups, PvP alerts, PvP kills, gold summary).

For each channel: in Discord, **Server Settings → Integrations → Webhooks → New Webhook**, pick the channel, then **Copy Webhook URL**, and paste it when ForeverNotify asks. Keep these URLs private: anyone with one can post to that channel.

## Changing settings later

Press **Space** in the ForeverNotify window to open the shortcuts, then:

- **C**: choose the Discord channels again (a new team code, or your own webhooks). New channels get a test message each.
- **W**: choose the WoW Forever folder again (the add-on is installed there).
- **A**: start with Windows on or off.

Watching pauses for the question and carries on afterwards. The shortcuts are also open for 15 seconds when ForeverNotify starts; they close by themselves (or press **Esc**), so a stray key press does nothing.

More options (turning a kind of message off, an @mention on PvP alerts so your phone pings, separate channels for PvP kills or the PvP flag) are in `config.toml` in `%LOCALAPPDATA%\ForeverNotify`: open it in Notepad and restart ForeverNotify afterwards. Its `[webhooks]` section names each channel:

| Name | Messages |
|---|---|
| `default` | Any channel left empty below. Set only this for one channel for everything. |
| `deaths` | 💀 Deaths, with the killer when known |
| `level_ups` | ⬆️ Level-ups |
| `pvp_alerts` | ⚔️ "Under attack" alerts |
| `pvp_kills` | 🗡️ Your PvP kills and group battle reports |
| `gold_summary` | 💰 Gold summary after logout |
| `pvp_flag` | PvP flag on/off (only with `/fnotify flag` in game); empty = `pvp_alerts` |

`[notify]` uses the same names (plus `test_messages`) to turn each kind off.

## Start with Windows and updates

ForeverNotify starts minimised when you sign in to Windows (for your user only; no admin rights) and waits quietly until WoW Forever is running. After you log out of the game it still posts the gold summary. Turn it off with **Space → A**, or in Windows' Settings → Apps → Startup. If the window doesn't stay minimised (some Windows Terminal setups), minimise it yourself; it's harmless.

It keeps itself up to date: at start-up, and every 6 hours while WoW is closed, it checks this page for a newer release, checks the download against the SHA-256 published with the release, swaps it in and restarts. If anything goes wrong the current version keeps running. `check_for_updates = false` in `config.toml` turns this off.

Windows SmartScreen may warn that the app is unrecognised, because it isn't code-signed: click **More info → Run anyway**. Each release lists the SHA-256 of the exe; in PowerShell, `Get-FileHash .\ForeverNotify.exe` should print the same.

## Check it works

In game, type `/fnotify test`. Within a few seconds each channel should get a sample message marked 🧪 TEST, each in the channel it's set up for. Test messages delete themselves after about a minute.

## In-game commands

| Command | Effect |
|---|---|
| `/fnotify` | Show status and which notifications are on |
| `/fnotify test` | Send a sample of every notification, each to its channel |
| `/fnotify death` / `level` / `pvp` / `kill` / `summary` / `flag` | Toggle that notification (`flag` = PvP flag on/off, off by default) |
| `/fnotify combatlog` | Turn combat-log reading on/off (off by default on Forever, which forbids it) |
| `/fnotify preview` | Show the signal grid for 5 seconds without taking a screenshot |
| `/fnotify debug` | Toggle debug output in chat |

## Keeping the team code inside the guild

For guild officers. The team code lets anyone who has it post into your guild's ForeverNotify channels (only post: a webhook can't read messages or reach other channels). ForeverNotify itself can't check who uses a code, so keep it inside the guild with Discord's permissions:

- Post it only in a channel locked to a guild role (a members-only channel), e.g. as a pinned message.
- When someone leaves on bad terms, or the code leaks: delete the webhooks in Discord (**Server Settings → Integrations → Webhooks**), which stops the old code at once; then whoever looks after ForeverNotify for the guild makes new ones and a new code, and posts it in the locked channel.
- Everyone's ForeverNotify then says Discord no longer has that channel and flashes its taskbar button; they get the new code from the locked channel and paste it with **Space** then **C**.


## How it works

WoW add-ons can't access the internet, so this has two parts:

1. **The add-on**: when an event happens, the add-on draws a tiny coded colour grid in the top-left corner for a single frame and takes a screenshot.
2. **ForeverNotify.exe**: a small app on your PC. It watches the Screenshots folder, decodes the grid, posts a text message to your Discord webhook and deletes the signal screenshot. The gold summary is read from the add-on's saved data, which the game writes when you log out.

If ForeverNotify wasn't running when a signal was taken, it cleans up at its next start: deaths and level-ups from the last 10 minutes are still posted (marked "sent late"), and older signal screenshots are deleted unposted. Each of your own screenshots is read once and remembered in `screenshot_cache.json`, so later start-ups skip it.

The grid is drawn in physical screen pixels, so resolution, UI scale and window size don't matter: it decodes from 720p to 4K and ultrawide, and in windowed mode.

ForeverNotify only reads files the game writes. It never touches the game process and never sends keystrokes. Your own screenshots are never changed or uploaded.


## Limits

- **Forever uses Midnight's add-on restrictions ("secret values").** The add-on checks every value before using it, so restricted values are skipped rather than causing errors. During boss encounters and Mythic+, some details (e.g. health) may be missing.
- **No combat log on Forever.** The client forbids add-ons from reading the combat log (trying shows a "blocked from an action only available to the Blizzard UI" popup), so the add-on leaves it off on clients with secret values. Attackers and killers are found from your target, focus, mouseover and nameplates instead: an enemy (player or NPC) has to be visible there and targeting you. For PvP alerts the player must also be able to attack you right now (so unflagged enemies in sanctuaries or neutral towns don't count), and players of your own faction are ignored (duels never alert). Keep enemy nameplates on for the best results. A stealthed attacker you never see shows up only once visible, and a death may say "Cause unknown" if the killer was never visible.
- **Blocked calls are reported.** If the game ever blocks the add-on, a red chat line names the function and `/fnotify` lists recent ones.
- **Kills come from the honorable-kill counter.** On Forever the combat log is blocked and the honor message doesn't name the victim ("You have been awarded 3 Honor."), so a kill is matched to an enemy player seen dying (your target or a nameplate). "Your kill" means they were your target when they died or in the 10 seconds before; killing blows can't be seen. In a group, kills you weren't targeting only appear in the battle report.
- **Time played per level comes from the server's `/played` count.** The add-on asks for it at login and /reload (the "Total time played" lines this would print in chat are hidden; a `/played` you type still shows). If the server doesn't answer, the add-on's own count is used, but only for a level it saw from the start, so the first level-up after installing it, or after levelling without it, may have no time.
- **The gold summary is posted about 30 seconds after logout.** The delay lets ForeverNotify tell a real logout from a `/reload`. If the game crashes, the session isn't saved and no summary is sent. If ForeverNotify wasn't running when you logged out, it posts that summary the next time it starts while WoW is closed (it remembers what it has posted in `state.json`, so nothing is sent twice).


## Troubleshooting

1. **Nothing in Discord?** Type `/fnotify test` in game. A sample should reach every channel within a few seconds, and the ForeverNotify window should log it. If the window shows nothing, check the add-on is enabled at character select and that ForeverNotify points at the right WoW Forever folder (press **Space** then **W** in the ForeverNotify window to choose it again).
2. **Something missing or odd?** Type `/fnotify` and check no "Blocked by the game" lines are listed.
3. **Reporting a problem:** turn on `/fnotify debug`, run ForeverNotify with `ForeverNotify.exe -v run`, reproduce it, and share what the window printed.
