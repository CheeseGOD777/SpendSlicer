/**
 * Shared-secret token plumbing for the API client.
 *
 * The backend accepts a token on every money-spending route via the
 * `X-SpendSlicer-Token` header or a `?token=` query parameter. Self-hosted users
 * usually leave `SPENDSLICER_AUTH_TOKEN` unset (the loopback-only default), in
 * which case everything here is a no-op and no header is sent.
 *
 * The desktop builds always set it: the launcher mints a random token per run
 * and hands it to the webview as `/app?token=...`. That closes a hole the
 * loopback bind alone does not — the server's CSRF check only guards
 * state-changing methods, so any page in the user's browser could otherwise
 * fire cross-origin GETs at the local port and spend real Cost Explorer money.
 * (CORS stops it reading the reply; it does not stop the request.)
 *
 * The token is captured once on load, kept in sessionStorage so a reload
 * inside the app window keeps working, then stripped from the visible URL so
 * it does not linger in history or in any copied link.
 */

const STORAGE_KEY = "spendslicer.token";

const readStored = () => {
  try {
    return sessionStorage.getItem(STORAGE_KEY) || "";
  } catch {
    // Private mode / blocked storage: fall back to the in-memory value.
    return "";
  }
};

const captureFromUrl = () => {
  let found = "";
  try {
    const url = new URL(window.location.href);
    found = url.searchParams.get("token") || "";
    if (found) {
      url.searchParams.delete("token");
      window.history.replaceState({}, "", url.pathname + url.search + url.hash);
    }
  } catch {
    /* non-browser context (tests) — nothing to capture */
  }
  return found;
};

let token = "";
if (typeof window !== "undefined") {
  token = captureFromUrl() || readStored();
  if (token) {
    try {
      sessionStorage.setItem(STORAGE_KEY, token);
    } catch {
      /* keep the in-memory copy */
    }
  }
}

/** Headers to merge into every API request. Empty when no token is in play. */
export const authHeaders = () => (token ? { "X-SpendSlicer-Token": token } : {});
