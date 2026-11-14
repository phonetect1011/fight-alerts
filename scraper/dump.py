#!/usr/bin/env python3
"""Debug helper: how do finished events look on Wikipedia? (past-events tables + a finished fight card)"""
import os
import re
import requests

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal non-commercial app)"}


def wt(page):
    r = requests.get(API, headers=HEADERS, params={"action": "parse", "page": page, "prop": "wikitext",
                                                    "format": "json", "formatversion": 2, "redirects": 1}, timeout=30)
    return r.json().get("parse", {}).get("wikitext", "")


out = []
for page in ("List of UFC events", "Real American Freestyle"):
    t = wt(page)
    heads = re.findall(r"^==+[^=].*?==+\s*$", t, re.M)
    out.append(f"##### {page} headings: {heads}")
    m = re.search(r"^==+\s*Past events\s*==+\s*$", t, re.M | re.I)
    out.append(f"##### {page} PAST EVENTS (first 3500 chars):\n" + (t[m.end():m.end() + 3500] if m else "(no Past events section)"))
    links = re.findall(r"\[\[([^|\]]+)", t[m.end():m.end() + 3500]) if m else []
    if links:
        ev = next((l for l in links if re.search(r"UFC|RAF", l)), None)
        if ev:
            et = wt(ev)
            c = re.search(r"^==+\s*(Fight card|Results|Card)\s*==+\s*$", et, re.M | re.I)
            out.append(f"##### FINISHED EVENT {ev} card (first 3000 chars):\n" + (et[c.end():c.end() + 3000] if c else et[:3000]))
for page in ("2026 in Bare Knuckle Fighting Championship", "2026 in ONE Championship"):
    t = wt(page)
    m = re.search(r"def\.", t)
    out.append(f"##### {page} first finished card around 'def.' (chars):\n" + (t[max(0, m.start() - 2500):m.start() + 1500] if m else "(no def.)"))
os.makedirs("data/debug", exist_ok=True)
open("data/debug/results_layout.txt", "w").write("\n\n".join(out))
print("ok")
