import { readSwr, writeSwr } from "./lib/swrCache";

const toParams = (params) => {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  return q.toString();
};

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
    if (err?.name === "AbortError") throw err;
    if (cached) return { data: cached.value, meta: { ceCalls: 0, ceCostUsd: 0, fromCache: "stale" } };
    throw err;
  }
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
