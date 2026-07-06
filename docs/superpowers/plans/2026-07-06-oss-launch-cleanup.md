# OSS Launch Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make aws-cost-dashboard publishable as an AWS-only open-source project: purge personal/company data from tracking, remove duplicated/legacy code (root `pricing.py`+`resources/`, the HTMX frontend), fix the frontend error-surfacing UX family, and make `run.sh`/`run.bat` actually work.

**Architecture:** Single React (Vite) frontend served by FastAPI at `/app`; JSON-only API routes (all HTMX partial-render endpoints removed). Frontend gains a `lib/format.js` shared formatting module, backend-error detection in `api.js`, a shared `Banner`/retry pattern via a `reload` handle on `useAsyncData`, URL-synced app state, and an ErrorBoundary.

**Tech Stack:** Python 3.9+/FastAPI/pytest, React 18/Vite 5/Recharts, Vitest (new, for frontend unit tests).

## Global Constraints

- The user will create a **fresh GitHub repo** for release, so git history rewriting is NOT needed — but tracked files must be cleaned so a fresh repo starts clean.
- Real AWS account ID `012178638401` must not appear anywhere in tracked files; use `123456789012`.
- Do not delete `csv+comparsion/` or `COST_EXPLORER_*.md` from disk — only untrack them. DO delete `aws-other-tools/`, root `pricing.py`, root `resources/`, and the HTMX UI from disk.
- Keep all JSON `/data` API endpoints and `/api/ui/context` working unchanged; only HTML-rendering endpoints are removed.
- App serves at port 8080 (`python -m aws_cost_ultra.web.app`); there is no `app.py` at repo root.
- Backend tests: `venv/bin/python -m pytest tests/ -x -q` from repo root. Frontend: `npm run build` and `npx vitest run` from `frontend/`.
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Untrack personal data + internal artifacts, extend .gitignore

**Files:**
- Modify: `.gitignore`
- Untrack (keep on disk): `csv+comparsion/`, `.claude/workflows/`, `.superpowers/`, `docs/superpowers/`, `COST_EXPLORER_AUDIT.md`, `COST_EXPLORER_FIXES.md`, `docs/IMPLEMENTATION.md`
- Delete from disk + untrack: `aws-other-tools/`

**Interfaces:**
- Produces: a clean `git ls-files` — later tasks assume these paths are gone from tracking.

- [ ] **Step 1: Replace .gitignore content**

```gitignore
*.pyc
__pycache__/
.pytest_cache/
node_modules/
venv/
.venv/
*.egg-info/
exports/
.cache/
.DS_Store
*.duckdb
*.duckdb.wal

# personal data / local-only working files — never publish
csv+comparsion/
aws-other-tools/
COST_EXPLORER_AUDIT.md
COST_EXPLORER_FIXES.md
docs/IMPLEMENTATION.md
docs/superpowers/

# AI-session tooling state
.claude/
.superpowers/
```

- [ ] **Step 2: Untrack / delete**

```bash
cd "/run/media/tirth/OS/Users/Tirth Teraiya/Personal Folder/aws-cost-dashboard"
git rm -r --cached --quiet 'csv+comparsion' '.claude' '.superpowers' 'docs/superpowers' COST_EXPLORER_AUDIT.md COST_EXPLORER_FIXES.md docs/IMPLEMENTATION.md 2>/dev/null || true
git rm -r --quiet 'aws-other-tools'
```

Note: `.claude/workflows/*` are currently **staged adds** (`A` in git status) — `git rm --cached` unstages them. If it errors, use `git restore --staged .claude` first.

- [ ] **Step 3: Verify nothing sensitive remains tracked**

Run: `git ls-files | grep -E 'csv\+comparsion|aws-other-tools|\.claude/|\.superpowers/|docs/superpowers|COST_EXPLORER|IMPLEMENTATION' ; echo "exit=$?"`
Expected: no file lines, `exit=1` (grep found nothing).

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: untrack personal data, vendored repos, and AI-session artifacts

csv+comparsion/ contained a real billing export; aws-other-tools/ were
vendored third-party repos (license risk). Public repo will be created
fresh so history scrubbing is handled by starting a new repo.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Scrub real AWS account ID from tests

**Files:**
- Modify: `tests/conftest.py` (4 occurrences), `tests/test_cur_store.py` (5 occurrences)

**Interfaces:**
- Produces: fixture account id `123456789012` — any later test additions must use it too.

- [ ] **Step 1: Replace the ID**

```bash
cd "/run/media/tirth/OS/Users/Tirth Teraiya/Personal Folder/aws-cost-dashboard"
sed -i 's/012178638401/123456789012/g' tests/conftest.py tests/test_cur_store.py
```

- [ ] **Step 2: Verify no occurrence remains in tracked files**

Run: `git ls-files -z | xargs -0 grep -l 012178638401 ; echo "exit=$?"`
Expected: no output, `exit=123` or `exit=1` (no matches).

- [ ] **Step 3: Run the affected tests**

Run: `venv/bin/python -m pytest tests/test_cur_store.py tests/test_cur_ingestor.py -q`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_cur_store.py
git commit -m "chore(tests): replace real account id with canonical example id

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Delete duplicated legacy root modules

