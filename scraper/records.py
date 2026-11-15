#!/usr/bin/env python3
"""
Fills in missing fight records (e.g. "10-0-0") from ESPN's public MMA scoreboard.

Wikipedia only has records for fighters with their own page, so newer fighters
show no record. ESPN's free, keyless scoreboard feed (the one espn.com's own
fight center uses) lists every bout with both fighters' records, for UFC and PFL.

Only fills records that are missing; a record from Wikipedia is never replaced.
Never fails the workflow: any problem is printed and the data is left as it was.
A short report goes to data/debug/espn_records.txt so you can see what matched.

Usage: python scraper/records.py data/events.json
"""
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata

import requests

LEAGUES = {"UFC": "ufc", "PFL": "pfl"}
URL = "https://site.api.espn.com/apis/site/v2/sports/mma/{league}/scoreboard"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal non-commercial app)"}
RECORD_RX = re.compile(r"^\d+-\d+(-\d+)?")


def norm(name):
    """'César Almeida' -> 'cesar almeida' (accents, dots, hyphens and case ignored)."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^a-z ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def surname(name):
    parts = norm(name).split()
    return parts[-1] if parts else ""


def record_of(comp):
    """ESPN puts the record in competitor.records[].summary (sometimes athlete.record)."""
    for r in comp.get("records") or []:
        s = (r.get("summary") or "").strip()
        if RECORD_RX.match(s):
            return s if s.count("-") == 2 else s + "-0"
    s = ((comp.get("athlete") or {}).get("record") or "").strip()
    if RECORD_RX.match(s):
        return s if s.count("-") == 2 else s + "-0"
    return ""


def espn_bouts(league, day):
    """[(name A, record A, name B, record B)] for every bout ESPN lists around that date."""
    out = []
    # a day either side: ESPN files events by US date, our date can be a day off
    span = f"{(day - dt.timedelta(days=1)):%Y%m%d}-{(day + dt.timedelta(days=1)):%Y%m%d}"
    r = requests.get(URL.format(league=league), params={"dates": span}, headers=HEADERS, timeout=20)
    r.raise_for_status()
    for ev in r.json().get("events", []):
        for comp in ev.get("competitions", []):
            cs = comp.get("competitors") or []
            if len(cs) != 2:
                continue
            names = [((c.get("athlete") or {}).get("displayName") or (c.get("athlete") or {}).get("fullName") or "")
                     for c in cs]
            out.append((names[0], record_of(cs[0]), names[1], record_of(cs[1])))
    time.sleep(0.5)  # be polite
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/events.json"
    report_path = os.path.join(os.path.dirname(path) or ".", "debug", "espn_records.txt")
    with open(path) as f:
        data = json.load(f)

    lines, filled, missing = [], 0, 0
    cache = {}
    for ev in data.get("events", []):
        league = LEAGUES.get(ev.get("promotion"))
        if not league or not ev.get("bouts"):
            continue
        need = [b for b in ev["bouts"] if not b["fa"].get("record") or not b["fb"].get("record")]
        if not need:
            continue
        day = dt.date.fromisoformat(ev["date"])
        key = (league, day)
        try:
            if key not in cache:
                cache[key] = espn_bouts(league, day)
        except Exception as e:
            lines.append(f"{ev['title']}: ESPN request failed: {e}")
            cache[key] = []
        bouts = cache[key]
        if not bouts:
            lines.append(f"{ev['title']}: ESPN has no bouts for {day}")
        # name -> record, exact names first, then surname when it's unique on that card
        exact, by_surname = {}, {}
        for a, ra, b, rb in bouts:
            for n, rec in ((a, ra), (b, rb)):
                if n and rec:
                    exact[norm(n)] = rec
                    by_surname.setdefault(surname(n), set()).add(rec)
        for bout in need:
            for f in (bout["fa"], bout["fb"]):
                if f.get("record"):
                    continue
                rec = exact.get(norm(f["name"]))
                if not rec:
                    recs = by_surname.get(surname(f["name"]), set())
                    rec = next(iter(recs)) if len(recs) == 1 else ""
                if rec:
                    f["record"] = rec
                    filled += 1
                    lines.append(f"  + {f['name']}: {rec}  ({ev['title']})")
                else:
                    missing += 1
                    lines.append(f"  - {f['name']}: not found on ESPN  ({ev['title']})")

    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(f"ESPN records: filled {filled}, still missing {missing}\n\n" + "\n".join(lines) + "\n")
    print(f"ESPN records: filled {filled}, still missing {missing}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # extras only: never break the fight data over this
        print(f"[WARN] ESPN records skipped: {e}")
