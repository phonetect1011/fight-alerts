#!/usr/bin/env python3
"""
Confirmed start times for data/events.json.

Wikipedia only gives dates, so wiki.py estimates start times. This script replaces
the estimate with a confirmed time, in this order:

  1. data/time-overrides.json  - times you type in yourself (always wins)
  2. UFC.com (UFC events only) - the official events page gives the exact start of the main card,
                                 prelims and early prelims. Wins over everything except overrides
  3. TheSportsDB               - free sports API (shared key "123"); its time is when the
                                 event starts (first fight), in UTC. If that's hours before
                                 the main card it's saved as the first prelims section instead
  4. otherwise a bookmaker time (odds.py runs first) if it was close to the estimate,
     or the estimate itself, which the app shows as "(approx.)"

Every section on the card (early prelims, prelims, main card) then gets its own start time:
confirmed where known, otherwise estimated from the usual gaps and flagged as an estimate.

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
LEAGUE_WORDS = {"UFC": ("ufc",), "ONE": ("one",), "BKFC": ("bkfc", "bare knuckle"), "RAF": ("raf", "real american"),
                "PFL": ("pfl", "professional fighters")}
STOP = {"vs", "v", "ufc", "one", "bkfc", "raf", "pfl", "professional", "fighters", "league", "fight", "night", "championship", "fights", "friday", "the", "inner", "circle"}
LOOKAHEAD_DAYS = 14
MAX_DAYS_PER_RUN = 10      # the shared free key is rate-limited, so keep calls few and spaced out
CACHE_HOURS = 12
DAY_MS = 86_400_000

UFC_EVENTS = "https://www.ufc.com/events"
UFC_SITE = "https://www.ufc.com"
UFC_CACHE_MIN = 60          # UFC.com times are re-checked hourly (one page per check)
UFC_MAX_PAGES = 4           # event pages fetched per run, only when the events list lacks times
# card section on UFC.com -> (our field, its "estimated" flag)
UFC_SECTIONS = {"main": ("startMs", "timeEstimated"), "prelims": ("prelimsMs", "prelimsEstimated"),
                "early": ("earlyPrelimsMs", "earlyPrelimsEstimated")}


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


# ---------------------------------------------------------------- UFC.com

def ufc_get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        time.sleep(2)  # be polite
        return r.status_code, (r.text if r.ok else "")
    except requests.RequestException as e:
        return f"error: {e}", ""


def section_kind(s):
    s = s.lower()
    if "early" in s:
        return "early"
    if "prelim" in s:
        return "prelims"
    if "main" in s:
        return "main"
    return None


def ufc_listing(html):
    """Events list -> [{url, title, times: {main/prelims/early: ms}}].
    Each event card has a link to /event/... with the headline, and a date block carrying
    data-main-card-timestamp / data-prelims-card-timestamp / data-early-card-timestamp (unix seconds)."""
    out = []
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'href="(/event/[A-Za-z0-9_-]+)"', html)]
    starts = []
    for pos, href in marks:            # a card links to its event several times: start at the first link
        if not starts or starts[-1][1] != href:
            starts.append((pos, href))
    for i, (pos, href) in enumerate(starts):
        seg = html[pos: starts[i + 1][0] if i + 1 < len(starts) else pos + 6000]
        title = re.search(r'href="' + re.escape(href) + r'"[^>]*>\s*([^<]{3,120}?)\s*<', seg)
        times = {}
        for m in re.finditer(r'data-([a-z-]*?)-?timestamp="(\d{9,11})"', seg):
            kind = section_kind(m.group(1)) if m.group(1) else None
            if kind and kind not in times:
                times[kind] = int(m.group(2)) * 1000
        out.append({"url": UFC_SITE + href, "title": title.group(1).strip() if title else href.rsplit("/", 1)[-1],
                    "times": times})
    return out


def ufc_event_page(html):
    """Event page -> {main/prelims/early: ms}: each card section (id="main-card", "prelims-card",
    "early-prelims") has a broadcaster time with data-timestamp."""
    times = {}
    marks = [(m.start(), section_kind(m.group(1))) for m in
             re.finditer(r'id="((?:early-)?(?:main|prelims?|early)[a-z-]*)"', html)]
    marks = [(p, k) for p, k in marks if k]
    for i, (pos, kind) in enumerate(marks):
        seg = html[pos: marks[i + 1][0] if i + 1 < len(marks) else pos + 8000]
        m = re.search(r'data-timestamp="(\d{9,11})"', seg)
        if m and kind not in times:
            times[kind] = int(m.group(1)) * 1000
    if "main" not in times:   # the page header shows the main card time
        m = re.search(r'c-hero__headline-suffix[^>]*data-timestamp="(\d{9,11})"', html)
        if m:
            times["main"] = int(m.group(1)) * 1000
    return times


def ufc_match(ours, theirs):
    """Same event: same date (give or take a day) and a shared fighter surname or event number."""
    main = theirs["times"].get("main") or theirs["times"].get("prelims") or theirs["times"].get("early")
    slug_date = re.search(r"([a-z]+)-(\d{1,2})-(\d{4})$", theirs["url"])
    if main and abs(main - ours["startMs"]) > 1.5 * DAY_MS:
        return False
    if not main and slug_date:   # e.g. /event/ufc-fight-night-november-21-2026
        try:
            d = dt.datetime.strptime(" ".join(slug_date.groups()), "%B %d %Y").date()
            if abs((d - dt.date.fromisoformat(ours["date"])).days) > 1:
                return False
        except ValueError:
            pass
    a = words(ours["title"])
    b = words(theirs["title"]) | words(theirs["url"].rsplit("/", 1)[-1].replace("-", " "))
    nums_a = {w for w in a if w.isdigit() and len(w) == 3}
    if nums_a:
        return bool(nums_a & b)          # "UFC 335" must be UFC 335
    return bool((a - {w for w in a if w.isdigit()}) & b)


def apply_ufc_times(events, cache, now, report):
    ufc = [e for e in events if e["promotion"] == "UFC" and now - DAY_MS < e["startMs"] < now + LOOKAHEAD_DAYS * DAY_MS]
    if not ufc:
        return 0
    c = cache.get("_ufc_com") or {}
    if now - c.get("checked", 0) > UFC_CACHE_MIN * 60_000:
        status, html = ufc_get(UFC_EVENTS)
        cards = ufc_listing(html) if html else []
        report.append(f"UFC.com events list: HTTP {status}, {len(cards)} events found")
        if not cards and html:
            i = html.find("timestamp")
            report.append("  (no events parsed; page sample near 'timestamp':)\n" + html[max(0, i - 800): i + 700])
        if cards:
            fetched = 0
            for card in cards:   # fill missing section times from the event's own page
                if card["times"].get("main") and card["times"].get("prelims"):
                    continue
                if not any(ufc_match(e, card) for e in ufc) or fetched >= UFC_MAX_PAGES:
                    continue
                pstatus, page = ufc_get(card["url"])
                fetched += 1
                ptimes = ufc_event_page(page) if page else {}
                report.append(f"  event page {card['url']}: HTTP {pstatus}, sections {sorted(ptimes)}")
                card["times"] = {**ptimes, **card["times"]}
            c = {"checked": now, "cards": cards}
        else:
            c = {"checked": now - (UFC_CACHE_MIN - 10) * 60_000, "cards": c.get("cards", [])}  # retry in 10 min
        cache["_ufc_com"] = c
    used = 0
    for e in ufc:
        card = next((x for x in c.get("cards", []) if ufc_match(e, x) and x["times"]), None)
        if not card:
            report.append(f"  no UFC.com match for {e['title']}")
            continue
        for kind, ms in card["times"].items():
            field, flag = UFC_SECTIONS[kind]
            e[field], e[flag] = ms, False
        e["timeSource"] = "UFC.com"
        used += 1
        fmt = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%a %d %b %H:%M UTC")
        report.append(f"  {e['title']} <- {card['title']}: " +
                      ", ".join(f"{k} {fmt(v)}" for k, v in sorted(card['times'].items())))
    return used


def sections(e):
    return {b.get("section") for b in e.get("bouts", [])}


def fill_section_times(e):
    """Give every section on the card a start time. Confirmed times are kept; the rest are estimated
    from the usual gaps (UFC numbered events: early prelims 4h and prelims 2h before the main card;
    Fight Nights: prelims about 3h before; other promotions about 2h) and flagged as estimates."""
    secs = sections(e)
    main = e["startMs"]
    numbered = bool(re.match(r"ufc \d+", e["title"].lower()))
    gap = 2 if numbered or e["promotion"] != "UFC" else 3
    if "Prelims" in secs and not e.get("prelimsMs"):
        e["prelimsMs"], e["prelimsEstimated"] = main - gap * 3_600_000, True
    if "Early prelims" in secs and not e.get("earlyPrelimsMs"):
        base = e.get("prelimsMs") or main
        e["earlyPrelimsMs"], e["earlyPrelimsEstimated"] = base - 2 * 3_600_000, True
    # keep the order sensible if a confirmed time and an estimate disagree
    if e.get("earlyPrelimsMs") and e.get("prelimsMs") and e["earlyPrelimsMs"] >= e["prelimsMs"] \
            and e.get("prelimsEstimated"):
        e["prelimsMs"] = e["earlyPrelimsMs"] + 90 * 60_000


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
    # also look at the day before/after (UTC dates can differ from the local date)
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
                if when < e["startMs"] - 90 * 60_000:
                    # TheSportsDB gives the first fight; well before the main card means it's the first prelim
                    if "Early prelims" in sections(e):
                        e["earlyPrelimsMs"], e["earlyPrelimsEstimated"] = when, False
                    else:
                        e["prelimsMs"], e["prelimsEstimated"] = when, False
                else:
                    e["startMs"], e["timeEstimated"], e["timeSource"] = when, False, "TheSportsDB"
                confirmed += 1
                break

    # 2) UFC.com: the official times for UFC events (beat TheSportsDB and the estimates)
    report = []
    try:
        ufc_used = apply_ufc_times(events, cache, now, report)
    except Exception as err:   # extra source only: never break the start times over it
        ufc_used = 0
        report.append(f"UFC.com step failed: {err}")
    try:
        os.makedirs(os.path.join(folder, "debug"), exist_ok=True)
        with open(os.path.join(folder, "debug", "ufc_times.txt"), "w") as f:
            f.write("\n".join(report) + "\n")
    except OSError:
        pass

    # 3) your own overrides always win
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

    for e in events:
        fill_section_times(e)

    # drop cache days that have passed
    cache = {d: v for d, v in cache.items()
             if d.startswith("_") or d >= (dt.date.today() - dt.timedelta(days=2)).isoformat()}
    events.sort(key=lambda e: e["startMs"])
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=1, ensure_ascii=False, sort_keys=True)
    print("\n".join(report))
    print(f"Start times: {ufc_used} from UFC.com, {confirmed} confirmed by TheSportsDB, {used} set by overrides, "
          f"{sum(1 for e in events if e.get('timeEstimated'))} still estimated")


if __name__ == "__main__":
    main()
