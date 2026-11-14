#!/usr/bin/env python3
"""
Fight card builder for the Fight Alerts app, using Wikipedia.

Wikipedia content is free to reuse under CC BY-SA (the app credits it), and the
official MediaWiki API is the sanctioned way for apps to read it. We make a
handful of polite, sequential requests per run with an identifying User-Agent.

Sources:
  UFC   "List of UFC events" -> Scheduled events table -> each event page's fight card
  RAF   "Real American Freestyle" -> Scheduled events table -> each event page
  BKFC  "<year> in Bare Knuckle Fighting Championship" -> one section per event
  ONE   "<year> in ONE Championship" -> one section per event

Fighters with their own Wikipedia page also get a photo (free-licence images
only, with the photographer and licence credited), record, nickname and stats.

Wikipedia gives dates but not start times, so each event gets an estimated
start time (flagged timeEstimated). scraper/odds.py later replaces it with the
real start time when bookmakers are pricing the fights.

Writes data/events.json. If a promotion fails, its previous data is kept, a
report goes to data/health.txt and the script exits 1 so the workflow opens an issue.

Usage: python scraper/wiki.py data/events.json
"""
import datetime as dt
import json
import os
import re
import sys
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "FightAlertsBot/1.0 (https://github.com/phonetect1011/fight-alerts; personal non-commercial app)"}
ET = ZoneInfo("America/New_York")
MAX_EVENTS_PER_PROMO = 8


class ScrapeError(Exception):
    pass


session = requests.Session()
session.headers.update(HEADERS)


def wikitext(page, required=True):
    for attempt in range(3):
        try:
            r = session.get(API, params={
                "action": "parse", "page": page, "prop": "wikitext", "format": "json",
                "formatversion": 2, "redirects": 1, "maxlag": 5,
            }, timeout=30)
            j = r.json()
            if "error" in j:
                if j["error"].get("code") == "missingtitle":
                    if required:
                        raise ScrapeError(f"Wikipedia page not found: {page}")
                    return None, None
                if j["error"].get("code") == "maxlag":
                    time.sleep(5)
                    continue
                raise ScrapeError(f"Wikipedia error for {page}: {j['error'].get('info')}")
            time.sleep(0.5)  # be polite
            return j["parse"]["title"], j["parse"]["wikitext"]
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise ScrapeError(f"Could not load Wikipedia page {page}: {last}")


def wiki_url(title, anchor=None):
    url = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
    if anchor:
        url += "#" + quote(anchor.replace(" ", "_"))
    return url


# ---------------------------------------------------------------- flags

