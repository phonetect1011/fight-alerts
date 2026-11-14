#!/usr/bin/env python3
"""Saves trimmed samples of next-fight.com page HTML into data/debug/ so the parser can be fixed."""
import os
import re

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def slim(s):
    s = re.sub(r"<svg.*?</svg>", "<svg/>", s, flags=re.S)
    s = re.sub(r'\s(srcset|srcSet|sizes|style|loading|decoding|data-[\w-]+)="[^"]*"', "", s)
    s = re.sub(r'<img[^>]*>', '<img/>', s)
    return s


os.makedirs("data/debug", exist_ok=True)
for f in os.listdir("data/debug"):
    os.remove(os.path.join("data/debug", f))

out = []
for url in ["https://next-fight.com/en/pronostics/ufc-334", "https://next-fight.com/en/event/ufc-334"]:
    html = requests.get(url, headers=HEADERS, timeout=30).text
    out.append(f"\n######## {url}  len={len(html)}  blocked={'Cloudflare' in html[:3000] and 'blocked' in html}")
    # every place mentioning favourite / odds / % near a fighter
    for kw in ["favourite", "favorite", "underdog", "odds", "nf-pred", "pred"]:
        hits = [m.start() for m in re.finditer(kw, html, re.I)]
        out.append(f"--- '{kw}': {len(hits)} hits")
    body = html.find("<body")
    i = html.find("favourite", body)
    if i < 0:
        i = html.find("Favourite", body)
    if "pronostics" in url:
        h1 = html.find("<h1", body)
        out.append("===== FROM H1 =====")
        out.append(slim(html[h1:h1 + 120000])[:22000])
    elif i > 0:
        out.append("===== AROUND FIRST 'favourite' =====")
        out.append(slim(html[i - 2500:i + 2500]))

with open("data/debug/predictions.txt", "w") as f:
    f.write("\n".join(out))
print("done")
