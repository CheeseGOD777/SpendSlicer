# Plan 3 — Frontend Bug Fixes + UX Polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the frontend race conditions, duplicate API calls, and missing error/loading states; show the per-request CE cost from Plan 1; ship the named per-resource view from Plan 2.

**Architecture:** Add `AbortController` to `useAsyncData`; introduce a thin in-memory + localStorage SWR cache; debounce filter changes; render the `X-CE-Calls-Spent` header into a footer badge; code-split Recharts per route.

**Tech Stack:** React 18, Vite 5, Recharts 2.

**Prerequisites:** Plan 1 (for `X-CE-Calls-Spent` header). Independent of Plan 2.

---

## Files affected

**Create:**
- `frontend/src/hooks/useAsyncData.js` — extract + fix the hook
- `frontend/src/hooks/useDebounced.js`
- `frontend/src/lib/swrCache.js` — minimal localStorage SWR layer
- `frontend/src/components/CostBadge.jsx` — "this session cost $0.04" footer
- `frontend/src/lib/ceMeter.js` — captures `X-CE-Calls-Spent` from response headers

**Modify:**
- `frontend/src/App.jsx` — wire new hook + cache; fix `api.context` call; lazy-load chart components; dedupe resources fetch
- `frontend/src/api.js` — return both `data` and `meta` (cost headers); use single AbortController per call
- `frontend/src/styles.css` — fix mobile table layout; better skeleton loaders
- `frontend/vite.config.js` — split-chunks for recharts
- `frontend/package.json` — remove unused `puppeteer`

---

## Task 1: AbortController-aware `useAsyncData`

**Files:**
- Create: `frontend/src/hooks/useAsyncData.js`
- Modify: `frontend/src/App.jsx` lines 27–40 (remove inline hook, import from new file)

Current bug: rapid prop changes leave the older fetch in flight; whichever resolves last wins. Replace with a per-effect `AbortController` so older fetches both stop wasting bytes and stop writing to state.

- [ ] **Step 1: Write the hook**

```js
// frontend/src/hooks/useAsyncData.js
import { useEffect, useRef, useState } from "react";

/**
 * loader receives an AbortSignal and should pass it to fetch().
 * State only updates from the latest in-flight request.
 */
export function useAsyncData(loader, deps) {
  const [state, setState] = useState({ loading: true, error: "", data: null, meta: null });
  const inFlight = useRef(null);

  useEffect(() => {
    // Cancel any prior in-flight request for this hook instance.
    inFlight.current?.abort();
    const ctrl = new AbortController();
    inFlight.current = ctrl;

    setState((prev) => ({ ...prev, loading: true, error: "" }));

    loader(ctrl.signal)
      .then(({ data, meta }) => {
        if (ctrl.signal.aborted) return;
        setState({ loading: false, error: "", data, meta: meta || null });
      })
      .catch((err) => {
        if (ctrl.signal.aborted || err?.name === "AbortError") return;
        setState((prev) => ({
          loading: false,
          error: err?.message || "Failed",
          data: prev.data,
          meta: prev.meta,
        }));
      });

    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
```

- [ ] **Step 2: Update `App.jsx` to import it + thread the signal**

In `App.jsx`, remove lines 27–40 (the inline `useAsyncData`) and add:

```js
import { useAsyncData } from "./hooks/useAsyncData";
```

Every call site already passes a `loader` callback. They need to thread `signal` through:

```js
// before
const data = useAsyncData(() => api.summary(profile, period), [profile, period]);

// after
const data = useAsyncData((signal) => api.summary(profile, period, { signal }), [profile, period]);
```

Mechanically: search `useAsyncData(()` in `App.jsx`, change every `() => api.X(...)` to `(signal) => api.X(..., { signal })`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useAsyncData.js frontend/src/App.jsx
git commit -m "fix(frontend): AbortController in useAsyncData — kills race conditions"
```

---

## Task 2: `api.js` accepts signal + returns `{data, meta}`

**Files:**
- Modify: `frontend/src/api.js`

Pass through `signal` for cancellation, and surface response headers (`X-CE-Calls-Spent`, `X-CE-Estimated-Cost-USD`) as `meta` so the UI can render them.

- [ ] **Step 1: Replace `api.js`**

```js
// frontend/src/api.js
const toParams = (params) => {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  return q.toString();
};