# flagicon codes/names -> (ISO 3166 alpha-2, display name)
COUNTRIES = {
    "USA": ("US", "United States"), "US": ("US", "United States"), "UNITED STATES": ("US", "United States"),
    "BRA": ("BR", "Brazil"), "BRAZIL": ("BR", "Brazil"), "RUS": ("RU", "Russia"), "RUSSIA": ("RU", "Russia"),
    "GEO": ("GE", "Georgia"), "GEORGIA": ("GE", "Georgia"), "ARM": ("AM", "Armenia"), "ARMENIA": ("AM", "Armenia"),
    "UAE": ("AE", "United Arab Emirates"), "ARE": ("AE", "United Arab Emirates"), "UNITED ARAB EMIRATES": ("AE", "United Arab Emirates"),
    "GBR": ("GB", "United Kingdom"), "UK": ("GB", "United Kingdom"), "UNITED KINGDOM": ("GB", "United Kingdom"),
    "IRL": ("IE", "Ireland"), "IRELAND": ("IE", "Ireland"), "CAN": ("CA", "Canada"), "CANADA": ("CA", "Canada"),
    "MEX": ("MX", "Mexico"), "MEXICO": ("MX", "Mexico"), "AUS": ("AU", "Australia"), "AUSTRALIA": ("AU", "Australia"),
    "NZL": ("NZ", "New Zealand"), "NEW ZEALAND": ("NZ", "New Zealand"), "FRA": ("FR", "France"), "FRANCE": ("FR", "France"),
    "GER": ("DE", "Germany"), "DEU": ("DE", "Germany"), "GERMANY": ("DE", "Germany"), "POL": ("PL", "Poland"), "POLAND": ("PL", "Poland"),
    "ITA": ("IT", "Italy"), "ITALY": ("IT", "Italy"), "ESP": ("ES", "Spain"), "SPAIN": ("ES", "Spain"),
    "POR": ("PT", "Portugal"), "PRT": ("PT", "Portugal"), "PORTUGAL": ("PT", "Portugal"), "NED": ("NL", "Netherlands"),
    "NLD": ("NL", "Netherlands"), "NETHERLANDS": ("NL", "Netherlands"), "BEL": ("BE", "Belgium"), "SUI": ("CH", "Switzerland"),
    "SWE": ("SE", "Sweden"), "SWEDEN": ("SE", "Sweden"), "NOR": ("NO", "Norway"), "DEN": ("DK", "Denmark"), "FIN": ("FI", "Finland"),
    "AUT": ("AT", "Austria"), "CZE": ("CZ", "Czech Republic"), "SVK": ("SK", "Slovakia"), "UKR": ("UA", "Ukraine"),
    "UKRAINE": ("UA", "Ukraine"), "BLR": ("BY", "Belarus"), "LTU": ("LT", "Lithuania"), "LAT": ("LV", "Latvia"), "EST": ("EE", "Estonia"),
    "MDA": ("MD", "Moldova"), "ROU": ("RO", "Romania"), "BUL": ("BG", "Bulgaria"), "BGR": ("BG", "Bulgaria"), "SRB": ("RS", "Serbia"),
    "SERBIA": ("RS", "Serbia"), "CRO": ("HR", "Croatia"), "HRV": ("HR", "Croatia"), "BIH": ("BA", "Bosnia and Herzegovina"),
    "MNE": ("ME", "Montenegro"), "MKD": ("MK", "North Macedonia"), "ALB": ("AL", "Albania"), "SLO": ("SI", "Slovenia"),
    "SVN": ("SI", "Slovenia"), "HUN": ("HU", "Hungary"), "GRE": ("GR", "Greece"), "GRC": ("GR", "Greece"), "CYP": ("CY", "Cyprus"),
    "TUR": ("TR", "Turkey"), "TURKEY": ("TR", "Turkey"), "AZE": ("AZ", "Azerbaijan"), "KAZ": ("KZ", "Kazakhstan"),
    "UZB": ("UZ", "Uzbekistan"), "KGZ": ("KG", "Kyrgyzstan"), "TJK": ("TJ", "Tajikistan"), "TKM": ("TM", "Turkmenistan"),
    "MGL": ("MN", "Mongolia"), "MNG": ("MN", "Mongolia"), "CHN": ("CN", "China"), "CHINA": ("CN", "China"), "JPN": ("JP", "Japan"),
    "JAPAN": ("JP", "Japan"), "KOR": ("KR", "South Korea"), "SOUTH KOREA": ("KR", "South Korea"), "PRK": ("KP", "North Korea"),
    "TPE": ("TW", "Taiwan"), "HKG": ("HK", "Hong Kong"), "THA": ("TH", "Thailand"), "THAILAND": ("TH", "Thailand"),
    "PHI": ("PH", "Philippines"), "PHL": ("PH", "Philippines"), "PHILIPPINES": ("PH", "Philippines"), "VIE": ("VN", "Vietnam"),
    "VNM": ("VN", "Vietnam"), "MAS": ("MY", "Malaysia"), "MYS": ("MY", "Malaysia"), "SGP": ("SG", "Singapore"), "SIN": ("SG", "Singapore"),
    "INA": ("ID", "Indonesia"), "IDN": ("ID", "Indonesia"), "IND": ("IN", "India"), "INDIA": ("IN", "India"), "PAK": ("PK", "Pakistan"),
    "AFG": ("AF", "Afghanistan"), "IRI": ("IR", "Iran"), "IRN": ("IR", "Iran"), "IRQ": ("IQ", "Iraq"), "SYR": ("SY", "Syria"),
    "JOR": ("JO", "Jordan"), "LBN": ("LB", "Lebanon"), "ISR": ("IL", "Israel"), "KSA": ("SA", "Saudi Arabia"), "SAU": ("SA", "Saudi Arabia"),
    "BHR": ("BH", "Bahrain"), "BRN": ("BH", "Bahrain"), "QAT": ("QA", "Qatar"), "KUW": ("KW", "Kuwait"), "EGY": ("EG", "Egypt"),
    "MAR": ("MA", "Morocco"), "TUN": ("TN", "Tunisia"), "ALG": ("DZ", "Algeria"), "NGR": ("NG", "Nigeria"), "NGA": ("NG", "Nigeria"),
    "CMR": ("CM", "Cameroon"), "COD": ("CD", "DR Congo"), "RSA": ("ZA", "South Africa"), "ZAF": ("ZA", "South Africa"),
    "GHA": ("GH", "Ghana"), "SEN": ("SN", "Senegal"), "ANG": ("AO", "Angola"), "ARG": ("AR", "Argentina"), "CHI": ("CL", "Chile"),
    "CHL": ("CL", "Chile"), "PER": ("PE", "Peru"), "COL": ("CO", "Colombia"), "VEN": ("VE", "Venezuela"), "ECU": ("EC", "Ecuador"),
    "ECUADOR": ("EC", "Ecuador"), "BOL": ("BO", "Bolivia"), "URU": ("UY", "Uruguay"), "URY": ("UY", "Uruguay"), "PAR": ("PY", "Paraguay"),
    "CUB": ("CU", "Cuba"), "CUBA": ("CU", "Cuba"), "DOM": ("DO", "Dominican Republic"), "PUR": ("PR", "Puerto Rico"),
    "PRI": ("PR", "Puerto Rico"), "JAM": ("JM", "Jamaica"), "HAI": ("HT", "Haiti"), "PAN": ("PA", "Panama"), "CRC": ("CR", "Costa Rica"),
    "GUA": ("GT", "Guatemala"), "SUR": ("SR", "Suriname"), "ISL": ("IS", "Iceland"), "MLT": ("MT", "Malta"),
    "ENG": ("ENG", "England"), "ENGLAND": ("ENG", "England"), "SCO": ("SCT", "Scotland"), "SCOTLAND": ("SCT", "Scotland"),
    "WAL": ("WLS", "Wales"), "WALES": ("WLS", "Wales"), "NIR": ("GB", "Northern Ireland"),
}
SUBDIVISION_FLAGS = {"ENG": "gbeng", "SCT": "gbsct", "WLS": "gbwls"}


