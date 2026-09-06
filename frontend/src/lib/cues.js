/* THE CUE RAISE — no figure on this board changes without the board saying why.
   A tiny pub/sub the shell subscribes to; every announcement carries a text
   equivalent and is rendered into an aria-live region. */

const listeners = new Set();
let current = { kind: "ready", what: "Board ready", detail: "", at: Date.now() };

export const KIND = {
  READY: "ready",     // steady state
  WORKING: "working", // a fetch is in flight
  STALE: "stale",     // cached figures are being shown
  FAULT: "fault",     // something failed
};

export function announce(kind, what, detail = "") {
  current = { kind, what, detail, at: Date.now() };
  listeners.forEach((fn) => fn(current));
}

export function subscribeCue(fn) {
  listeners.add(fn);
  fn(current);
  return () => listeners.delete(fn);
}

export function readCue() {
  return current;
}

/* Human phrasing for the two switches the user drives directly. */
export const cuePeriodChanged = (label) =>
  announce(KIND.WORKING, "Period changed", `Re-reading the board for ${label}.`);
export const cueProfileChanged = (profile) =>
  announce(KIND.WORKING, "Profile changed", `Now reading AWS profile ${profile}.`);
