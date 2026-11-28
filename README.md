# ForeverNotify

**World of Warcraft: Forever → Discord.** An add-on plus a small Windows app that posts your deaths, level-ups, PvP fights and kills, and a gold summary when you log out, to your guild's Discord channels as text, as they happen.

It's built for guilds where everyone runs it: each player's events land in the shared channels, setting up posts nothing to them, and the app updates itself.

**[Download ForeverNotify.exe](https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases/latest/download/ForeverNotify.exe)** · [All releases](https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases)

## Quick start (joining a guild that already uses it)

Have your guild's **team code** ready: it's in the pinned message of your guild's members-only Discord channel.

1. Download **[ForeverNotify.exe](https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases/latest/download/ForeverNotify.exe)** (direct link: https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier/releases/latest/download/ForeverNotify.exe).
2. Run it. If Windows SmartScreen says it protected your PC (the app isn't code-signed), click **More info**, then **Run anyway**.
3. When it asks, paste the team code (copy it with the copy button on the code block in Discord; right-click pastes into the window). There's nothing else to answer.

It then does the rest by itself: installs itself in `%LOCALAPPDATA%\ForeverNotify` (with a Start menu shortcut; you can delete the downloaded file), finds your WoW Forever folder, installs the add-on, checks with Discord that every channel works (quietly: nothing is posted, and it only says something if a channel doesn't work) and turns on **start with Windows**. It finishes with a short summary (`All set:` with the channels, WoW folder, add-on and start with Windows), minimises its window and keeps watching. If WoW Forever was already running, it tells you to type `/reload` in game.

To change anything later, press **Space** in the ForeverNotify window, then **C** (Discord channels, e.g. a new team code), **W** (WoW Forever folder) or **A** (start with Windows on/off). If it can't find your WoW folder by itself, it asks.

Already running ForeverNotify? Don't download it again: it updates itself, and nothing changes for you. Using your own Discord channels instead? See [Your own channels](#your-own-channels).


## What it posts

- 💀 **Death**: where you died, and who killed you (player or NPC) when known. Not posted inside raids and dungeons (the group leader's raid or dungeon post shows the wipes instead), battlegrounds or arenas
- ⬆️ **Level up**: new level, location, time played at the previous level (as in `/played`, so offline time doesn't count)
- ⚔️ **PvP attack**: your location (zone, subzone, coordinates, zone type), attacker name, level, race, class and guild, your health, and the number of hostile players nearby. World PvP only: not in battlegrounds or arenas
- 🗡️ **PvP kill**: each enemy-faction player *you* killed (in a group: your target when they died), with their level, class, race and guild when they were your target or had a nameplate, honor earned, your kill streak since your last death, and DOUBLE / TRIPLE / MULTI-KILL and KILLING SPREE → LEGENDARY callouts. Solo, every honorable kill is yours
- ⚔️ **Battle report**: one post per group fight (after 30 s out of combat) with your kills, the group's kills, honor, fight length and the enemies seen dying, instead of a post for every kill your group got. Posted by the group leader's ForeverNotify only, so a fight gets one report however many of you run it
- 💰 **Logout gold summary**: session length, net gold change and gold/hour, income and spending by source (loot, quests, vendor, AH, mail…), deaths, levels gained, and total gold across all your characters


## Your own channels

Not joining a guild with a team code? At the first question press **Enter** for the other options: one Discord channel for everything, or a separate channel per kind of message (deaths, level-ups, PvP alerts, PvP kills, gold summary).

For each channel: in Discord, **Server Settings → Integrations → Webhooks → New Webhook**, pick the channel, then **Copy Webhook URL**, and paste it when ForeverNotify asks. Keep these URLs private: anyone with one can post to that channel.

## Changing settings later

Press **Space** in the ForeverNotify window to open the shortcuts, then:

- **C**: choose the Discord channels again (a new team code, or your own webhooks). The new channels are checked quietly; only a channel that doesn't work is reported.
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
| `raid_nights` | 🏰 Raid-night feed (raid leaders; a Discord forum channel). Never uses `default` |
| `dungeons` | Dungeon runs (a plain text channel). Never uses `default` |

`[notify]` uses the same names (plus `test_messages`) to turn each kind off.

## Start with Windows and updates

ForeverNotify starts minimised when you sign in to Windows (for your user only; no admin rights) and waits quietly until WoW Forever is running. After you log out of the game it still posts the gold summary. Turn it off with **Space → A**, or in Windows' Settings → Apps → Startup. If the window doesn't stay minimised (some Windows Terminal setups), minimise it yourself; it's harmless.

It keeps itself up to date: at start-up, and every 6 hours while WoW is closed, it checks this page for a newer release, checks the download against the SHA-256 published with the release, swaps it in and restarts. If anything goes wrong the current version keeps running. `check_for_updates = false` in `config.toml` turns this off.

Windows SmartScreen may warn that the app is unrecognised, because it isn't code-signed: click **More info → Run anyway**. Each release lists the SHA-256 of the exe; in PowerShell, `Get-FileHash .\ForeverNotify.exe` should print the same.

## Check it works

In game, type `/fnotify test`. Within a few seconds the ForeverNotify window shows the test arriving (`Signal TEST`) and checks every channel with Discord, the raid-night and dungeon channels included. Nothing is posted to Discord: the window only says something if a channel doesn't work.

## In-game commands

| Command | Effect |
|---|---|
| `/fnotify` | Show status and which notifications are on |
| `/fnotify test` | Check the whole path from the game to the ForeverNotify window, and every Discord channel (posts nothing) |
| `/fnotify death` / `level` / `pvp` / `kill` / `summary` / `flag` | Toggle that notification (`flag` = PvP flag on/off, off by default) |
| `/fnotify raid` / `photos` / `dungeons` | Toggle the raid-night feed (on), the boss-kill photo question (on) or dungeon runs (on); see [Raid nights](#raid-nights) |
| `/fnotify photo` | Take the boss-kill group photo now |
| `/fnotify end` | End the dungeon run (group photo, then posted) or raid night now, and remember the last boss you killed as that instance's final boss (leader) |
| `/fnotify record` | Start recording this raid night or dungeon run after saying "Not this time" (raid or party leader) |
| `/fnotify probe` | Check what the game allows for the raid-night feed and save the report |
| `/fnotify combatlog` | Turn combat-log reading on/off (off by default on Forever, which forbids it) |
| `/fnotify preview` | Show the signal grid for 5 seconds without taking a screenshot |
| `/fnotify debug` | Toggle debug output in chat |

## Raid nights

For raid leaders (and dungeon leaders). Get the guild's raid team code from the members-only channel and paste it with **Space** then **C**; it adds the `raid_nights` channel (a Discord forum) and, if the guild uses one, the `dungeons` channel. Nobody else in the raid needs to do anything: only the raid leader's ForeverNotify posts, and if the leader doesn't run it there's no feed that night. Nothing pings anyone.

**Recording is the leader's choice**: when you start leading a raid (or a dungeon party) inside the instance, a popup asks "post this raid night to your guild's Discord?". **Record** posts it; **Not this time** posts nothing for that raid or run. Changed your mind? Type `/fnotify record` to start recording after all. A `/reload` keeps your answer, and a raid night that moves on to another raid carries on without asking again.

Using your own channels instead of a team code? Close ForeverNotify and, in a Command Prompt, run `%LOCALAPPDATA%\ForeverNotify\ForeverNotify.exe set-webhook raid_nights` (paste the forum channel's webhook when asked; it also starts the **Guild records** post) and `... set-webhook dungeons` for a dungeons text channel. Then start ForeverNotify again.

**What gets posted**: one forum post per night, named after the raid and the date (e.g. "Molten Core – Thu 11 Dec"), started at the first boss pull. In it, as they happen:

- **Boss kills**: fight time, the attempt number that night, "first guild kill" when the boss isn't in the guild records yet, and a group photo
- **Wipes**: how far into the fight, and the boss's health when the game allows it
- **Loot** of epic quality or better: the item, who won it and the Need rolls, highest first

**The group photo** is optional: after each boss kill the raid leader is asked "Take a group photo?". **Skip** (or no answer within a minute) takes none. **Count down** starts a 10-second countdown, "Group photo in 10 – face the boss", so the raid can turn to the boss; click **Take now** (or type `/fnotify photo`) to take it straight away. The photo is taken with the whole UI hidden for a moment and uploaded to the night's post. In combat it waits up to 10 seconds more for combat to end. `/fnotify photos` turns the photo question off altogether (and on again).

**End of the night**: when the raid's final boss dies, the leader is asked "Raid complete – post the night's summary?". **Post summary** ends the night; **Not yet** carries on (you're asked again at the next final-boss kill). The night also ends after 10 minutes out of the group, or at logout. The summary is put at the top of the post: the full loot list with rolls, and each boss's kill time, marked when it sets or beats the guild record. The shared **Guild records** post in the forum keeps the best time for each boss across all raid leaders.

**Dungeon runs** (on by default; type `/fnotify dungeons` to turn them off): posted when you lead the party, say **Record** when asked, and your guild has a `dungeons` channel. Each run is one message when the last boss dies or you leave: run time, bosses with their kill times and wipes (the final boss crowned), every rare or better item anyone got and who got it (with the Need rolls for epic items; green items are counted), the party, and a group photo of the final boss. ForeverNotify knows how every Forever dungeon ends: its final boss, each wing's final boss, or, for Ragefire Chasm and the Stockade, all of their bosses (except Blackmaw Hold, not yet published; you're told in game when the last boss isn't known). Where it doesn't, or gets it wrong, type `/fnotify end` after the last boss: the group photo countdown starts, the run is posted, and that boss is remembered so the next run there finishes by itself.

**Before the first raid**: type `/fnotify probe` in a dungeon or raid (best after a boss fight with a loot roll) and share what it prints with your officers. It checks what the Forever client allows: encounter events, boss health, loot-roll chat lines, which boss is last, and hiding the UI for the photo.

`/fnotify raid` turns the whole feed off for you (and on again).

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

ForeverNotify only reads files the game writes. It never touches the game process and never sends keystrokes. Your own screenshots are never changed or uploaded (the only picture it uploads is the raid or dungeon group photo, taken by the add-on when the leader chooses **Count down**).


## Privacy: what it sends and what it keeps

**What goes to Discord**, and only to the channels your guild set up (through the team code or your own webhooks):

- Your character's name, level and where you are (zone, area, coordinates) with each death, level-up and PvP alert.
- Who attacked or killed you, and the enemy players you killed (name, level, class, race, guild), as the game showed them.
- Time played per level, and after logout your gold for the session (earned and spent by source) and across your characters.
- If you lead a raid or dungeon run and choose to record it: the bosses, fight times and wipes, the loot and who won it (Need rolls for epic items), the party's names, classes and levels, and the group photo.

**Nothing else is sent anywhere.** There's no account, no analytics and nothing sent to the developer. Besides your guild's Discord webhooks, ForeverNotify only contacts GitHub, to check for and download updates.

**What stays on your PC**, in `%LOCALAPPDATA%\ForeverNotify`: `config.toml` (your settings and the guild's webhook addresses) and small state files so nothing is posted twice. The add-on keeps its own saved data in your WoW folder like any add-on. Signal screenshots are deleted as soon as they're read, and a group photo is deleted once Discord has it.

**Keep the team code and webhook addresses private.** Anyone who has them can post into your guild's channels, so never paste them in public places (including GitHub). If one leaks, see [Keeping the team code inside the guild](#keeping-the-team-code-inside-the-guild).


## Limits

- **Forever uses Midnight's add-on restrictions ("secret values").** The add-on checks every value before using it, so restricted values are skipped rather than causing errors. During boss encounters and Mythic+, some details (e.g. health) may be missing.
- **No combat log on Forever.** The client forbids add-ons from reading the combat log (trying shows a "blocked from an action only available to the Blizzard UI" popup), so the add-on leaves it off on clients with secret values. Attackers and killers are found from your target, focus, mouseover and nameplates instead: an enemy (player or NPC) has to be visible there and targeting you. For PvP alerts the player must also be able to attack you right now (so unflagged enemies in sanctuaries or neutral towns don't count), and players of your own faction are ignored (duels never alert). Keep enemy nameplates on for the best results. A stealthed attacker you never see shows up only once visible, and a death may say "Cause unknown" if the killer was never visible.
- **Blocked calls are reported.** If the game ever blocks the add-on, a red chat line names the function and `/fnotify` lists recent ones.
- **Kills come from the honorable-kill counter.** On Forever the combat log is blocked and the honor message doesn't name the victim ("You have been awarded 3 Honor."), so a kill is matched to an enemy player seen dying (your target or a nameplate). "Your kill" means they were your target when they died or in the 10 seconds before; killing blows can't be seen. In a group, kills you weren't targeting only appear in the battle report.
- **Time played per level comes from the server's `/played` count.** The add-on asks for it at login and /reload (the "Total time played" lines this would print in chat are hidden; a `/played` you type still shows). If the server doesn't answer, the add-on's own count is used, but only for a level it saw from the start, so the first level-up after installing it, or after levelling without it, may have no time.
- **The gold summary is posted about 30 seconds after logout.** The delay lets ForeverNotify tell a real logout from a `/reload`. If the game crashes, the session isn't saved and no summary is sent. If ForeverNotify wasn't running when you logged out, it posts that summary the next time it starts while WoW is closed (it remembers what it has posted in `state.json`, so nothing is sent twice).


## Troubleshooting

1. **Nothing in Discord?** Type `/fnotify test` in game. Within a few seconds the ForeverNotify window should log `Signal TEST`, plus a line for any channel that doesn't work. If the window shows nothing, check the add-on is enabled at character select and that ForeverNotify points at the right WoW Forever folder (press **Space** then **W** in the ForeverNotify window to choose it again).
2. **Something missing or odd?** Type `/fnotify` and check no "Blocked by the game" lines are listed.
3. **Reporting a problem:** turn on `/fnotify debug`, run ForeverNotify with `ForeverNotify.exe -v run`, reproduce it, and share what the window printed.
