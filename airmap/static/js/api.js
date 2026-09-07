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
    throw new ApiError(response.status, detail);
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