def flag_emoji(iso):
    if iso in SUBDIVISION_FLAGS:
        tag = "".join(chr(0xE0000 + ord(ch)) for ch in SUBDIVISION_FLAGS[iso])
        return "\U0001F3F4" + tag + "\U000E007F"
    if len(iso) == 2 and iso.isalpha():
        return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in iso.upper())
    return ""


def country_from(cell):
    m = re.search(r"\{\{\s*(?:flagicon|flag|flagathlete|flagcountry)\s*\|\s*([^|}]+)", cell, re.I)
    if not m:
        return "", ""
    key = m.group(1).strip().upper()
    if key in COUNTRIES:
        iso, name = COUNTRIES[key]
        return name, flag_emoji(iso)
    if len(key) == 2 and key.isalpha():
        return "", flag_emoji(key)
    return m.group(1).strip(), ""


# ---------------------------------------------------------------- wikitext helpers

def strip_refs(s):
    s = re.sub(r"<ref[^>]*/>", "", s, flags=re.S)
    return re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)


def plain(s):
    """Wikitext -> plain text (links -> their label, templates removed)."""
    s = strip_refs(s or "")
    s = re.sub(r"\{\{\s*sortname\s*\|([^|}]*)\|([^|}]*)[^}]*\}\}", r"\1 \2", s, flags=re.I)
    s = re.sub(r"\{\{\s*(?:nowrap|small)\s*\|([^{}]*)\}\}", r"\1", s, flags=re.I)
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def link_target(s):
    m = re.search(r"\[\[([^|\]#]+)(?:#[^|\]]*)?(?:\|[^\]]*)?\]\]", s or "")
    return m.group(1).strip() if m else None


def find_template_end(text, start):
    depth, i = 0, start
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    return len(text)


