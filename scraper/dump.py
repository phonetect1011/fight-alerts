#!/usr/bin/env python3
"""Saves trimmed samples of next-fight.com page HTML into data/debug/ so the parser can be fixed."""
import os
import re

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
PAGES = {
    "fighter-ufc": "https://next-fight.com/en/fighter/ciryl-gane",
    "fighter-bkfc": "https://next-fight.com/en/fighter/dustin-pague",
    "fighter-raf": "https://next-fight.com/en/fighter/kyle-dake",
}


def slim(s):
    s = re.sub(r"<svg.*?</svg>", "<svg/>", s, flags=re.S)
    s = re.sub(r'\s(srcset|srcSet|sizes|style|loading|decoding|data-[\w-]+)="[^"]*"', "", s)
    s = re.sub(r'src="/_next/image\?url=([^&"]*)[^"]*"', r'src="NEXTIMG:\1"', s)
    s = re.sub(r'\sclass="[^"]*"', lambda m: m.group(0) if 'nf-' in m.group(0) or len(m.group(0)) < 60 else ' class="…"', s)
    return s


os.makedirs("data/debug", exist_ok=True)
for f in os.listdir("data/debug"):
    os.remove(os.path.join("data/debug", f))

# flag markup inside an event fight row
html = requests.get("https://next-fight.com/en/event/ufc-334", headers=HEADERS, timeout=30).text
i = html.find('class="nf-fight-name"')
with open("data/debug/event-flag.txt", "w") as f:
    f.write(html[i - 200:i + 1500])

for name, url in PAGES.items():
    html = requests.get(url, headers=HEADERS, timeout=30).text
    out = [f"URL {url}", f"TOTAL HTML LENGTH {len(html)}", ""]
    body = html.find("<h1")
    out.append("===== FROM H1 (slimmed) =====")
    out.append(slim(html[max(0, body - 3000):body + 150000])[:30000])
    ld = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
    out.append("\n===== JSON-LD BLOCKS: %d =====" % len(ld))
    for block in ld:
        if "Person" in block or "Athlete" in block:
            out.append(block[:6000])
    with open(f"data/debug/{name}.txt", "w") as f:
        f.write("\n".join(out))
    print(name, len(html))
