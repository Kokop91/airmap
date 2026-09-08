/**
 * Phase 5 "Historia" tab: a scan-range picker, a signal-over-time chart for
 * one chosen BSSID, and a networks-visible-over-time trend chart. Built on
 * top of the Phase 2 history endpoints plus two small Phase 5 aggregates
 * (`/history/counts`, `/history/networks`) that do the per-scan counting and
 * de-duplication server-side, so this module never has to reduce raw
 * per-reading data itself.
 */

import {
  getBssidHistory,
  getHistory,
  getHistoryCounts,
  getHistoryNetworks,
} from "./api.js";

// Fewer scans than this in the whole database and a timeline is not yet
// meaningful -- shown as a note, not as a reason to hide the (still real,
// just sparse) data underneath it.
const LOW_DATA_THRESHOLD = 3;

let currentLimit = 50; // null means "all scans"
let selectedBssid = null;
let countMode = "total"; // "total" | "band"
let currentScanList = []; // rows from /history/counts for the active range, chronological (oldest first)
let listenersAttached = false;

function parseLimitValue(value) {
  return value === "all" ? null : Number(value);
}

function formatTimestamp(iso) {
  return new Date(iso).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "medium" });
}

function scanCountLabel(n) {
  return n === 1 ? "skan" : "skanów";
}

