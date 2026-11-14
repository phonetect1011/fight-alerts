#!/usr/bin/env python3
"""
Confirmed start times for data/events.json.

Wikipedia only gives dates, so wiki.py estimates start times. This script replaces
the estimate with a confirmed time, in this order:

  1. data/time-overrides.json  - times you type in yourself (always wins)
  2. TheSportsDB               - free sports API (shared key "123"); its time is when the
                                 event starts (first fight), in UTC. If that's hours before
                                 the main card it's saved as the prelims start instead
  3. otherwise the estimate stays and the app shows "(approx.)"; odds.py may still
     use a bookmaker time if it's close to the estimate

The app converts every time to the phone's own timezone.

Overrides file format (edit it on GitHub; the key is any part of the event title):
  {
    "RAF Abu Dhabi": "2026-11-14 11:00 America/New_York",
    "UFC 335": "2026-12-13T01:00:00Z"
  }

Usage: python scraper/times.py data/events.json
"""
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
from zoneinfo import ZoneInfo

import requests

SPORTSDB = "https://www.thesportsdb.com/api/v1/json/123/eventsday.php"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal non-commercial app)"}
LEAGUE_WORDS = {"UFC": ("ufc",), "ONE": ("one",), "BKFC": ("bkfc", "bare knuckle"), "RAF": ("raf", "real american")}
STOP = {"vs", "v", "ufc", "one", "bkfc", "raf", "fight", "night", "championship", "fights", "friday", "the", "inner", "circle"}
LOOKAHEAD_DAYS = 14
MAX_DAYS_PER_RUN = 10      # the shared free key is rate-limited, so keep calls few and spaced out
CACHE_HOURS = 12
DAY_MS = 86_400_000


def words(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z]+|\d+", s)) - STOP


def parse_when(value):
    """'2026-11-14T16:00:00Z', '2026-11-14T11:00:00-05:00' or '2026-11-14 11:00 America/New_York' -> ms."""
    value = value.strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})\s+([A-Za-z_]+/[A-Za-z_]+)$", value)
    if m:
        d = dt.date.fromisoformat(m.group(1))
        t = dt.datetime.combine(d, dt.time(int(m.group(2)), int(m.group(3))), ZoneInfo(m.group(4)))
        return int(t.timestamp() * 1000)
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp() * 1000)


def sportsdb_day(day):
    for attempt in range(3):
        try:
            r = requests.get(SPORTSDB, params={"d": day, "s": "Fighting"}, headers=HEADERS, timeout=20)
            if r.status_code == 429:
                print(f"  TheSportsDB rate limit on {day}, waiting")
                time.sleep(20)
                continue
            time.sleep(4)
            return (r.json() or {}).get("events") or []
        except (requests.RequestException, ValueError) as e:
            print(f"  TheSportsDB request failed for {day}: {e}")
            time.sleep(5)
    return None   # unknown (not the same as "no events")


def sportsdb_start(e):
    """UTC start in ms, or None when TheSportsDB has no real time (it uses 00:00:00 for unknown)."""
    ts = (e.get("strTimestamp") or "").replace("+00:00", "")
    if not ts or ts.endswith("T00:00:00"):
        return None
    try:
        return parse_when(ts if ts.endswith("Z") else ts + "Z")
    except ValueError:
        return None


def same_event(ours, theirs):
    league = (theirs.get("strLeague") or "").lower() + " " + (theirs.get("strEvent") or "").lower()
    if not any(w in league for w in LEAGUE_WORDS.get(ours["promotion"], ())):
        return False
    a, b = words(ours["title"]), words(theirs.get("strEvent"))
    if not a or not b:
        return False
    nums_a, nums_b = {w for w in a if w.isdigit()}, {w for w in b if w.isdigit()}
    names_a, names_b = a - nums_a, b - nums_b
    if nums_a & nums_b and (not names_a or names_a & names_b):
        return True                       # "UFC 334" + a matching name
    return len(names_a & names_b) >= 2    # e.g. both main-event surnames


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/events.json"
    folder = os.path.dirname(path) or "."
    cache_path = os.path.join(folder, "times-cache.json")
    overrides_path = os.path.join(folder, "time-overrides.json")

    with open(path) as f:
        data = json.load(f)
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    try:
        with open(overrides_path) as f:
            overrides = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except FileNotFoundError:
        overrides = {}
    except Exception as e:
        print(f"[WARN] time-overrides.json is not valid JSON, ignoring it: {e}")
        overrides = {}

    now = int(time.time() * 1000)
    events = data.get("events", [])

    # 1) TheSportsDB, one request per upcoming date (cached for 12 hours)
    days = sorted({e["date"] for e in events if e.get("date") and now - DAY_MS < e["startMs"] < now + LOOKAHEAD_DAYS * DAY_MS})
    fetched = 0
    for day in days:
        c = cache.get(day)
        if c and now - c.get("checked", 0) < CACHE_HOURS * 3_600_000:
            continue
        if fetched >= MAX_DAYS_PER_RUN:
            break
        found = sportsdb_day(day)
        fetched += 1
        if found is not None:
            cache[day] = {"checked": now, "events": [
                {"strLeague": x.get("strLeague"), "strEvent": x.get("strEvent"), "strTimestamp": x.get("strTimestamp"),
                 "strTimeLocal": x.get("strTimeLocal")} for x in found]}
    # also look at the day after (UTC dates can run a day ahead of the local date)
    confirmed = 0
    for e in events:
        if not e.get("date"):
            continue
        d0 = dt.date.fromisoformat(e["date"])
        candidates = []
        for d in (d0 - dt.timedelta(days=1), d0, d0 + dt.timedelta(days=1)):
            candidates += (cache.get(d.isoformat()) or {}).get("events", [])
        for x in candidates:
            when = sportsdb_start(x)
            if when and same_event(e, x) and abs(when - e["startMs"]) < 1.5 * DAY_MS:
                if when < e["startMs"] - 2 * 3_600_000:
                    # TheSportsDB gives the first fight; well before the main card means that's the prelims
                    e["prelimsMs"] = when
                else:
                    e["startMs"], e["timeEstimated"], e["timeSource"] = when, False, "TheSportsDB"
                confirmed += 1
                break

    # 2) your own overrides always win
    used = 0
    for key, value in overrides.items():
        for e in events:
            if key.lower() in e["title"].lower() or key == e.get("id"):
                try:
                    e["startMs"] = parse_when(value)
                    e["timeEstimated"], e["timeSource"] = False, "Set by you"
                    used += 1
                except ValueError as err:
                    print(f"[WARN] Could not read the time for '{key}': {value} ({err})")

    # drop cache days that have passed
    cache = {d: v for d, v in cache.items() if d >= (dt.date.today() - dt.timedelta(days=2)).isoformat()}
    events.sort(key=lambda e: e["startMs"])
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f"Start times: {confirmed} confirmed by TheSportsDB, {used} set by overrides, "
          f"{sum(1 for e in events if e.get('timeEstimated'))} still estimated")


if __name__ == "__main__":
    main()
