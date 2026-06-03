import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { useAsyncData } from "./hooks/useAsyncData";
import { useDebounced } from "./hooks/useDebounced";
import { Donut, StackedBars } from "./charts";
import { CostBadge } from "./components/CostBadge";

const NAV = [
  { group: "Visibility", items: ["dashboard", "services", "resources"] },
  { group: "FinOps", items: ["audit", "export"] },
];

const TITLES = {
  dashboard: "Dashboard",
  services: "Services",
  resources: "Resources",
  audit: "Audit",
  export: "Export",
};

const usd = (n, dec = 3) => {
  let num = Number(n || 0);
  // CE sometimes returns tiny negative floats (-0.00001); clamp to zero before display
  if (num < 0 && Math.abs(num) < 5 * Math.pow(10, -(dec + 1))) num = 0;
  return `$${num.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec })}`;
};
const pct = (n) => `${n >= 0 ? "+" : ""}${Number(n || 0).toFixed(1)}%`;
const value = (v, fallback = 0) => Number(v ?? fallback);

const PERIOD_LABEL = {
  mtd: "month to date",
  "30d": "last 30 days",
  "60d": "last 60 days",
  "90d": "last 90 days",
  last_month: "previous month",
  "3m": "rolling 3 months",
  "6m": "trailing 6 months",
  "12m": "trailing 12 months",
};
const periodLabel = (p) => PERIOD_LABEL[p] || p;

