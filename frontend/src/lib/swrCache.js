// frontend/src/lib/swrCache.js
const PREFIX = "acu:swr:";
const TTL_MS = 5 * 60 * 1000;         // fresh for 5 min
const STALE_MS = 24 * 60 * 60 * 1000; // serve-stale up to 24h
const MAX_ENTRY_BYTES = 256 * 1024;   // skip caching payloads larger than ~256KB

// Evict the oldest acu:swr: entries (by stored ts) to free quota. Returns the
// number of entries removed.
function evictOldest(count = 1) {
  const entries = [];
  for (const k of Object.keys(localStorage)) {
    if (!k.startsWith(PREFIX)) continue;
    let ts = 0;
    try {
      ts = JSON.parse(localStorage.getItem(k))?.ts || 0;
    } catch {
      ts = 0; // unparseable entry — treat as oldest so it gets evicted first
    }
    entries.push({ k, ts });
  }
  entries.sort((a, b) => a.ts - b.ts);
  let removed = 0;
  for (const { k } of entries.slice(0, count)) {
    localStorage.removeItem(k);
    removed += 1;
  }
  return removed;
}

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
  let serialized;
  try {
    serialized = JSON.stringify({ ts: Date.now(), value });
  } catch {
    return; // non-serializable — skip caching
  }
  // Per-entry size cap: never store oversized payloads (e.g. unbounded
  // resource/composition lists) in localStorage.
  if (serialized.length > MAX_ENTRY_BYTES) return;

  try {
    localStorage.setItem(PREFIX + key, serialized);
  } catch (err) {
    // Likely QuotaExceededError. Evict the oldest entries and retry once.
    const isQuota =
      err && (err.name === "QuotaExceededError" || err.code === 22 || err.code === 1014);
    if (!isQuota) return; // storage disabled or other error — non-fatal
    if (evictOldest(5) === 0) return; // nothing to evict — give up quietly
    try {
      localStorage.setItem(PREFIX + key, serialized);
    } catch {
      // still failing — give up quietly
    }
  }
}

export function bustSwr(prefix = "") {
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith(PREFIX + prefix)) localStorage.removeItem(k);
  }
}
