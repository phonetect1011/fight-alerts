#!/usr/bin/env python3
"""
Fight data scraper for the Fight Alerts app.

Pulls upcoming UFC, BKFC, ONE and RAF cards from next-fight.com and writes
data/events.json, which the app downloads.

Health check: if a promotion returns no usable events (site changed, blocked,
etc.) it is marked broken in the JSON, its previous data is kept, a report is
written to data/health.txt and the script exits with code 1 so the GitHub
workflow opens an issue.

Usage: python scraper/scrape.py data/events.json
"""
import datetime as dt
import json
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

BASE = "https://next-fight.com"
ET = ZoneInfo("America/New_York")
MAX_EVENTS_PER_PROMO = 6
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# list page + regex that event links on that page must match
PROMOS = {
    "UFC": ("/en/organization/ufc", r"^/en/event/[^/?#]*ufc[^/?#]*$"),
    "BKFC": ("/en/bkfc", r"^/en/bkfc/[^/?#]+$"),
    "ONE": ("/en/organization/one-championship", r"^/en/event/one-championship-[^/?#]+$"),
    "RAF": ("/en/raf", r"^/en/raf/[^/?#]+$"),
}

SECTION_LABELS = ["cancelled fights", "early prelims", "co-main event",
                  "main event", "main card", "prelims"]
WEIGHT_RE = re.compile(
    r"\b((?:women'?s\s+)?(?:straw|fly|bantam|feather|light|welter|middle|"
    r"light\s*heavy|light-heavy|cruiser|heavy)weight|catchweight[^·\n]*|"
    r"open\s*weight|\d{2,3}\s*(?:lb|lbs|kg)\b)", re.I)
TIME = r"(\d{1,2}:\d{2}\s*[AP]M)"
MAIN_START_RE = re.compile(
    r"starts on\s+(?:[A-Za-z]+,?\s+)?([A-Za-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?\s+at\s+"
    + TIME + r"\s+(?:Eastern|ET\b|EST\b|EDT\b)", re.I)
EARLY_RE = re.compile(r"early\s+prelims?[^.]{0,60}?" + TIME + r"\s*(?:Eastern|ET\b|EST\b|EDT\b)", re.I)
PRELIM_RE = re.compile(r"(?<!early )(?<!early\s)prelims?[^.]{0,60}?" + TIME + r"\s*(?:Eastern|ET\b|EST\b|EDT\b)", re.I)
STOP_HEADING_RE = re.compile(r"frequently asked|what time|faq|newsletter|explore|partners|latest results|related", re.I)


class ScrapeError(Exception):
    pass


session = requests.Session()
session.headers.update(HEADERS)


def get(path):
    url = path if path.startswith("http") else BASE + path
    last = None
    for attempt in range(3):
        try:
            r = session.get(url, timeout=25)
            if r.status_code == 200:
                time.sleep(1.0)  # be polite
                return BeautifulSoup(r.text, "html.parser")
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(3 * (attempt + 1))
    raise ScrapeError(f"Could not load {url}: {last}")


def norm_href(href):
    if not href:
        return None
    href = href.split("#")[0].split("?")[0]
    if href.startswith(BASE):
        href = href[len(BASE):]
    return href if href.startswith("/") else None


def event_links(promo):
    path, pattern = PROMOS[promo]
    soup = get(path)
    rx = re.compile(pattern)
    links = []
    # walk the page in order; stop once we reach the past "results" section
    for el in soup.body.descendants if soup.body else []:
        if isinstance(el, Tag) and el.name in ("h2", "h3") and re.search(r"result|past events", el.get_text(), re.I):
            break
        if isinstance(el, Tag) and el.name == "a":
            href = norm_href(el.get("href"))
            if href and rx.match(href) and href != path and href not in links:
                links.append(href)
    return links[:MAX_EVENTS_PER_PROMO]


def parse_time(day, t):
    return dt.datetime.combine(day, dt.datetime.strptime(t.replace(" ", "").upper(), "%I:%M%p").time(), ET)


def infer_date(month_name, day, year):
    month = dt.datetime.strptime(month_name[:3].title(), "%b").month
    today = dt.datetime.now(ET).date()
    if year:
        return dt.date(int(year), month, int(day))
    d = dt.date(today.year, month, int(day))
    if d < today - dt.timedelta(days=60):
        d = dt.date(today.year + 1, month, int(day))
    return d


def fighter_name(a, slug):
    name = a.get_text(" ", strip=True)
    if not name:
        img = a.find("img")
        name = (img.get("alt") or "").strip() if img else ""
    if not name:
        name = re.sub(r"-\d+$", "", slug).replace("-", " ").title()
    return re.sub(r"\s+", " ", name)


