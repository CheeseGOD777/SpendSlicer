// frontend/src/lib/ceMeter.js
const listeners = new Set();
let total = { calls: 0, costUsd: 0 };

export function recordCe(meta) {
  if (!meta || !meta.ceCalls) return;
  total = { calls: total.calls + meta.ceCalls, costUsd: total.costUsd + meta.ceCostUsd };
  listeners.forEach((fn) => fn(total));
}

export function subscribeCe(fn) {
  listeners.add(fn);
  fn(total);
  return () => listeners.delete(fn);
}

export function resetCe() {
  total = { calls: 0, costUsd: 0 };
  listeners.forEach((fn) => fn(total));
}
