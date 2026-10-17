# Assistant bot: scoping notes

Status: **scoping only, nothing built yet.** This doc is about adding an assistant bot to the Discord channels ForeverNotify already posts to, so people can ask questions about what happened in game and get recaps.

## Where things stand

- **Everything flows one way.** The add-on draws a signal grid and takes a screenshot. The companion decodes it and posts an embed through a Discord **webhook** (`companion/forever_notify/discord.py`). Nothing ever comes back.
- **A webhook can only post.** It can't read messages, answer slash commands or react to anything. So an assistant has to be a separate Discord **bot** (bot token, gateway connection) that runs all the time.
- **The team already posts into the same channels.** Builds carry encrypted team webhooks (`teamhooks.py`, `team_data.py`). A central bot can see every player's events, not just one person's. That's where most of the value is.
- **Only formatted text reaches Discord.** The raw payload fields stay on the player's PC. The formatter (`formatting.py`) turns them into embed text, and the raw event is thrown away:

  | Signal | Raw fields (payload keys) |
  |---|---|
  | `DEATH` | killer `k`, killer-is-player `kpvp`, zone/subzone/coords, level |
  | `LEVEL` | new level `new`, time on previous level `prev`, session `sess` |
  | `PVP` | attackers `a1`–`a3` (+`more`), health `hp`, hostiles nearby `near`, zone type |
  | `KILL` / `BATTLE` | victim `v`, honor `hon`, streak `streak`, multi-kill `multi`, fight length `dur` |
  | Logout summary | start/end money, income/expense by source, deaths, levels, account gold, zone |

- **The bot can't talk back to the game.** Add-ons can't go online, and the companion deliberately never touches the game process or sends keystrokes. The bot is read-only as far as WoW goes. That's intentional and should stay that way.

## Integration options

| Option | Change to the notifier | Pros | Cons |
|---|---|---|---|
| **A. Bot reads the existing channels and parses the embeds** | None | Works today. Can **backfill** from channel history | Breaks when message wording changes. Some detail is lost in formatting |
| **B. Companion also posts the raw payload as JSON** to a hidden `#fn-data` channel through one more webhook | Small: one more event in `[webhooks]`. `Notifier.handle_signal` / `Notifier.tick` already send through a pluggable `send` | Exact data, versioned, no fragile parsing. Every companion already has webhook access, and nothing new needs hosting | Players have to update their exe. Pre-update history only exists as embeds |
| C. Companion pushes directly to a bot HTTP API | Medium | Most direct | Needs a public endpoint, TLS and per-player auth. Not worth it here |

**Recommendation: A first, then B.** A gets a working bot plus all existing history straight away. B swaps the fragile embed parser for clean data before much gets built on top. Keep the A parser as a fallback for old messages.

### Sketch of option B

In `[webhooks]` config:

```toml
data = "https://discord.com/api/webhooks/..."   # private #fn-data channel, bot-only
```

In the companion, alongside the normal post:

```python
self.send(self.config.webhooks["data"], {"content": "```json\n" + json.dumps({"v": 1, **payload}) + "\n```"})
```

Include a schema version (`"v": 1`) so the bot can handle old and new companions side by side. Typical payloads are a few hundred bytes, but the signal grid allows up to 4 KB, which is more than Discord's 2000-character `content` limit. Either put the JSON in an embed `description` (4096 characters) or split anything that's too long.

## Bot architecture

```
WoW add-on ──screenshot──▶ companion (player PC) ──webhook──▶ Discord channels
                                                                   │
                                                  gateway (outbound websocket)
                                                                   ▼
                                                     assistant bot (always on)
                                                     ├─ ingest: embeds / #fn-data JSON
                                                     ├─ SQLite: events, players, attackers
                                                     ├─ rules: nemesis, streaks, recaps
                                                     └─ /ask → Claude with SQL-backed tools
```

- **Language:** Python (`discord.py`), so it matches the companion and can import `formatting.py` constants directly.
- **Storage:** SQLite to start, with one `events` table (`ts, player, realm, kind, zone, json`) plus views for attackers, kills and gold.
- **Claude:** used only for `/ask` and the weekly write-up. It gets a few narrow tools (e.g. `query_events(kind, player, since, zone)`, `top_attackers(...)`, `gold_summary(...)`) rather than raw SQL or raw chat history. Use a small, fast model for Q&A and a larger one for the weekly recap.

## Feature ideas, roughly by value per effort

1. **Nemesis replies (no AI needed).** When a PvP alert lands, the bot replies in a thread: *"Gankerx (60 Undead Rogue, <Guild>) has attacked the team 7 times; last seen 12 min ago in Stranglethorn."*
2. **`/stats` slash commands (no AI needed).** Deaths, levels, kills and gold/hour per player and per week.
3. **Weekly team recap.** Posted Sunday night: deaths, levels, kills, best gold/hour, deadliest zone, top nemesis.
4. **`/ask` in plain English.** *"How much gold did I make from the AH this week?"*, *"Where do we die most at 30–40?"*
5. **Death patterns.** Zones and level bands that keep killing people, plus PvP vs NPC split.

## Hosting

- The bot only makes **outbound** connections (the Discord gateway websocket and the Claude API). That means no port forwards, no inbound firewall rules and no public IP.
- A Raspberry Pi or home server is fine, and so is a small VPS. Run it as a systemd service or a Docker container with a restart policy.
- Keep it separate from the companion. The companion only runs while that player's PC is on.

## Security

- **The bot token is the most sensitive secret here.** It can read every channel the bot has access to, not just post. Keep it in an env var or a secrets file on the host. Never put it in the repo or the exe. Give it the minimum Discord permissions: read messages and history, send messages, create threads, and use slash commands. Grant the Message Content intent only if option A needs it.
- **Team webhook encryption is light by design** (see `teamhooks.py`): anyone with the repo or the exe can recover the URLs. That's acceptable for posting, but if a `#fn-data` channel is added, restrict that channel to the bot so it isn't cluttered or spoofed. Consider ignoring JSON from any webhook ID the bot doesn't recognise.
- **Claude API key** lives on the bot host only, with a spend limit set on the account.

## Risks

- **The notifier hasn't been validated in-game yet** (see the README's *First beta session checklist*). Do that first. The bot is only as good as the event stream.
- **Forever's restrictions mean some fields are often missing.** With no combat log and "secret values", killers and attackers can be unknown. Bot answers need to handle "unknown" honestly instead of guessing.
- **Embed parsing (option A) is coupled to `formatting.py`.** Changing a title or field name silently breaks ingest. Add a test that runs the bot's parser over `formatting.sample_messages()`.

## Proposed phases

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Run the in-game first-session checklist and fix what breaks | — |
| 1 | Bot skeleton: connect, ingest embeds (option A), backfill history into SQLite | Bot token, host |
| 2 | Nemesis thread replies and `/stats` | Phase 1 |
| 3 | Option B: `#fn-data` raw JSON from the companion, versioned schema | New exe release |
| 4 | `/ask` with Claude and narrow tools; weekly recap | Claude API key |

## Open decisions

1. **What kind of bot:** Claude-powered Q&A from the start, or slash commands and stats first (phases 1–2) with AI added later?
2. **Who it's for:** just you, or the whole team? This affects permissions, the per-player privacy of gold data, and whether stats are per player or shared.
3. **Where it runs:** home Pi/server or a VPS?
4. **Where the code lives:** a `bot/` folder in this repo (easiest to keep option B's schema in sync) or a separate repo?