**Files:**
- Delete: `pricing.py`, `resources/` (root level — pre-package leftovers duplicating `aws_cost_ultra/core/pricing.py` and `aws_cost_ultra/resources/`)

**Interfaces:**
- Consumes: nothing — verified: the only importers of root `pricing` are the root `resources/*.py` files themselves.

- [ ] **Step 1: Re-verify no external importers**

Run: `grep -rn "^import pricing\|^from pricing\|from resources import\|^import resources" --include='*.py' . | grep -v venv | grep -v '^\./resources/'`
Expected: no output.

- [ ] **Step 2: Delete**

```bash
git rm -r --quiet pricing.py resources
```

- [ ] **Step 3: Full test suite**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: all PASS (same pass count as before deletion).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove pre-package duplicate pricing.py and resources/ from repo root

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Remove the legacy HTMX frontend (single-UI cleanup)

**Files:**
- Delete: `aws_cost_ultra/web/templates/` (all), `aws_cost_ultra/web/static/` (all), `aws_cost_ultra/web/render.py`
- Modify: `aws_cost_ultra/web/routes/pages.py` (drop HTML page routes, keep `/`, `/app`, `/app/{path}`, `/api/ui/context`)
- Modify: `aws_cost_ultra/web/routes/cost.py`, `resources_api.py`, `audit_api.py`, `export_api.py` (drop `render(...)`-returning endpoints only)
- Modify: `aws_cost_ultra/web/app.py` (drop `/static` mount + StaticFiles import)
- Modify: `pyproject.toml` (package-data)
- Modify: `frontend/vite.config.js` (drop `/static` proxy)
- Modify/Delete tests that exercised removed HTML endpoints

**Interfaces:**
- Produces: JSON-only API surface. The React app consumes exactly: `/api/ui/context`, `/api/cost/summary/data`, `/api/cost/services/data`, `/api/cost/trend/data`, `/api/cost/services/composition/data`, `/api/resources/data`, `/api/resources/top/data`, `/api/audit/summary/data`, `/api/budgets/data`, `/api/export/download`, `/api/export/run` — none of these may be removed.

- [ ] **Step 1: Inventory the render endpoints**

Run: `grep -n "render(" aws_cost_ultra/web/routes/*.py`
Expected (current known set): `pages.py` page routes (dashboard/services/audit/trends/resources/export), `cost.py:341,345,393,598,619`, `resources_api.py:203,305`, `audit_api.py:91`, `export_api.py:251,263`.

- [ ] **Step 2: Trim pages.py**

Keep only: module docstring, imports (`Path`, `APIRouter`, `Query`, `FileResponse`, `HTMLResponse`, `JSONResponse`, `RedirectResponse`, `base_ctx`), `_FRONTEND_DIST`, `root_redirect` (change target from `/app` — it already is `/app`, keep), `ui_context`, `react_app_index`, `react_app_assets`. Delete `dashboard`, `services_page`, `audit_page`, `trends_page`, `resources_page`, `export_page` and the now-unused `Request`/`render` imports.

- [ ] **Step 3: Trim the partial-render endpoints in the four API modules**

In each of `cost.py`, `resources_api.py`, `audit_api.py`, `export_api.py`: delete the whole route functions whose return statement is `render(request, "partials/...", ...)` (each is a distinct `@router.get/post` function — the `/data` JSON siblings stay). Then delete the now-unused `from aws_cost_ultra.web.render import render` imports (and `Request` params/imports if no longer referenced in that file). Do NOT touch the ctx-builder functions (`_build_summary_ctx`, `build_resources_ctx`, `build_audit_ctx`, ...) — the JSON routes share them.

- [ ] **Step 4: Delete the files and the static mount**

```bash
git rm -r --quiet aws_cost_ultra/web/templates aws_cost_ultra/web/static aws_cost_ultra/web/render.py
```

In `aws_cost_ultra/web/app.py`: remove `from fastapi.staticfiles import StaticFiles` (line 15) and the `app.mount("/static", ...)` line (141).
In `frontend/vite.config.js`: remove the `"/static": backendUrl,` proxy entry.
In `pyproject.toml`: replace the package-data block with:

```toml
[tool.setuptools.package-data]
aws_cost_ultra = []
```

- [ ] **Step 5: Fix tests that referenced removed endpoints**

Run: `grep -rln "render\|partials\|/legacy\|templates" tests/`, then run `venv/bin/python -m pytest tests/ -q`. For each failing test that asserted an HTML partial route: delete the test if it only covered the removed endpoint; keep and repoint to the `/data` JSON sibling if it covered shared ctx logic. `test_middleware.py` and `test_smoke.py` are the likely candidates.

- [ ] **Step 6: Full verification**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: all PASS.
Run: `venv/bin/python -c "from aws_cost_ultra.web.app import app; print(len(app.routes))"`
Expected: prints a route count with no ImportError.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(web): remove legacy HTMX UI; React app at /app is the single frontend

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend test harness + shared format module

**Files:**
- Create: `frontend/src/lib/format.js`, `frontend/src/lib/format.test.js`, `frontend/vitest.config.js`
- Modify: `frontend/package.json`, `frontend/src/App.jsx` (imports + delete local helpers), `frontend/src/charts.jsx` (imports + delete local `usdK`)

