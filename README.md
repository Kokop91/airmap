# Airmap

A cross-platform (Windows + Linux) WiFi analysis tool: scans nearby access
points, tracks channel occupancy and signal strength over time, and (in
later phases) will visualize this as a network graph and history dashboard.

This repo currently contains:

- **Phase 1** — `airmap` package: a stdlib-only WiFi scanning abstraction
  (`netsh` on Windows, `nmcli` on Linux) usable from the CLI.
- **Phase 2** — a FastAPI backend on top of Phase 1: on-demand scans,
  scheduled background scanning, and scan history persisted to SQLite.
- **Phase 3** — a static HTML/CSS/JS frontend (no build step, no framework),
  served by the same FastAPI process: a table of currently detected
  networks and a channel-occupancy chart (Plotly.js).
- **Phase 5** — a "Historia" tab in the same frontend: a scan-range picker,
  a signal-over-time chart for one chosen access point, and a
  networks-visible-over-time trend chart, built on the scan history that's
  been collected since Phase 2.

A network topology graph (originally planned as "Phase 4") was never
built in this repo, so there is no third tab for it -- see the note at the
end of the Phase 5 section below.

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

Then open **http://127.0.0.1:8000/** for the frontend (see below), or
**http://127.0.0.1:8000/docs** for the interactive Swagger UI, or use
`curl` directly. The SQLite database is created at `airmap/data/airmap.db`
on first request that needs it.

#### Endpoints

| Method & path | Description |
|---|---|
| `POST /scan` | Run one scan now, persist it, return the detected networks. |
| `GET /networks/latest` | Return the most recently *recorded* scan without scanning again. |
| `GET /history` | List every recorded scan (id + timestamp), most recent first. |
| `GET /history/{scan_id}` | Full detail (all networks) of one past scan. |
| `GET /history/network/{bssid}` | Every historical reading for one access point, oldest first — the Phase 5 "signal over time" chart. |
| `GET /history/counts` | Per-scan network totals (overall + per band), oldest first — the Phase 5 "networks over time" chart. Optional `?limit=N` keeps only the most recent N scans. |
| `GET /history/networks` | Distinct networks (ssid, bssid, band, last seen) within the most recent `limit` scans — backs the Phase 5 BSSID picker. Optional `?limit=N`; omitted means all-time. |
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

### Frontend (Phase 3)

With the server running, open **http://127.0.0.1:8000/** in a browser:

- A table of the most recently recorded scan (SSID, BSSID, channel, band,
  signal, security). Click a column header to sort by it (defaults to
  strongest signal first). Shows "Brak danych, wykonaj pierwszy skan" if
  no scan has been recorded yet.
- Two channel-occupancy bar charts (2.4GHz and 5GHz — different channel
  numbering, so they're separate charts), showing how many networks share
  each channel; hover a bar to see which SSIDs are on it.
- A **"Skanuj teraz"** button that runs `POST /scan` and re-renders the
  table and charts in place, no page reload.
- A small badge showing whether auto-scan is currently active and at what
  interval (`GET /scan/auto/status`) — starting/stopping auto-scan itself
  is still done via `/docs` or `curl`, not from this page.

The frontend is plain HTML/CSS/JS (`airmap/static/`), loaded as native ES
modules — no npm, no bundler, no framework. Plotly.js is loaded from its
CDN in `index.html`.

### History / timeline (Phase 5)

A second tab, **"Historia"**, next to "Lista sieci":

- **Zakres czasu** — a range picker (last 10/25/50/100 scans, or all) plus
  a list of the scans in that range with their timestamps and network
  counts. Defaults to the last 50 scans so a database with hundreds of
  scans doesn't have to load (or chart) all of them at once.
- **Siła sygnału w czasie** — pick one network (SSID + BSSID, from a
  dropdown scoped to the selected range) and see its signal strength
  (dBm, or % if that's all the platform reports) plotted over the scans in
  range. A scan where that AP wasn't seen leaves a genuine gap in the
  line (`connectgaps: false` over a `null` y-value) rather than
  interpolating or dropping to zero.
- **Liczba widocznych sieci w czasie** — total detected networks per scan,
  toggleable between one combined line and a per-band (2.4/5/6GHz)
  breakdown.
- With fewer than 3 scans recorded, a banner says so explicitly instead of
  rendering a timeline that isn't meaningful yet — the sparse real data
  underneath (even a single point) is still shown, not hidden.

A graph-playback scrubber (replaying the Phase 4 network graph over time)
was scoped as optional for this phase, contingent on Phase 4 existing.
Phase 4 (the network topology graph, `graph.js` / `/graph`) was never
actually implemented in this repo — building it was out of scope for a
history/timeline phase, so the scrubber was skipped along with it. The
history tab was added directly alongside the existing single view instead
of as a third tab.

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
├── app.py               # FastAPI app, endpoints, and static frontend mount
├── data/                # airmap.db lives here (gitignored)
└── static/              # Phase 3 frontend (plain HTML/CSS/JS, no build step)
    ├── index.html
    ├── css/style.css
    └── js/
        ├── api.js       # fetch wrappers for the backend endpoints
        ├── table.js     # renders + sorts the networks table
        ├── chart.js     # Plotly channel-occupancy charts
        ├── history.js   # Phase 5: range picker + timeline charts
        └── app.js       # entry point, wires the above together (incl. tabs)
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
