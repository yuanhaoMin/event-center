import json
from datetime import date, datetime, timedelta

import streamlit as st

from db import (
    count_by_source,
    delete_all_events,
    get_conn,
    init_db,
    insert_events_ignore_duplicates,
    query_events,
)
from normalize import normalize_flohmarkt, normalize_hamelnr, normalize_siwikultur
from scrapers.hamelnr_scraper import scrape_hamelnr
from scrapers.meine_flohmarkt_termine_scraper import scrape_flohmarkt
from scrapers.siwikultur_scraper import scrape_siwikultur

st.set_page_config(page_title="Event Collector", layout="wide")


@st.cache_resource
def _db():
    conn = get_conn("events.sqlite3")
    init_db(conn)
    return conn


def fmt_dt(value: str | None) -> str:
    """
    Anzeigeformat:
    - Standard: YYYY-MM-DDTHH:MM
    - Wenn Uhrzeit 00:00: nur YYYY-MM-DD
    - entfernt Sekunden und Zeitzone
    """
    if not value:
        return "N/A"
    s = str(value).strip()

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
        dt = dt.replace(tzinfo=None, second=0, microsecond=0)
        if dt.hour == 0 and dt.minute == 0:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%dT%H:%M")
    except Exception:
        for sep in ["+", "-"]:
            if sep in s[10:] and ":" in s.split(sep, 1)[-1]:
                s = s.split(sep, 1)[0]
                break
        if len(s) >= 19 and s[16] == ":":
            s = s[:16]
        if len(s) >= 16 and s[11:16] == "00:00":
            return s[:10]
        if len(s) == 10:
            return s
        return s


def page_ingest():
    st.title("Events importieren")

    conn = _db()

    # =========================
    # 1) siwikultur
    # =========================
    st.subheader("siwikultur.de")
    colA, colB = st.columns([2, 1])
    with colA:
        siwi_date = st.date_input("Datum (Da=)", value=date.today(), key="siwi_date")
        siwi_url = f"https://www.siwikultur.de/termine/index.php?Da={siwi_date.isoformat()}&K=mit"
        st.code(siwi_url, language="text")
    with colB:
        siwi_run = st.button("siwikultur importieren", type="primary", key="btn_siwi")

    if siwi_run:
        with st.status("siwikultur wird abgerufen ...", expanded=False) as status:
            raw = scrape_siwikultur(siwi_url)
            unified = [normalize_siwikultur(x) for x in raw]
            res = insert_events_ignore_duplicates(conn, unified)
            status.update(
                label=f"siwikultur fertig: eingefügt {res['inserted']}, ignoriert (Duplikate) {res['ignored']}",
                state="complete",
            )

    st.divider()

    # =========================
    # 2) meine-flohmarkt-termine
    # =========================
    st.subheader("meine-flohmarkt-termine.de")
    colA, colB = st.columns([2, 1])
    with colA:
        fm_date = st.date_input("Suchdatum (query=)", value=date.today(), key="fm_date")
        floh_url = f"https://meine-flohmarkt-termine.de/suche?query={fm_date.strftime('%d.%m.%Y')}&country=de"
        st.code(floh_url, language="text")
        floh_limit = st.number_input("Limit", 1, 200, 40, key="fm_limit")
    with colB:
        fm_run = st.button("flohmarkt importieren", type="primary", key="btn_fm")

    if fm_run:
        with st.status("flohmarkt wird abgerufen ...", expanded=False) as status:
            raw = scrape_flohmarkt(floh_url, limit=int(floh_limit))
            unified = [
                normalize_flohmarkt(x)
                for x in raw
                if isinstance(x, dict) and not x.get("error")
            ]
            res = insert_events_ignore_duplicates(conn, unified)
            status.update(
                label=f"flohmarkt fertig: eingefügt {res['inserted']}, ignoriert (Duplikate) {res['ignored']}",
                state="complete",
            )

    st.divider()

    # =========================
    # 3) hamelnr
    # =========================
    st.subheader("hamelnr.de")
    colA, colB = st.columns([2, 1])
    with colA:
        ham_limit = st.number_input("Limit", 1, 200, 50, key="ham_limit")
        st.caption(
            "hamelnr wird aktuell über die Event-Listen-Seite gescraped (Limit steuert die Anzahl)."
        )
    with colB:
        ham_run = st.button("hamelnr importieren", type="primary", key="btn_ham")

    if ham_run:
        with st.status("hamelnr wird abgerufen ...", expanded=False) as status:
            raw = scrape_hamelnr(limit=int(ham_limit))
            unified = [
                normalize_hamelnr(x)
                for x in raw
                if isinstance(x, dict) and not x.get("error")
            ]
            res = insert_events_ignore_duplicates(conn, unified)
            status.update(
                label=f"hamelnr fertig: eingefügt {res['inserted']}, ignoriert (Duplikate) {res['ignored']}",
                state="complete",
            )

    st.divider()

    # =========================
    # DB stats
    # =========================
    st.subheader("Aktuelle Datenbank-Statistik")
    stats = count_by_source(conn)
    if stats:
        st.json([{"quelle": r["source"], "anzahl": r["cnt"]} for r in stats])
    else:
        st.info("Noch keine Daten in der Datenbank.")