def split_params(body):
    """Split template body on top-level pipes (not inside {{ }} or [[ ]])."""
    parts, depth_t, depth_l, cur, i = [], 0, 0, "", 0
    while i < len(body):
        two = body[i:i + 2]
        if two == "{{":
            depth_t += 1; cur += two; i += 2; continue
        if two == "}}":
            depth_t -= 1; cur += two; i += 2; continue
        if two == "[[":
            depth_l += 1; cur += two; i += 2; continue
        if two == "]]":
            depth_l -= 1; cur += two; i += 2; continue
        if body[i] == "|" and depth_t == 0 and depth_l == 0:
            parts.append(cur); cur = ""; i += 1; continue
        cur += body[i]
        i += 1
    parts.append(cur)
    return parts


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(s):
    s = s or ""
    m = re.search(r"\{\{\s*(?:start date|dts|date)\s*\|\s*(\d{4})\s*\|\s*([A-Za-z]+|\d{1,2})\s*\|\s*(\d{1,2})", s, re.I)
    if m:
        y, mo, d = m.groups()
        mo = int(mo) if mo.isdigit() else MONTHS.get(mo[:3].lower())
        if mo:
            return dt.date(int(y), mo, int(d))
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", plain(s))
    if m and m.group(1)[:3].lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", plain(s))
    if m and m.group(2)[:3].lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    return None


def infobox_field(text, field):
    m = re.search(r"^\s*\|\s*" + field + r"\s*=\s*(.*)$", text, re.M | re.I)
    return m.group(1).strip() if m else ""


def section(text, heading_rx):
    m = re.search(r"^(==+)\s*" + heading_rx + r"\s*\1\s*$", text, re.M | re.I)
    if not m:
        return ""
    level = len(m.group(1))
    nxt = re.search(r"^={2," + str(level) + r"}[^=].*?={2," + str(level) + r"}\s*$", text[m.end():], re.M)
    return text[m.end(): m.end() + nxt.start() if nxt else len(text)]


# ---------------------------------------------------------------- fight cards

def normalise_section(name, event_title=""):
    n = plain(name)
    n = re.sub(r"\s*\(.*?\)\s*$", "", n).strip()   # drop broadcaster "(Paramount+)"
    low = n.lower()
    if not n or low in ("fight card", "card") or (event_title and low == plain(event_title).lower()):
        return "Main card"
    if "early" in low and "prelim" in low:
        return "Early prelims"
    if "prelim" in low:
        return "Prelims"
    if "main" in low:
        return "Main card"
    return n


def make_fighter(cell):
    country, flag = country_from(cell)
    raw = plain(cell)
    champ = bool(re.search(r"\(\s*c\s*\)", raw))
    name = re.sub(r"\(\s*(?:c|ic)\s*\)", "", raw).strip()
    f = {"name": name}
    if country:
        f["country"] = country
    if flag:
        f["flag"] = flag
    if champ:
        f["rank"] = "C"
    target = link_target(cell)
    if target:
        f["url"] = wiki_url(target)
        f["_page"] = target  # used by enrich_fighters(), removed before saving
    return f


def make_bout(weight, a, mid, b, notes, sect):
    if not plain(a) or not plain(b):
        return None
    if plain(mid).lower().startswith("def"):
        return None  # already happened
    fa, fb = make_fighter(a), make_fighter(b)
    if not fa["name"] or not fb["name"] or fa["name"].upper() == "TBA" or fb["name"].upper() == "TBA":
        return None
    note = plain(notes)
    title = bool(re.search(r"\bfor the\b.*\b(championship|title)\b", note, re.I)) and "eliminator" not in note.lower()
    return {"a": fa["name"], "b": fb["name"], "section": sect, "weight": plain(weight),
            "title": title, "notes": note, "fa": fa, "fb": fb}


def parse_mmaevent_templates(text, event_title):
    """{{MMAevent card|Main card}} {{MMAevent bout|weight|A|vs.|B|method|round|time|notes}} (UFC/RAF pages)."""
    bouts, sect = [], "Main card"
    for m in re.finditer(r"\{\{\s*MMAevent (card|bout)\b", text, re.I):
        end = find_template_end(text, m.start())
        params = split_params(text[m.start() + 2: end - 2])[1:]
        if m.group(1).lower() == "card":
            sect = normalise_section(params[0] if params else "", event_title)
            continue
        params += [""] * (8 - len(params))
        b = make_bout(params[0], params[1], params[2], params[3], params[7], sect)
        if b:
            bouts.append(b)
    return bouts


