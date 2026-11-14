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


def section(text, heading_rx, limit=14000):
    m = re.search(r"^==+\s*" + heading_rx + r"\s*==+\s*$", text, re.M | re.I)
    if not m:
        return "(section not found)\nHEADINGS: " + " | ".join(re.findall(r"^==+\s*(.*?)\s*==+", text, re.M))[:3000]
    nxt = re.search(r"^==[^=].*==\s*$", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[m.start():end][:limit]


os.makedirs("data/debug", exist_ok=True)
for f in os.listdir("data/debug"):
    os.remove(os.path.join("data/debug", f))

out = []
for page, rx in [
    ("List of UFC events", r"Scheduled events"),
    ("List of Bare Knuckle Fighting Championship events", r"(Scheduled|Upcoming) events"),
    ("List of ONE Championship events", r"(Scheduled|Upcoming) events"),
    ("Real American Freestyle", r"(Scheduled|Upcoming) events|Events"),
]:
    title, text = wikitext(page)
    out.append(f"\n######## LIST: {page} -> {title}")
    out.append(section(text, rx) if title else f"ERROR: {text}")

for page in ["UFC 334", "UFC 335", "BKFC Fight Night Hershey", "ONE Samurai 5"]:
    title, text = wikitext(page)
    out.append(f"\n######## EVENT: {page} -> {title}")
    if not title:
        out.append(f"ERROR: {text}")
        continue
    out.append(text[:1500])
    out.append("...\n" + section(text, r"Fight card", 9000))

with open("data/debug/wikipedia.txt", "w") as f:
    f.write("\n".join(out))
print("done")
