"""FastAPI application: on-demand scans, scan history, and an auto-scan mode.

Run with: `uvicorn airmap.app:app --reload`
Then browse to http://127.0.0.1:8000/docs for the interactive Swagger UI.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db
from .base import ScanParseError, UnsupportedPlatformError, WifiScanner
from .factory import get_scanner
from .models import NetworkInfo
from .scheduler import MIN_INTERVAL_SECONDS, AutoScanScheduler

logger = logging.getLogger(__name__)


# --- Pydantic response/request models -----------------------------------
#
# Kept separate from the Phase 1 `NetworkInfo` dataclass rather than
# converting it to a Pydantic model. `NetworkInfo` is an internal domain
# object produced by the scanners and is explicitly out of bounds for
# modification this phase; a parallel Pydantic schema for the HTTP contract
# avoids touching it at all, and it's arguably the cleaner split anyway --
# the API's shape (e.g. no per-reading `timestamp`, since that lives on the
# parent scan) already differs slightly from `NetworkInfo`'s.


class NetworkReadingOut(BaseModel):
    """One access point as recorded in a scan (mirrors `NetworkInfo` minus `timestamp`)."""

    ssid: str
    bssid: str
    channel: int
    frequency_mhz: int
    band: str
    signal_dbm: int | None
    signal_percent: int | None
    security: str


class ScanSummaryOut(BaseModel):
    """One row of `GET /history`: enough to build a timeline list."""

    id: int
    timestamp: datetime


class ScanDetailOut(BaseModel):
    """Full detail of one scan: its timestamp plus every network found."""

    id: int
    timestamp: datetime
    networks: list[NetworkReadingOut]


class BssidHistoryEntryOut(BaseModel):
    """One historical reading of a specific BSSID, for the signal-over-time view."""

    scan_id: int
    timestamp: datetime
    ssid: str
    channel: int
    frequency_mhz: int
    band: str
    signal_dbm: int | None
    signal_percent: int | None
    security: str


class AutoScanStartRequest(BaseModel):
    interval_seconds: float = Field(
        ge=MIN_INTERVAL_SECONDS,
        description=f"Seconds between automatic scans (minimum {MIN_INTERVAL_SECONDS}).",
    )


class AutoScanStatusOut(BaseModel):
    active: bool
    interval_seconds: float | None


# --- App setup ------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    try:
        app.state.scanner = get_scanner()
    except UnsupportedPlatformError as exc:
        logger.error("no WiFi scanner available on this platform: %s", exc)
        app.state.scanner = None
    app.state.auto_scanner = AutoScanScheduler()
    yield
    await app.state.auto_scanner.stop()


app = FastAPI(title="Airmap", version="0.2.0", lifespan=lifespan)

# Wide-open for any localhost port: the Phase 3 frontend will be a separate
# dev-server process on its own port, and this is a single-machine local
# dev tool with no auth, so there's no origin to restrict beyond "not the
# public internet".
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _to_reading_out(network: NetworkInfo) -> NetworkReadingOut:
    return NetworkReadingOut(
        ssid=network.ssid,
        bssid=network.bssid,
        channel=network.channel,
        frequency_mhz=network.frequency_mhz,
        band=network.band,
        signal_dbm=network.signal_dbm,
        signal_percent=network.signal_percent,
        security=network.security,
    )


def _require_scanner() -> WifiScanner:
    scanner = app.state.scanner
    if scanner is None:
        raise HTTPException(503, "No WiFi scanner is available on this platform.")
    if not scanner.is_available():
        raise HTTPException(
            503, f"Required system tool ({scanner.TOOL_NAME}) was not found on PATH."
        )
    return scanner


def _run_scan_and_persist(scanner: WifiScanner) -> tuple[int, datetime, list[NetworkInfo]]:
    """Run one scan and store it. Shared by `POST /scan` and the auto-scan loop.

    The scan's own timestamp is captured *before* invoking the scanner, so a
    scan that finds zero networks (a normal outcome, not an error) still
    gets a sensible timestamp instead of needing special-case handling.
    """
    started_at = datetime.now(timezone.utc)
    networks = scanner.scan()  # raises only ScanParseError
    scan_id = db.insert_scan(networks, started_at)
    return scan_id, started_at, networks


# --- Endpoints --------------------------------------------------------------


@app.post("/scan", response_model=ScanDetailOut)
def scan_now() -> ScanDetailOut:
    """Perform one scan right now and persist it."""
    scanner = _require_scanner()
    try:
        scan_id, timestamp, networks = _run_scan_and_persist(scanner)
    except ScanParseError as exc:
        raise HTTPException(503, f"Scan failed: {exc}") from exc
    return ScanDetailOut(
        id=scan_id, timestamp=timestamp, networks=[_to_reading_out(n) for n in networks]
    )


@app.get("/networks/latest", response_model=ScanDetailOut)
def get_latest_networks() -> ScanDetailOut:
    """Return the most recently *recorded* scan, without scanning again."""
    scan_id = db.get_latest_scan_id()
    if scan_id is None:
        raise HTTPException(404, "No scans recorded yet. Run POST /scan first.")
    detail = db.get_scan_detail(scan_id)
    assert detail is not None  # scan_id was just read from the same table
    return ScanDetailOut(**detail)


@app.get("/history", response_model=list[ScanSummaryOut])
def get_history() -> list[ScanSummaryOut]:
    """List every recorded scan (id + timestamp only), most recent first."""
    return [ScanSummaryOut(**row) for row in db.get_all_scans()]


@app.get("/history/{scan_id}", response_model=ScanDetailOut)
def get_history_detail(scan_id: int) -> ScanDetailOut:
    """Full detail (every detected network) of one specific past scan."""
    detail = db.get_scan_detail(scan_id)
    if detail is None:
        raise HTTPException(404, f"No scan with id {scan_id}.")
    return ScanDetailOut(**detail)


@app.get("/history/network/{bssid}", response_model=list[BssidHistoryEntryOut])
def get_bssid_history(bssid: str) -> list[BssidHistoryEntryOut]:
    """Every historical reading of one access point, oldest first.

    `bssid` is lower-cased before querying since both scanners normalize
    stored BSSIDs to lowercase, so lookups are case-insensitive for callers.
    """
    rows = db.get_bssid_history(bssid.lower())
    return [BssidHistoryEntryOut(**row) for row in rows]


@app.post("/scan/auto/start", response_model=AutoScanStatusOut)
async def start_auto_scan(request: AutoScanStartRequest) -> AutoScanStatusOut:
    """Start (or restart, at a new interval) the periodic background scan."""
    scanner = _require_scanner()
    scheduler: AutoScanScheduler = app.state.auto_scanner
    try:
        await scheduler.start(
            request.interval_seconds, lambda: _run_scan_and_persist(scanner)
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return AutoScanStatusOut(active=scheduler.is_running, interval_seconds=scheduler.interval_seconds)


@app.post("/scan/auto/stop", response_model=AutoScanStatusOut)
async def stop_auto_scan() -> AutoScanStatusOut:
    """Stop the periodic background scan, if running."""
    scheduler: AutoScanScheduler = app.state.auto_scanner
    await scheduler.stop()
    return AutoScanStatusOut(active=scheduler.is_running, interval_seconds=scheduler.interval_seconds)


@app.get("/scan/auto/status", response_model=AutoScanStatusOut)
def get_auto_scan_status() -> AutoScanStatusOut:
    """Whether the periodic background scan is active, and at what interval."""
    scheduler: AutoScanScheduler = app.state.auto_scanner
    return AutoScanStatusOut(active=scheduler.is_running, interval_seconds=scheduler.interval_seconds)