def parse_wikitables(text, event_title):
    """Season pages: | weight || {{flagicon}} A || vs. || B || method || round || time || notes."""
    bouts = []
    for table in re.findall(r"\{\|.*?\n\|\}", text, re.S):
        sect = "Main card"
        for row in re.split(r"\n\|-[^\n]*", table):
            lines = [ln for ln in row.split("\n") if ln.strip()]
            if any(ln.lstrip().startswith("!") for ln in lines):
                head = " ".join(lines)
                bold = re.search(r"'''(.+?)'''", head)
                if bold and "colspan" in head:
                    sect = normalise_section(bold.group(1), event_title)
                continue
            cells = []
            for ln in lines:
                if not ln.startswith("|") or ln.startswith("|}") or ln.startswith("{|"):
                    if cells:
                        cells[-1] += "\n" + ln
                    continue
                for c in (ln[1:].split("||") if "||" in ln else [ln[1:]]):
                    # drop cell attributes like "align=center|vs."
                    sub = split_params(c)
                    cells.append(sub[-1] if len(sub) > 1 and "=" in sub[0] and "[[" not in sub[0] and "{{" not in sub[0] else c)
            if len(cells) >= 4 and re.match(r"\s*(vs\.?|def\.?)\s*$", plain(cells[2]), re.I):
                cells += [""] * (8 - len(cells))
                b = make_bout(cells[0], cells[1], cells[2], cells[3], cells[7], sect)
                if b:
                    bouts.append(b)
    return bouts


def parse_card(text, event_title):
    card = section(text, r"(Fight card|Results|Card)") or text
    return parse_mmaevent_templates(card, event_title) or parse_wikitables(card, event_title)


# ---------------------------------------------------------------- start-time estimates

def estimate_start(promo, title, day, city=""):
    """Wikipedia only has dates. Rough usual main-card start times; replaced by real times from odds.py."""
    t = title.lower()
    tz, hour, minute = "America/New_York", 20, 0
    if promo == "UFC":
        hour = 21 if re.match(r"ufc \d+", t) else 20
    elif promo == "ONE":
        if "friday fights" in t:
            tz, hour, minute = "Asia/Bangkok", 19, 30
        elif "samurai" in t or "japan" in city.lower() or "tokyo" in city.lower():
            tz, hour = "Asia/Tokyo", 17
        else:
            tz, hour = "Asia/Bangkok", 8
    city_l = city.lower()
    for key, zone, h in (("abu dhabi", "Asia/Dubai", 20), ("riyadh", "Asia/Riyadh", 20), ("qatar", "Asia/Qatar", 20),
                         ("al rayyan", "Asia/Qatar", 20), ("sydney", "Australia/Sydney", 13), ("perth", "Australia/Perth", 13),
                         ("england", "Europe/London", 20), ("london", "Europe/London", 20), ("newcastle", "Europe/London", 20),
                         ("glasgow", "Europe/London", 20), ("manchester", "Europe/London", 20), ("birmingham", "Europe/London", 20),
                         ("paris", "Europe/Paris", 21), ("moscow", "Europe/Moscow", 20), ("tbilisi", "Asia/Tbilisi", 20)):
        if key in city_l and promo != "ONE":
            tz, hour, minute = zone, h, 0
            break
    start = dt.datetime.combine(day, dt.time(hour, minute), ZoneInfo(tz))
    return int(start.timestamp() * 1000)


# ---------------------------------------------------------------- per-promotion

def event_record(promo, title, day, url, bouts, city=""):
    slug = re.sub(r"[^a-z0-9]+", "-", plain(title).lower()).strip("-")
    return {
        "id": f"{promo.lower()}-{slug}",
        "promotion": promo,
        "title": plain(title),
        "url": url,
        "date": day.isoformat(),
        "startMs": estimate_start(promo, plain(title), day, city),
        "timeEstimated": True,
        "prelimsMs": None,
        "earlyPrelimsMs": None,
        "bouts": bouts,
    }


