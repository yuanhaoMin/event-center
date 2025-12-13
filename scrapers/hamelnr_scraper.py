import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://hamelnr.de/events/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")


def is_event_url(url: str) -> bool:
    """
    hamelnr 的 /events/ 列表页里会混入普通文章（/business-bildung/.../12345/ 等）。
    真正的活动页一般在 /event/ 或 /events/ 路径下。
    """
    path = urlparse(url).path.rstrip("/")
    return path.startswith("/event/") or path.startswith("/events/")


def parse_list_page(soup: BeautifulSoup):
    events = []
    for item in soup.select('div[data-elementor-type="loop-item"].e-loop-item'):
        link_el = item.select_one("a[href]")
        if not link_el:
            continue

        url = urljoin(LIST_URL, link_el.get("href", "").strip())
        if not url:
            continue

        if not is_event_url(url):
            continue

        title_el = item.select_one(
            "h3.elementor-heading-title, h2.elementor-heading-title, "
            ".elementor-post__title, .elementor-post__title a, "
            "h3 a[href], h2 a[href]"
        )
        list_title = clean_text(title_el.get_text()) if title_el else None

        date_el = item.select_one(
            ".elementor-post-info__item, .elementor-post-info, time"
        )
        list_date = clean_text(date_el.get_text()) if date_el else None

        img_el = item.select_one("[data-dce-background-image-url]")
        if img_el and img_el.get("data-dce-background-image-url"):
            list_image = img_el.get("data-dce-background-image-url")
        else:
            img2 = item.select_one("img[src]")
            list_image = img2["src"] if img2 else None

        badges = []
        for b in item.select(
            ".elementor-absolute a.elementor-button .elementor-button-text"
        ):
            t = clean_text(b.get_text())
            if t and t not in badges:
                badges.append(t)

        events.append(
            {
                "list_title": list_title,
                "list_date": list_date,
                "url": url,
                "list_image": list_image,
                "badges": badges,
            }
        )
    return events


def parse_detail_page(soup: BeautifulSoup, url: str):
    h1 = soup.select_one("h1.elementor-heading-title")
    title = clean_text(h1.get_text()) if h1 else None

    scope = h1.find_parent("div") if h1 else soup

    cover_image = None
    img_el = scope.select_one("[data-dce-background-image-url]") or soup.select_one(
        "[data-dce-background-image-url]"
    )
    if img_el and img_el.get("data-dce-background-image-url"):
        cover_image = img_el.get("data-dce-background-image-url")

    fields = {}
    for box in scope.select(".elementor-widget-icon-box"):
        k_el = box.select_one(
            ".elementor-icon-box-title span, .elementor-icon-box-title"
        )
        if not k_el:
            continue

        key = clean_text(k_el.get_text()).strip(":：")
        if not key:
            continue

        schedule = box.select_one(".event-schedule-wrapper")
        if schedule:
            rows = [
                clean_text(x.get_text()) for x in schedule.select(".event-schedule-row")
            ]
            val = " | ".join([r for r in rows if r]) or clean_text(schedule.get_text())
        else:
            v_el = box.select_one(".elementor-icon-box-description")
            val = clean_text(v_el.get_text()) if v_el else ""

        if val:
            fields[key] = val

    description = None
    candidates = [
        ".elementor-widget-theme-post-content",
        ".elementor-location-single .elementor-widget-container",
        "main .elementor",
    ]
    text = ""
    for sel in candidates:
        node = soup.select_one(sel)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) >= 50:
                break
    if text:
        description = text

    page_type = "event" if fields else "unknown"

    return {
        "url": url,
        "page_type": page_type,
        "title": title,
        "cover_image": cover_image,
        "fields": fields,
        "description": description,
    }


def scrape_hamelnr(limit: int | None = None, sleep_sec: float = 0.3) -> list[dict]:
    session = requests.Session()
    list_soup = get_soup(session, LIST_URL)

    items = parse_list_page(list_soup)
    if limit:
        items = items[:limit]

    results = []
    for it in items:
        url = it["url"]
        try:
            detail_soup = get_soup(session, url)
            detail = parse_detail_page(detail_soup, url)

            results.append(
                {
                    "url": url,
                    "badges": it.get("badges", []),
                    "list": {
                        "title": it.get("list_title"),
                        "date": it.get("list_date"),
                        "image": it.get("list_image"),
                    },
                    "detail": detail,
                }
            )
        except Exception as e:
            results.append(
                {
                    "url": url,
                    "error": str(e),
                    "badges": it.get("badges", []),
                    "list": {
                        "title": it.get("list_title"),
                        "date": it.get("list_date"),
                        "image": it.get("list_image"),
                    },
                }
            )

        time.sleep(sleep_sec)

    return results


if __name__ == "__main__":
    results = scrape_hamelnr(5)
    print(results)
