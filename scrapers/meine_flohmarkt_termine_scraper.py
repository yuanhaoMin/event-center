import json
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://meine-flohmarkt-termine.de"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


def get_soup(url: str) -> BeautifulSoup:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")


def parse_search_list(search_url: str):
    soup = get_soup(search_url)
    rows = soup.select("div.row[data-link]")
    items = []

    for row in rows:
        detail_url = row.get("data-link")
        if detail_url:
            detail_url = urljoin(BASE, detail_url)

        title_tag = row.select_one("a.d-block.h5")
        title = title_tag.get_text(" ", strip=True) if title_tag else None

        time_tag = row.select_one("time[datetime]")
        dt = (
            time_tag["datetime"].strip()
            if time_tag and time_tag.has_attr("datetime")
            else None
        )

        cat_tag = row.select_one("span.d-none.d-md-inline-block.highlight")
        category = cat_tag.get_text(" ", strip=True) if cat_tag else None

        highlight_spans = row.select("div.col-12.col-md-10 span.highlight")
        address_block = (
            highlight_spans[-1].get_text("\n", strip=True) if highlight_spans else None
        )

        items.append(
            {
                "title_list": title,
                "datetime_list": dt,
                "category_list": category,
                "address_block_list": address_block,
                "detail_url": detail_url,
            }
        )

    return items


def parse_ld_json(soup: BeautifulSoup):
    scripts = soup.select('script[type="application/ld+json"]')
    for sc in scripts:
        txt = sc.get_text(strip=True)
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except json.JSONDecodeError:
            continue

        if isinstance(data, dict):
            if data.get("@type") == "Event":
                return data
            if "@graph" in data and isinstance(data["@graph"], list):
                for node in data["@graph"]:
                    if isinstance(node, dict) and node.get("@type") == "Event":
                        return node
        elif isinstance(data, list):
            for node in data:
                if isinstance(node, dict) and node.get("@type") == "Event":
                    return node
    return None


def parse_features_block(soup: BeautifulSoup):
    blocks = {}
    for h2 in soup.select("h2"):
        title = h2.get_text(" ", strip=True)
        if title in ("Infos für Besucher", "Infos für Händler"):
            box = h2.find_parent()
            if not box:
                continue
            lis = box.select("ul.features li")
            feats = [li.get_text(" ", strip=True) for li in lis]
            blocks[title] = feats
    return {
        "visitor_infos": blocks.get("Infos für Besucher", []),
        "dealer_infos": blocks.get("Infos für Händler", []),
    }


def parse_last_updated(soup: BeautifulSoup):
    div = soup.select_one("div.small.text-end")
    if not div:
        return None
    txt = div.get_text(" ", strip=True)
    m = re.search(r"Stand der Angaben:\s*(\d{2}\.\d{2}\.\d{4})", txt)
    return m.group(1) if m else txt


def parse_organizer_contact(soup: BeautifulSoup):
    h2 = soup.find("h2", id="veranstalterkontakt")
    if not h2:
        return None
    section = h2.find_parent()
    if not section:
        return None
    addr = section.select_one("address")
    address_text = addr.get_text("\n", strip=True) if addr else None

    org_no = None
    p = section.find("p", string=re.compile(r"Veranstalternummer"))
    if p:
        org_no = p.get_text(" ", strip=True).replace("Veranstalternummer:", "").strip()

    website = None
    for a in section.select('a[rel*="nofollow"]'):
        href = a.get("href")
        if href and "Website des Veranstalters" in a.get_text(" ", strip=True):
            website = href
            break

    return {
        "organizer_address_block": address_text,
        "organizer_number": org_no,
        "organizer_website": website,
    }


def parse_event_detail(detail_url: str):
    soup = get_soup(detail_url)

    h1 = soup.select_one("h1.hyphens-auto, h1")
    title = h1.get_text(" ", strip=True) if h1 else None

    category = None
    cat_a = soup.select_one('div.container.detail a[href*="/veranstaltungsarten/"]')
    if cat_a:
        category = cat_a.get_text(" ", strip=True)

    time_tag = soup.select_one("div.container.detail time[datetime]")
    datetime_raw = (
        time_tag["datetime"].strip()
        if time_tag and time_tag.has_attr("datetime")
        else None
    )
    time_text = time_tag.get_text(" ", strip=True) if time_tag else None

    ld = parse_ld_json(soup)

    gut = None
    gut_h2 = soup.find("h2", string=re.compile(r"Gut zu Wissen"))
    if gut_h2:
        sec = gut_h2.find_parent()
        if sec:
            nxt = gut_h2.find_next_sibling("div")
            if nxt:
                gut = nxt.get_text("\n", strip=True)

    out = {
        "detail_url": detail_url,
        "title": title,
        "category": category,
        "datetime_raw": datetime_raw,
        "time_text": time_text,
        "last_updated": parse_last_updated(soup),
        "ld_json": ld,
        "features": parse_features_block(soup),
        "gut_zu_wissen": gut,
        "organizer_contact": parse_organizer_contact(soup),
    }

    if isinstance(ld, dict):
        loc = ld.get("location", {})
        addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
        out["startDate"] = ld.get("startDate")
        out["endDate"] = ld.get("endDate")
        out["description"] = ld.get("description")
        out["eventStatus"] = ld.get("eventStatus")
        out["place_name"] = loc.get("name") if isinstance(loc, dict) else None
        out["streetAddress"] = addr.get("streetAddress")
        out["postalCode"] = addr.get("postalCode")
        out["addressLocality"] = addr.get("addressLocality")
        out["addressCountry"] = addr.get("addressCountry")
        org = ld.get("organizer")
        if isinstance(org, dict):
            out["organizer_name"] = org.get("name")
        elif isinstance(org, str):
            out["organizer_name"] = org

    return out


def scrape_flohmarkt(
    search_url: str, sleep_sec: float = 0.5, limit: int | None = None
) -> list[dict]:
    results = []
    lst = parse_search_list(search_url)
    if limit:
        lst = lst[:limit]

    for it in lst:
        url = it.get("detail_url")
        if not url:
            continue
        try:
            detail = parse_event_detail(url)
            detail.update(
                {
                    "title_list": it.get("title_list"),
                    "datetime_list": it.get("datetime_list"),
                    "category_list": it.get("category_list"),
                    "address_block_list": it.get("address_block_list"),
                }
            )
            results.append(detail)
        except Exception as e:
            results.append({"detail_url": url, "error": str(e)})
        time.sleep(sleep_sec)

    return results