def from_list_page(promo, list_page):
    """UFC / RAF: scheduled-events table linking to one page per event."""
    _, text = wikitext(list_page)
    table_src = section(text, r"Scheduled events")
    if not table_src:
        raise ScrapeError(f"No 'Scheduled events' section on {list_page} (layout changed?)")
    today = dt.datetime.now(ET).date()
    rows = []
    for row in re.split(r"\n\|-[^\n]*", table_src):
        cells = [c for c in re.split(r"\n\|", "\n" + row) if c.strip()]
        cells = [c for c in cells if not c.lstrip().startswith(("!", "{|", "}"))]
        ev_cell = next((c for c in cells if re.search(r"\[\[|^\s*\D", c) and not parse_date(c)
                        and not re.match(r"\s*(align|scope|style)", c)), None)
        day = next((parse_date(c) for c in cells if parse_date(c)), None)
        if not ev_cell or not day or day < today - dt.timedelta(days=1):
            continue
        city = plain(cells[-1]) if cells else ""
        rows.append((day, ev_cell, city))
    rows.sort(key=lambda r: r[0])
    events = []
    for day, ev_cell, city in rows[:MAX_EVENTS_PER_PROMO]:
        target = link_target(ev_cell)
        label = plain(ev_cell)
        if target:
            ptitle, ptext = wikitext(target, required=False)
            if ptext:
                name = plain(infobox_field(ptext, "name")) or label
                pday = parse_date(infobox_field(ptext, "date")) or day
                pcity = plain(infobox_field(ptext, "city")) or city
                events.append(event_record(promo, name, pday, wiki_url(ptitle), parse_card(ptext, name), pcity))
                continue
        events.append(event_record(promo, label, day, wiki_url(list_page), [], city))
    return events


def from_season_pages(promo, page_fmt):
    """BKFC / ONE: '<year> in ...' pages with one ==section== per event."""
    today = dt.datetime.now(ET).date()
    years = [today.year] + ([today.year + 1] if today.month >= 10 else [])
    events, found_page = [], False
    for year in years:
        page = page_fmt.format(year=year)
        ptitle, text = wikitext(page, required=(year == today.year))
        if not text:
            continue
        found_page = True
        for m in re.finditer(r"^==([^=].*?)==\s*$", text, re.M):
            heading = m.group(1).strip()
            body = section(text, re.escape(heading))
            if "infobox" not in body.lower():
                continue
            day = parse_date(infobox_field(body, "date"))
            if not day or day < today - dt.timedelta(days=1):
                continue
            name = plain(infobox_field(body, "name")) or heading
            city = plain(infobox_field(body, "city"))
            bouts = parse_card(body, name)
            if re.search(r"\(cancelled\)", heading, re.I):
                continue
            events.append(event_record(promo, name, day, wiki_url(ptitle, heading), bouts, city))
    if not found_page:
        raise ScrapeError(f"No season page found for {promo}")
    events.sort(key=lambda e: e["startMs"])
    return events[:MAX_EVENTS_PER_PROMO]


# ---------------------------------------------------------------- fighter pages (photo, record, stats)

def api_query(params):
    base = {"action": "query", "format": "json", "formatversion": 2, "maxlag": 5}
    for attempt in range(3):
        try:
            r = session.get(API, params={**base, **params}, timeout=30)
            j = r.json()
            if j.get("error", {}).get("code") == "maxlag":
                time.sleep(5)
                continue
            time.sleep(0.5)
            return j
        except (requests.RequestException, ValueError):
            time.sleep(3 * (attempt + 1))
    return {}


def template_params(tpl):
    """{{name|a|b|k=v}} -> (positional list, named dict)."""
    parts = split_params(tpl[2:-2])
    pos, named = [], {}
    for part in parts[1:]:
        if "=" in part and not part.lstrip().startswith(("[[", "{{")):
            k, v = part.split("=", 1)
            named[k.strip().lower()] = v.strip()
        else:
            pos.append(part.strip())
    return pos, named


def first_template(value, names):
    m = re.search(r"\{\{\s*(" + names + r")\s*\|", value or "", re.I)
    if not m:
        return None
    end = find_template_end(value, m.start())
    return template_params(value[m.start():end])


