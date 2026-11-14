#!/usr/bin/env python3
"""Debug helper: saves the top of a few fighter pages' wikitext (the infobox) via the MediaWiki API."""
import os
import requests

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal non-commercial app)"}
PAGES = ["Khamzat Chimaev", "Jiří Procházka", "Mike Perry (fighter)", "Joshua Pacio"]

os.makedirs("data/debug", exist_ok=True)
for page in PAGES:
    r = requests.get(API, headers=HEADERS, params={"action": "parse", "page": page, "prop": "wikitext",
                                                    "format": "json", "formatversion": 2, "redirects": 1}, timeout=30)
    text = r.json().get("parse", {}).get("wikitext", "(missing)")
    name = page.replace(" ", "_").replace("(", "").replace(")", "")
    with open(f"data/debug/infobox_{name}.txt", "w") as f:
        f.write(text[:6000])
    print(page, len(text))
