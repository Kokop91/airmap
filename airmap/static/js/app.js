/**
 * Entry point: wires the API, table, and chart modules together. This is
 * the only script tag in index.html (loaded as `type="module"`); it pulls
 * in the other files via native ES module imports, so no build step or
 * bundler is involved.
 */

import { ApiError, getAutoScanStatus, getLatestNetworks, postScan } from "./api.js";
import { renderChannelCharts } from "./chart.js";
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

document.getElementById("scan-button").addEventListener("click", handleScanClick);

loadLatest();
loadAutoScanStatus();
