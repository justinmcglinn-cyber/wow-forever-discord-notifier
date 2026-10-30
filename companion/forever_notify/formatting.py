"""Turn decoded add-on payloads and logout summaries into Discord messages."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .discord import DELETE_AFTER

TEST_LINGER_SECONDS = 60  # test samples delete themselves after this long, so channels don't fill up

COLOURS = {
    "DEATH": 0x8B0000,
    "LEVEL": 0xF1C40F,
    "PVP": 0xE74C3C,
    "KILL": 0x9B59B6,
    "BATTLE": 0x71368A,
    "FLAG": 0xE67E22,
    "SUMMARY_UP": 0x2ECC71,
    "SUMMARY_DOWN": 0x95A5A6,
}

# (minimum streak, callout), highest first.
STREAKS = ((20, "LEGENDARY"), (15, "GODLIKE"), (10, "UNSTOPPABLE"), (7, "DOMINATING"), (5, "RAMPAGE"),
           (3, "KILLING SPREE"))
MULTI_KILLS = {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUAD KILL"}


def kill_callouts(multi: int, streak: int) -> list[str]:
    """Big-text lines for a kill: multi-kill first, then the streak tier."""
    lines = []
    if multi >= 2:
        lines.append(f"💥 **{MULTI_KILLS.get(multi, f'MULTI-KILL ×{multi}')}!**")
    for minimum, name in STREAKS:
        if streak >= minimum:
            lines.append(f"🔥 **{name}** — {streak} kills without dying")
            break
    return lines


ZONE_TYPES = {
    "contested": "Contested",
    "hostile": "Hostile territory",
    "friendly": "Friendly territory",
    "sanctuary": "Sanctuary",
    "combat": "Combat zone",
    "arena": "Arena",
}

GOLD_CATEGORIES = {
    "loot": "Loot",
    "quest": "Quests",
    "vendor": "Vendor / repairs",
    "auction": "Auction house",
    "mail": "Mail",
    "trainer": "Training",
    "flight": "Flights",
    "trade": "Trades",
    "guildbank": "Guild bank",
    "other": "Other",
}


def to_int(value: Any, default: Any = 0) -> Any:
    """value as a whole number, or default if it isn't one: one odd field must never stop the companion."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return int(number) if math.isfinite(number) else default


def money(copper: int | float, signed: bool = False) -> str:
    copper = int(copper)
    sign = "-" if copper < 0 else ("+" if signed and copper > 0 else "")
    copper = abs(copper)
    g, rest = divmod(copper, 10000)
    s, c = divmod(rest, 100)
    parts = []
    if g:
        parts.append(f"{g:,}g")
    if s or g:
        parts.append(f"{s}s")
    parts.append(f"{c}c")
    return sign + " ".join(parts)


