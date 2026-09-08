/**
 * Phase 4 "Graf sieci" tab: a logical channel-similarity graph -- NOT a
 * physical connectivity graph (Airmap has no way to know what devices are
 * associated with which AP) -- rendered with vis.js Network (loaded
 * globally from the CDN script tag in index.html, so `vis` is just a
 * global, same pattern as Plotly in chart.js/history.js).
 *
 * Nodes are access points from the most recent scan; an edge means two APs
 * are close enough in channel to potentially interfere. The actual edge
 * rules live server-side (`graph.py`) -- this module only renders whatever
 * `GET /graph` returns.
 */

import { getGraph } from "./api.js";

const BAND_BORDER_COLORS = {
  "2.4GHz": "#3a7bd5",
  "5GHz": "#e8912d",
  "6GHz": "#4caf7d",
};
const DEFAULT_BORDER_COLOR = "#888888";

const EDGE_COLORS = {
  same_channel: "#c0392b",
  partial_overlap: "#e0a458",
};

let network = null;
let nodesDataSet = null;
let edgesDataSet = null;
let listenersAttached = false;
let latestNodesById = new Map();

function signalValue(node) {
  if (node.signal_dbm !== null && node.signal_dbm !== undefined) {
    return node.signal_dbm;
  }
  if (node.signal_percent !== null && node.signal_percent !== undefined) {
    return node.signal_percent;
  }
  return null;
}

function formatSignal(node) {
  const parts = [];
  if (node.signal_dbm !== null && node.signal_dbm !== undefined) {
    parts.push(`${node.signal_dbm} dBm`);
  }
  if (node.signal_percent !== null && node.signal_percent !== undefined) {
    parts.push(`${node.signal_percent}%`);
  }
  return parts.length ? parts.join(" / ") : "brak danych";
}

/** 0 (weak) .. 1 (strong), regardless of whether the platform reports dBm or percent. */
function normalizedSignal(node) {
  if (node.signal_percent !== null && node.signal_percent !== undefined) {
    return Math.max(0, Math.min(100, node.signal_percent)) / 100;
  }
  if (node.signal_dbm !== null && node.signal_dbm !== undefined) {
    const clamped = Math.max(-90, Math.min(-30, node.signal_dbm));
    return (clamped + 90) / 60;
  }
  return 0.5;
}

function signalFillColor(node) {
  const hue = normalizedSignal(node) * 120; // 0 = red (weak), 120 = green (strong)
  return `hsl(${hue}, 65%, 45%)`;
}