function showWarning(message) {
  const banner = document.getElementById("history-warning");
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function clearWarning() {
  const banner = document.getElementById("history-warning");
  banner.classList.add("hidden");
  banner.textContent = "";
}

function renderScanList(scans) {
  const container = document.getElementById("history-scan-list");
  if (!scans.length) {
    container.innerHTML = '<p class="empty-message">Brak skanów w wybranym zakresie.</p>';
    return;
  }

  const rowsHtml = [...scans]
    .reverse() // most recent first in the list, independent of the charts' chronological order
    .map((s) => `<tr><td>#${s.id}</td><td>${formatTimestamp(s.timestamp)}</td><td>${s.total}</td></tr>`)
    .join("");

  container.innerHTML = `
    <table class="networks-table">
      <thead><tr><th>Skan</th><th>Data i godzina</th><th>Liczba sieci</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;
}

function populateBssidSelect(networks) {
  const select = document.getElementById("history-bssid-select");
  const previousSelection = selectedBssid;

  if (!networks.length) {
    select.innerHTML = '<option value="">(brak sieci w tym zakresie)</option>';
    select.disabled = true;
    selectedBssid = null;
    return;
  }

  select.disabled = false;
  select.innerHTML = networks
    .map((n) => `<option value="${n.bssid}">${n.ssid || "(ukryta sieć)"} — ${n.bssid}</option>`)
    .join("");

  const stillPresent = previousSelection && networks.some((n) => n.bssid === previousSelection);
  selectedBssid = stillPresent ? previousSelection : networks[0].bssid;
  select.value = selectedBssid;
}

/**
 * Aligns one BSSID's sparse readings to the full scan timeline: `null` for
 * any scan where that AP was not seen. Plotly leaves a gap at `null` points
 * (with `connectgaps: false`) instead of drawing a straight line across a
 * period the AP was out of range -- a real gap, not an interpolation.
 */
function buildSignalSeries(scanList, bssidRows) {
  const byScanId = new Map(bssidRows.map((r) => [r.scan_id, r]));
  const preferDbm = bssidRows.some((r) => r.signal_dbm !== null && r.signal_dbm !== undefined);
  const x = [];
  const y = [];
  for (const scan of scanList) {
    x.push(scan.timestamp);
    const reading = byScanId.get(scan.id);
    if (!reading) {
      y.push(null);
      continue;
    }
    const value = preferDbm ? reading.signal_dbm : reading.signal_percent;
    y.push(value ?? null);
  }
  return { x, y, unit: preferDbm ? "dBm" : "%" };
}

async function renderSignalChart() {
  const el = document.getElementById("history-signal-chart");

  if (!selectedBssid || !currentScanList.length) {
    Plotly.purge(el);
    el.innerHTML = '<p class="empty-message">Wybierz sieć, aby zobaczyć wykres sygnału.</p>';
    return;
  }

  let rows;
  try {
    rows = await getBssidHistory(selectedBssid);
  } catch (err) {
    Plotly.purge(el);
    el.innerHTML = `<p class="empty-message">Nie udało się pobrać historii sieci: ${err.message}</p>`;
    return;
  }

  el.innerHTML = "";
  const { x, y, unit } = buildSignalSeries(currentScanList, rows);

  Plotly.newPlot(
    el,
    [
      {
        x,
        y,
        type: "scatter",
        mode: "lines+markers",
        connectgaps: false,
        line: { color: "#3a7bd5" },
      },
    ],
    {
      xaxis: { title: "Czas skanu" },
      yaxis: { title: `Sygnał (${unit})` },
      margin: { t: 20 },
    },
    { responsive: true, displayModeBar: false }
  );
}

function renderCountChart() {
  const el = document.getElementById("history-count-chart");

  if (!currentScanList.length) {
    Plotly.purge(el);
    el.innerHTML = '<p class="empty-message">Brak danych w wybranym zakresie.</p>';
    return;
  }

  el.innerHTML = "";
  const x = currentScanList.map((s) => s.timestamp);
  const traces =
    countMode === "total"
      ? [
          {
            x,
            y: currentScanList.map((s) => s.total),
            name: "Wszystkie sieci",
            type: "scatter",
            mode: "lines+markers",
            line: { color: "#3a7bd5" },
          },
        ]
      : [
          { key: "count_2_4ghz", name: "2.4GHz", color: "#3a7bd5" },
          { key: "count_5ghz", name: "5GHz", color: "#e8912d" },
          { key: "count_6ghz", name: "6GHz", color: "#4caf7d" },
        ].map(({ key, name, color }) => ({
          x,
          y: currentScanList.map((s) => s[key]),
          name,
          type: "scatter",
          mode: "lines+markers",
          line: { color },
        }));

  Plotly.newPlot(
    el,
    traces,
    {
      xaxis: { title: "Czas skanu" },
      yaxis: { title: "Liczba sieci", rangemode: "tozero", dtick: 1 },
      margin: { t: 20 },
      showlegend: countMode === "band",
    },
    { responsive: true, displayModeBar: false }
  );
}

async function refreshHistory() {
  const loading = document.getElementById("history-loading");
  loading.classList.remove("hidden");
  try {
    await refreshHistoryData();
  } finally {
    loading.classList.add("hidden");
  }
}

async function refreshHistoryData() {
  clearWarning();

  let allScans;
  try {
    allScans = await getHistory();
  } catch (err) {
    showWarning(`Nie udało się pobrać historii skanów: ${err.message}`);
    return;
  }

  const totalScans = allScans.length;
  const info = document.getElementById("history-range-info");

  if (totalScans === 0) {
    showWarning(
      'Brak zapisanej historii. Wykonaj co najmniej jeden skan (przycisk "Skanuj teraz" w zakładce ' +
        '"Lista sieci"), aby zobaczyć dane.'
    );
    currentScanList = [];
    info.textContent = "";
    renderScanList([]);
    populateBssidSelect([]);
    renderCountChart();
    await renderSignalChart();
    return;
  }

  if (totalScans < LOW_DATA_THRESHOLD) {
    showWarning(
      `Za mało danych do sensownego timeline (${totalScans} ${scanCountLabel(totalScans)} w bazie). ` +
        "Wykonaj więcej skanów lub włącz tryb cykliczny (POST /scan/auto/start), aby zobaczyć trendy w czasie."
    );
  }

  let counts, networks;
  try {
    [counts, networks] = await Promise.all([
      getHistoryCounts(currentLimit),
      getHistoryNetworks(currentLimit),
    ]);
  } catch (err) {
    showWarning(`Nie udało się pobrać danych historii: ${err.message}`);
    return;
  }

  currentScanList = counts;
  info.textContent =
    currentLimit == null
      ? `Baza zawiera ${totalScans} ${scanCountLabel(totalScans)} — wyświetlono wszystkie.`
      : `Baza zawiera ${totalScans} ${scanCountLabel(totalScans)} — wyświetlono ostatnie ${counts.length}.`;

  renderScanList(counts);
  populateBssidSelect(networks);
  await renderSignalChart();
  renderCountChart();
}

function attachListeners() {
  if (listenersAttached) {
    return;
  }
  listenersAttached = true;

  document.getElementById("history-range-select").addEventListener("change", (e) => {
    currentLimit = parseLimitValue(e.target.value);
    refreshHistory();
  });

  document.getElementById("history-bssid-select").addEventListener("change", (e) => {
    selectedBssid = e.target.value || null;
    renderSignalChart();
  });

  document.querySelectorAll(".history-count-controls .toggle-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      countMode = btn.dataset.mode;
      document
        .querySelectorAll(".history-count-controls .toggle-button")
        .forEach((b) => b.classList.toggle("active", b === btn));
      renderCountChart();
    });
  });
}

/** Called each time the Historia tab is activated: wires up controls (once) and reloads data (every time). */
export function initHistoryTab() {
  attachListeners();
  refreshHistory();
}