// Copy text to clipboard with a fallback for insecure contexts (plain HTTP LAN)
// where navigator.clipboard is unavailable or its write promise rejects.
// Returns true on success, false on failure.
async function copyToClipboard(text) {
  const value = String(text ?? "");
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // fall through to legacy fallback
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

// Defensive client-side render cap. The server already bounds the row count,
// but we paginate to keep the DOM small even at the cap.
const RESOURCE_PAGE_SIZE = 100;
// Bounded limit requested from the backend (instead of the old unbounded 0).
const RESOURCE_FETCH_LIMIT = 200;


function Sidebar({ page, setPage, profile, collapsed, setCollapsed }) {
  return (
    <aside className="side">
      <div className="side-brand">
        <div className="side-logo">CL</div>
        <div className="side-brand-text">
          <span className="name">Cloud Ledger</span>
          <span className="tag">FinOps Edition</span>
        </div>
      </div>
      <button className="collapse-btn" onClick={() => setCollapsed((v) => !v)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>{collapsed ? ">" : "<"}</button>
      <nav style={{ flex: 1 }}>
        {NAV.map((g) => (
          <div key={g.group} className="side-group">
            <div className="side-group-label">{g.group}</div>
            {g.items.map((it) => (
              <button
                key={it}
                type="button"
                className={`side-item ${page === it ? "active" : ""}`}
                onClick={() => setPage(it)}
                aria-current={page === it ? "page" : undefined}
              >
                <span className="side-item-text">{TITLES[it]}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div className="side-bottom">
        <div className="side-profile">
          <div className="side-avatar">{(profile || "p")[0].toUpperCase()}</div>
          <div className="side-profile-text"><span className="side-profile-name">{profile}</span></div>
        </div>
      </div>
    </aside>
  );
}

function Topbar({ period, setPeriod, profile, setProfile, context }) {
  return (
    <div className="topbar">
      <div className="topbar-meta">
        <span className="live-dot" /><span className="live-text">Live</span><span className="meta-sep" />
        <span className="meta-text">{context?.cost_basis_label || "Pre-credit"}</span>
      </div>
      <div className="topbar-controls">
        <select className="btn-ctl is-mono" value={period} onChange={(e) => setPeriod(e.target.value)}>
          {context?.periods?.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        <select className="btn-ctl" value={profile} onChange={(e) => setProfile(e.target.value)}>
          {context?.profile_choices?.map((p) => <option key={p.profile} value={p.profile}>{p.label}</option>)}
        </select>
      </div>
    </div>
  );
}

function Kpi({ label, valueText, delta, note }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{valueText}</div>
      <div className="kpi-foot">
        {delta !== undefined && <span className={`delta ${delta <= 0 ? "pos" : "neg"}`}>{pct(delta)}</span>}
        {note && <span className="delta-note">{note}</span>}
      </div>
    </div>
  );
}

function DashboardPage({ profile, period }) {
  const [warmingTick, setWarmingTick] = useState(0);
  const summary = useAsyncData((signal) => api.summary(profile, period, { signal }), [profile, period]);
  const services = useAsyncData((signal) => api.services(profile, period, 8, { signal }), [profile, period]);
  const trend = useAsyncData((signal) => api.trend(profile, period, { signal }), [profile, period]);
  const topResources = useAsyncData(
    (signal) => api.resourcesTop(profile, period, "all", 10, { signal }),
    [profile, period, warmingTick],
  );
  // While the backend is still computing resource attribution, poll every
  // 3s so the user doesn't have to manually refresh.
  useEffect(() => {
    if (!topResources.data?.warming) return;
    const t = setTimeout(() => setWarmingTick((n) => n + 1), 3000);
    return () => clearTimeout(t);
  }, [topResources.data?.warming, warmingTick]);

  if (summary.error) return <div className="loading err">{summary.error}</div>;

  const s = summary.data || {};
  const serviceRows = (services.data?.services || []).slice(0, 6);
  const trendValues = trend.data?.values || [];
  const trendLabels = trend.data?.labels || [];
  const trendRows = trendValues.map((cost, idx) => ({
    month: trendLabels[idx]?.slice(5) || trendLabels[idx] || String(idx + 1),
    Spend: value(cost),
  }));
  const trendMax = Math.max(...trendValues, 0);
  const trendAvg = trendValues.length ? trendValues.reduce((a, b) => a + value(b), 0) / trendValues.length : 0;
  const trendPeakLabel = trendLabels[trendValues.findIndex((x) => x === trendMax)] || "";
  const topResourcesRows = (topResources.data?.rows || []).slice(0, 10);
  const topResourceMax = Math.max(...topResourcesRows.map((r) => value(r.cost, 1)), 1);
  const palette = ["#1C5E3F", "#2D5478", "#9E3B2E", "#A77418", "#1F6E6E", "#5D3A53", "#6E6048", "#847A6E"];

  return (
    <div className="page">
      <div className="page-h">
        <div>
          <h1>Dashboard</h1>
          <div className="sub">{profile} <span style={{ margin: "0 6px", opacity: 0.5 }}>—</span> {periodLabel(period)}</div>
        </div>
      </div>
      <div className="kpi-row">
        <Kpi label="Period spend" valueText={summary.loading ? "..." : usd(s.total_mtd)} delta={value(s.change_pct)} note="vs previous period" />
        <Kpi label="Previous period" valueText={summary.loading ? "..." : usd(s.total_prev)} note="comparison baseline" />
        <Kpi label="Forecast" valueText={summary.loading ? "..." : usd(s.forecast)} note="projected month close" />
        <Kpi label="Top service" valueText={summary.loading ? "..." : s.top_service_name || "-"} note={usd(s.top_service_cost)} />
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-title">
          <div>
            <h2>Spend Trend</h2>
            <div className="sub" style={{ marginTop: 4 }}>
              Selected period trend
              {trendValues.length > 0 && (
                <>
                  {" · "}peak <span className="mono">{usd(trendMax, 2)}</span>
                  {trendPeakLabel ? ` on ${trendPeakLabel.slice(5) || trendPeakLabel}` : ""}
                  {" · "}avg <span className="mono">{usd(trendAvg, 2)}</span>
                  {" · "}{trendValues.length} samples
                </>
              )}
            </div>
          </div>
        </div>
        {trend.loading ? <div className="skel skel-kpi" /> : trendRows.length >= 2 ? <StackedBars data={trendRows} keys={["Spend"]} /> : <div className="loading">No chart for this period (needs at least 2 points).</div>}
      </div>

      <div className="split" style={{ marginTop: 24 }}>
        <div className="card">
          <div className="card-title"><div><h2>Service mix</h2><div className="sub" style={{ marginTop: 4 }}>Share of period spend</div></div></div>
          {services.loading ? <div className="skel skel-kpi" /> : (
            <Donut data={serviceRows.map((row, idx) => ({
              key: String(idx), name: (row.name || "Unknown").replace("Amazon ", "").replace("AWS ", ""), value: value(row.cost), color: palette[idx % palette.length],
            }))} />
          )}
        </div>

        <div className="tbl-wrap">
          <div className="tbl-head-row"><h2>Top 10 resources</h2></div>
          {topResources.loading ? <div><div className="skel skel-row" /><div className="skel skel-row" /><div className="skel skel-row" /></div> : topResources.error ? (
            <div className="loading err">Resources unavailable right now. Please retry in a few seconds.</div>
          ) : topResources.data?.warming ? (
            <div className="loading">Resource attribution is warming up. Refresh in a few seconds.</div>
          ) : (
            <table className="tbl">
              <thead><tr><th>Service</th><th>Resource</th><th style={{ textAlign: "right" }}>Cost</th></tr></thead>
              <tbody>
                {topResourcesRows.map((row) => (
                  <tr key={`${row.service}-${row.resource_id}`}>
                    <td>{row.service}</td>
                    <td style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.name || row.resource_id}</td>
                    <td className="num">{usd(row.cost)}
                      <div className="cell-bar-track" style={{ marginTop: 6, maxWidth: 140, marginLeft: "auto" }}>
                        <div className="cell-bar-fill" style={{ width: `${(value(row.cost) / topResourceMax) * 100}%` }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

const COMPOSITION_BUCKETS = ["compute", "storage", "data-transfer", "network", "other"];
const COMPOSITION_COLORS = {
  compute: "#1C5E3F",        // emerald
  storage: "#2D5478",        // navy
  "data-transfer": "#A77418", // ochre
  network: "#1F6E6E",        // deep teal
  other: "#847A6E",          // stone
};

function ServiceComposition({ buckets }) {
  if (!buckets) return <div className="comp-empty">No composition data for this service.</div>;
  const total = COMPOSITION_BUCKETS.reduce((s, k) => s + value(buckets[k]), 0);
  if (total <= 0) return <div className="comp-empty">No composition data for this service.</div>;
  const rows = COMPOSITION_BUCKETS
    .map((k) => ({ key: k, amount: value(buckets[k]), pct: (value(buckets[k]) / total) * 100 }))
    .filter((r) => r.amount > 0)
    .sort((a, b) => b.amount - a.amount);
  return (
    <div className="comp-wrap">
      <div className="comp-bar">
        {rows.map((r) => (
          <span
            key={r.key}
            className="comp-bar-seg"
            style={{ width: `${r.pct}%`, background: COMPOSITION_COLORS[r.key] }}
            title={`${r.key}: ${usd(r.amount, 2)} (${r.pct.toFixed(1)}%)`}
          />
        ))}
      </div>
      <ul className="comp-legend">
        {rows.map((r) => (
          <li key={r.key}>
            <span className="comp-dot" style={{ background: COMPOSITION_COLORS[r.key] }} />
            <span className="comp-key">{r.key}</span>
            <span className="comp-amt mono">{usd(r.amount, 2)}</span>
            <span className="comp-pct mono">{r.pct.toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ServicesPage({ profile, period }) {
  const services = useAsyncData((signal) => api.services(profile, period, 0, { signal }), [profile, period]);
  const composition = useAsyncData(
    (signal) => api.servicesComposition(profile, period, { signal }),
    [profile, period],
  );
  const [expanded, setExpanded] = useState(null);
  const [visible, setVisible] = useState(RESOURCE_PAGE_SIZE);
  if (services.error) return <div className="loading err">{services.error}</div>;
  const compMap = composition.data?.services || {};
  const allRows = services.data?.services || [];
  const rows = allRows.slice(0, visible);
  return (
    <div className="page">
      <div className="page-h">
        <div>
          <h1>Services</h1>
          <div className="sub">Click a row to see what's driving its bill (compute, storage, data transfer, network).</div>
        </div>
      </div>
      {services.loading ? <div><div className="skel skel-row" /><div className="skel skel-row" /><div className="skel skel-row" /></div> : (
        <div className="tbl-wrap">
          <table className="tbl tbl-svc">
            <thead>
              <tr>
                <th style={{ width: 28 }} />
                <th>Service</th>
                <th style={{ textAlign: "right" }}>Cost</th>
                <th style={{ textAlign: "right" }}>Share</th>
                <th style={{ textAlign: "right" }}>Vs prior</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isOpen = expanded === row.name;
                const toggle = () => setExpanded(isOpen ? null : row.name);
                return (
                  <Fragment key={row.name}>
                    <tr className={`svc-row ${isOpen ? "open" : ""}`} onClick={toggle}>
                      <td className="svc-caret">{isOpen ? "▾" : "▸"}</td>
                      <td>{row.name}</td>
                      <td className="num">{usd(row.cost)}</td>
                      <td className="num">{Number(row.pct_of_total || 0).toFixed(1)}%</td>
                      <td className="num">{pct(row.change_pct || 0)}</td>
                    </tr>
                    {isOpen && (
                      <tr className="svc-row-detail">
                        <td colSpan={5}>
                          {composition.loading
                            ? <div className="skel skel-row" />
                            : <ServiceComposition buckets={compMap[row.name]} />}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          {visible < allRows.length && (
            <div style={{ marginTop: 12 }}>
              <button type="button" className="btn" onClick={() => setVisible((v) => v + RESOURCE_PAGE_SIZE)}>
                Show more ({allRows.length - visible} more)
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CopyIdButton({ resourceId }) {
  const [copied, setCopied] = useState(null); // null | "ok" | "fail"
  const onCopy = async () => {
    const ok = await copyToClipboard(resourceId);
    setCopied(ok ? "ok" : "fail");
    setTimeout(() => setCopied(null), 1500);
  };
  return (
    <button
      className="copy-id"
      onClick={onCopy}
      title={copied === "ok" ? "Copied" : copied === "fail" ? "Copy failed" : "Copy resource ID"}
    >
      {copied === "ok" ? "Copied ✓" : copied === "fail" ? "Copy failed" : resourceId}
    </button>
  );
}

function ResourcesPage({ profile, period }) {
  const [service, setService] = useState("");
  const [limit, setLimit] = useState(RESOURCE_FETCH_LIMIT);
  const [visible, setVisible] = useState(RESOURCE_PAGE_SIZE);
  const debouncedService = useDebounced(service, 300);
  const resources = useAsyncData(
    (signal) => api.resources(profile, period, "all", debouncedService, limit, { signal }),
    [profile, period, debouncedService, limit]
  );
  // Reset client-side pagination when the filter or fetch size changes.
  useEffect(() => { setVisible(RESOURCE_PAGE_SIZE); }, [debouncedService, limit]);
  // Reset the requested fetch limit back to default when the filter changes.
  useEffect(() => { setLimit(RESOURCE_FETCH_LIMIT); }, [debouncedService]);
  if (resources.error) return <div className="loading err">{resources.error}</div>;
  const d = resources.data || {};
  const allRows = d.rows || [];
  const shownRows = allRows.slice(0, visible);
  const totalCount = Number(d.total_count ?? allRows.length);
  // How many rows the server actually returned (bounded by the requested limit).
  const fetchedCount = allRows.length;
  return (
    <div className="page">
      <div className="page-h">
        <div>
          <h1>Resources</h1>
          <div className="sub">Per-resource attribution reconciled against Cost Explorer total</div>
        </div>
      </div>
      <div className="recon-card">
        <div className="recon-head">
          <h2>Reconciliation Overview</h2>
          <p>
            Total Attributed = sum of resource-level costs we could map.
            Drift = CE total minus attributed remainder (charges not yet attributable to a specific resource row).
          </p>
        </div>
        <div className="recon-stats">
          <div className="recon-stat"><span className="recon-stat-label">Total Attributed</span><span className="recon-stat-val">{usd(d.total)}</span></div>
          <div className="recon-stat"><span className="recon-stat-label">CE Total</span><span className="recon-stat-val">{usd(d.ce_total)}</span></div>
          <div className="recon-stat"><span className="recon-stat-label">Drift</span><span className="recon-stat-val drift">{usd(d.unattributed)}</span></div>
        </div>
      </div>
      <div className="svc-filter-row">
        <span className="svc-filter-label">Services:</span>
        <div className="pill-tabs">
          <button type="button" className={`pill-tab ${service === "" ? "dark" : ""}`} onClick={() => setService("")}>All</button>
          {(d.services_summary || []).map((s) => <button key={s.service} type="button" className={`pill-tab ${service === s.service ? "dark" : ""}`} onClick={() => setService(s.service)}>{s.service}</button>)}
        </div>
      </div>
      {resources.loading ? <div><div className="skel skel-row" /><div className="skel skel-row" /><div className="skel skel-row" /></div> : (
        <div className="tbl-wrap">
          {totalCount > fetchedCount && (
            <div className="sub" style={{ marginBottom: 8 }}>
              Showing {Math.min(visible, fetchedCount)} of {totalCount} resources.
            </div>
          )}
          <table className="tbl tbl-res">
            <thead>
              <tr>
                <th>Name</th>
                <th>Service</th>
                <th>Resource ID</th>
                <th style={{ textAlign: "right" }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {shownRows.map((r) => (
                <tr key={`${r.service}-${r.resource_id}`}>
                  <td><strong>{r.name || r.resource_id}</strong></td>
                  <td className="muted">{r.service}</td>
                  <td>
                    <CopyIdButton resourceId={r.resource_id} />
                  </td>
                  <td className="num">{usd(r.cost, 2)}</td>
                </tr>
              ))}
              {!service && value(d.unattributed) > 0.01 && visible >= fetchedCount && (
                <tr className="unattributed-row">
                  <td><span className="unattributed-label">Unattributed charges</span><span className="unattributed-hint"> — likely terminated / deleted resources</span></td>
                  <td className="muted">—</td>
                  <td className="muted faint">gap vs CE total</td>
                  <td className="num">{usd(d.unattributed, 2)}</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="res-controls" style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
            {visible < fetchedCount && (
              <button type="button" className="btn" onClick={() => setVisible((v) => v + RESOURCE_PAGE_SIZE)}>
                Show more ({fetchedCount - visible} more loaded)
              </button>
            )}
            {visible >= fetchedCount && totalCount > fetchedCount && (
              <button type="button" className="btn" onClick={() => setLimit((l) => l + RESOURCE_FETCH_LIMIT)}>
                Load more from server ({totalCount - fetchedCount} not yet loaded)
              </button>
            )}
          </div>
        </div>
      )}
      {(d.rows || []).length === 0 && !resources.loading && (
        <div className="empty-state">
          <p>No resources attributed for this window.</p>
          <p className="muted">
            If you just enabled CUR, data takes ~24h to arrive. Run{" "}
            <code>aws-cost-ultra cur status</code> to check.
          </p>
        </div>
      )}
    </div>
  );
}

function AuditPage({ profile }) {
  const audit = useAsyncData((signal) => api.audit(profile, "all", { signal }), [profile]);
  const budgets = useAsyncData((signal) => api.budgets(profile, { signal }), [profile]);
  if (audit.error) return <div className="loading err">{audit.error}</div>;
  return (
    <div className="page">
      <div className="page-h">
        <div>
          <h1>Audit</h1>
          <div className="sub">Budgets, idle resources, untagged spend</div>
        </div>
      </div>
      <div className="grid-2" style={{ marginBottom: 20 }}>
        <div className="budget-card">
          <h2 style={{ marginTop: 0 }}>Budgets</h2>
          {budgets.loading ? <div><div className="skel skel-row" /><div className="skel skel-row" /></div> : (budgets.data?.findings || []).map((b, idx) => (
            <div className="budget-row" key={b.budget_name}>
              <div className="budget-head"><span className="budget-name">{b.budget_name}</span><span className="budget-amt">{usd(value(b.actual_spend, b.actual_spend_usd))} / {usd(value(b.limit_amount, b.limit_usd))}</span></div>
              <div className="budget-track"><div className={`budget-fill ${b.status === "breached" ? "danger" : b.status === "warning" ? "warn" : ""}`} style={{ width: `${Math.min(100, value(b.utilization_pct, idx === 0 ? 0 : 10))}%` }} /></div>
            </div>
          ))}
        </div>
        <div className="col">
          <div className="card card-tight">Idle findings: {(audit.data?.idle || []).length}</div>
          <div className="card card-tight">Untagged findings: {(audit.data?.untagged || []).length}</div>
        </div>
      </div>
    </div>
  );
}

function ExportPage({ profile, period }) {
  const [fmt, setFmt] = useState("pdf");
  const [fileName, setFileName] = useState("");
  const [status, setStatus] = useState("");
  const [running, setRunning] = useState(false);
  const runExport = async () => {
    setRunning(true);
    setStatus("Report is generating...");
    try {
      const res = await api.downloadExport(profile, period, fmt, fileName);
      setStatus(`Downloaded: ${res.filename}`);
    } catch (err) {
      setStatus(err.message || "Export failed");
    } finally {
      setRunning(false);
    }
  };
  return (
    <div className="page">
      <div className="page-h">
        <div>
          <h1>Export</h1>
          <div className="sub">Generate a snapshot of this window for sharing or archiving</div>
        </div>
      </div>
      <div className="card" style={{ maxWidth: 560 }}>
        <div className="form-row">
          <label>Format</label>
          <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
            <option value="pdf">PDF</option>
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
        </div>
        <div className="form-row">
          <label>File name (optional)</label>
          <input type="text" placeholder={`cloud_ledger_report.${fmt}`} value={fileName} onChange={(e) => setFileName(e.target.value)} />
        </div>
        <button className="btn btn-primary" onClick={runExport} disabled={running}>
          {running ? "Generating…" : "Generate report"}
        </button>
        {status ? <div style={{ marginTop: 14, fontFamily: "var(--font-mono)", fontSize: 12.5, color: status.startsWith("Failed") || status.startsWith("Export") ? "var(--neg)" : "var(--ink-3)" }}>{status}</div> : null}
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [profile, setProfile] = useState(() => localStorage.getItem("acu:profile") || "default");
  const [period, setPeriod] = useState(() => localStorage.getItem("acu:period") || "mtd");
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => { localStorage.setItem("acu:profile", profile); }, [profile]);
  useEffect(() => { localStorage.setItem("acu:period", period); }, [period]);
  const contextState = useAsyncData((signal) => api.context(profile, period, { signal }), [profile, period]);

  useEffect(() => {
    if (!contextState.data) return;
    const validProfiles = contextState.data.profiles || [];
    if (validProfiles.length > 0 && !validProfiles.includes(profile)) setProfile(validProfiles[0]);
    const validPeriods = (contextState.data.periods || []).map((p) => p.value);
    if (validPeriods.length > 0 && !validPeriods.includes(period)) setPeriod(validPeriods[0]);
  }, [contextState.data, profile, period]);

  const pageNode = useMemo(() => {
    if (page === "services") return <ServicesPage profile={profile} period={period} />;
    if (page === "resources") return <ResourcesPage profile={profile} period={period} />;
    if (page === "audit") return <AuditPage profile={profile} />;
    if (page === "export") return <ExportPage profile={profile} period={period} />;
    return <DashboardPage profile={profile} period={period} />;
  }, [page, profile, period]);

  return (
    <div className={`app ${collapsed ? "collapsed" : ""}`}>
      <Sidebar page={page} setPage={setPage} profile={profile} collapsed={collapsed} setCollapsed={setCollapsed} />
      <div className="main">
        <Topbar context={contextState.data} period={period} setPeriod={setPeriod} profile={profile} setProfile={setProfile} />
        <div className="scroll">{pageNode}</div>
      </div>
      <CostBadge />
    </div>
  );
}
