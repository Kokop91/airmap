# Airmap

A cross-platform (Windows + Linux) WiFi analysis tool: scans nearby access
points, tracks channel occupancy and signal strength over time, and (in
later phases) will visualize this as a network graph and history dashboard.

This repo currently contains:

- **Phase 1** — `airmap` package: a stdlib-only WiFi scanning abstraction
  (`netsh` on Windows, `nmcli` on Linux) usable from the CLI.
- **Phase 2** — a FastAPI backend on top of Phase 1: on-demand scans,
  scheduled background scanning, and scan history persisted to SQLite.

No frontend yet (planned for a later phase).

## Requirements

- Python 3.10+
- **Windows**: `netsh` (built into Windows, no setup needed)
- **Linux**: [NetworkManager](https://networkmanager.dev/)'s `nmcli` on PATH
  (e.g. `sudo apt install network-manager`)

> The Linux (`nmcli`) scanning path is implemented from documented `nmcli`
> output format but has not been exercised against a live system — treat it
> as unverified until tested on a real Linux box. The Windows (`netsh`) path
> has been verified against a live system.

## Setup

```bash
git clone https://github.com/Kokop91/airmap.git
cd airmap
pip install -r requirements.txt
```

No virtualenv, database migration, or build step is required — the SQLite
database file is created automatically on first run.

## Usage

### CLI (Phase 1): one-off scan, no server

Runs a single scan and prints the detected networks as a table:

```bash
python -m airmap.main
```

### API server (Phase 2)

Start the dev server:

```bash
uvicorn airmap.app:app --reload
```

Then open **http://127.0.0.1:8000/docs** for the interactive Swagger UI, or
use `curl`. The SQLite database is created at `airmap/data/airmap.db` on
first request that needs it.

#### Endpoints

| Method & path | Description |
|---|---|
| `POST /scan` | Run one scan now, persist it, return the detected networks. |
| `GET /networks/latest` | Return the most recently *recorded* scan without scanning again. |
| `GET /history` | List every recorded scan (id + timestamp), most recent first. |
| `GET /history/{scan_id}` | Full detail (all networks) of one past scan. |
| `GET /history/network/{bssid}` | Every historical reading for one access point, oldest first — the basis for a future "signal over time" chart. |
| `POST /scan/auto/start` | Start (or restart at a new interval) periodic background scanning. Body: `{"interval_seconds": 15}` (minimum 10). |
| `POST /scan/auto/stop` | Stop periodic background scanning. |
| `GET /scan/auto/status` | Whether auto-scan is active, and at what interval. |

#### Example session

```bash
# Run one scan and see what it found
curl -X POST http://127.0.0.1:8000/scan

# List all recorded scans
curl http://127.0.0.1:8000/history

# Start scanning every 30 seconds in the background
curl -X POST http://127.0.0.1:8000/scan/auto/start \
  -H "Content-Type: application/json" \
  -d '{"interval_seconds": 30}'

# ...let it run for a while, then check the history has grown...
curl http://127.0.0.1:8000/history

# Stop background scanning
curl -X POST http://127.0.0.1:8000/scan/auto/stop

# Track one access point's signal over time (BSSID is case-insensitive)
curl http://127.0.0.1:8000/history/network/aa:bb:cc:dd:ee:ff
```

## Project layout

```
airmap/
├── models.py            # NetworkInfo dataclass + band/frequency/security helpers
├── base.py              # WifiScanner ABC, shared subprocess/error handling
├── linux_scanner.py     # LinuxWifiScanner (nmcli) — untested on a live system
├── windows_scanner.py   # WindowsWifiScanner (netsh) — verified live
├── factory.py           # get_scanner() -- picks the right scanner for the OS
├── main.py              # CLI runner (python -m airmap.main)
├── db.py                # SQLite schema + persistence (stdlib sqlite3)
├── scheduler.py         # asyncio-based periodic background scan loop
├── app.py               # FastAPI app and endpoints
└── data/                # airmap.db lives here (gitignored)
```

## Notes on design choices

- **SQLite via raw `sqlite3`**, not an ORM: the schema is two small, stable
  tables with one clear join query (per-BSSID history), so an ORM would add
  a dependency and an abstraction layer without real benefit at this scale.
- **`NetworkInfo` stays a plain dataclass**; the API layer uses separate
  Pydantic models (`app.py`) for its HTTP contract, since a dataclass
  produced internally by a scanner and a validated wire format are
  different concerns.
- **Auto-scan runs via `asyncio`** (not a thread or subprocess) as a single
  background task tracked in the FastAPI app's state; it does not survive a
  server restart, and a failure in one scan cycle is logged and does not
  stop the loop.
