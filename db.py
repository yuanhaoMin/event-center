import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DB_PATH_DEFAULT = "events.sqlite3"


def get_conn(db_path: str = DB_PATH_DEFAULT) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")

    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            source_url TEXT,

            title TEXT,
            start_datetime TEXT,
            end_datetime TEXT,
            description TEXT,

            location_name TEXT,
            location_address TEXT,
            image_url TEXT,
            tags_json TEXT,
            metadata_json TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            UNIQUE(source, source_event_id)
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_datetime);"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);")
    conn.commit()


def insert_events_ignore_duplicates(
    conn: sqlite3.Connection, events: Iterable[Dict[str, Any]]
) -> Dict[str, int]:
    """
    events: unified event dicts (see normalize.py output)
    """
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    inserted = 0
    ignored = 0

    sql = """
    INSERT OR IGNORE INTO events (
        source, source_event_id, source_url,
        title, start_datetime, end_datetime, description,
        location_name, location_address, image_url,
        tags_json, metadata_json,
        created_at, updated_at
    ) VALUES (
        :source, :source_event_id, :source_url,
        :title, :start_datetime, :end_datetime, :description,
        :location_name, :location_address, :image_url,
        :tags_json, :metadata_json,
        :created_at, :updated_at
    );
    """

    for e in events:
        payload = {
            "source": e.get("source"),
            "source_event_id": e.get("source_event_id"),
            "source_url": e.get("source_url"),
            "title": e.get("title"),
            "start_datetime": e.get("start_datetime"),
            "end_datetime": e.get("end_datetime"),
            "description": e.get("description"),
            "location_name": e.get("location_name"),
            "location_address": e.get("location_address"),
            "image_url": e.get("image_url"),
            "tags_json": json.dumps(e.get("tags") or [], ensure_ascii=False),
            "metadata_json": json.dumps(e.get("metadata") or {}, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        cur = conn.execute(sql, payload)
        if cur.rowcount == 1:
            inserted += 1
        else:
            ignored += 1

    conn.commit()
    return {"inserted": inserted, "ignored": ignored}


def query_events(
    conn: sqlite3.Connection,
    source: Optional[str] = None,
    q: Optional[str] = None,
    start_from: Optional[str] = None,
    start_to: Optional[str] = None,
    limit: int = 500,
) -> List[sqlite3.Row]:
    where = []
    params: Dict[str, Any] = {"limit": limit}

    if source and source != "ALL":
        where.append("source = :source")
        params["source"] = source

    if q:
        where.append("(title LIKE :q OR description LIKE :q)")
        params["q"] = f"%{q}%"

    if start_from:
        where.append("(start_datetime IS NULL OR start_datetime >= :start_from)")
        params["start_from"] = start_from

    if start_to:
        where.append("(start_datetime IS NULL OR start_datetime <= :start_to)")
        params["start_to"] = start_to

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
    SELECT *
    FROM events
    {where_sql}
    ORDER BY
      CASE WHEN start_datetime IS NULL THEN 1 ELSE 0 END,
      start_datetime ASC,
      id DESC
    LIMIT :limit
    """
    return list(conn.execute(sql, params).fetchall())


def count_by_source(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT source, COUNT(*) AS cnt FROM events GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
    )


def delete_all_events(conn: sqlite3.Connection, vacuum: bool = True) -> Dict[str, int]:
    cur = conn.execute("SELECT COUNT(*) AS cnt FROM events;")
    before = int(cur.fetchone()["cnt"])

    conn.execute("DELETE FROM events;")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='events';")
    conn.commit()

    if vacuum:
        conn.execute("VACUUM;")
        conn.commit()

    return {"deleted": before}
