"""SQLite persistence for scan history.

Uses the stdlib `sqlite3` module directly rather than an ORM (SQLAlchemy /
SQLModel) -- see the Phase 2 summary for the full rationale. In short: the
schema is two small, stable tables with one clear join query
(`get_bssid_history`), there is no need for migrations or a query builder at
this scale, and staying on stdlib keeps the persistence layer trivial to
read end-to-end in one file.

Each function opens and closes its own short-lived connection rather than
sharing one across the process. FastAPI serves sync endpoints from a
threadpool and the auto-scan background loop runs its blocking work via
`asyncio.to_thread`, so multiple threads can call into this module
concurrently; per-call connections sidestep sqlite3's "single connection,
single thread" constraint without needing an explicit connection pool.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import NetworkInfo

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS network_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    ssid TEXT NOT NULL,
    bssid TEXT NOT NULL,
    channel INTEGER NOT NULL,
    frequency_mhz INTEGER NOT NULL,
    band TEXT NOT NULL,
    signal_dbm INTEGER,
    signal_percent INTEGER,
    security TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_network_readings_bssid ON network_readings(bssid);
CREATE INDEX IF NOT EXISTS idx_network_readings_scan_id ON network_readings(scan_id);
"""


def get_db_path() -> Path:
    """Location of the SQLite file: `airmap/data/airmap.db`."""
    return Path(__file__).parent / "data" / "airmap.db"


@contextlib.contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Open a connection with sane pragmas, closing it on exit.

    WAL mode lets readers (GET endpoints) proceed without blocking on a
    writer (an in-progress scan insert) and vice versa, which matters once
    the auto-scan loop is writing every few seconds while the API is also
    being queried.
    """
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create the schema if it doesn't already exist. Safe to call every startup."""
    with _connection() as conn, conn:
        conn.executescript(_SCHEMA)


def insert_scan(networks: list[NetworkInfo], timestamp: datetime) -> int:
    """Persist one completed scan (its timestamp + every detected network).

    `timestamp` is passed in explicitly (the moment the scan was *initiated*)
    rather than derived from `networks[0].timestamp`, so that a scan which
    finds zero networks -- a normal, expected outcome -- still gets a correct
    timestamp instead of needing special-case handling.
    """
    with _connection() as conn, conn:
        cursor = conn.execute(
            "INSERT INTO scans (timestamp) VALUES (?)", (timestamp.isoformat(),)
        )
        scan_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO network_readings
                (scan_id, ssid, bssid, channel, frequency_mhz, band,
                 signal_dbm, signal_percent, security)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    scan_id,
                    n.ssid,
                    n.bssid,
                    n.channel,
                    n.frequency_mhz,
                    n.band,
                    n.signal_dbm,
                    n.signal_percent,
                    n.security,
                )
                for n in networks
            ],
        )
        return scan_id


def get_all_scans() -> list[dict[str, Any]]:
    """All recorded scans (id + timestamp only), most recent first."""
    with _connection() as conn:
        rows = conn.execute("SELECT id, timestamp FROM scans ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]


def get_latest_scan_id() -> int | None:
    """Id of the most recently recorded scan, or None if the db is empty."""
    with _connection() as conn:
        row = conn.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"] if row is not None else None


def get_scan_detail(scan_id: int) -> dict[str, Any] | None:
    """One scan's timestamp plus every network reading from it, or None if not found."""
    with _connection() as conn:
        scan_row = conn.execute(
            "SELECT id, timestamp FROM scans WHERE id = ?", (scan_id,)
        ).fetchone()
        if scan_row is None:
            return None
        reading_rows = conn.execute(
            """
            SELECT ssid, bssid, channel, frequency_mhz, band,
                   signal_dbm, signal_percent, security
            FROM network_readings
            WHERE scan_id = ?
            ORDER BY id
            """,
            (scan_id,),
        ).fetchall()
        return {
            "id": scan_row["id"],
            "timestamp": scan_row["timestamp"],
            "networks": [dict(row) for row in reading_rows],
        }


def get_scan_counts(limit: int | None = None) -> list[dict[str, Any]]:
    """Per-scan network totals (overall + per band), oldest first.

    Aggregated in SQL, not Python: the Phase 5 "networks over time" chart
    only needs one row per scan, so summing here keeps the response small
    even once `scans` grows into the hundreds. `limit`, when given, keeps
    only the most recent N scans (still returned oldest-first, for charting
    left-to-right).
    """
    query = """
        SELECT s.id AS id, s.timestamp AS timestamp,
               COUNT(r.id) AS total,
               SUM(CASE WHEN r.band = '2.4GHz' THEN 1 ELSE 0 END) AS count_2_4ghz,
               SUM(CASE WHEN r.band = '5GHz' THEN 1 ELSE 0 END) AS count_5ghz,
               SUM(CASE WHEN r.band = '6GHz' THEN 1 ELSE 0 END) AS count_6ghz
        FROM scans s
        LEFT JOIN network_readings r ON r.scan_id = s.id
        GROUP BY s.id
        ORDER BY s.id DESC
    """
    with _connection() as conn:
        if limit is not None:
            rows = conn.execute(query + " LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute(query).fetchall()
    result = [dict(row) for row in rows]
    result.reverse()
    return result


def get_distinct_networks(limit: int | None = None) -> list[dict[str, Any]]:
    """Distinct (ssid, bssid) pairs seen in the most recent `limit` scans.

    `limit=None` means "across all recorded history". Relies on SQLite's
    documented bare-column-with-MAX() behavior: `ssid` and `band` come from
    the same row that produced `MAX(timestamp)` within each bssid group, so
    they reflect that network's most recent reading rather than an arbitrary
    one (matters if an SSID were ever renamed on the same AP).
    """
    scan_filter = ""
    params: tuple[Any, ...] = ()
    if limit is not None:
        scan_filter = "WHERE s.id IN (SELECT id FROM scans ORDER BY id DESC LIMIT ?)"
        params = (limit,)
    query = f"""
        SELECT r.ssid AS ssid, r.bssid AS bssid, r.band AS band,
               MAX(s.timestamp) AS last_seen
        FROM network_readings r
        JOIN scans s ON s.id = r.scan_id
        {scan_filter}
        GROUP BY r.bssid
        ORDER BY last_seen DESC
    """
    with _connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_bssid_history(bssid: str) -> list[dict[str, Any]]:
    """Every reading for one BSSID across all scans, oldest first.

    This is the query the Phase 5 "signal over time" chart is built on:
    one row per (scan, this BSSID) pair, so a caller can plot signal vs.
    scan timestamp directly without any further joining.
    """
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT s.id AS scan_id, s.timestamp AS timestamp,
                   r.ssid, r.channel, r.frequency_mhz, r.band,
                   r.signal_dbm, r.signal_percent, r.security
            FROM network_readings r
            JOIN scans s ON s.id = r.scan_id
            WHERE r.bssid = ?
            ORDER BY s.timestamp ASC
            """,
            (bssid,),
        ).fetchall()
        return [dict(row) for row in rows]
