#!/usr/bin/env python3
"""Saves Wikipedia wikitext samples into data/debug/ (via the official MediaWiki API) to design the parser."""
import os
import re

import requests

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal app)"}


def wikitext(page):
    r = requests.get(API, params={
        "action": "parse", "page": page, "prop": "wikitext", "format": "json",
        "formatversion": 2, "redirects": 1,
    }, headers=HEADERS, timeout=30)
    j = r.json()
    if "error" in j:
        return None, j["error"].get("info")
    return j["parse"]["title"], j["parse"]["wikitext"]


os.makedirs("data/debug", exist_ok=True)
for f in os.listdir("data/debug"):
    os.remove(os.path.join("data/debug", f))

out = []
for page, keywords in [
    ("2026 in Bare Knuckle Fighting Championship", ["Hershey", "Myrtle Beach"]),
    ("2026 in ONE Championship", ["Samurai 5", "Fight Night 49", "Friday Fights 179"]),
]:
    title, text = wikitext(page)
    out.append(f"\n######## {page} -> {title}  (length {len(text) if title else 0})")
    if not title:
        out.append(f"ERROR: {text}")
        continue
    out.append("HEADINGS: " + " | ".join(re.findall(r"^(==+\s*.*?\s*==+)", text, re.M))[:6000])
    out.append("----- first 2500 chars -----")
    out.append(text[:2500])
    for kw in keywords:
        m = re.search(r"^==+[^\n]*" + re.escape(kw) + r"[^\n]*==+\s*$", text, re.M)
        out.append(f"----- section for '{kw}': {'found' if m else 'NOT FOUND'} -----")
        if m:
            out.append(text[m.start():m.start() + 5000])

for page in ["RAF 15", "RAF Abu Dhabi"]:
    title, text = wikitext(page)
    out.append(f"\n######## EVENT: {page} -> {title}")
    if not title:
        out.append(f"ERROR: {text}")
        continue
    i = text.find("card")
    m = re.search(r"^==+\s*(Fight card|Card|Results|Match card)\s*==+", text, re.M | re.I)
    out.append(text[:1200])
    out.append("...\n" + (text[m.start():m.start() + 6000] if m else "(no card section) HEADINGS: " + " | ".join(re.findall(r"^==+\s*(.*?)\s*==+", text, re.M))))

with open("data/debug/wikipedia2.txt", "w") as f:
    f.write("\n".join(out))
print("done")
