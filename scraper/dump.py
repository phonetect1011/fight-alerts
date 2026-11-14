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
    "ufc-334": "https://next-fight.com/en/event/ufc-334",
    "one-samurai-5": "https://next-fight.com/en/event/one-championship-one-samurai-5",
}


def slim(s):
    s = re.sub(r"<svg.*?</svg>", "<svg/>", s, flags=re.S)
    s = re.sub(r'<img[^>]*?alt="([^"]*)"[^>]*>', r'<img alt="\1"/>', s)
    s = re.sub(r"<img[^>]*>", "<img/>", s)
    s = re.sub(r'\s(srcset|srcSet|sizes|style|loading|decoding|data-[\w-]+)="[^"]*"', "", s)
    return s


os.makedirs("data/debug", exist_ok=True)
for name, url in PAGES.items():
    html = requests.get(url, headers=HEADERS, timeout=30).text
    out = [f"URL {url}", f"TOTAL HTML LENGTH {len(html)}", ""]
    body = html.find("<body")
    first = html.find("/en/fighter/", body)
    out.append("===== FROM FIRST FIGHTER LINK (slimmed) =====")
    out.append(slim(html[max(0, first - 4000):first + 120000])[:38000])
    ld = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
    out.append("\n===== JSON-LD BLOCKS: %d =====" % len(ld))
    for block in ld:
        if "SportsEvent" in block or "FAQ" in block:
            out.append(block[:5000])
    with open(f"data/debug/{name}.txt", "w") as f:
        f.write("\n".join(out))
    print(name, len(html))
