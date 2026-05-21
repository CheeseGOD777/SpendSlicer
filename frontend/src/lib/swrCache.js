// frontend/src/lib/swrCache.js
const PREFIX = "acu:swr:";
const TTL_MS = 5 * 60 * 1000;         // fresh for 5 min
const STALE_MS = 24 * 60 * 60 * 1000; // serve-stale up to 24h

export function readSwr(key) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const { ts, value } = JSON.parse(raw);
    const age = Date.now() - ts;
    if (age > STALE_MS) {
      localStorage.removeItem(PREFIX + key);
      return null;
    }
    return { value, fresh: age < TTL_MS };
  } catch {
    return null;
  }
}

export function writeSwr(key, value) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify({ ts: Date.now(), value }));
  } catch {
    // quota or disabled — non-fatal
  }
}

export function bustSwr(prefix = "") {
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith(PREFIX + prefix)) localStorage.removeItem(k);
  }
}
