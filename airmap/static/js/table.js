/**
 * Renders the "detected networks" table into a fixed container element and
 * handles click-to-sort on its headers. Sort state and the last-rendered
 * dataset are kept module-local (there's only ever one such table on the
 * page), so `renderNetworksTable` can be called again after a re-scan
 * without the caller needing to remember what column was sorted.
 */

const CONTAINER_ID = "networks-table-container";

const COLUMNS = [
  { key: "ssid", label: "SSID" },
  { key: "bssid", label: "BSSID" },
  { key: "channel", label: "Kanał" },
  { key: "band", label: "Pasmo" },
  { key: "signal", label: "Sygnał" },
  { key: "security", label: "Zabezpieczenia" },
];

let lastNetworks = [];
// Default: strongest signal first -- the single most useful ordering when
// you've just scanned and want to see what's actually usable nearby.
let sortColumn = "signal";
let sortAscending = false;

/** A single comparable number for "signal", regardless of which unit the
 * platform provided (dBm vs. percent) -- see the module docstring caveat:
 * this is only meaningful because one scan's rows all come from the same
 * platform, so they're never a dBm/percent mix within one table. */
function signalValue(network) {
  if (network.signal_dbm !== null && network.signal_dbm !== undefined) {
    return network.signal_dbm;
  }
  if (network.signal_percent !== null && network.signal_percent !== undefined) {
    return network.signal_percent;
  }
  return null;
}

function formatSignal(network) {
  const parts = [];
  if (network.signal_dbm !== null && network.signal_dbm !== undefined) {
    parts.push(`${network.signal_dbm} dBm`);
  }
  if (network.signal_percent !== null && network.signal_percent !== undefined) {
    parts.push(`${network.signal_percent}%`);
  }
  return parts.length ? parts.join(" / ") : "brak danych";
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function sortedNetworks() {
  // Sort a (network, originalIndex) pairing so equal keys keep their
  // original relative order (a stable sort) instead of jumping around
  // between re-renders.
  const withIndex = lastNetworks.map((network, index) => [network, index]);
  withIndex.sort(([a, ai], [b, bi]) => {
    let cmp;
    if (sortColumn === "signal") {
      const av = signalValue(a);
      const bv = signalValue(b);
      cmp = (av ?? -Infinity) - (bv ?? -Infinity);
    } else if (sortColumn === "channel") {
      cmp = a.channel - b.channel;
    } else {
      cmp = String(a[sortColumn] ?? "").localeCompare(String(b[sortColumn] ?? ""));
    }
    if (cmp === 0) {
      cmp = ai - bi;
    }
    return sortAscending ? cmp : -cmp;
  });
  return withIndex.map(([network]) => network);
}

function attachHeaderHandlers() {
  const container = document.getElementById(CONTAINER_ID);
  container.querySelectorAll("th[data-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (sortColumn === key) {
        sortAscending = !sortAscending;
      } else {
        sortColumn = key;
        sortAscending = true;
      }
      render();
    });
  });
}

function render() {
  const container = document.getElementById(CONTAINER_ID);

  if (!lastNetworks.length) {
    container.innerHTML = '<p class="empty-message">Brak danych, wykonaj pierwszy skan.</p>';
    return;
  }

  const rows = sortedNetworks();

  const headerHtml = COLUMNS.map((col) => {
    const arrow = sortColumn === col.key ? (sortAscending ? " ▲" : " ▼") : "";
    return `<th data-key="${col.key}">${col.label}${arrow}</th>`;
  }).join("");

  const rowsHtml = rows
    .map(
      (n) => `
    <tr>
      <td>${n.ssid ? escapeHtml(n.ssid) : "(ukryta sieć)"}</td>
      <td>${escapeHtml(n.bssid)}</td>
      <td>${n.channel}</td>
      <td>${escapeHtml(n.band)}</td>
      <td>${formatSignal(n)}</td>
      <td>${escapeHtml(n.security)}</td>
    </tr>`
    )
    .join("");

  container.innerHTML = `
    <table class="networks-table">
      <thead><tr>${headerHtml}</tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;

  attachHeaderHandlers();
}

/** Renders (or re-renders, keeping current sort) the networks table. */
export function renderNetworksTable(networks) {
  lastNetworks = networks;
  render();
}
