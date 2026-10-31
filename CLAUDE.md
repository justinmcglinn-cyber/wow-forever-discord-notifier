# ForeverNotify — notes for Claude

WoW: Forever add-on + Windows companion that posts in-game events to the guild's Discord channels via webhooks.
Owner: justinmcglinn-cyber (Perth, WA; network infrastructure analyst). Public repo; every guild member runs the exe.

## How it works

- `addon/ForeverNotify/` (Lua 5.1, Forever = Midnight 12.x UI API). Add-ons can't reach the network, so on an event the
  add-on draws a coded colour grid top-left for one frame and calls `Screenshot()` (`Signal.lua`). Grid: row 0 white/black
  calibration, data rows 3 bits/block, `FN` + version + length + payload + Fletcher-16. Payload = `key=value` lines.
- `companion/forever_notify/` (Python 3.11+, Pillow; built to `ForeverNotify.exe` with PyInstaller onefile).
  `app.py` watches Screenshots, decodes (`signal_decode.py`), formats (`formatting.py`), posts via `discord.py`, deletes the
  signal screenshot. Gold summary comes from SavedVariables written at logout (`luasv.py` parser).
- Module map: `Util.lua` (helpers, `ns.call` secret-safe wrapper, payloads), `Gold.lua` (session gold by source),
  `Played.lua` (/played per level), `PvP.lua` (attack detection from target/nameplates), `Kills.lua` (honour kills,
  battle reports), `Core.lua` (events, /fnotify). Companion: `cli.py`, `config.py`, `setup_wizard.py`, `teamhooks.py`
  (team code `FNTEAM1-…`), `sweep.py` (start-up clean-up of leftover signal screenshots), `updater.py` (self-update),
  `jsonstate.py` (state files), `addon_install.py` (installs/updates the bundled add-on), `keyhints.py` (the
  highlighted shortcut line).

## Hard-won facts about the Forever client

- Secret values: guard everything with `ns.safe`/`ns.call`. Combat log is forbidden (registering pops a "blocked" dialog),
  so it's off by default; attackers/killers come from unit scans.
- Honour message is just "You have been awarded N Honor." (no victim): kills use PLAYER_PVP_KILLS_CHANGED +
  GetPVPSessionStats matched to enemies seen dead; in groups only kills you targeted count as yours.
- At logout the client blanks the name, gives realm "Classic Beta PvP" and GetMoney() 0: use values cached at login
  (`ns.SessionKey()`, session lastMoney).
- PLAYER_LOGOUT also fires on /reload; the add-on sends a RELOAD signal so the companion discards that summary.
- Forever already has an official Discord↔guild-chat bridge, a Classic-style LFG board, and add-ons like Guild Professions
  & Recipes / GuildOS / RareScanner. Don't rebuild those.

## Rules

- Never commit a real Discord webhook URL (CI greps for them). Webhooks live in `config.toml` (git-ignored) or team codes.
  Old embedded webhooks are in git history from 10–17 Oct; they were rotated.
- Tests must pass before pushing: `lua5.1 tests/lua/run_scenario.lua addon/ForeverNotify /tmp/out` and
  `cd companion && python -m unittest discover -s tests -t .`
- One bad message must never stop the companion (each item in the watch loop is guarded; numbers parse via `to_int`).
- Release tag == add-on version. The updater compares the release tag with the exe's bundled add-on version, so a mismatch
  would loop. CI refuses mismatched tags; the updater also won't re-offer a release it already installed.

## Releasing

Bump `## Version` in `addon/ForeverNotify/ForeverNotify.toc` in the release commit and push to `main`. CI tests, builds the exe
and publishes `v<version>` (tag created by the release; exe attached on its own + zip). Other pushes to main only build.
Also possible: Actions → test → Run workflow (optionally a commit), or push a matching tag. Cloud Claude sessions can push
to main but can't push tags, delete branches or start workflows, which is why release-on-version-bump exists.

## Status (31 Oct 2026)

- Latest release: **v0.1.15**: adds Reset Discord channels / Reset WoW folder. In the companion window Space opens a
  shortcuts menu (also open for 15 s at start; closes on its own or with Esc); C or W then asks that setup question again,
  saves it (other settings kept) and carries on watching. Also `ForeverNotify.exe reset-channels` / `reset-wow-folder`.
- v0.1.14 (0969141) features: deaths, level-ups (time played at level), PvP attack alerts, PvP kills +
  battle reports, PvP flag, logout gold summary; test messages delete themselves after ~60s (`pending_deletes.json`);
  start-up sweep of leftover signal screenshots; decoding works 720p–5K, windowed (2.4–15px blocks).
- v0.1.13 (3776fbc) is the first exe with the updater; it was never released, but its exe is the `ForeverNotify-windows`
  artifact of Actions run 41008481434 (expires 28 Jan 2027).
- v0.1.11 exes have no updater: guildmates on it must replace the exe by hand once.
- Dates: Forever launch 4 Nov 2026; raids open 9 Dec; Hardcore in winter.

## Next steps

1. Updater tested for real on 31 Oct: v0.1.13 → v0.1.14 downloaded, checksum OK, swapped and restarted in the same window,
   add-on updated, no re-offer. Still to see for real: v0.1.14 → v0.1.15 (first update that writes `installed` to
   `update.json`; v0.1.13 only recorded skips).
2. Then post the Discord announcement for the latest release (install = download `ForeverNotify.exe` from the release;
   v0.1.11 users replace the exe once; Space → C/W to change channels or folder).
3. Repo housekeeping (owner, in GitHub UI): fill the About box; delete merged branches `kill-noise`, `pvp-kills`,
   `windows-exe` and `ccr-9030cd7a-e3c2tv` (Discord-bot scoping notes, dropped: no bot for now).
4. Feature roadmap agreed (no bot; every member runs the exe; add-ons talk via hidden add-on messages; each shared event
   has one owner to avoid duplicate posts):
   - **Defence calls** (next): when a guildmate is attacked, alert online guildmates in game with a waypoint + ping a
     @Defence role in #defence. Needs a beta/live check that add-on messages over GUILD work outside instances and
     that the add-on can set map waypoints (a `/fnotify probe` command was proposed for this).
   - **Raid-night feed** (before 9 Dec): raid leader's companion posts boss kills/wipes/loot into one Discord forum thread
     per night.
   - **Most-wanted list**: killers of guildmates shared add-on-to-add-on; nameplate warning; board edited in place.
   - Skipped as already covered: chat bridge, LFG, crafting directory, sign-ups, attendance.
5. Optional clean-ups not done: simplify the team-code format (keep reading FNTEAM1), unify the two `set_webhook`
   functions (tests use both names), unused imports in three test files.
