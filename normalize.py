import re
from datetime import date, datetime, time
from typing import Any, Dict, Optional, Tuple

from dateutil import tz
from dateutil.parser import parse as du_parse

BERLIN_TZ = tz.gettz("Europe/Berlin")

DE_MONTH = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


def parse_german_long_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    m = re.search(r"\b(\d{1,2})\.?\s+([A-Za-zÄÖÜäöüß]+)\s+(\d{4})\b", s)
    if not m:
        return None
    dd = int(m.group(1))
    mon_raw = m.group(2).lower()
    yyyy = int(m.group(3))

    mon_norm = (
        mon_raw.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    mm = DE_MONTH.get(mon_raw) or DE_MONTH.get(mon_norm)
    if not mm:
        return None
    return date(yyyy, mm, dd)


def parse_time_range_bis(text: str) -> Tuple[Optional[time], Optional[time]]:
    t = (text or "").replace("Uhr", "")
    t = t.replace(".", ":")
    m = re.search(r"\b(\d{1,2}:\d{2})\s*bis\s*(\d{1,2}:\d{2})\b", t, re.I)
    if not m:
        return None, None
    st = parse_time_hhmm(m.group(1))
    et = parse_time_hhmm(m.group(2))
    return st, et


def _safe_strip(s: Any) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s if s else None


def parse_german_ddmmyyyy(s: str) -> Optional[date]:
    m = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", s or "")
    if not m:
        return None
    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(yyyy, mm, dd)


def parse_time_hhmm(s: str) -> Optional[time]:
    s = (s or "").replace("Uhr", "").strip()
    s = s.replace(".", ":")
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    return time(hh, mm)


def combine_local(d: Optional[date], t: Optional[time]) -> Optional[str]:
    if not d:
        return None
    dt = datetime.combine(d, t or time(0, 0)).replace(tzinfo=BERLIN_TZ)
    return dt.isoformat()


def parse_range_ddmmyyyy(raw: str) -> Tuple[Optional[date], Optional[date]]:
    raw = raw or ""
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*bis\s*(\d{2}\.\d{2}\.\d{4})", raw, re.I)
    if not m:
        d = parse_german_ddmmyyyy(raw)
        return d, None
    return parse_german_ddmmyyyy(m.group(1)), parse_german_ddmmyyyy(m.group(2))


def parse_time_window_from_text(s: str) -> Tuple[Optional[time], Optional[time]]:
    s = (s or "").replace("Uhr", "")
    s = s.replace(".", ":")
    s = s.replace("–", "-")
    m = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", s)
    if not m:
        return None, None
    st = parse_time_hhmm(m.group(1))
    et = parse_time_hhmm(m.group(2))
    return st, et


def try_du_parse_iso(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        dt = du_parse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BERLIN_TZ)
        return dt.isoformat()
    except Exception:
        return None


def ensure_event_id(source: str, raw: Dict[str, Any]) -> str:
    """
    如果原始数据里没有稳定 id，就从 URL 里提取。
    """
    if source == "siwikultur":
        return str(
            raw.get("event_id")
            or raw.get("links", {}).get("ical")
            or raw.get("organizer", {}).get("name")
        )
    if source == "flohmarkt":
        url = raw.get("detail_url") or ""
        m = re.search(r"/(\d+)/details", url)
        return m.group(1) if m else url
    if source == "hamelnr":
        url = raw.get("url") or raw.get("detail", {}).get("url") or ""
        m = re.search(r"^https?://[^/]+(/.+?)/?$", url)
        return m.group(1) if m else url
    return str(raw.get("id") or raw.get("url") or raw.get("detail_url"))


def normalize_siwikultur(raw: Dict[str, Any]) -> Dict[str, Any]:
    title = _safe_strip(raw.get("title"))
    event_id = ensure_event_id("siwikultur", raw)
    url = _safe_strip(raw.get("organizer", {}).get("url")) or _safe_strip(
        raw.get("links", {}).get("ical")
    )

    d_start, d_end = parse_range_ddmmyyyy(
        raw.get("date") or raw.get("datetime_raw") or ""
    )
    t_start = parse_time_hhmm(raw.get("time") or "")
    start_dt = combine_local(d_start, t_start)
    end_dt = combine_local(d_end, None) if d_end else None

    loc = raw.get("location") or {}
    images = raw.get("images") or {}
    return {
        "source": "siwikultur",
        "source_event_id": str(event_id),
        "source_url": url,
        "title": title,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "description": _safe_strip(raw.get("description")),
        "location_name": _safe_strip(loc.get("name")),
        "location_address": None,
        "image_url": _safe_strip(images.get("full"))
        or _safe_strip(images.get("thumb")),
        "tags": [],
        "metadata": raw,
    }


def normalize_flohmarkt(raw: Dict[str, Any]) -> Dict[str, Any]:
    event_id = ensure_event_id("flohmarkt", raw)
    url = _safe_strip(raw.get("detail_url")) or _safe_strip(
        raw.get("ld_json", {}).get("url")
    )
    title = _safe_strip(raw.get("title")) or _safe_strip(raw.get("title_list"))

    ld = raw.get("ld_json") or {}
    start_date = None
    end_date = None

    if isinstance(ld, dict):
        if ld.get("startDate"):
            try:
                start_date = du_parse(ld["startDate"]).date()
            except Exception:
                start_date = None
        if ld.get("endDate"):
            try:
                end_date = du_parse(ld["endDate"]).date()
            except Exception:
                end_date = None

    st, et = parse_time_window_from_text(raw.get("time_text") or "")

    start_dt = (
        combine_local(start_date, st)
        if start_date
        else try_du_parse_iso(raw.get("datetime_raw") or raw.get("datetime_list"))
    )
    end_dt = combine_local(end_date or start_date, et) if (start_date and et) else None

    place_name = _safe_strip(raw.get("place_name"))
    addr = []
    if raw.get("postalCode") or raw.get("addressLocality"):
        addr.append(
            f"{raw.get('postalCode') or ''} {raw.get('addressLocality') or ''}".strip()
        )
    if raw.get("streetAddress"):
        addr.append(str(raw.get("streetAddress")))
    location_address = "\n".join([a for a in addr if a]) or _safe_strip(
        raw.get("address_block_list")
    )

    tags = []
    if raw.get("category"):
        tags.append(str(raw["category"]))
    if raw.get("category_list") and raw["category_list"] not in tags:
        tags.append(str(raw["category_list"]))

    return {
        "source": "flohmarkt",
        "source_event_id": str(event_id),
        "source_url": url,
        "title": title,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "description": _safe_strip(raw.get("gut_zu_wissen"))
        or _safe_strip(raw.get("description")),
        "location_name": place_name,
        "location_address": location_address,
        "image_url": None,
        "tags": tags,
        "metadata": raw,
    }


def normalize_hamelnr(raw: Dict[str, Any]) -> Dict[str, Any]:
    detail = raw.get("detail") or {}
    url = _safe_strip(detail.get("url") or raw.get("url"))

    event_id = ensure_event_id("hamelnr", {"url": url})

    title = _safe_strip(detail.get("title")) or _safe_strip(
        (raw.get("list") or {}).get("title")
    )
    desc = _safe_strip(detail.get("description"))

    list_date_raw = _safe_strip((raw.get("list") or {}).get("date"))
    d = parse_german_long_date(list_date_raw or "")

    st, et = parse_time_range_bis(desc or "")

    fields = detail.get("fields") or {}
    datum = uhr = addr = ort = None
    for k, v in fields.items():
        k_low = (k or "").lower()
        if "datum" in k_low:
            datum = v
        elif "uhr" in k_low or "zeit" in k_low:
            uhr = v
        elif "adresse" in k_low:
            addr = v
        elif "ort" in k_low:
            ort = v

    if datum:
        d_start, d_end = parse_range_ddmmyyyy(datum)
        if d_start:
            d = d_start

    if uhr:
        st2, et2 = parse_time_range_bis(uhr)
        if st2 or et2:
            st, et = st2, et2
        else:
            st_single = parse_time_hhmm(uhr)
            if st_single:
                st = st_single

    start_dt = combine_local(d, st) if d else None
    end_dt = combine_local(d, et) if (d and et) else None

    cover = _safe_strip(detail.get("cover_image")) or _safe_strip(
        (raw.get("list") or {}).get("image")
    )
    tags = raw.get("badges") or []

    return {
        "source": "hamelnr",
        "source_event_id": str(event_id),
        "source_url": url,
        "title": title,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "description": desc,
        "location_name": _safe_strip(ort),
        "location_address": _safe_strip(addr),
        "image_url": cover,
        "tags": tags,
        "metadata": raw,
    }
