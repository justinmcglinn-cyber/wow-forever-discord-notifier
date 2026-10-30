# wow-forever-discord-notifier

Sends World of Warcraft: Forever events to a Discord channel as text messages:

- 💀 **Death**: where you died, and who killed you (player or NPC) when known
- ⬆️ **Level up**: new level, location, time played at the previous level (as in `/played`, so offline time doesn't count)
- ⚔️ **PvP attack**: your location (zone, subzone, coordinates, zone type), attacker name, level, race, class and guild, your health, and the number of hostile players nearby
- 🗡️ **PvP kill**: each enemy-faction player *you* killed (in a group: your target when they died), with their level, class, race and guild when they were your target or had a nameplate, honor earned, your kill streak since your last death, and DOUBLE / TRIPLE / MULTI-KILL and KILLING SPREE → LEGENDARY callouts. Solo, every honorable kill is yours
- ⚔️ **Battle report**: one post per group fight (after 30 s out of combat) with your kills, the group's kills, honor, fight length and the enemies seen dying, instead of a post for every kill your group got
- 💰 **Logout gold summary**: session length, net gold change and gold/hour, income and spending by source (loot, quests, vendor, AH, mail…), deaths, levels gained, and total gold across all your characters

## How it works

WoW add-ons can't access the internet, so this has two parts:

1. **`addon/ForeverNotify`**: when an event happens, the add-on draws a tiny coded colour grid in the top-left corner for a single frame and takes a screenshot.
2. **`companion/`**: a small Python app on your PC. It watches the Screenshots folder, decodes the grid, posts a text message to your Discord webhook and deletes the signal screenshot. The gold summary is read from the add-on's saved data, which the game writes when you log out.

If the companion wasn't running when a signal was taken, it cleans up at its next start: deaths and level-ups from the last 10 minutes are still posted (marked "sent late"), and older signal screenshots are deleted unposted. Each of your own screenshots is read once and remembered in `screenshot_cache.json`, so later start-ups skip it.

The grid is drawn in physical screen pixels, so resolution, UI scale and window size don't matter: it decodes from 720p to 4K and ultrawide, and in windowed mode.

The companion only reads files the game writes. It never touches the game process and never sends keystrokes. Your own screenshots are never changed or uploaded.

## Setup

### 1. Discord webhook
**Joining a guild that already uses ForeverNotify?** Skip this: ask for the guild's **team code** and paste it when setup asks.

In your Discord server, go to **Server Settings → Integrations → Webhooks → New Webhook**, pick the channel, then click **Copy Webhook URL**. Keep this URL private, because anyone with it can post to the channel.

Want each notification type in its own channel (e.g. `#deaths`, `#levelup`, `#pvp-alerts`, `#gold`)? Create one webhook per channel; setup asks for each.

### 2. Add-on
`ForeverNotify.exe` installs the add-on for you during setup (step 3), and checks it every time it starts: a missing or older add-on is installed/updated automatically, an identical one is left alone, and a newer one (by the `.toc` version) is never downgraded. `ForeverNotify.exe install-addon` force-reinstalls the exe's copy. To do it by hand instead, copy `addon/ForeverNotify` into `<WoW Forever folder>\Interface\AddOns\`.

If the character screen says the add-on is out of date, tick **Load out of date AddOns**.

The add-on switches the screenshot format to PNG on login, because JPEG compression can corrupt the signal grid.

### 3. Companion (Windows)
1. Download `ForeverNotify.exe` from the latest [release](../../releases) (or from the **build-exe** artifact of a recent Actions run), or build it yourself (see below).
2. Put it in its own folder, e.g. `Documents\ForeverNotify`, and double-click it.
3. The first time, it asks for your guild's team code, or, for your own channels, whether you want one Discord channel for everything or a separate channel per notification type (deaths, level ups, PvP alerts, gold summary) and the webhook URL(s). Then it asks for your WoW Forever folder (it offers any it finds). It saves `config.toml` next to the exe and posts a test message to each channel, saying which notifications will land there. Run `ForeverNotify.exe setup` to go through this again later. To change just one channel's webhook, run `ForeverNotify.exe set-webhook <channel>` (`deaths`, `level_ups`, `pvp_alerts`, `pvp_kills` or `gold_summary`): it asks for the URL, updates only that line in `config.toml` and posts a sample to that channel.
4. Leave the window open while you play. Close it to stop.

**Sharing with your team (team code):** the exe and this repo hold no webhooks, so everyone downloads the same public release. Set up your own `config.toml` with the team's channels, then run `py -3 make_team_hooks.py` in `companion\` (it reads `dist\config.toml`, or a path you give). It prints a team code (one line starting `FNTEAM1-`) and saves it to `dist\team_code.txt`. Post it somewhere only your team can see, e.g. a pinned message in a private channel. Teammates paste it at setup; it fills in every channel's webhook. The code is encrypted only against casual reading and secret scanners: anyone with it can post to your channels. If it leaks, delete and recreate the webhooks in Discord, make a new code and have everyone run `ForeverNotify.exe setup` again. A config from an older exe with the webhooks built in asks for the code on start-up and keeps its other settings.

**Updates:** at start-up the exe checks GitHub for a newer release. If there is one it asks `Update now? [Y]es / [n]o / [s]kip this version` (and carries on without updating after 30 seconds). On yes it downloads the new exe, checks it against the SHA-256 GitHub publishes, swaps it in and restarts; the add-on is updated by the new exe as usual. Nothing is installed without asking, and if anything goes wrong the current version keeps running. `ForeverNotify.exe update` checks on demand (including a skipped version); `check_for_updates = false` in `config.toml` turns the start-up check off.

**Checking a download:** each release is built by GitHub Actions from the tagged commit, and its notes list the SHA-256 of the exe and the zip with a link to the build log. In PowerShell, `Get-FileHash .\ForeverNotify.exe` should print the same hash. With the [GitHub CLI](https://cli.github.com), `gh attestation verify ForeverNotify.exe -R justinmcglinn-cyber/wow-forever-discord-notifier` also confirms the exe was built by this repo's workflow.

**Personal build with your settings built in:** copy your `config.toml` to `companion\baked_config.toml` (git-ignored) and run `build_exe.bat`. That exe restores those settings whenever it starts without a `config.toml`, so it works in any folder or on another PC with no setup. Your webhooks are inside that exe, so don't share it.

Windows SmartScreen may warn that the app is unrecognised, because it isn't code-signed. Click **More info → Run anyway**.

Extra options (per-event channels, @mentions…) live in `config.toml`; open it in Notepad and restart the exe after editing. The exe also accepts the same commands as the Python version, e.g. `ForeverNotify.exe test-webhook` or `ForeverNotify.exe -v run`.

<details>
<summary>Run from source instead</summary>

1. Install Python 3.11+ from python.org (tick "Add to PATH").
2. In `companion\`, run `py -m pip install -r requirements.txt`.
3. Copy `config.example.toml` to `config.toml`. Paste your webhook URL(s) under `[webhooks]` and set `wow_dir` to your Forever install folder (the one containing `Screenshots` and `WTF`).
4. Run `py -m forever_notify test-webhook`. A sample of each notification should appear in Discord.
5. Start the companion with `run.bat`, or `py -m forever_notify run`, and leave it running while you play.
</details>

### 4. Check it end to end
In game, type `/fnotify test`. Within a few seconds each channel should get a sample message marked 🧪 TEST: a death, a level-up, a PvP alert and a gold summary, each in the channel it's configured for. `ForeverNotify.exe test-webhook` sends the same samples without the game. Test messages delete themselves after about a minute, so they don't clutter the channels (if the companion is closed first, it removes them the next time it runs).

## In-game commands

| Command | Effect |
|---|---|
| `/fnotify` | Show status and which notifications are on |
| `/fnotify test` | Send a sample of every notification, each to its channel |
| `/fnotify death` / `level` / `pvp` / `kill` / `summary` / `flag` | Toggle that notification (`flag` = PvP flag on/off, off by default) |
| `/fnotify combatlog` | Turn combat-log reading on/off (off by default on Forever, which forbids it) |
| `/fnotify preview` | Show the signal grid for 5 seconds without taking a screenshot |
| `/fnotify debug` | Toggle debug output in chat |

Companion options live in `config.toml`: per-event on/off, separate webhooks per event (e.g. a `#pvp` channel), and a Discord @mention on PvP alerts so your phone pings. Its `[webhooks]` section names each channel:

| Name | Messages |
|---|---|
| `default` | Any channel left empty below. Set only this for one channel for everything. |
| `deaths` | 💀 Deaths, with the killer when known |
| `level_ups` | ⬆️ Level-ups |
| `pvp_alerts` | ⚔️ "Under attack" alerts |
| `pvp_kills` | 🗡️ Your PvP kills and group battle reports |
| `gold_summary` | 💰 Gold summary after logout |
| `pvp_flag` | PvP flag on/off (only with `/fnotify flag` in game); empty = `pvp_alerts` |

`[notify]` uses the same names (plus `test_messages`) to turn each kind off. Configs from versions before 0.1.11 (`webhook_url`, `death`, `kill`, `summary`…) still work.

## Limits

- **Forever uses Midnight's add-on restrictions ("secret values").** The add-on checks every value before using it, so restricted values are skipped rather than causing errors. During boss encounters and Mythic+, some details (e.g. health) may be missing.
- **No combat log on Forever.** The client forbids add-ons from reading the combat log (trying shows a "blocked from an action only available to the Blizzard UI" popup), so the add-on leaves it off on clients with secret values. Attackers and killers are found from your target, focus, mouseover and nameplates instead: an enemy (player or NPC) has to be visible there and targeting you. For PvP alerts the player must also be able to attack you right now (so unflagged enemies in sanctuaries or neutral towns don't count), and players of your own faction are ignored (duels never alert). Keep enemy nameplates on for the best results. A stealthed attacker you never see shows up only once visible, and a death may say "Cause unknown" if the killer was never visible.
- **Blocked calls are reported.** If the game ever blocks the add-on, a red chat line names the function and `/fnotify` lists recent ones.
- **Kills come from the honorable-kill counter.** On Forever the combat log is blocked and the honor message doesn't name the victim ("You have been awarded 3 Honor."), so a kill is matched to an enemy player seen dying (your target or a nameplate). "Your kill" means they were your target when they died or in the 10 seconds before; killing blows can't be seen. In a group, kills you weren't targeting only appear in the battle report.
- **Time played per level comes from the server's `/played` count.** The add-on asks for it at login and /reload (the "Total time played" lines this would print in chat are hidden; a `/played` you type still shows). If the server doesn't answer, the add-on's own count is used, but only for a level it saw from the start, so the first level-up after installing it, or after levelling without it, may have no time.
- **The gold summary is posted about 30 seconds after logout.** The delay lets the companion tell a real logout from a `/reload`. If the game crashes, the session isn't saved and no summary is sent. If the companion wasn't running when you logged out, it posts that summary the next time it starts while WoW is closed (it remembers what it has posted in `state.json`, so nothing is sent twice).

## First beta session checklist

None of this has been run in the real client yet. On first use:

1. Run `/fnotify test` and confirm a sample arrives in every channel and the signal screenshot is deleted.
2. Run `/fnotify` and check no "Blocked by the game" lines are listed.
3. Die once, level once and log out once, and check each message.
4. If anything fails, turn on `/fnotify debug`, run the companion with `ForeverNotify.exe -v run` (or `py -m forever_notify -v run`), and share the output.

## Development

```
lua5.1 tests/lua/run_scenario.lua addon/ForeverNotify /tmp/out   # add-on under a stubbed WoW API
cd companion && python -m unittest discover -s tests -t .           # decoder, formatting, watcher, end-to-end
companion\build_exe.bat                                            # builds companion\dist\ForeverNotify.exe (PyInstaller)
```

To release: bump `## Version` in `addon/ForeverNotify/ForeverNotify.toc` and push that commit to `main`. When `main` gets a version that isn't released yet, CI tests it, builds the exe and publishes release `v<version>` (the exe, plus a zip with the exe, the example config and the add-on), creating the tag itself; other pushes to `main` only build, so bump the version only in the commit that should be released. A release can also be made by running the **test** workflow by hand (Actions → test → Run workflow, optionally for an earlier commit) or by pushing a matching tag; CI refuses a tag that doesn't match the add-on version. Releasing an older version than one already out doesn't mark it as the latest.