def measure(value):
    """Heights / reaches: {{height|ft=6|in=1}}, {{convert|76|in|cm}}, or plain text."""
    value = strip_refs(value or "")
    h = first_template(value, r"height")
    if h:
        _, n = h
        if n.get("ft"):
            return f"{n['ft']} ft {n.get('in', '0')} in"
        if n.get("m"):
            return f"{n['m']} m"
        if n.get("cm"):
            return f"{n['cm']} cm"
    c = first_template(value, r"convert|cvt")
    if c:
        pos, _ = c
        if len(pos) >= 2:
            if len(pos) >= 4 and pos[1] == "ft" and re.match(r"^\d", pos[2]):
                return f"{pos[0]} ft {pos[2]} in"
            return f"{pos[0]} {pos[1]}"
    return plain(re.split(r"<br\s*/?>", value)[0])


def age_from(value):
    t = first_template(value, r"birth date and age|birth-date and age|bda")
    if t:
        nums = [x for x in t[0] if re.match(r"^\d+$", x)]
        if len(nums) >= 3:
            born = dt.date(int(nums[0]), int(nums[1]), int(nums[2]))
            today = dt.date.today()
            return str(today.year - born.year - ((today.month, today.day) < (born.month, born.day)))
    return ""


def parse_infobox(text):
    m = re.search(r"\{\{\s*Infobox", text or "", re.I)
    if not m:
        return {}
    _, named = template_params(text[m.start():find_template_end(text, m.start())])
    return named


def fighter_details(text):
    box = parse_infobox(text)
    out, stats = {}, {}
    nick = plain(re.split(r"<br\s*/?>", box.get("nickname", ""))[0]).strip("\"'“” ")
    if nick:
        out["nickname"] = nick

    def num(key):
        v = re.sub(r"\D", "", plain(box.get(key, "")))
        return int(v) if v else None

    def tally(prefix):
        """Records are split by finish type: mma_ko_win, mma_sub_win, mma_dec_win ... (or a plain mma_win total)."""
        res = []
        for kind in ("win", "loss"):
            total = num(f"{prefix}_{kind}")
            if total is None:
                parts = [num(k) for k in box if re.fullmatch(prefix + r"_[a-z]+_" + kind, k)]
                parts = [x for x in parts if x is not None]
                total = sum(parts) if parts else None
            res.append(total)
        res.append(num(f"{prefix}_draw"))
        return res
    wins, losses, draws = tally("mma")
    if wins is None and losses is None:  # boxers / bare-knuckle only
        wins, losses, draws = num("wins"), num("losses"), num("draws")
    if wins is None and losses is None:  # kickboxers / Muay Thai (common on ONE cards)
        wins, losses, draws = tally("kick")
    if wins is not None or losses is not None:
        out["record"] = f"{wins or 0}-{losses or 0}-{draws or 0}"
    age = age_from(box.get("birth_date", ""))
    if age:
        stats["Age"] = age
    for key, label in (("height", "Height"), ("reach", "Reach")):
        v = measure(box.get(key, ""))
        if v:
            stats[label] = v
    teams = [plain(t).lstrip("* ") for t in re.split(r"<br\s*/?>|\n\*", strip_refs(box.get("team", "")))]
    teams = [t for t in teams if t]
    team = re.sub(r"\s*\([^)]*\)\s*$", "", teams[-1]) if teams else ""  # most recent team, years dropped
    if team:
        stats["Team"] = team
    if stats:
        out["stats"] = stats
    return out


