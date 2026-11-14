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
    "bkfc-hershey": ("https://next-fight.com/en/bkfc/bkfc-fight-night-hershey", "Semelsberger"),
    "raf-abu-dhabi": ("https://next-fight.com/en/raf/raf-abu-dhabi", "Weidman"),
    "ufc-334": ("https://next-fight.com/en/event/ufc-334", "Hokit"),
}


def slim(s):
    s = re.sub(r"<svg.*?</svg>", "<svg/>", s, flags=re.S)
    s = re.sub(r'\s(srcset|sizes|style|data-[\w-]+)="[^"]*"', "", s)
    s = re.sub(r'src="/_next/image\?[^"]*"', 'src="IMG"', s)
    return s


os.makedirs("data/debug", exist_ok=True)
for name, (url, needle) in PAGES.items():
    html = requests.get(url, headers=HEADERS, timeout=30).text
    out = [f"URL {url}", f"TOTAL HTML LENGTH {len(html)}", ""]

    start = html.find("Fight Card")
    if start < 0:
        start = html.find("Fight card")
    end = html.find("Seen in MMA", start)
    if end < 0:
        end = start + 60000
    out.append("===== CARD HTML (slimmed) =====")
    out.append(slim(html[max(0, start - 1500):end])[:45000])

    out.append("\n===== SCRIPT/JSON OCCURRENCES OF '%s' =====" % needle)
    count = 0
    for m in re.finditer(re.escape(needle), html):
        before = html.rfind("<script", 0, m.start())
        after_close = html.rfind("</script>", 0, m.start())
        if before > after_close:  # inside a <script>
            out.append(f"--- at {m.start()} ---")
            out.append(html[max(0, m.start() - 1200):m.start() + 1200])
            count += 1
            if count >= 3:
                break
    if count == 0:
        out.append("(none inside scripts)")

    ld = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
    out.append("\n===== JSON-LD BLOCKS: %d =====" % len(ld))
    for block in ld[:3]:
        out.append(block[:4000])

    with open(f"data/debug/{name}.txt", "w") as f:
        f.write("\n".join(out))
    print(name, len(html))
