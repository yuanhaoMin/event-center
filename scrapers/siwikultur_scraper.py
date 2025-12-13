import re
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def clean_ws(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def safe_bs4(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def parse_date_time(line: str) -> dict:
    line = clean_ws(line)
    out = {"weekday": None, "date": None, "time": None, "raw": line}
    if not line:
        return out

    m_range = re.search(
        r"(\d{2}\.\d{2}\.\d{4})\s*bis\s*(\d{2}\.\d{2}\.\d{4})", line, re.I
    )
    if m_range:
        out["date"] = f"{m_range.group(1)} bis {m_range.group(2)}"
        return out

    parts = [p.strip() for p in re.split(r"\s*\|\s*", line) if p.strip()]
    if len(parts) >= 2:
        if re.search(r"[A-Za-zÄÖÜäöüß]", parts[0]) and not re.search(
            r"\d{2}\.\d{2}\.\d{4}", parts[0]
        ):
            out["weekday"] = parts[0]
            out["date"] = parts[1]
            if len(parts) >= 3:
                out["time"] = parts[2]
            return out
        if re.search(r"\d{2}\.\d{2}\.\d{4}", parts[0]):
            out["date"] = parts[0]
            if len(parts) >= 2 and "Uhr" in parts[1]:
                out["time"] = parts[1]
            return out

    m_date = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", line)
    if m_date:
        out["date"] = m_date.group(1)

    m_time = re.search(r"\b(\d{1,2}\.\d{2}\s*Uhr)\b", line)
    if m_time:
        out["time"] = clean_ws(m_time.group(1))

    return out


def pick_datetime_line(va_tag) -> str:
    lines = [clean_ws(x) for x in va_tag.get_text("\n", strip=True).split("\n")]
    lines = [x for x in lines if x]
    for line in lines:
        if re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", line):
            return line
    for line in lines:
        if "Uhr" in line:
            return line
    return lines[0] if lines else ""


def extract_text_between(start_node, stop_predicate) -> str:
    chunks = []
    for sib in start_node.next_siblings:
        if hasattr(sib, "name") and sib.name is not None:
            if stop_predicate(sib):
                break
            t = sib.get_text(" ", strip=True)
        else:
            t = str(sib)
        t = clean_ws(t)
        if t:
            chunks.append(t)
    return clean_ws(" ".join(chunks))


def normalize_img_url(u: Optional[str], base_url: str) -> Optional[str]:
    if not u:
        return None
    return urljoin(base_url, u)


def parse_events_from_html(html: str, base_url: str) -> list[dict]:
    soup = safe_bs4(html)
    events = []

    for va in soup.select("div#va"):
        vaid = va.find("vaid")
        if not vaid or not vaid.get("id"):
            continue
        event_id = vaid["id"].strip()

        dt_line = pick_datetime_line(va)
        dt = parse_date_time(dt_line)

        title_el = va.select_one("span.fett")
        title = clean_ws(title_el.get_text(" ", strip=True)) if title_el else None

        img_a = va.select_one(".BILDKL a[href], .BILDKR a[href]")
        img_img = va.select_one(".BILDKL img[src], .BILDKR img[src]")
        copyright_el = va.select_one(".BILDKL .copyright, .BILDKR .copyright")

        image_full = normalize_img_url(img_a.get("href"), base_url) if img_a else None
        image_thumb = (
            normalize_img_url(img_img.get("src"), base_url) if img_img else None
        )
        copyright_text = (
            clean_ws(copyright_el.get_text(" ", strip=True)) if copyright_el else None
        )

        meta_div = va.find("div", id=event_id)

        map_a = va.find("a", href=re.compile(r"^https://maps\.google\.[^/]+/maps"))
        location_a = None
        if map_a:
            nxt = map_a.find_next("a", href=True)
            if nxt:
                location_a = nxt

        location_name = (
            clean_ws(location_a.get_text(" ", strip=True)) if location_a else None
        )
        location_url = (
            normalize_img_url(location_a.get("href"), base_url) if location_a else None
        )
        map_url = map_a.get("href") if map_a else None

        phone = None
        tel_img = va.find("img", src=re.compile(r"tel\.gif"))
        if tel_img:
            b = tel_img.find_next("b")
            if b:
                phone = clean_ws(b.get_text(" ", strip=True))

        organizer_name = organizer_url = None
        facebook_share = None
        ical_url = None

        if meta_div:
            for a in meta_div.find_all("a", href=True):
                href = a.get("href", "")
                if "facebook.com/sharer" in href:
                    facebook_share = href
                elif href.startswith("ical.php"):
                    ical_url = urljoin(base_url, href)

            for a in meta_div.find_all("a", href=True):
                txt = clean_ws(a.get_text(" ", strip=True))
                href = a.get("href", "")
                if not txt:
                    continue
                if "facebook.com/sharer" in href:
                    continue
                if href.startswith("ical.php"):
                    continue
                if href.startswith("mailto:"):
                    continue
                if href.startswith("http"):
                    organizer_name = txt
                    organizer_url = href
                    break

        desc = None
        img_block = va.select_one(".BILDKL, .BILDKR")
        if img_block:

            def stop_pred(tag):
                if tag.name == "a" and (tag.get("href", "") or "").startswith(
                    "https://maps.google."
                ):
                    return True
                if tag.name == "img" and "tel.gif" in (tag.get("src", "") or ""):
                    return True
                if tag.name == "div" and tag.get("id") == event_id:
                    return True
                return False

            desc = extract_text_between(img_block, stop_pred) or None
        else:
            if title_el:

                def stop_pred2(tag):
                    if tag.name == "a" and (tag.get("href", "") or "").startswith(
                        "https://maps.google."
                    ):
                        return True
                    if tag.name == "img" and "tel.gif" in (tag.get("src", "") or ""):
                        return True
                    if tag.name == "div" and tag.get("id") == event_id:
                        return True
                    return False

                desc = extract_text_between(title_el, stop_pred2) or None

        events.append(
            {
                "event_id": event_id,
                "title": title,
                "weekday": dt["weekday"],
                "date": dt["date"],
                "time": dt["time"],
                "datetime_raw": dt["raw"],
                "description": desc,
                "location": {
                    "name": location_name,
                    "url": location_url,
                    "map_url": map_url,
                },
                "phone": phone,
                "images": {
                    "full": image_full,
                    "thumb": image_thumb,
                    "copyright": copyright_text,
                },
                "organizer": {"name": organizer_name, "url": organizer_url},
                "links": {"facebook_share": facebook_share, "ical": ical_url},
            }
        )

    return events


def scrape_siwikultur(start_url: str) -> list[dict]:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
    )
    r = s.get(start_url, timeout=30)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    html = r.text
    return parse_events_from_html(html, base_url=start_url)
