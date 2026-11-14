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
import unicodedata
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

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

TIME = r"(\d{1,2}:\d{2}\s*[AP]M)"
MAIN_START_RE = re.compile(
    r"starts on\s+(?:[A-Za-z]+,?\s+)?([A-Za-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?\s+at\s+"
    + TIME + r"\s+(?:Eastern|ET\b|EST\b|EDT\b)", re.I)
PRELIM_RE = re.compile(r"(?<!early )(?<!early\s)prelims?[^.]{0,60}?" + TIME + r"\s*(?:Eastern|ET\b|EST\b|EDT\b)", re.I)


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


def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def ld_start(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") == "SportsEvent" and item.get("startDate"):
                try:
                    return parse_iso(item["startDate"])
                except ValueError:
                    pass
    return None


def twemoji_flag(src):
    """twemoji URL like .../1f1eb-1f1f7.svg -> the flag emoji itself."""
    m = re.search(r"/([0-9a-f]{4,5}(?:-[0-9a-f]{4,5})+)\.svg", src or "")
    if not m:
        return ""
    try:
        return "".join(chr(int(x, 16)) for x in m.group(1).split("-"))
    except ValueError:
        return ""


def image_url(img):
    if img is None:
        return ""
    for attr in ("src", "srcset", "srcSet"):
        val = (img.get(attr) or "").split(" ")[0]
        if not val:
            continue
        if val.startswith("/_next/image"):
            q = parse_qs(urlparse(val).query).get("url", [""])[0]
            if q.startswith("http"):
                return q
        elif val.startswith("http"):
            return val
    return ""


def parse_side(side):
    full = side.find(class_="nf-fight-full")
    name = clean(full.get_text(" ")) if full else ""
    portrait = side.find(class_="nf-fight-portrait")
    p_img = portrait.find("img") if portrait else None
    if not name and p_img is not None:
        name = clean(p_img.get("alt"))
    info = {"name": name}
    flag = side.find("img", class_="nf-fight-flag")
    if flag is not None:
        info["country"] = clean(flag.get("alt"))
        info["flag"] = twemoji_flag(flag.get("src"))
    for key, cls in (("rank", "nf-fight-rank"), ("record", "nf-fight-record"), ("nickname", "nf-fight-nick")):
        el = side.find(class_=cls)
        if el is not None:
            info[key] = clean(el.get_text(" ")).strip("“”\" ")
    photo = image_url(p_img)
    if photo:
        info["photo"] = photo
    link = side.find("a", href=re.compile(r"^/en/fighter/"))
    if link is not None:
        info["url"] = BASE + link["href"]
    return {k: v for k, v in info.items() if v}


def parse_stats(row):
    """Height/reach/age/stance table that UFC/ONE pages show under each fight."""
    holder = row.parent if row.parent is not None and row.parent.name == "details" else None
    dl = holder.find(class_="nf-fight-stats") if holder is not None else None
    a, b = {}, {}
    if dl is None:
        return a, b
    for dt_ in dl.find_all("dt"):
        label = clean(dt_.get_text(" "))
        if not label or label.lower() == "nickname":
            continue
        prev, nxt = dt_.find_previous_sibling("dd"), dt_.find_next_sibling("dd")
        for target, cell in ((a, prev), (b, nxt)):
            val = clean(cell.get_text(" ")) if cell is not None else ""
            if val and val not in ("—", "-"):
                target[label] = val
    return a, b


def parse_card(soup):
    """Reads section#fight-card. Returns (bouts, {section label: start datetime})."""
    card = soup.find(id="fight-card")
    if card is None:
        return None, {}
    bouts, times, section = [], {}, "Main card"
    for el in card.find_all(True):
        cls = el.get("class") or []
        if el.name == "div" and "pt-4" in cls and "nf-fight-row" not in cls:
            span = el.find("span")
            label = clean(span.get_text(" ") if span else el.get_text(" "))
            section = label or "Undercard"
            t = el.find("time")
            if t and t.get("datetime"):
                try:
                    times[section.lower()] = parse_iso(t["datetime"])
                except ValueError:
                    pass
        elif "nf-fight-row" in cls:
            sides = el.find_all(class_="nf-fight-side", recursive=False) or el.find_all(class_="nf-fight-side")
            if len(sides) < 2:
                continue
            fa, fb = parse_side(sides[0]), parse_side(sides[1])
            if not fa.get("name") or not fb.get("name"):
                continue
            sa, sb = parse_stats(el)
            if sa:
                fa["stats"] = sa
            if sb:
                fb["stats"] = sb
            title, weight = False, ""
            meta = el.find(class_="nf-fight-meta-idle")
            if meta:
                belt = meta.find(class_="nf-fight-belt")
                if belt:
                    title = True
                    belt.extract()
                weight = clean(meta.get_text(" ")).strip(" ·")
            if section.lower().startswith("cancel"):
                continue
            bouts.append({"a": fa["name"], "b": fb["name"], "section": section, "weight": weight,
                          "title": title, "fa": fa, "fb": fb})
    return bouts, times


def norm_name(n):
    n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", n.lower())


def parse_predictions(soup):
    """next-fight's prediction page: favourite, model odds, confidence, reason, crowd vote per fight."""
    preds = {}
    for row in soup.find_all(class_="is-prediction"):
        sides = row.find_all(class_="nf-fight-side", recursive=False) or row.find_all(class_="nf-fight-side")
        if len(sides) < 2:
            continue
        names = [clean(s.find(class_="nf-fight-full").get_text(" ")) if s.find(class_="nf-fight-full") else "" for s in sides[:2]]
        if not all(names):
            continue
        fav_idx = next((i for i, s in enumerate(sides[:2]) if s.find(class_="nf-fight-fav")), None)
        odds = {}
        odds_p = row.find(class_="nf-pred-odds")
        if odds_p:
            for m in re.finditer(r"([^\d·]+?)\s+(\d+(?:\.\d+)?)", clean(odds_p.get_text(" ")).replace("Next-Fight odds", "")):
                odds[norm_name(m.group(1))[-6:]] = float(m.group(2))

        def odd_for(name):
            key = norm_name(name.split(" ")[-1])[-6:]
            return odds.get(key)

        pred = {
            "names": names,
            "fav": fav_idx,
            "odds": [odd_for(names[0]), odd_for(names[1])],
        }
        for key, cls in (("tier", "nf-pred-tier"), ("why", "nf-pred-why"), ("crowd", "nf-pred-public")):
            el = row.find(class_=cls)
            if el is not None:
                pred[key] = clean(el.get_text(" "))
        preds[frozenset(norm_name(n) for n in names)] = pred
    return preds


def attach_predictions(bouts, preds):
    for b in bouts:
        p = preds.get(frozenset((norm_name(b["a"]), norm_name(b["b"]))))
        if not p:
            continue
        # work out which of our two fighters the prediction's favourite is
        a_is_first = norm_name(p["names"][0]) == norm_name(b["a"])
        odds_a, odds_b = (p["odds"][0], p["odds"][1]) if a_is_first else (p["odds"][1], p["odds"][0])
        fav = None
        if p["fav"] is not None:
            fav = "a" if (p["fav"] == 0) == a_is_first else "b"
        elif odds_a and odds_b and odds_a != odds_b:
            fav = "a" if odds_a < odds_b else "b"
        out = {"fav": fav}
        if odds_a and odds_b:
            ia, ib = 1 / odds_a, 1 / odds_b
            out["pctA"] = round(100 * ia / (ia + ib))
            out["pctB"] = 100 - out["pctA"]
            out["oddsA"], out["oddsB"] = odds_a, odds_b
        for key in ("tier", "why", "crowd"):
            if p.get(key):
                out[key] = p[key]
        if fav or "pctA" in out:
            b["pred"] = out


def parse_event(promo, path):
    soup = get(path)
    h1 = soup.find("h1")
    title = clean(h1.get_text(" ")) if h1 else path.rsplit("/", 1)[-1]
    text = re.sub(r"\s+", " ", soup.get_text(" "))

    bouts, times = parse_card(soup)
    if bouts is None:
        fighter_links = len(soup.select('a[href^="/en/fighter/"]'))
        if fighter_links >= 4:
            raise ScrapeError(f"Fight card section missing on {path} (layout changed?)")
        bouts = []  # card not announced yet

    pred_link = soup.find("a", href=re.compile(r"^/en/pronostics/[^/?#]+$"))
    if pred_link is not None and bouts:
        try:
            attach_predictions(bouts, parse_predictions(get(pred_link["href"])))
        except ScrapeError as e:
            print(f"  [warn] predictions unavailable for {path}: {e}")

    main = times.get("main card") or ld_start(soup)
    faq = MAIN_START_RE.search(text)
    if main is None and faq:
        main = parse_time(infer_date(faq.group(1), faq.group(2), faq.group(3)), faq.group(4))
    if main is None:
        raise ScrapeError(f"No start time found on {path}")

    prelims = times.get("prelims")
    early = times.get("early prelims")
    if prelims is None and faq:  # fall back to the FAQ text
        mm = PRELIM_RE.search(text[faq.start():faq.start() + 1500])
        if mm:
            t = parse_time(main.astimezone(ET).date(), mm.group(1))
            if t > main:
                t -= dt.timedelta(days=1)
            prelims = t if t != main else None

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
        "bouts": bouts,
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