const getJson = async (path, params = {}, opts = {}) => {
  const qs = toParams(params);
  const res = await fetch(`${path}${qs ? `?${qs}` : ""}`, { signal: opts.signal });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  const data = await res.json();
  const meta = {
    ceCalls: Number(res.headers.get("X-CE-Calls-Spent") || 0),
    ceCostUsd: Number(res.headers.get("X-CE-Estimated-Cost-USD") || 0),
  };
  return { data, meta };
};

export const api = {
  context: (profile, period, opts) => getJson("/api/ui/context", { profile, period }, opts),
  summary: (profile, period, opts) => getJson("/api/cost/summary/data", { profile, period }, opts),
  services: (profile, period, limit = 0, opts) =>
    getJson("/api/cost/services/data", { profile, period, limit }, opts),
  trend: (profile, period, opts) => getJson("/api/cost/trend/data", { profile, period }, opts),
  trendTable: (profile, period, opts) =>
    getJson("/api/cost/trend-table/data", { profile, period }, opts),
  resources: (profile, period, region = "all", service = "", limit = 0, opts) =>
    getJson("/api/resources/data", { profile, period, region, service, limit }, opts),
  resourcesTop: (profile, period, region = "all", limit = 10, opts) =>
    getJson("/api/resources/top/data", { profile, period, region, limit }, opts),
  audit: (profile, region = "all", opts) =>
    getJson("/api/audit/summary/data", { profile, region }, opts),
  budgets: (profile, opts) => getJson("/api/budgets/data", { profile }, opts),
  downloadExport: async (profile, period, fmt, name = "") => {
    const qs = toParams({ profile, period, fmt, name });
    const res = await fetch(`/api/export/download?${qs}`);
    if (!res.ok) {
      let msg = `Export failed: ${res.status}`;
      try {
        const err = await res.json();
        if (err?.error) msg = err.error;
      } catch (_) {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/i);
    const filename = m?.[1] || `cloud_ledger_${Date.now()}.${fmt}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return { filename };
  },
  runExport: async (profile, period, fmt, outputDir = "./exports") => {
    const qs = toParams({ profile, period, fmt, output_dir: outputDir });
    const res = await fetch(`/api/export/run?${qs}`, { method: "POST" });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    return res.json();
  },
};
```

- [ ] **Step 2: Update call sites in `App.jsx`**

The `useAsyncData` callbacks now look like `(signal) => api.summary(profile, period, { signal })`. The hook already destructures `{ data, meta }`. Pages that read `data.something` now need to read `state.data?.something` from the hook return (it was already that way), so no change beyond passing `signal`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.js frontend/src/App.jsx
git commit -m "refactor(api): accept AbortSignal, surface X-CE-Calls-Spent as meta"
```

---

## Task 3: Fix `api.context` hardcoded call

**Files:** `frontend/src/App.jsx` lines ~350–360.

Currently `api.context("default", "mtd")` runs once at mount regardless of selected profile/period.

- [ ] **Step 1: Move into `useAsyncData`**

```js
const ctxState = useAsyncData(
  (signal) => api.context(profile, period, { signal }),
  [profile, period]
);
const contextState = ctxState.data || null;
```

Delete the separate one-shot effect that called `api.context("default", "mtd")`.

- [ ] **Step 2: Commit**

```bash
git commit -am "fix(frontend): context follows current profile/period"
```

---

## Task 4: Dedupe `api.resources()` in `ResourcesPage`

**Files:** `frontend/src/App.jsx` around line 215–230.

Two `useAsyncData` calls hit `/api/resources/data` with identical params, once for reconciliation stats and once for the row table. The endpoint already returns both shapes — compute the stats client-side from the rows.

- [ ] **Step 1: Find the dual call**

The shape is roughly:
```js
const stats = useAsyncData(() => api.resources(profile, period, "all", service), [profile, period, service]);
const rows  = useAsyncData(() => api.resources(profile, period, "all", service), [profile, period, service]);
```

- [ ] **Step 2: Replace with single fetch + derived stats**

```js
const resData = useAsyncData(
  (signal) => api.resources(profile, period, "all", service, 0, { signal }),
  [profile, period, service]
);

const stats = useMemo(() => {
  const d = resData.data;
  if (!d) return null;
  return {
    ce_total: d.ce_total,
    attributed_total: d.attributed_total,
    unattributed: d.unattributed,
    variance_pct: d.variance_pct,
  };
}, [resData.data]);

const rows = resData.data?.rows || [];
```

- [ ] **Step 3: Commit**

```bash
git commit -am "perf(frontend): dedupe ResourcesPage fetch — stats derived from rows"
```

---

## Task 5: Debounce filter changes

**Files:**
- Create: `frontend/src/hooks/useDebounced.js`
- Modify: `frontend/src/App.jsx` (ResourcesPage)

- [ ] **Step 1: Write `useDebounced`**

```js
// frontend/src/hooks/useDebounced.js
import { useEffect, useState } from "react";

export function useDebounced(value, delayMs = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
```

- [ ] **Step 2: Use in ResourcesPage**

```js
import { useDebounced } from "./hooks/useDebounced";
// ...
const [service, setService] = useState("");
const debouncedService = useDebounced(service, 300);

const resData = useAsyncData(
  (signal) => api.resources(profile, period, "all", debouncedService, 0, { signal }),
  [profile, period, debouncedService]
);
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useDebounced.js frontend/src/App.jsx
git commit -m "perf(frontend): debounce service filter 300ms"
```

---

## Task 6: localStorage SWR cache

**Files:**
- Create: `frontend/src/lib/swrCache.js`
- Modify: `frontend/src/api.js` to read/write through it

Cache responses by URL + params in localStorage. On the next visit, render stale data immediately while refetching in the background. Survives reloads.

- [ ] **Step 1: Write the cache**

```js
// frontend/src/lib/swrCache.js
const PREFIX = "acu:swr:";
const TTL_MS = 5 * 60 * 1000;       // fresh for 5 min
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
```

- [ ] **Step 2: Wrap `getJson` in `api.js`**

```js
import { readSwr, writeSwr } from "./lib/swrCache";

const cacheKey = (path, params) => `${path}?${toParams(params)}`;

const getJson = async (path, params = {}, opts = {}) => {
  const key = cacheKey(path, params);
  const cached = readSwr(key);
  if (cached?.fresh) {
    return { data: cached.value, meta: { ceCalls: 0, ceCostUsd: 0, fromCache: "fresh" } };
  }

  const qs = toParams(params);
  try {
    const res = await fetch(`${path}${qs ? `?${qs}` : ""}`, { signal: opts.signal });
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    const data = await res.json();
    const meta = {
      ceCalls: Number(res.headers.get("X-CE-Calls-Spent") || 0),
      ceCostUsd: Number(res.headers.get("X-CE-Estimated-Cost-USD") || 0),
      fromCache: null,
    };
    writeSwr(key, data);
    return { data, meta };
  } catch (err) {
    if (cached) return { data: cached.value, meta: { ceCalls: 0, ceCostUsd: 0, fromCache: "stale" } };
    throw err;
  }
};
```

- [ ] **Step 3: Persist profile/period selection**

In `App.jsx`:

```js
const [profile, setProfile] = useState(() => localStorage.getItem("acu:profile") || "default");
const [period, setPeriod]   = useState(() => localStorage.getItem("acu:period")  || "mtd");

useEffect(() => { localStorage.setItem("acu:profile", profile); }, [profile]);
useEffect(() => { localStorage.setItem("acu:period", period); }, [period]);
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/swrCache.js frontend/src/api.js frontend/src/App.jsx
git commit -m "perf(frontend): localStorage SWR cache + persisted profile/period"
```

---

## Task 7: `CostBadge` footer — show cumulative CE spend this session

**Files:**
- Create: `frontend/src/lib/ceMeter.js`
- Create: `frontend/src/components/CostBadge.jsx`
- Modify: `frontend/src/App.jsx` — render badge; subscribe to meter

- [ ] **Step 1: Meter (tiny pub/sub)**

```js
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
```

- [ ] **Step 2: Hook meter into `useAsyncData`**

```js
// frontend/src/hooks/useAsyncData.js — inside the .then() success branch
import { recordCe } from "../lib/ceMeter";
// ...
.then(({ data, meta }) => {
  if (ctrl.signal.aborted) return;
  recordCe(meta);
  setState({ loading: false, error: "", data, meta: meta || null });
})
```

- [ ] **Step 3: Component**

```jsx
// frontend/src/components/CostBadge.jsx
import { useEffect, useState } from "react";
import { resetCe, subscribeCe } from "../lib/ceMeter";

export function CostBadge() {
  const [total, setTotal] = useState({ calls: 0, costUsd: 0 });
  useEffect(() => subscribeCe(setTotal), []);
  if (total.calls === 0) return null;
  return (
    <div className="cost-badge" title="Cost Explorer spend this session — click to reset">
      <button onClick={resetCe} aria-label="Reset session cost meter">
        CE: {total.calls} call{total.calls === 1 ? "" : "s"} · ${total.costUsd.toFixed(4)}
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Render badge in App shell**

```jsx
import { CostBadge } from "./components/CostBadge";
// in App's return, near the bottom of the layout
<CostBadge />
```

- [ ] **Step 5: Style**

```css
/* frontend/src/styles.css — append */
.cost-badge {
  position: fixed;
  bottom: 12px;
  right: 12px;
  z-index: 100;
}
.cost-badge button {
  background: var(--surface-2, #1c1f24);
  color: var(--text-2, #aab1bd);
  border: 1px solid var(--border, #2a2f37);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12px;
  font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  cursor: pointer;
}
.cost-badge button:hover { color: var(--text-1, #e5e7eb); }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/ceMeter.js frontend/src/components/CostBadge.jsx \
        frontend/src/hooks/useAsyncData.js frontend/src/App.jsx frontend/src/styles.css
git commit -m "feat(frontend): CostBadge — passive session CE-spend counter"
```

---

## Task 8: Code-split Recharts per route

**Files:**
- Modify: `frontend/src/App.jsx` — `lazy` import of chart-heavy pages
- Modify: `frontend/vite.config.js` — manual chunk for recharts

- [ ] **Step 1: Lazy-load chart-heavy pages**

```jsx
// frontend/src/App.jsx top
import { lazy, Suspense } from "react";
const TrendsPage = lazy(() => import("./pages/TrendsPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
```

Extract `DashboardPage`/`TrendsPage` into their own files (`frontend/src/pages/`). Wrap render with `<Suspense fallback={<Spinner/>}>`.

- [ ] **Step 2: Manual chunk in vite**

```js
// frontend/vite.config.js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          recharts: ["recharts"],
          react: ["react", "react-dom"],
        },
      },
    },
  },
});
```

- [ ] **Step 3: Verify bundle**

```bash
cd frontend && npm run build
ls -la dist/assets/
```
Expected: separate `recharts-*.js` chunk (~180 KB) only loaded by Dashboard/Trends pages; initial route bundle drops below ~250 KB.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/pages/ frontend/vite.config.js
git commit -m "perf(frontend): code-split recharts and chart-heavy pages"
```

---

## Task 9: Mobile + a11y baseline

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.jsx` — sidebar uses semantic buttons

- [ ] **Step 1: Sidebar buttons (a11y)**

Replace `<div className="side-item" onClick={...}>` with:

```jsx
<button
  type="button"
  className={`side-item ${page === it ? "active" : ""}`}
  onClick={() => setPage(it)}
  aria-current={page === it ? "page" : undefined}
>
  <span className="side-item-text">{TITLES[it]}</span>
</button>
```

Add a `aria-label` to the collapse button.

- [ ] **Step 2: Mobile table**

```css
/* styles.css */
@media (max-width: 760px) {
  .tbl-res, .tbl-svc {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }
  .split { grid-template-columns: 1fr; }
}
```

- [ ] **Step 3: Skeleton loaders**

Replace text spinners ("Loading summary...") with a CSS-only skeleton:

```css
.skel {
  background: linear-gradient(90deg, #1c1f24 0%, #262a30 50%, #1c1f24 100%);
  background-size: 200% 100%;
  animation: skel 1.2s ease-in-out infinite;
  border-radius: 6px;
}
@keyframes skel { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }
.skel-kpi { height: 72px; }
.skel-row { height: 28px; margin: 4px 0; }
```

In each page's loading branch, render `<div className="skel skel-kpi" />` (or appropriate variant) instead of spinner text.

- [ ] **Step 4: Commit**

```bash
git commit -am "a11y/mobile: semantic sidebar buttons + responsive tables + skeleton loaders"
```

---

## Task 10: Render named per-resource view from Plan 2

**Files:** `frontend/src/App.jsx` — ResourcesPage rendering.

After Plan 2 ships, `/api/resources/data` returns rows with `name`, `tags`, `resource_id`, `service`, `cost`. Replace the existing column layout:

- [ ] **Step 1: Update the table**

```jsx
<table className="tbl-res">
  <thead>
    <tr>
      <th>Name</th>
      <th>Service</th>
      <th>Resource ID</th>
      <th style={{ textAlign: "right" }}>Cost</th>
    </tr>
  </thead>
  <tbody>
    {rows.map((r) => (
      <tr key={r.resource_id}>
        <td><strong>{r.name}</strong></td>
        <td className="muted">{r.service}</td>
        <td className="mono small">{r.resource_id}</td>
        <td style={{ textAlign: "right" }}>{usd(r.cost, 2)}</td>
      </tr>
    ))}
  </tbody>
</table>
```

If `name === resource_id` (no Name tag), show the resource id in the Name column too. That's intentional — the user sees "this untagged bucket cost $X" and decides whether to add a tag.

- [ ] **Step 2: "Copy ID" affordance**

Wrap the resource_id in a click-to-copy `<button>`:

```jsx
<td>
  <button
    className="copy-id"
    onClick={() => navigator.clipboard?.writeText(r.resource_id)}
    title="Copy resource id"
  >{r.resource_id}</button>
</td>
```

- [ ] **Step 3: Empty state**

```jsx
{rows.length === 0 && (
  <div className="empty">
    <p>No resources attributed for this window.</p>
    <p className="muted">
      If you just enabled CUR, data takes ~24h to arrive. Run{" "}
      <code>aws-cost-ultra cur status</code> to check.
    </p>
  </div>
)}
```

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(resources): named per-resource table + copy-id + empty state"
```

---

## Task 11: Clean unused deps

**Files:** `frontend/package.json`.

- [ ] **Step 1: Remove `puppeteer`**

```bash
cd frontend && npm uninstall puppeteer
```

- [ ] **Step 2: Verify build**

```bash
npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(deps): drop unused puppeteer"
```

---

## Self-Review

**Spec coverage check** against §6 frontend items:

| Spec item | Plan task |
|---|---|
| 8. AbortController in useAsyncData | Task 1 |
| 9. Debounce filter changes | Task 5 |
| `api.context` hardcoded args | Task 3 |
| Dedupe `api.resources()` | Task 4 |
| localStorage SWR | Task 6 |
| `X-CE-Calls-Spent` UI | Task 7 |
| Code-split Recharts | Task 8 |
| Mobile + a11y | Task 9 |
| Skeleton loaders | Task 9 step 3 |
| Named per-resource rows | Task 10 (depends on Plan 2) |
| Drop unused puppeteer | Task 11 |

**Placeholder scan:** All code blocks concrete. The "extract DashboardPage/TrendsPage into their own files" in Task 8 is the only non-trivial restructure — that's left as an obvious mechanical refactor since the page bodies already exist in `App.jsx`.

---

## Verification (end-to-end)

After all 11 tasks:

1. **Race condition gone**: Open DevTools → Network → rapidly switch profile/period. Only the latest request should resolve into the UI; older ones should appear as `(canceled)`.
2. **CostBadge present**: Bottom-right corner shows e.g. `CE: 3 calls · $0.0300` after a fresh dashboard load. Click → resets.
3. **Resource names visible**: After Plan 2 + CUR ingest, Resources page lists `web-1`, `my-app-assets`, etc. — not just instance IDs.
4. **Reload survives**: Refresh the page → profile/period preserved; cached data renders instantly with a background revalidation.
5. **Mobile works**: Resize browser to 600px wide → tables scroll horizontally, layout doesn't break.
6. **Bundle split**: `dist/assets/` shows separate `recharts-*.js` chunk.
