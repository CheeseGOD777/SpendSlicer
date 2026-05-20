const toParams = (params) => {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  return q.toString();
};

const getJson = async (path, params = {}) => {
  const qs = toParams(params);
  const res = await fetch(`${path}${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
};

export const api = {
  context: (profile, period) => getJson("/api/ui/context", { profile, period }),
  summary: (profile, period) => getJson("/api/cost/summary/data", { profile, period }),
  services: (profile, period, limit = 0) =>
    getJson("/api/cost/services/data", { profile, period, limit }),
  trend: (profile, period) => getJson("/api/cost/trend/data", { profile, period }),
  trendTable: (profile, period) => getJson("/api/cost/trend-table/data", { profile, period }),
  resources: (profile, period, region = "all", service = "", limit = 0) =>
    getJson("/api/resources/data", { profile, period, region, service, limit }),
  resourcesTop: (profile, period, region = "all", limit = 10) =>
    getJson("/api/resources/top/data", { profile, period, region, limit }),
  audit: (profile, region = "all") => getJson("/api/audit/summary/data", { profile, region }),
  budgets: (profile) => getJson("/api/budgets/data", { profile }),
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