def duration(seconds: int | float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def unit(summary: str) -> str:
    """Format the add-on's "name|realm|level|class|race|guild" unit summary."""
    fields = (summary.split("|") + [""] * 6)[:6]
    name, realm, level, cls, race, guild = fields
    text = f"**{name}**" + (f"-{realm}" if realm else "")
    details = " ".join(x for x in (f"Lv {level}" if level else "", race, cls) if x)
    if details:
        text += f" ({details})"
    if guild:
        text += f" <{guild}>"
    return text


def location(p: dict[str, str]) -> str:
    place = p.get("zone") or "Unknown zone"
    if p.get("sz") and p.get("sz") != p.get("zone"):
        place += f" › {p['sz']}"
    if p.get("x") and p.get("y"):
        place += f" ({p['x']}, {p['y']})"
    extras = []
    if p.get("pvp"):
        extras.append(ZONE_TYPES.get(p["pvp"], p["pvp"]))
    if p.get("inst") and p["inst"] != "none":
        extras.append(f"instance: {p['inst']}")
    if extras:
        place += " · " + ", ".join(extras)
    return place


def _timestamp(p: dict[str, Any], key: str = "ts") -> str | None:
    try:
        return datetime.fromtimestamp(int(p[key]), tz=timezone.utc).isoformat()
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None


def _who(p: dict[str, str]) -> str:
    return f"{p.get('c', 'Unknown')}-{p.get('r', '?')}"


def _embed(kind: str, title: str, p: dict[str, Any], description: str = "", fields=None) -> dict:
    embed: dict[str, Any] = {"title": title, "color": COLOURS.get(kind, 0x7289DA)}
    if description:
        embed["description"] = description
    if fields:
        embed["fields"] = [{"name": n, "value": v[:1024], "inline": inline} for n, v, inline in fields]
    late = " · sent late (companion wasn't running)" if p.get("late") else ""
    embed["footer"] = {"text": _who(p) + (f" · Lv {p['lv']}" if p.get("lv") else "") + late}
    ts = _timestamp(p)
    if ts:
        embed["timestamp"] = ts
    return embed


def _location_field(p: dict[str, str]) -> tuple:
    return ("Location", location(p), False)


def _health_fields(p: dict[str, str]) -> list[tuple]:
    return [("Your health", f"{p['hp']}%", True)] if p.get("hp") else []


# One function per notification type: (payload, character name) -> (title, description, fields).

def _death(p: dict[str, str], name: str) -> tuple:
    if p.get("k"):
        pvp = p.get("kpvp") == "1"
        how = "Killed by " + (unit(p["k"]) if pvp else f"**{p['k']}**") + (" — **PvP**" if pvp else "")
    else:
        how = "Cause unknown"
    return f"💀 {name} died", how, [_location_field(p)]


def _level(p: dict[str, str], name: str) -> tuple:
    fields = [_location_field(p)]
    prev, sess, new = to_int(p.get("prev"), None), to_int(p.get("sess"), None), to_int(p.get("new"), None)
    if prev is not None:
        label = f"Played at level {new - 1}" if new else "Played on previous level"
        fields.append((label, duration(prev), True))
    if sess is not None:
        fields.append(("This session", duration(sess), True))
    return f"⬆️ {name} reached level {p.get('new', '?')}", "", fields


def _pvp(p: dict[str, str], name: str) -> tuple:
    attackers = [unit(p[k]) for k in ("a1", "a2", "a3") if p.get(k)]
    if p.get("more"):
        attackers.append(f"…and {p['more']} more")
    fields = [("Attackers", "\n".join(attackers) or "Unknown", False), _location_field(p), *_health_fields(p)]
    if p.get("near"):
        fields.append(("Hostile players nearby", p["near"], True))
    return f"⚔️ {name} is under attack!", "", fields


def _kill(p: dict[str, str], name: str) -> tuple:
    victim = p.get("v", "")
    victim_name = victim.split("|")[0] if victim else ""
    title = f"🗡️ {name} killed {victim_name}" if victim_name else f"🗡️ {name} scored an honorable kill"
    multi, streak = to_int(p.get("multi"), 1) or 1, to_int(p.get("streak"), 1) or 1
    fields = []
    if "|" in victim:
        fields.append(("Victim", unit(victim), False))
    if p.get("vr"):
        fields.append(("PvP rank", p["vr"], True))
    if p.get("hon"):
        fields.append(("Honor", f"+{p['hon']}", True))
    fields += [("Streak", str(streak), True), _location_field(p), *_health_fields(p)]
    return title, "\n".join(kill_callouts(multi, streak)), fields


def _battle(p: dict[str, str], name: str) -> tuple:
    total, mine = to_int(p.get("k")), to_int(p.get("mine"))
    title = f"⚔️ Battle report: {name}'s group took down {total} {'enemy' if total == 1 else 'enemies'}"
    fields = [("Your kills", str(mine), True), ("Group kills", str(total), True)]
    if p.get("hon"):
        fields.append(("Honor", f"+{p['hon']}", True))
    if p.get("dur"):
        fields.append(("Fight length", duration(to_int(p["dur"])), True))
    if p.get("streak"):
        fields.append(("Your streak", p["streak"], True))
    if p.get("v"):
        fields.append(("Enemies down", p["v"] + (f" and {p['more']} more" if p.get("more") else ""), False))
    return title, "", fields + [_location_field(p)]


def _flag(p: dict[str, str], name: str) -> tuple:
    state = "now flagged for PvP" if p.get("on") == "1" else "no longer flagged for PvP"
    return f"🚩 {name} is {state}", "", [_location_field(p)]


_FORMATTERS = {"DEATH": _death, "LEVEL": _level, "PVP": _pvp, "KILL": _kill, "BATTLE": _battle, "FLAG": _flag}


def format_signal(p: dict[str, str], pvp_mention: str = "") -> dict | None:
    """Return a Discord webhook body for a decoded signal, or None if it isn't posted as is
    (RELOAD is internal; TEST becomes sample_messages)."""
    kind = p.get("t", "")
    formatter = _FORMATTERS.get(kind)
    if formatter is None:
        return None
    title, description, fields = formatter(p, p.get("c", "Unknown"))
    body: dict[str, Any] = {"embeds": [_embed(kind, title, p, description, fields)]}
    if kind == "PVP" and pvp_mention:
        body["content"] = pvp_mention
        body["allowed_mentions"] = {"parse": ["users", "roles", "everyone"]}
    return body


def _breakdown(bucket: Any) -> str:
    if not isinstance(bucket, dict) or not bucket:
        return "—"
    rows = sorted(bucket.items(), key=lambda kv: -kv[1])
    return "\n".join(f"{GOLD_CATEGORIES.get(k, k)}: {money(v)}" for k, v in rows if v)


def format_summary(s: dict[str, Any]) -> dict:
    start_money = to_int(s.get("startMoney"))
    end_money = to_int(s.get("endMoney"), start_money)
    net = end_money - start_money
    length = max(0, to_int(s.get("stop")) - to_int(s.get("start")))
    hours = length / 3600

    rate = f" ({money(net / hours, signed=True)}/h)" if hours >= 0.05 else ""
    fields = [
        ("Session", duration(length), True),
        ("Net change", money(net, signed=True) + rate, True),
        ("Gold now", money(end_money), True),
        ("Started with", money(start_money), True),
        ("Income", _breakdown(s.get("income")), True),
        ("Spending", _breakdown(s.get("expense")), True),
    ]
    start_level, end_level = s.get("startLevel"), s.get("endLevel")
    if start_level and end_level and end_level != start_level:
        fields.append(("Levels", f"{start_level} → {end_level}", True))
    if s.get("deaths"):
        fields.append(("Deaths", str(s["deaths"]), True))
    if s.get("accountMoney") is not None:
        chars = s.get("accountChars", 0)
        fields.append(("All characters", f"{money(to_int(s['accountMoney']))} across {chars} character"
                       + ("s" if chars != 1 else ""), False))

    p = {"c": s.get("char", "Unknown"), "r": s.get("realm", "?"), "lv": s.get("endLevel"), "ts": s.get("stop")}
    kind = "SUMMARY_UP" if net >= 0 else "SUMMARY_DOWN"
    title = f"💰 {p['c']} logged out — gold summary"
    description = f"Logged out in {s['zone']}" if s.get("zone") else ""
    return {"embeds": [_embed(kind, title, p, description, fields)]}


def sample_messages(p: dict[str, str], pvp_mention: str = "") -> dict[str, dict]:
    """A made-up example of each notification, marked as a test, keyed by event.

    `p` is a TEST signal payload (character, location, time) so the samples
    look like real messages for that character.
    """
    base = {k: v for k, v in p.items() if k in ("c", "r", "lv", "ts", "zone", "sz", "x", "y", "pvp", "inst")}
    base.setdefault("c", "Companion")
    base.setdefault("r", "PC")
    base.setdefault("ts", str(int(datetime.now(timezone.utc).timestamp())))
    try:
        level = int(base.get("lv") or 24)
    except ValueError:
        level = 24
    base["lv"] = str(level)
    stop = int(base["ts"])

    samples = {
        "death": format_signal({**base, "t": "DEATH", "k": "Murloc Forager", "kpvp": "0"}),
        "level": format_signal({**base, "t": "LEVEL", "new": str(level + 1), "prev": "4500", "sess": "5400"}),
        "pvp": format_signal({**base, "t": "PVP", "a1": "Gankster|Stormrage|60|Rogue|Undead|Shadow Council",
                              "hp": "45", "near": "2"}, pvp_mention),
        "kill": format_signal({**base, "t": "KILL", "v": "Lightbringer|Stormrage|26|Paladin|Human|Silver Hand",
                               "vr": "Knight", "hon": "45", "streak": "5", "multi": "3", "hp": "38"}),
        "summary": format_summary({
            "char": base["c"], "realm": base["r"], "start": stop - 5400, "stop": stop,
            "startMoney": 80130, "endMoney": 97300, "startLevel": level, "endLevel": level + 1,
            "income": {"loot": 6490, "quest": 12000}, "expense": {"vendor": 1320}, "deaths": 1,
            "zone": base.get("zone"),
        }),
    }
    for body in samples.values():
        embed = body["embeds"][0]
        embed["title"] = "🧪 TEST · " + embed["title"]
        note = ("*Test message: if you can read this, this channel is set up correctly. "
                "It deletes itself in about a minute.*")
        embed["description"] = (embed.get("description", "") + "\n\n" + note).strip()
        body[DELETE_AFTER] = TEST_LINGER_SECONDS
    return samples
