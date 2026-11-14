#!/usr/bin/env python3
"""
Adds favourite / underdog info to data/events.json using real bookmaker odds
from The Odds API (https://the-odds-api.com, free plan: 500 credits/month).

One request returns every upcoming MMA fight the bookmakers are pricing.
We average each fighter's implied win chance across bookmakers (with the
bookmaker margin removed), then match fights to our cards by fighter name.
Where an event still only has an estimated time and the bookmakers list a
main-card fight close to it, their start time replaces the estimate.

Needs the API key in the ODDS_API_KEY environment variable (a GitHub secret).

Usage: python scraper/odds.py data/events.json
Exit code 1 (so the workflow opens an issue) if the API call fails.
"""
import datetime as dt
import json
import os
import re
import statistics
import sys
import time
import unicodedata

import requests

API_URL = "https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds"
# us + au bookmakers: 2 credits per run. Every 6 hours ~= 240 of the 500 free credits a month.
REGIONS = "us,au"
# A bookmaker start time only replaces our estimate when the two are within 3 hours.
# (RAF Abu Dhabi was listed 5 hours early by bookmakers; our estimate was right.)
TRUST_WINDOW_MS = 3 * 3_600_000


def norm(name):
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def last(name):
    parts = norm(name).split()
    return parts[-1] if parts else ""


def same_fighter(a, b):
    """Full-name match, or same surname plus same first initial (handles 'Alex' vs 'Alexander')."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na.replace(" ", "") == nb.replace(" ", ""):
        return True
    return last(a) == last(b) and na[0] == nb[0]


def tier_for(fav_pct):
    gap = abs(fav_pct - 50)
    if gap < 6:
        return "Pick'em"
    if gap < 15:
        return "Slight favourite"
    if gap < 30:
        return "Clear favourite"
    return "Heavy favourite"


def fight_odds(fight):
    """Average decimal price and margin-free win chance for each fighter, across bookmakers."""
    names = [fight.get("home_team", ""), fight.get("away_team", "")]
    prices = {n: [] for n in names}
    probs = {n: [] for n in names}
    books = 0
    for bm in fight.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = {o["name"]: float(o["price"]) for o in market.get("outcomes", []) if o.get("price")}
            if not all(n in outcomes for n in names):
                continue
            implied = {n: 1 / outcomes[n] for n in names}
            total = sum(implied.values())
            for n in names:
                prices[n].append(outcomes[n])
                probs[n].append(implied[n] / total)
            books += 1
    if not books:
        return None
    return {
        "commence": fight.get("commence_time"),
        "names": names,
        "price": {n: statistics.median(prices[n]) for n in names},
        "prob": {n: statistics.mean(probs[n]) for n in names},
        "books": books,
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/events.json"
    key = os.environ.get("ODDS_API_KEY", "").strip()
    report_path = os.path.join(os.path.dirname(path) or ".", "odds-health.txt")

    def fail(msg):
        print(f"[BROKEN] {msg}")
        with open(report_path, "w") as f:
            f.write(f"The odds fetcher hit a problem:\n\n- {msg}\n\n"
                    "Fight cards are unaffected; FAV/DOG tags just won't update until this is fixed.\n")
        sys.exit(1)

    if not key:
        fail("No ODDS_API_KEY secret found. Add it under Settings -> Secrets and variables -> Actions.")

    try:
        r = requests.get(API_URL, params={
            "apiKey": key, "regions": REGIONS, "markets": "h2h", "oddsFormat": "decimal",
        }, timeout=30)
    except requests.RequestException as e:
        fail(f"Could not reach The Odds API: {e}")
    if r.status_code == 401:
        fail("The Odds API rejected the key (HTTP 401). Check the ODDS_API_KEY secret.")
    if r.status_code == 429:
        fail("Out of free credits for this month (HTTP 429). They reset monthly.")
    if r.status_code != 200:
        fail(f"The Odds API returned HTTP {r.status_code}: {r.text[:200]}")

    remaining = r.headers.get("x-requests-remaining", "?")
    fights = [o for o in (fight_odds(f) for f in r.json()) if o]
    print(f"Got odds for {len(fights)} fights. Credits left this month: {remaining}")

    with open(path) as f:
        data = json.load(f)

    def commence_ms(fo):
        try:
            return int(dt.datetime.fromisoformat(fo["commence"].replace("Z", "+00:00")).timestamp() * 1000)
        except (AttributeError, TypeError, ValueError):
            return None

    matched = 0
    for event in data.get("events", []):
        main_card_times = []
        estimate = event["startMs"]
        for bout in event.get("bouts", []):
            for fo in fights:
                when = commence_ms(fo)
                # same fighters could meet again one day; only match fights within 3 days of this event
                if when and abs(when - event["startMs"]) > 3 * 86_400_000:
                    continue
                n1, n2 = fo["names"]
                if same_fighter(bout["a"], n1) and same_fighter(bout["b"], n2):
                    key_a, key_b = n1, n2
                elif same_fighter(bout["a"], n2) and same_fighter(bout["b"], n1):
                    key_a, key_b = n2, n1
                else:
                    continue
                pa, pb = fo["prob"][key_a], fo["prob"][key_b]
                pct_a = round(100 * pa / (pa + pb))
                bout["pred"] = {
                    "fav": "a" if pa > pb else "b" if pb > pa else None,
                    "pctA": pct_a,
                    "pctB": 100 - pct_a,
                    "oddsA": round(fo["price"][key_a], 2),
                    "oddsB": round(fo["price"][key_b], 2),
                    "tier": tier_for(max(pct_a, 100 - pct_a)),
                    "why": "",
                    "crowd": f"Average of {fo['books']} bookmaker{'s' if fo['books'] != 1 else ''}",
                    "source": "Bookmaker odds",
                }
                matched += 1
                # bookmakers sometimes list placeholder times, so only trust one close to our estimate
                if when and bout.get("section", "Main card") == "Main card" \
                        and abs(when - estimate) <= TRUST_WINDOW_MS:
                    main_card_times.append(when)
                break
        if main_card_times and event.get("timeEstimated", True):
            # bookmakers' start time for the main card replaces our estimate (never a confirmed time)
            event["startMs"] = min(main_card_times)
            event["timeEstimated"] = False

    data["oddsUpdatedMs"] = int(time.time() * 1000)
    data["oddsCreditsLeft"] = remaining
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    with open(report_path, "w") as f:
        f.write(f"Odds OK: {len(fights)} fights priced, {matched} matched to cards, {remaining} credits left.\n")
    print(f"Matched odds to {matched} bouts on our cards.")


if __name__ == "__main__":
    main()