def page_browse():
    st.title("Events anzeigen")

    conn = _db()

    col1, col2, col3, col4 = st.columns([1, 2, 1, 1])
    with col1:
        source = st.selectbox("Quelle", ["ALL", "siwikultur", "flohmarkt", "hamelnr"])
    with col2:
        q = st.text_input("Stichwortsuche (Titel/Beschreibung)", value="")
    with col3:
        start_from_date = st.date_input(
            "Startdatum (von)", value=None, key="start_from_date"
        )
    with col4:
        start_to_date = st.date_input("Enddatum (bis)", value=None, key="start_to_date")

    start_from = f"{start_from_date.isoformat()}T00:00" if start_from_date else None
    start_to = f"{start_to_date.isoformat()}T23:59" if start_to_date else None
    rows = query_events(
        conn,
        source=source,
        q=q or None,
        start_from=start_from or None,
        start_to=start_to or None,
        limit=500,
    )
    st.caption(f"{len(rows)} Treffer (max. 500 angezeigt)")

    for r in rows:
        title = r["title"] or "(ohne Titel)"
        when = fmt_dt(r["start_datetime"])
        sub = f"{r['source']} | {when}"
        with st.expander(f"{title} — {sub}", expanded=False):
            left, right = st.columns([2, 1])
            with left:
                st.write("**Quell-URL:**", r["source_url"])
                start_s = fmt_dt(r["start_datetime"])
                end_raw = r["end_datetime"]

                if end_raw:
                    st.write("**Zeit:**", start_s, "→", fmt_dt(end_raw))
                else:
                    st.write("**Zeit:**", start_s)
                st.write(
                    "**Ort:**",
                    r["location_name"] or "",
                    "\n\n",
                    r["location_address"] or "",
                )
                if r["description"]:
                    st.write("**Beschreibung:**")
                    st.write(r["description"])
            with right:
                if r["image_url"]:
                    st.image(r["image_url"], width="stretch")
                tags = json.loads(r["tags_json"] or "[]")
                if tags:
                    st.write("**Tags:**", ", ".join(tags))

            meta = json.loads(r["metadata_json"] or "{}")
            st.write("**Metadaten (roh):**")
            st.json(meta)


def page_admin():
    st.title("Administration / Gefährliche Aktionen")

    conn = _db()

    st.warning(
        "⚠️ Diese Aktion ist **nicht rückgängig** zu machen. Alle Events werden dauerhaft gelöscht."
    )

    stats = count_by_source(conn)
    total = sum(int(r["cnt"]) for r in stats) if stats else 0
    st.write(f"Aktuelle Anzahl Events in der Datenbank: **{total}**")

    st.divider()

    st.subheader("Alle Events löschen")

    confirm_text = st.text_input(
        "Bitte gib exakt **DELETE ALL** ein, um das Löschen zu bestätigen (Groß-/Kleinschreibung beachten):",
        value="",
        key="confirm_delete_all",
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        do_vacuum = st.checkbox(
            "Zusätzlich VACUUM ausführen (Speicher freigeben)", value=True
        )

    with col2:
        st.caption(
            "Hinweis: VACUUM kann je nach DB-Größe etwas dauern, reduziert aber die Dateigröße der SQLite-Datenbank."
        )

    disabled = confirm_text != "DELETE ALL"
    if st.button("🧨 Events-Datenbank leeren", type="primary", disabled=disabled):
        with st.status("Lösche Daten ...", expanded=False) as status:
            res = delete_all_events(conn, vacuum=do_vacuum)
            status.update(
                label=f"Fertig: {res['deleted']} Datensätze gelöscht.",
                state="complete",
            )
        st.success(
            "Die Events wurden gelöscht. Du kannst jetzt unter „Import“ neue Daten importieren."
        )


st.sidebar.title("Navigation")
page = st.sidebar.radio("Seite auswählen", ["Import", "Anzeige", "Administration"])

if page == "Import":
    page_ingest()
elif page == "Anzeige":
    page_browse()
else:
    page_admin()
