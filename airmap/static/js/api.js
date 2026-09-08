/**
 * Thin fetch wrapper for the Airmap backend. Same-origin (the frontend is
 * served by the same FastAPI process), so no base URL or CORS handling is
 * needed here -- relative paths are enough.
 */

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Normalizes a FastAPI error body's `detail` to a plain string.
 * On a 422, `detail` is an array of pydantic error objects (not a string) --
 * passed straight through, `new Error(detail)` would stringify it via
 * Array.prototype.toString into the useless "[object Object]". */
function detailToMessage(detail) {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((e) => (e && typeof e === "object" && e.msg) || JSON.stringify(e)).join("; ");
  }
  return JSON.stringify(detail);
}

async function request(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body && body.detail) {
        detail = body.detail;
      }
    } catch {
      // Response wasn't JSON (e.g. a raw 500 page) -- keep the status text.
    }
    throw new ApiError(response.status, detailToMessage(detail));
  }
  return response.json();
}

/** GET /networks/latest -- throws ApiError(404) if no scan has ever been recorded. */
export function getLatestNetworks() {
  return request("/networks/latest");
}

/** POST /scan -- runs a scan now; can take several seconds. */
export function postScan() {
  return request("/scan", { method: "POST" });
}

/** GET /scan/auto/status */
export function getAutoScanStatus() {
  return request("/scan/auto/status");
}

/** GET /history -- every recorded scan (id + timestamp), most recent first. */
export function getHistory() {
  return request("/history");
}

/** GET /history/counts -- per-scan network totals, oldest first. `limit` (optional) keeps only the most recent N scans. */
export function getHistoryCounts(limit) {
  const qs = limit != null ? `?limit=${encodeURIComponent(limit)}` : "";
  return request(`/history/counts${qs}`);
}

/** GET /history/networks -- distinct networks seen in the most recent `limit` scans (all scans if omitted). */
export function getHistoryNetworks(limit) {
  const qs = limit != null ? `?limit=${encodeURIComponent(limit)}` : "";
  return request(`/history/networks${qs}`);
}

/** GET /history/network/{bssid} -- every historical reading of one access point, oldest first. */
export function getBssidHistory(bssid) {
  return request(`/history/network/${encodeURIComponent(bssid)}`);
}

/** GET /graph -- logical channel-similarity graph for the most recently recorded scan. */
export function getGraph() {
  return request("/graph");
}