function nodeSize(node) {
  return 14 + normalizedSignal(node) * 24; // 14..38
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function toVisNode(n) {
  const borderColor = BAND_BORDER_COLORS[n.band] || DEFAULT_BORDER_COLOR;
  return {
    id: n.id,
    label: n.ssid || "(ukryta sieć)",
    shape: "dot",
    size: nodeSize(n),
    color: {
      background: signalFillColor(n),
      border: borderColor,
      highlight: { background: signalFillColor(n), border: borderColor },
      hover: { background: signalFillColor(n), border: borderColor },
    },
    borderWidth: 3,
    borderWidthSelected: 4,
    font: { color: "#1f2430" },
  };
}

function toVisEdge(e) {
  const isStrong = e.reason === "same_channel";
  return {
    from: e.source,
    to: e.target,
    width: isStrong ? 5 : 2,
    color: { color: EDGE_COLORS[e.reason] || "#999999" },
    dashes: !isStrong,
    smooth: false,
  };
}

function renderDetails(node) {
  const container = document.getElementById("graph-details");
  if (!node) {
    container.innerHTML = '<p class="empty-message">Kliknij węzeł, aby zobaczyć szczegóły.</p>';
    return;
  }
  container.innerHTML = `
    <dl class="graph-details-list">
      <dt>SSID</dt><dd>${node.ssid ? escapeHtml(node.ssid) : "(ukryta sieć)"}</dd>
      <dt>BSSID</dt><dd>${escapeHtml(node.bssid)}</dd>
      <dt>Kanał</dt><dd>${node.channel} (${escapeHtml(node.band)})</dd>
      <dt>Sygnał</dt><dd>${formatSignal(node)}</dd>
      <dt>Zabezpieczenia</dt><dd>${escapeHtml(node.security)}</dd>
    </dl>`;
}

function ensureNetworkCreated() {
  if (network) {
    return;
  }
  const container = document.getElementById("graph-container");
  nodesDataSet = new vis.DataSet([]);
  edgesDataSet = new vis.DataSet([]);
  network = new vis.Network(
    container,
    { nodes: nodesDataSet, edges: edgesDataSet },
    {
      nodes: { shape: "dot" },
      interaction: { hover: true, tooltipDelay: 150 },
      physics: { stabilization: { iterations: 150 } },
    }
  );
  network.on("click", (params) => {
    // Not `params.nodes` -- confirmed live (real clicks, not synthetic
    // events) that vis.js can report an empty `params.nodes` for a click
    // that's genuinely on a node, while `getNodeAt` on that same click's
    // own `pointer.canvas` correctly finds it. Asking directly is reliable
    // where trusting the event's own summary isn't.
    const nodeId = network.getNodeAt(params.pointer.canvas);
    renderDetails(nodeId ? latestNodesById.get(nodeId) : null);
  });
  // Physics is only needed to *find* a layout, not to keep simulating one
  // forever -- left running, nodes keep gently drifting indefinitely, which
  // fights the user every time they try to drag one to a resting spot.
  // Turning it off after stabilization doesn't affect dragging (vis.js moves
  // a dragged node directly regardless of the physics setting).
  network.on("stabilizationIterationsDone", () => {
    network.setOptions({ physics: false });
  });
}

function isGraphTabVisible() {
  return !document.getElementById("tab-panel-graph").classList.contains("hidden");
}

function showWarning(message) {
  const banner = document.getElementById("graph-warning");
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function clearWarning() {
  const banner = document.getElementById("graph-warning");
  banner.classList.add("hidden");
  banner.textContent = "";
}

function renderGraph(data) {
  ensureNetworkCreated();
  latestNodesById = new Map(data.nodes.map((n) => [n.id, n]));
  nodesDataSet.clear();
  nodesDataSet.add(data.nodes.map(toVisNode));
  edgesDataSet.clear();
  edgesDataSet.add(data.edges.map(toVisEdge));
  renderDetails(null);
  network.fit();
}

/**
 * Refetches `/graph` and, if the tab is currently visible, re-renders it.
 * Called on every tab activation *and* after every completed scan (mirrors
 * the Lista tab's refresh mechanism), so the graph never shows stale data
 * once the user actually looks at it -- but never touches vis.js while the
 * tab panel is `display:none`, since instantiating/resizing a Network into
 * a zero-size hidden container is a known way to end up with a broken
 * (0x0) layout that doesn't recover just by unhiding the panel later.
 */
export async function refreshGraph() {
  let data;
  try {
    data = await getGraph();
  } catch (err) {
    if (err.status === 404) {
      if (isGraphTabVisible()) {
        showWarning('Brak zapisanej historii. Wykonaj co najmniej jeden skan (przycisk "Skanuj teraz"), aby zobaczyć graf.');
        renderGraph({ nodes: [], edges: [] });
      }
      return;
    }
    if (isGraphTabVisible()) {
      showWarning(`Nie udało się pobrać grafu sieci: ${err.message}`);
    }
    return;
  }

  if (!isGraphTabVisible()) {
    return;
  }
  clearWarning();
  if (!data.nodes.length) {
    showWarning('Ostatni skan nie znalazł żadnych sieci -- brak danych do narysowania grafu.');
  }
  renderGraph(data);
}

function attachListeners() {
  if (listenersAttached) {
    return;
  }
  listenersAttached = true;
  window.addEventListener("resize", () => {
    if (network && isGraphTabVisible()) {
      network.redraw();
    }
  });
}

/** Called each time the Graf tab is activated: wires up (once) and reloads data (every time). */
export function initGraphTab() {
  attachListeners();
  refreshGraph();
}