def enrich_fighters(events):
    """Adds photo (free-licence images only), record, nickname and stats from each fighter's Wikipedia page."""
    wanted = {}
    for e in events:
        for b in e["bouts"]:
            for f in (b["fa"], b["fb"]):
                page = f.pop("_page", None)
                if page:
                    wanted.setdefault(page, []).append(f)
    titles = list(wanted)
    found = {}      # requested title -> page dict
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        j = api_query({"prop": "pageimages|revisions", "piprop": "thumbnail|name", "pithumbsize": 400,
                       "pilicense": "free", "rvprop": "content", "rvslots": "main", "redirects": 1,
                       "titles": "|".join(chunk)})
        q = j.get("query", {})
        alias = {}
        for m in q.get("normalized", []) + q.get("redirects", []):
            alias[m["from"]] = m["to"]
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in chunk:
            final = t
            for _ in range(3):
                final = alias.get(final, final)
            if final in pages:
                found[t] = pages[final]

    # credits for the photos (author + licence), from Commons file metadata
    files = sorted({"File:" + p["pageimage"] for p in found.values() if p.get("pageimage") and p.get("thumbnail")})
    credit = {}
    for i in range(0, len(files), 50):
        j = api_query({"prop": "imageinfo", "iiprop": "extmetadata", "iiextmetadatalanguage": "en",
                       "iiextmetadatafilter": "Artist|LicenseShortName", "titles": "|".join(files[i:i + 50])})
        q = j.get("query", {})
        alias = {m["from"]: m["to"] for m in q.get("normalized", [])}
        back = {alias.get(f, f): f for f in files[i:i + 50]}
        for p in q.get("pages", []):
            meta = (p.get("imageinfo") or [{}])[0].get("extmetadata", {})
            artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
            lic = meta.get("LicenseShortName", {}).get("value", "").strip()
            parts = [x for x in (artist[:60], lic) if x]
            credit[back.get(p["title"], p["title"]).replace(" ", "_")] = " · ".join(parts)

    got = 0
    for t, page in found.items():
        text = ((page.get("revisions") or [{}])[0].get("slots", {}).get("main", {}).get("content", ""))
        details = fighter_details(text) if text else {}
        thumb = (page.get("thumbnail") or {}).get("source")
        if thumb:
            details["photo"] = thumb
            c = credit.get(("File:" + page.get("pageimage", "")).replace(" ", "_"), "")
            details["photoCredit"] = ("Photo: " + c + " (Wikimedia Commons)") if c else "Photo: Wikimedia Commons"
            got += 1
        for f in wanted[t]:
            f.update(details)
    print(f"Fighter pages: {len(found)}/{len(titles)} found, {got} with photos")


PROMOS = {
    "UFC": lambda: from_list_page("UFC", "List of UFC events"),
    "BKFC": lambda: from_season_pages("BKFC", "{year} in Bare Knuckle Fighting Championship"),
    "ONE": lambda: from_season_pages("ONE", "{year} in ONE Championship"),
    "RAF": lambda: from_list_page("RAF", "Real American Freestyle"),
}


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
    for promo, fetch in PROMOS.items():
        try:
            events = fetch()
            if promo == "UFC" and not events:
                raise ScrapeError("No upcoming UFC events found (layout changed?)")
            all_events += events
            nb = sum(len(e["bouts"]) for e in events)
            health[promo] = {"ok": True, "events": len(events), "message": ""}
            print(f"[OK] {promo}: {len(events)} events, {nb} bouts")
        except Exception as e:
            msg = str(e)
            health[promo] = {"ok": False, "events": 0, "message": msg}
            print(f"[BROKEN] {promo}: {msg}")
            report.append(f"- **{promo} BROKEN**: {msg}")
            all_events += [ev for ev in previous.get("events", [])
                           if ev.get("promotion") == promo and (ev.get("startMs") or 0) > now_ms - 6 * 3600_000]

    try:
        enrich_fighters(all_events)
    except Exception as e:  # extras only: never break the fight cards over this
        print(f"[WARN] Could not load fighter pages: {e}")
    for ev in all_events:
        for b in ev.get("bouts", []):
            b["fa"].pop("_page", None)
            b["fb"].pop("_page", None)
    all_events.sort(key=lambda e: e["startMs"])
    data = {
        "generatedMs": now_ms,
        "source": "Wikipedia (CC BY-SA)",
        "health": health,
        "events": all_events,
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    with open(health_path, "w") as f:
        if report:
            f.write("The fight card scraper (Wikipedia) hit problems:\n\n" + "\n".join(report) +
                    "\n\nThe app keeps showing the last good data for broken promotions. "
                    "Fix `scraper/wiki.py`, then re-run the **Update fight data** workflow.\n")
        else:
            f.write("All promotions OK.\n")
    sys.exit(1 if report else 0)


if __name__ == "__main__":
    main()