**Interfaces:**
- Produces: `usd(n, dec=3) -> string` (sign-before-dollar for negatives), `usdCompact(v) -> string` (axis/compact), `usdTip(v) -> string` (tooltip, 2dp), `pct(n) -> string`, `value(v, fallback=0) -> number` — all later frontend tasks import from `./lib/format` (or `../lib/format`).

- [ ] **Step 1: Add vitest**

In `frontend/package.json` add to `devDependencies`: `"vitest": "^2.1.9"`, and to `scripts`: `"test": "vitest run"`. Then run `cd frontend && npm install`.

Create `frontend/vitest.config.js`:

```js
import { defineConfig } from "vite";

export default defineConfig({
  test: { environment: "node", include: ["src/**/*.test.js"] },
});
```

- [ ] **Step 2: Write the failing test**

`frontend/src/lib/format.test.js`:

```js
import { describe, it, expect } from "vitest";
import { usd, usdCompact, usdTip, pct, value } from "./format";

describe("usd", () => {
  it("formats positive with 3 decimals by default", () => {
    expect(usd(1234.5)).toBe("$1,234.500");
  });
  it("clamps tiny CE negative floats to zero", () => {
    expect(usd(-0.00001)).toBe("$0.000");
  });
  it("puts the sign before the dollar for real negatives", () => {
    expect(usd(-12.34, 2)).toBe("-$12.34");
  });
});

describe("usdCompact", () => {
  it("compacts thousands and millions", () => {
    expect(usdCompact(1500)).toBe("$1.5k");
    expect(usdCompact(2_500_000)).toBe("$2.5M");
  });
  it("compacts negatives symmetrically", () => {
    expect(usdCompact(-1500)).toBe("-$1.5k");
  });
});

describe("usdTip", () => {
  it("keeps cents in tooltips", () => {
    expect(usdTip(45.678)).toBe("$45.68");
  });
});

describe("pct/value", () => {
  it("signs percentages", () => {
    expect(pct(3.14159)).toBe("+3.1%");
    expect(pct(-2)).toBe("-2.0%");
  });
  it("value falls back on null/undefined", () => {
    expect(value(null, 7)).toBe(7);
    expect(value("3")).toBe(3);
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run`
Expected: FAIL — cannot resolve `./format`.

- [ ] **Step 4: Implement `frontend/src/lib/format.js`**

```js
// Shared money/number formatting. Single source of truth for the app,
// charts, and PDF-adjacent UI so credits/negatives render consistently.

export const value = (v, fallback = 0) => Number(v ?? fallback);

export const usd = (n, dec = 3) => {
  let num = Number(n || 0);
  // CE sometimes returns tiny negative floats (-0.00001); clamp to zero before display
  if (num < 0 && Math.abs(num) < 5 * Math.pow(10, -(dec + 1))) num = 0;
  const sign = num < 0 ? "-" : "";
  return `${sign}$${Math.abs(num).toLocaleString("en-US", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  })}`;
};

// Compact form for axis ticks: $1.5k / $2.5M, sign outside the dollar.
export const usdCompact = (v) => {
  const num = Number(v || 0);
  const sign = num < 0 ? "-" : "";
  const abs = Math.abs(num);
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  if (abs >= 1) return `${sign}$${abs.toFixed(0)}`;
  return `${sign}$${abs.toFixed(2)}`;
};

// Tooltip form: always keep cents — a cost tool must not round $45.67 to $46 on hover.
export const usdTip = (v) => usd(v, 2);

export const pct = (n) => `${Number(n || 0) >= 0 ? "+" : ""}${Number(n || 0).toFixed(1)}%`;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run` — Expected: PASS.

- [ ] **Step 6: Wire into App.jsx and charts.jsx**

In `App.jsx`: delete the local `usd`, `pct`, `value` definitions (lines 21-28) and add `import { usd, pct, value } from "./lib/format";`. Also delete the dead `"60d": "last 60 days",` entry from `PERIOD_LABEL` (backend has no 60d period).
In `charts.jsx`: delete the local `usdK` (lines ~30-36) and import `{ usdCompact, usdTip } from "./lib/format"`; use `usdCompact` for axis tick formatters and `usdTip` for tooltip `formatter`s (three call sites, ~lines 98/124/159). Also delete the unused exported `Sparkline` and `AreaChart` components and the dead `SERIES_COLORS`/`fillForKey` indirection if only ever hit by the `"Spend"` fallback — replace with a direct `var(--accent)` fill.

- [ ] **Step 7: Build + commit**

Run: `cd frontend && npm run build` — Expected: build succeeds.

```bash
git add frontend/src/lib/format.js frontend/src/lib/format.test.js frontend/vitest.config.js frontend/package.json frontend/package-lock.json frontend/src/App.jsx frontend/src/charts.jsx
git commit -m "refactor(frontend): shared format module (negative-safe), vitest harness, prune dead chart code

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Backend-error detection in api.js (the $0.000-on-failure fix)

**Files:**
- Modify: `frontend/src/api.js`
- Create: `frontend/src/api.test.js`

**Interfaces:**
- Consumes: backend ctx builders return HTTP 200 with an `error` string field on failure (sometimes alongside partial data, e.g. audit).
- Produces: `getJson` result becomes `{ data, meta }` where `meta.backendError` is the backend `error` string (or null). Error payloads are **never** written to the SWR cache. `useAsyncData` (Task 7) surfaces it as `state.backendError`.

- [ ] **Step 1: Write the failing test** — `frontend/src/api.test.js`:

```js
import { describe, it, expect, vi, beforeEach } from "vitest";

