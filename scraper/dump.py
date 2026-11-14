#!/usr/bin/env python3
"""Debug helper: checks how many fighters on our cards TheSportsDB (free v1 key) has photos for."""
import json
import os
import time
import requests

API = "https://www.thesportsdb.com/api/v1/json/123/searchplayers.php"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal non-commercial app)"}

data = json.load(open("data/events.json"))
fighters = []
for e in data["events"]:
    for b in e["bouts"]:
        for f in (b["fa"], b["fb"]):
            fighters.append((e["promotion"], f["name"], bool(f.get("photo"))))

# sample: every fighter who has no Wikipedia photo, up to 60 (stay well under 30 requests/minute)
sample = [x for x in fighters if not x[2]][:60]
os.makedirs("data/debug", exist_ok=True)
lines, hits, first_raw = [], 0, None
for promo, name, _ in sample:
    try:
        r = requests.get(API, params={"p": name}, headers=HEADERS, timeout=20)
        j = r.json() if r.status_code == 200 else {}
    except Exception as ex:
        j = {"error": str(ex)}
    players = j.get("player") or []
    mma = [p for p in players if (p.get("strSport") or "").lower() in ("fighting", "mma", "boxing", "kickboxing")]
    pick = (mma or players or [None])[0]
    if pick and first_raw is None:
        first_raw = pick
    img = pick and (pick.get("strCutout") or pick.get("strThumb") or pick.get("strRender"))
    if img:
        hits += 1
    lines.append(f"{promo:4} {name:30} http={r.status_code if 'r' in dir() else '?'} found={len(players)} sport={pick and pick.get('strSport')} img={img}")
    time.sleep(2.2)
lines.insert(0, f"{hits}/{len(sample)} fighters without a Wikipedia photo have a TheSportsDB image\n")
open("data/debug/sportsdb_test.txt", "w").write("\n".join(lines) + "\n\nFIRST RAW RECORD:\n" + json.dumps(first_raw, indent=1)[:4000])
print(lines[0])
