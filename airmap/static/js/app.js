/**
 * Entry point: wires the API, table, and chart modules together. This is
 * the only script tag in index.html (loaded as `type="module"`); it pulls
 * in the other files via native ES module imports, so no build step or
 * bundler is involved.
 */

import { ApiError, getAutoScanStatus, getLatestNetworks, postScan } from "./api.js";
import { renderChannelCharts } from "./chart.js";
import { initGraphTab, refreshGraph } from "./graph.js";
import { initHistoryTab } from "./history.js";
import { renderNetworksTable } from "./table.js";

function showError(message) {
  const banner = document.getElementById("error-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function clearError() {
  const banner = document.getElementById("error-banner");
  banner.classList.add("hidden");
  banner.textContent = "";
}

function renderNetworks(networks) {
  renderNetworksTable(networks);
  renderChannelCharts(networks);
  // Same mechanism as the table/charts above: re-render after every load or
  // scan. refreshGraph() itself no-ops the actual vis.js draw when the Graf
  // tab isn't the visible one, so this is cheap when it's not being looked at.
  refreshGraph();
}

async function loadLatest() {
  try {
    const scan = await getLatestNetworks();
    renderNetworks(scan.networks);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      // No scan has ever been recorded -- not an error, just an empty state.
      renderNetworks([]);
    } else {
      showError(`Nie udało się pobrać ostatniego skanu: ${err.message}`);
      renderNetworks([]);
    }
  }
}

async function loadAutoScanStatus() {
  const badge = document.getElementById("auto-scan-status");
  try {
    const status = await getAutoScanStatus();
    badge.textContent = status.active
      ? `Auto-skan: aktywny (co ${status.interval_seconds}s)`
      : "Auto-skan: nieaktywny";
    badge.classList.toggle("active", status.active);
  } catch {
    badge.textContent = "Auto-skan: status nieznany";
    badge.classList.remove("active");
  }
}

async function handleScanClick() {
  const button = document.getElementById("scan-button");
  const spinner = document.getElementById("scan-spinner");

  clearError();
  button.disabled = true;
  spinner.classList.remove("hidden");
  try {
    const scan = await postScan();
    renderNetworks(scan.networks);
  } catch (err) {
    showError(`Skan nie powiódł się: ${err.message}`);
  } finally {
    button.disabled = false;
    spinner.classList.add("hidden");
  }
}

const TABS = [
  { buttonId: "tab-btn-list", panelId: "tab-panel-list" },
  { buttonId: "tab-btn-graph", panelId: "tab-panel-graph" },
  { buttonId: "tab-btn-history", panelId: "tab-panel-history" },
];

function activateTab(targetButtonId) {
  for (const { buttonId, panelId } of TABS) {
    const isActive = buttonId === targetButtonId;
    document.getElementById(buttonId).classList.toggle("active", isActive);
    document.getElementById(buttonId).setAttribute("aria-selected", String(isActive));
    document.getElementById(panelId).classList.toggle("hidden", !isActive);
  }
  // Reloaded on every activation (not just the first) so switching back in
  // always reflects any scans taken while on another tab.
  if (targetButtonId === "tab-btn-graph") {
    initGraphTab();
  } else if (targetButtonId === "tab-btn-history") {
    initHistoryTab();
  }
}

for (const { buttonId } of TABS) {
  document.getElementById(buttonId).addEventListener("click", () => activateTab(buttonId));
}

document.getElementById("scan-button").addEventListener("click", handleScanClick);

loadLatest();
loadAutoScanStatus();
