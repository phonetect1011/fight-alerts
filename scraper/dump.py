#!/usr/bin/env python3
"""Debug helper: what does TheSportsDB (free v1 key) have for UFC / ONE / BKFC / RAF events and start times?"""
import datetime as dt
import json
import os
import time
import requests

BASE = "https://www.thesportsdb.com/api/v1/json/123/"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal non-commercial app)"}
os.makedirs("data/debug", exist_ok=True)
out = []


def get(path, **params):
    for _ in range(3):
        r = requests.get(BASE + path, params=params, headers=HEADERS, timeout=20)
        if r.status_code == 429:
            time.sleep(20)
            continue
        time.sleep(3)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:300]}
    return 429, {}


code, j = get("search_all_leagues.php", s="Fighting")
leagues = (j or {}).get("countries") or (j or {}).get("leagues") or []
out.append(f"search_all_leagues Fighting: http={code} count={len(leagues)}")
for lg in leagues:
    out.append(f"  {lg.get('idLeague')}  {lg.get('strLeague')}  alt={lg.get('strLeagueAlternate')}")

want = [lg for lg in leagues if any(k in ((lg.get('strLeague') or '') + ' ' + (lg.get('strLeagueAlternate') or '')).lower()
        for k in ("ufc", "one championship", "bare knuckle", "bkfc", "real american", "raf"))]
for lg in want:
    code, j = get("eventsnextleague.php", id=lg["idLeague"])
    evs = (j or {}).get("events") or []
    out.append(f"\nNEXT {lg['strLeague']} ({lg['idLeague']}): http={code} events={len(evs)}")
    for e in evs:
        out.append(f"  {e.get('dateEvent')} {e.get('strTime')} | local {e.get('dateEventLocal')} {e.get('strTimeLocal')} | ts={e.get('strTimestamp')} | {e.get('strEvent')} | venue={e.get('strVenue')} | status={e.get('strStatus')}")

for d in ("2026-11-14", "2026-11-18", "2026-11-21"):
    code, j = get("eventsday.php", d=d, s="Fighting")
    evs = (j or {}).get("events") or []
    out.append(f"\nDAY {d}: http={code} events={len(evs)}")
    for e in evs:
        out.append(f"  {e.get('strLeague')} | {e.get('strTime')} | ts={e.get('strTimestamp')} | {e.get('strEvent')}")

open("data/debug/sportsdb_times.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