// In-memory localStorage for the swrCache dependency (vitest runs in node env).
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  key: (i) => [...store.keys()][i] ?? null,
  get length() { return store.size; },
};

const jsonResponse = (body) => ({
  ok: true,
  status: 200,
  headers: { get: () => "0" },
  json: async () => body,
});

describe("getJson backend-error handling", () => {
  beforeEach(() => { store.clear(); vi.restoreAllMocks(); });

  it("exposes data.error as meta.backendError and does not cache it", async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ error: "ExpiredToken: please re-auth", total_mtd: 0 }))
      .mockResolvedValueOnce(jsonResponse({ total_mtd: 42 }));
    const { api } = await import("./api");

    const first = await api.summary("default", "mtd");
    expect(first.meta.backendError).toBe("ExpiredToken: please re-auth");

    // Second call must NOT be served from cache (error payload was not cached).
    const second = await api.summary("default", "mtd");
    expect(second.data.total_mtd).toBe(42);
    expect(second.meta.backendError).toBeNull();
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("caches clean payloads as before", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse({ total_mtd: 7 }));
    const { api } = await import("./api");
    await api.summary("p", "mtd");
    const again = await api.summary("p", "mtd");
    expect(again.meta.fromCache).toBe("fresh");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/api.test.js`
Expected: FAIL — `meta.backendError` is `undefined`.

- [ ] **Step 3: Implement in `api.js`**

In `getJson`, after `const data = await res.json();` replace the meta/cache block with:

```js
    const finite = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
    // Backend ctx builders report failures as HTTP 200 + {error: "..."} —
    // surface that instead of rendering zeroed figures as if they were real.
    const backendError = data && typeof data === "object" && typeof data.error === "string" && data.error
      ? data.error
      : null;
    const meta = {
      ceCalls: finite(res.headers.get("X-CE-Calls-Spent") || 0),
      ceCostUsd: finite(res.headers.get("X-CE-Estimated-Cost-USD") || 0),
      fromCache: null,
      backendError,
    };
    // Don't cache transient placeholders ({warming:true}) or error payloads —
    // otherwise a single expired-credentials response poisons the view for
    // the whole SWR TTL even after the user fixes the problem.
    if (!data?.warming && !backendError) writeSwr(key, data);
    return { data, meta };
```

Also add `backendError: null` to the fresh-cache early return's meta (line 17) and to the stale-fallback meta (line 42) so the shape is uniform.

- [ ] **Step 4: Run tests** — `cd frontend && npx vitest run` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.js frontend/src/api.test.js
git commit -m "fix(frontend): surface backend {error} payloads instead of caching them as \$0 data

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Retry handle + shared banners + ErrorBoundary

**Files:**
- Modify: `frontend/src/hooks/useAsyncData.js`
- Create: `frontend/src/components/Banner.jsx`, `frontend/src/components/ErrorBoundary.jsx`
- Modify: `frontend/src/main.jsx`

**Interfaces:**
- Produces:
  - `useAsyncData(loader, deps)` now returns `{ loading, error, backendError, data, meta, reload }` where `reload()` re-runs the loader and `backendError` mirrors `meta.backendError`.
  - `<Banner tone="error"|"warn" onRetry={fn}>children</Banner>` — inline dismissable-free banner with optional Retry button.
  - `<ErrorBoundary>` — wraps `<App/>`, renders a readable crash card instead of a white page.
- Task 8 consumes all three.

- [ ] **Step 1: Extend useAsyncData**

```js
// frontend/src/hooks/useAsyncData.js
import { useCallback, useEffect, useRef, useState } from "react";
import { recordCe } from "../lib/ceMeter";

/**
 * loader receives an AbortSignal and should pass it to fetch().
 * State only updates from the latest in-flight request.
 * `reload()` re-runs the loader (used by Retry buttons and polls).
 * `backendError` carries HTTP-200 {error:"..."} payload messages.
 */
export function useAsyncData(loader, deps) {
  const [state, setState] = useState({ loading: true, error: "", backendError: null, data: null, meta: null });
  const [tick, setTick] = useState(0);
  const inFlight = useRef(null);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    inFlight.current?.abort();
    const ctrl = new AbortController();
    inFlight.current = ctrl;

    setState((prev) => ({ ...prev, loading: true, error: "" }));

    loader(ctrl.signal)
      .then((result) => {
        if (ctrl.signal.aborted) return;
        const { data, meta } = result ?? {};
        recordCe(meta);
        setState({
          loading: false,
          error: "",
          backendError: meta?.backendError || null,
          data: data ?? null,
          meta: meta || null,
        });
      })
      .catch((err) => {
        if (ctrl.signal.aborted || err?.name === "AbortError") return;
        setState((prev) => ({
          loading: false,
          error: err?.message || "Failed",
          backendError: prev.backendError,
          data: prev.data,
          meta: prev.meta,
        }));
      });

    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { ...state, reload };
}
```

- [ ] **Step 2: Create `frontend/src/components/Banner.jsx`**

```jsx
// Inline status banner used for backend errors, partial-data caveats,
// and stale-cache warnings. Keeps failure states visible instead of
// letting pages silently render $0.000.
const TONES = {
  error: { background: "#9E3B2E", color: "#fff" },
  warn: { background: "#A77418", color: "#fff" },
};