def parse_bouts(soup):
    h1 = soup.find("h1")
    start = None
    for h in soup.find_all(["h2", "h3"]):
        if re.search(r"fight card", h.get_text(), re.I):
            start = h
            break
    if start is None:
        start = h1 or soup.body

    tokens = []
    started = False
    for el in soup.body.descendants:
        if el is start:
            started = True
            continue
        if not started:
            continue
        if isinstance(el, Tag) and el.name in ("h2", "h3") and STOP_HEADING_RE.search(el.get_text()):
            break
        if isinstance(el, Tag) and el.name == "a":
            href = norm_href(el.get("href")) or ""
            m = re.match(r"^/en/fighter/([^/]+)$", href)
            if m:
                tokens.append(("fighter", m.group(1), fighter_name(el, m.group(1))))
        elif isinstance(el, NavigableString):
            if el.parent and el.parent.name == "a" and "/en/fighter/" in (el.parent.get("href") or ""):
                continue
            txt = re.sub(r"\s+", " ", str(el)).strip()
            if not txt:
                continue
            low = txt.lower()
            for label in SECTION_LABELS:
                if low.startswith(label) and len(txt) <= len(label) + 30:
                    tokens.append(("section", label))
                    break
            else:
                if low == "title" or low.startswith("title fight"):
                    tokens.append(("title",))
                wm = WEIGHT_RE.search(txt)
                if wm and len(txt) < 60:
                    tokens.append(("weight", wm.group(1).strip().title()))

    bouts, pending, section, orphan = [], None, "", {}
    last_slug = None
    for tok in tokens:
        kind = tok[0]
        if kind == "section":
            section = tok[1]
        elif kind == "fighter":
            slug, name = tok[1], tok[2]
            if slug == last_slug:  # image link + name link for same fighter
                if pending and pending.get("b_slug") is None and pending["a_slug"] == slug and len(name) > len(pending["a"]):
                    pending["a"] = name
                continue
            last_slug = slug
            if pending is None:
                pending = {"a": name, "a_slug": slug, "b_slug": None, "section": section,
                           "weight": orphan.get("weight", ""), "title": orphan.get("title", False)}
                orphan = {}
            else:
                pending["b"], pending["b_slug"] = name, slug
                bouts.append(pending)
                pending = None
        elif kind in ("weight", "title"):
            target = pending if pending else (bouts[-1] if bouts else None)
            key = "weight" if kind == "weight" else "title"
            val = tok[1] if kind == "weight" else True
            if target is not None and not target.get(key):
                target[key] = val
            elif target is None or target is not pending:
                orphan[key] = val

    out = []
    for b in bouts:
        if b["section"] == "cancelled fights":
            continue
        out.append({
            "a": b["a"], "b": b["b"],
            "section": b["section"].title().replace("Co-Main", "Co-main"),
            "weight": b.get("weight", ""), "title": bool(b.get("title")),
        })
    return out


def parse_event(promo, path):
    soup = get(path)
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else path.rsplit("/", 1)[-1]
    text = re.sub(r"\s+", " ", soup.get_text(" "))

    m = MAIN_START_RE.search(text)
    if not m:
        raise ScrapeError(f"No start time found on {path}")
    day = infer_date(m.group(1), m.group(2), m.group(3))
    main = parse_time(day, m.group(4))

    def card_time(rx):
        mm = rx.search(text[m.start():m.start() + 1500])
        if not mm:
            return None
        t = parse_time(day, mm.group(1))
        if t > main:  # e.g. prelims at 11 PM the night before? keep it before main card
            t -= dt.timedelta(days=1)
        return t if t != main else None

    early = card_time(EARLY_RE)
    prelims = card_time(PRELIM_RE)
    if prelims and early and prelims == early:
        prelims = None

    def ms(t):
        return int(t.timestamp() * 1000) if t else None

    return {
        "id": promo.lower() + "-" + path.rstrip("/").rsplit("/", 1)[-1],
        "promotion": promo,
        "title": title,
        "url": BASE + path,
        "startMs": ms(main),
        "prelimsMs": ms(prelims),
        "earlyPrelimsMs": ms(early),
        "bouts": parse_bouts(soup),
    }


def scrape_promo(promo):
    links = event_links(promo)
    if not links:
        raise ScrapeError("No event links found on the promotion page (layout changed?)")
    events, errors = [], []
    for link in links:
        try:
            events.append(parse_event(promo, link))
        except Exception as e:  # one bad event shouldn't kill the rest
            errors.append(f"{link}: {e}")
    if not events:
        raise ScrapeError("Found events but couldn't parse any. " + "; ".join(errors[:3]))
    cutoff = int(time.time() * 1000) - 6 * 3600_000
    return [e for e in events if e["startMs"] > cutoff], errors


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "data/events.json"
    health_path = os.path.join(os.path.dirname(out_path) or ".", "health.txt")
    try:
        with open(out_path) as f:
            previous = json.load(f)
    except Exception:
        previous = {"events": []}

    now_ms = int(time.time() * 1000)
    all_events, health, report = [], {}, []
    for promo in PROMOS:
        try:
            events, warnings = scrape_promo(promo)
            all_events += events
            health[promo] = {"ok": True, "events": len(events), "message": ""}
            print(f"[OK] {promo}: {len(events)} events")
            for w in warnings:
                print(f"  [warn] {w}")
                report.append(f"- {promo} (minor): {w}")
        except Exception as e:
            msg = str(e)
            health[promo] = {"ok": False, "events": 0, "message": msg}
            print(f"[BROKEN] {promo}: {msg}")
            report.insert(0, f"- **{promo} BROKEN**: {msg}")
            # keep last good data for this promotion so the app still shows something
            all_events += [ev for ev in previous.get("events", [])
                           if ev.get("promotion") == promo and (ev.get("startMs") or 0) > now_ms - 6 * 3600_000]

    all_events.sort(key=lambda e: e["startMs"])
    data = {"generatedMs": now_ms, "source": "next-fight.com", "health": health, "events": all_events}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)

    broken = [p for p, h in health.items() if not h["ok"]]
    with open(health_path, "w") as f:
        if broken:
            f.write("The fight data scraper hit problems:\n\n" + "\n".join(report) +
                    "\n\nThe app keeps showing the last good data for broken promotions. "
                    "Fix `scraper/scrape.py`, then re-run the **Update fight data** workflow.\n")
        else:
            f.write("All promotions OK.\n" + "\n".join(report) + "\n")
    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