export function Banner({ tone = "warn", onRetry, children }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      style={{
        ...TONES[tone],
        padding: "8px 12px",
        borderRadius: 6,
        marginBottom: 12,
        fontSize: 13,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <span style={{ flex: 1 }}>{children}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          style={{
            background: "rgba(255,255,255,0.18)", color: "inherit", border: "1px solid rgba(255,255,255,0.4)",
            borderRadius: 4, padding: "3px 10px", cursor: "pointer", fontSize: 12,
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

// Convenience: one warning line when any hook on the page served stale cache.
export function StaleBanner({ hooks }) {
  const stale = hooks.some((h) => h?.meta?.fromCache === "stale");
  if (!stale) return null;
  return (
    <Banner tone="warn">
      Showing cached data — couldn't reach the server for fresh figures. These numbers may be stale.
    </Banner>
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/ErrorBoundary.jsx`**

```jsx
import { Component } from "react";

// Last-resort guard: an unexpected API shape must show a readable card,
// not a blank white page.
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ maxWidth: 560, margin: "80px auto", fontFamily: "system-ui, sans-serif" }}>
        <h1 style={{ fontSize: 20 }}>Something went wrong rendering the dashboard</h1>
        <pre style={{ background: "#f4f2ee", padding: 12, borderRadius: 6, overflowX: "auto", fontSize: 12 }}>
          {String(this.state.error?.message || this.state.error)}
        </pre>
        <button type="button" onClick={() => window.location.reload()} style={{ padding: "6px 14px", cursor: "pointer" }}>
          Reload
        </button>
        <p style={{ fontSize: 13, opacity: 0.7 }}>
          If this keeps happening, please open an issue with the message above.
        </p>
      </div>
    );
  }
}
```

- [ ] **Step 4: Wrap the app in `frontend/src/main.jsx`**

```jsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./tokens.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
```

(Keep whatever import list main.jsx already has for CSS — adjust to the actual current file rather than dropping imports.)

- [ ] **Step 5: Verify** — `cd frontend && npx vitest run && npm run build` — Expected: PASS + build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useAsyncData.js frontend/src/components/Banner.jsx frontend/src/components/ErrorBoundary.jsx frontend/src/main.jsx
git commit -m "feat(frontend): reload handle, shared error/stale banners, ErrorBoundary

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Page-level UX fixes in App.jsx

**Files:**
- Modify: `frontend/src/App.jsx` (all sections below), `frontend/src/charts.jsx` (Donut center total — only if needed per Step 3)

**Interfaces:**
- Consumes: `useAsyncData().reload/backendError`, `Banner`/`StaleBanner`, `usd/pct/value/usdTip` from earlier tasks.
- Consumes (backend, verified): `/api/cost/services/data` → `{services:[{name,cost,pct_of_total,change_pct}], total, error?}`; `/api/resources/data` → `{rows, total, ce_total, unattributed, total_count, services_summary, incomplete?, warnings?, error?}`; `/api/audit/summary/data` → `{idle, untagged, error?}`; `/api/budgets/data` → `{findings:[{budget_name, actual_spend, limit_amount, utilization_pct, status}], error?}`; summary → `{total_mtd,total_prev,forecast,top_service_name,top_service_cost,change_pct?,error?}`.

- [ ] **Step 1: DashboardPage — error/stale/retry surfacing**

Add `import { Banner, StaleBanner } from "./components/Banner";`. Replace the hard return `if (summary.error) ...` and the inline stale div with:

```jsx
  const pageHooks = [summary, services, trend, topResources];
  const fatal = summary.error || summary.backendError;
  if (fatal) {
    return (
      <div className="page">
        <div className="page-h"><div><h1>Dashboard</h1></div></div>
        <Banner tone="error" onRetry={summary.reload}>{fatal}</Banner>
      </div>
    );
  }
```

and inside the returned page, directly under `<div className="page-h">...</div>`:

```jsx
      <StaleBanner hooks={pageHooks} />
      {(services.backendError || trend.backendError) && (
        <Banner tone="warn" onRetry={() => { services.reload(); trend.reload(); }}>
          Some panels failed to load: {services.backendError || trend.backendError}
        </Banner>
      )}
```

Delete the old `isStale` computation and its banner div (lines 214-231).

- [ ] **Step 2: Dashboard KPI — hide the delta when the backend omitted it**

Backend omits `change_pct` when prior spend < $0.50; rendering `+0.0%` fabricates a comparison. Change the first `<Kpi>`:

```jsx
        <Kpi
          label="Period spend"
          valueText={summary.loading ? "..." : usd(s.total_mtd)}
          delta={s.change_pct == null ? undefined : value(s.change_pct)}
          note="vs previous period"
        />
```

- [ ] **Step 3: Donut — add the "Other" remainder so shares are shares of the real total**

Replace the donut data mapping (lines 263-265):

```jsx
            (() => {
              const grandTotal = value(services.data?.total);
              const topSum = serviceRows.reduce((a, r) => a + value(r.cost), 0);
              const other = Math.max(0, grandTotal - topSum);
              const segs = serviceRows.map((row, idx) => ({
                key: String(idx),
                name: (row.name || "Unknown").replace("Amazon ", "").replace("AWS ", ""),
                value: value(row.cost),
                color: palette[idx % palette.length],
              }));
              if (other > 0.005) segs.push({ key: "other", name: "Other", value: other, color: "#847A6E" });
              return <Donut data={segs} />;
            })()
```

Check `charts.jsx` `Donut`: it computes `total` from passed segments — with the Other segment included the center total now equals the period total, so no chart change is needed. If `services.data.total` turns out to be absent at runtime, fall back to `topSum` (the `Math.max(0, ...)` already makes this safe).

- [ ] **Step 4: Trend labels — keep month + year, and 2dp tooltips**

Replace the label mapping (line 204):

```jsx
  // "2026-01" -> "Jan 26", "2026-01-15" -> "Jan 15" — never a bare month number.
  const shortLabel = (raw) => {
    if (!raw) return "";
    const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(raw);
    if (!m) return raw;
    const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const mon = MON[Number(m[2]) - 1];
    return m[3] ? `${mon} ${Number(m[3])}` : `${mon} ${m[1].slice(2)}`;
  };
  const trendRows = trendValues.map((cost, idx) => ({
    month: shortLabel(trendLabels[idx]) || String(idx + 1),
    Spend: value(cost),
  }));
```

Also update the peak label in the card subtitle: replace `trendPeakLabel.slice(5) || trendPeakLabel` with `shortLabel(trendPeakLabel)`.

- [ ] **Step 5: Top-resources — retry affordance + clamped bars**

Replace the error branch (line 271-272):

```jsx
          ) : topResources.error || topResources.backendError ? (
            <Banner tone="error" onRetry={topResources.reload}>
              Resources unavailable right now: {topResources.error || topResources.backendError}
            </Banner>
          ) : ...
```

And clamp the bar width (line 285): `width: `${Math.max(0, Math.min(100, (value(row.cost) / topResourceMax) * 100))}%``.

- [ ] **Step 6: ResourcesPage — surface `incomplete`/`warnings`, fix the "More services…" select, error retry**

Replace `if (resources.error) return <div className="loading err">{resources.error}</div>;` with:

```jsx
  if (resources.error || resources.backendError) {
    return (
      <div className="page">
        <div className="page-h"><div><h1>Resources</h1></div></div>
        <Banner tone="error" onRetry={resources.reload}>{resources.error || resources.backendError}</Banner>
      </div>
    );
  }
```

After the reconciliation card (`</div>` closing `recon-card`), add:

```jsx
      {(d.incomplete || (d.warnings || []).length > 0) && (
        <Banner tone="warn" onRetry={resources.reload}>
          {(d.warnings || []).join(" ") || "Attribution incomplete — attributed totals may be understated."}
        </Banner>
      )}
      <StaleBanner hooks={[resources]} />
```

Fix the overflow select (lines 536-543) so the placeholder can't reset the filter:

```jsx
            <select
              className="btn-ctl"
              value={(d.services_summary || []).slice(0, 15).some((s) => s.service === service) ? "" : service}
              onChange={(e) => { if (e.target.value) selectService(e.target.value); }}
            >
              <option value="" disabled>More services…</option>
              {(d.services_summary || []).slice(15).map((s) => <option key={s.service} value={s.service}>{s.service}</option>)}
            </select>
```

- [ ] **Step 7: CopyIdButton — timeout cleanup + no copy button on the aggregate row**

```jsx
function CopyIdButton({ resourceId }) {
  const [copied, setCopied] = useState(null); // null | "ok" | "fail"
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const onCopy = async () => {
    const ok = await copyToClipboard(resourceId);
    setCopied(ok ? "ok" : "fail");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(null), 1500);
  };
  ...
```

(add `useRef` to the react import). In the resources table body, render the aggregate tail row without a copy button:

```jsx
                  <td>
                    {String(r.resource_id).startsWith("aggregate:")
                      ? <span className="muted faint">{r.resource_id}</span>
                      : <CopyIdButton resourceId={r.resource_id} />}
                  </td>
```

- [ ] **Step 8: AuditPage — show audit/budget failures and drop phantom fields**

```jsx
function AuditPage({ profile }) {
  const audit = useAsyncData((signal) => api.audit(profile, "all", { signal }), [profile]);
  const budgets = useAsyncData((signal) => api.budgets(profile, { signal }), [profile]);
  if (audit.error) {
    return (
      <div className="page">
        <div className="page-h"><div><h1>Audit</h1></div></div>
        <Banner tone="error" onRetry={audit.reload}>{audit.error}</Banner>
      </div>
    );
  }
  return (
    <div className="page">
      <div className="page-h">
        <div>
          <h1>Audit</h1>
          <div className="sub">Budgets, idle resources, untagged spend</div>
        </div>
      </div>
      {audit.backendError && (
        <Banner tone="warn" onRetry={audit.reload}>
          {audit.backendError} — the counts below may be incomplete.
        </Banner>
      )}
      {budgets.backendError && (
        <Banner tone="warn" onRetry={budgets.reload}>Budgets: {budgets.backendError}</Banner>
      )}
      <StaleBanner hooks={[audit, budgets]} />
      ...
```

In the budget row, replace the phantom fallback fields (line 628) with real ones, showing an explicit dash when AWS hasn't computed actuals:

```jsx
              <div className="budget-head">
                <span className="budget-name">{b.budget_name}</span>
                <span className="budget-amt">
                  {b.actual_spend == null ? "—" : usd(value(b.actual_spend))} / {b.limit_amount == null ? "—" : usd(value(b.limit_amount))}
                </span>
              </div>
```

- [ ] **Step 9: ExportPage — track success as a boolean, not a string prefix**

```jsx
  const [status, setStatus] = useState(null); // null | {ok: boolean, msg: string}
  const runExport = async () => {
    setRunning(true);
    setStatus({ ok: true, msg: "Report is generating..." });
    try {
      const res = await api.downloadExport(profile, period, fmt, fileName);
      setStatus({ ok: true, msg: `Downloaded: ${res.filename}` });
    } catch (err) {
      setStatus({ ok: false, msg: err.message || "Export failed" });
    } finally {
      setRunning(false);
    }
  };
```

and the render: `{status ? <div style={{ marginTop: 14, fontFamily: "var(--font-mono)", fontSize: 12.5, color: status.ok ? "var(--ink-3)" : "var(--neg)" }}>{status.msg}</div> : null}`

- [ ] **Step 10: ServicesPage — same error treatment**

Replace `if (services.error) ...` with the Banner+retry pattern from Step 6 (title "Services", hook `services`), and add `<StaleBanner hooks={[services]} />` under the page header.

- [ ] **Step 11: Verify + commit**

Run: `cd frontend && npx vitest run && npm run build` — Expected: PASS + clean build.

```bash
git add frontend/src/App.jsx frontend/src/charts.jsx
git commit -m "feat(frontend): error/stale/partial-data surfacing with retry on every page; donut Other segment; formatting fixes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: URL-synced app state (shareable links, working back button)

**Files:**
- Modify: `frontend/src/App.jsx` (the `App` component only)

**Interfaces:**
- Produces: `?page=resources&period=mtd&profile=default` round-trips; browser back/forward navigates pages. localStorage remains the fallback when the URL has no params.

- [ ] **Step 1: Implement**

Replace the state initialization in `App()` with:

```jsx
const readUrlState = () => {
  const q = new URLSearchParams(window.location.search);
  return { page: q.get("page"), profile: q.get("profile"), period: q.get("period") };
};

export default function App() {
  const urlInit = readUrlState();
  const [page, setPage] = useState(urlInit.page && TITLES[urlInit.page] ? urlInit.page : "dashboard");
  const [profile, setProfile] = useState(() => urlInit.profile || localStorage.getItem("acu:profile") || "default");
  const [period, setPeriod] = useState(() => urlInit.period || localStorage.getItem("acu:period") || "mtd");
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => { localStorage.setItem("acu:profile", profile); }, [profile]);
  useEffect(() => { localStorage.setItem("acu:period", period); }, [period]);

  // Keep the URL shareable: push state changes into query params, and follow
  // browser back/forward. Uses replaceState for profile/period tweaks and
  // pushState for page changes so Back navigates pages, not every dropdown touch.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const prevPage = q.get("page");
    q.set("page", page); q.set("period", period); q.set("profile", profile);
    const url = `${window.location.pathname}?${q.toString()}`;
    if (prevPage !== null && prevPage !== page) window.history.pushState({}, "", url);
    else window.history.replaceState({}, "", url);
  }, [page, period, profile]);

  useEffect(() => {
    const onPop = () => {
      const s = readUrlState();
      if (s.page && TITLES[s.page]) setPage(s.page);
      if (s.period) setPeriod(s.period);
      if (s.profile) setProfile(s.profile);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
```

(the rest of `App` is unchanged).

- [ ] **Step 2: Verify + commit**

Run: `cd frontend && npm run build` — Expected: clean build.

```bash
git add frontend/src/App.jsx
git commit -m "feat(frontend): sync page/period/profile to URL query params

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Self-hosted fonts, favicon, responsive/accessibility quick wins

**Files:**
- Modify: `frontend/index.html`, `frontend/package.json`, `frontend/src/main.jsx`, `frontend/src/tokens.css`, `frontend/src/App.jsx` (select labels)

- [ ] **Step 1: Bundle the fonts**

```bash
cd frontend && npm install @fontsource/hanken-grotesk @fontsource/jetbrains-mono
```

In `frontend/src/main.jsx`, add at the top (before CSS imports):

```js
import "@fontsource/hanken-grotesk/400.css";
import "@fontsource/hanken-grotesk/500.css";
import "@fontsource/hanken-grotesk/600.css";
import "@fontsource/hanken-grotesk/700.css";
import "@fontsource/hanken-grotesk/800.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
```

In `frontend/index.html`: delete the two `<link rel="preconnect">` lines and the Google Fonts stylesheet link, and add a favicon:

```html
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>💸</text></svg>" />
```

- [ ] **Step 2: Accessibility — label the topbar selects and restore a visible focus ring**

In `Topbar` (App.jsx): add `aria-label="Period"` to the period `<select>` and `aria-label="AWS profile"` to the profile `<select>`.
In `tokens.css` find `.btn-ctl:focus { outline: none` (~line 433) and replace the rule with:

```css
.btn-ctl:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
```

- [ ] **Step 3: Responsive minimum — tables scroll instead of breaking the page**

In `tokens.css`, add at the end:

```css
/* Below the desktop breakpoint, let wide tables scroll inside their card
   instead of forcing horizontal page scroll. */
.tbl-wrap { overflow-x: auto; }
@media (max-width: 900px) {
  .app { grid-template-columns: 1fr; }
  .side { display: none; }
}
```

Note: hiding the sidebar under 900px is a stopgap — navigation on mobile then relies on URL params (Task 9). Acceptable for launch; a drawer is follow-up work.

- [ ] **Step 4: Verify + commit**

Run: `cd frontend && npm run build` — Expected: clean build, and `grep -rn "fonts.googleapis" dist/` returns nothing.

```bash
git add frontend/index.html frontend/package.json frontend/package-lock.json frontend/src/main.jsx frontend/src/tokens.css frontend/src/App.jsx
git commit -m "feat(frontend): self-hosted fonts, favicon, focus ring, responsive table overflow

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: Working run scripts + fresh committed dist + README quickstart

**Files:**
- Modify: `run.sh`, `run.bat`, `README.md`
- Rebuild + recommit: `frontend/dist/` (delete stale tracked bundles first)

**Interfaces:**
- Consumes: `pip install -e ".[web,cur]"` extras from pyproject; server entry `python -m aws_cost_ultra.web.app` on port 8080; `/app` served from `frontend/dist`.

- [ ] **Step 1: Rewrite `run.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "  aws-cost-ultra"
echo "============================================"
echo

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is not installed or not in PATH."
    exit 1
fi

if [ ! -f "venv/bin/activate" ]; then
    if [ -d "venv" ]; then
        echo "Removing incompatible virtual environment (created on another OS)..."
        rm -rf venv
    fi
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -e ".[web,cur]"

echo
echo "Starting dashboard at http://127.0.0.1:8080/app"
echo "Press Ctrl+C to stop."
echo
python -m aws_cost_ultra.web.app
```

- [ ] **Step 2: Rewrite `run.bat`**

```bat
@echo off
cd /d "%~dp0"
echo ============================================
echo   aws-cost-ultra
echo ============================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install --quiet --upgrade pip
pip install --quiet -e ".[web,cur]"

echo.
echo Starting dashboard at http://127.0.0.1:8080/app
echo Press Ctrl+C to stop.
echo.
python -m aws_cost_ultra.web.app
```

- [ ] **Step 3: Verify run.sh end-to-end**

```bash
bash run.sh &
sleep 12
curl -sf http://127.0.0.1:8080/app | head -c 200
curl -sf "http://127.0.0.1:8080/api/ui/context" | head -c 200
kill %1
```

Expected: `/app` returns the React index.html, `/api/ui/context` returns JSON. (AWS credentials not needed for these two.)

- [ ] **Step 4: Rebuild dist and recommit fresh**

```bash
git rm -r --quiet frontend/dist
cd frontend && npm run build && cd ..
git add -f frontend/dist
```

- [ ] **Step 5: Update README quickstart**

In `README.md`: replace the quickstart section so it reads (adjust surrounding prose to match reality — port 8080, `/app`, no HTMX):

````markdown
## Quickstart

```bash
git clone <repo-url>
cd aws-cost-dashboard
./run.sh          # Windows: run.bat
```

Then open http://127.0.0.1:8080/app

The run script creates a virtualenv, installs the package with the `web`
and `cur` extras, and starts the server. A pre-built frontend is committed
under `frontend/dist/`, so Node.js is **not** required to run the dashboard.

### Hacking on the frontend

```bash
cd frontend
npm install
npm run dev      # Vite dev server on :5173, proxying /api to :8080
npm run build    # refresh frontend/dist served at /app
```

### Security note

The server binds to 127.0.0.1 by default. If you expose it on any other
interface, set `ACU_AUTH_TOKEN` — never run it unauthenticated on a network.
````

Also remove any README references to HTMX/templates if present.

- [ ] **Step 6: Add the LICENSE file (README/pyproject already claim MIT; without this file the project is legally all-rights-reserved)**

Create `LICENSE` at repo root with the standard MIT license text:

```text
MIT License

Copyright (c) 2026 aws-cost-ultra contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 7: Commit**

```bash
git add run.sh run.bat README.md LICENSE
git commit -m "fix(scripts): working run.sh/run.bat (editable install, real entrypoint, port 8080); fresh dist; LICENSE; README quickstart

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: Final verification sweep

- [ ] **Step 1: Full backend tests** — `venv/bin/python -m pytest tests/ -q` → all PASS.
- [ ] **Step 2: Frontend tests + build** — `cd frontend && npx vitest run && npm run build` → PASS.
- [ ] **Step 3: Sensitive-data sweep over tracked files**

```bash
git ls-files -z | xargs -0 grep -lE "012178638401|463062864564|creatorx|acu-cur-" ; echo "exit=$?"
```

Expected: no output (exit 1/123).

- [ ] **Step 4: Boot + click-through** — run `bash run.sh`, open `http://127.0.0.1:8080/app`, verify: dashboard loads; with no/expired AWS creds an error banner with a Retry button appears (NOT $0.000 KPIs); URL updates when switching pages; back button works; export failure shows red text.
- [ ] **Step 5: `git status` is clean** (everything committed).
