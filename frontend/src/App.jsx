import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { useAsyncData } from "./hooks/useAsyncData";
import { useDebounced } from "./hooks/useDebounced";
import { AreaChart, Donut, StackedBars } from "./charts";

const NAV = [
  { group: "Visibility", items: ["dashboard", "services", "resources", "trends"] },
  { group: "FinOps", items: ["audit", "export"] },
];

const TITLES = {
  dashboard: "Dashboard",
  services: "Services",
  resources: "Resources",
  trends: "Trends",
  audit: "Audit",
  export: "Export",
};

const usd = (n, dec = 3) =>
  `$${Number(n || 0).toLocaleString("en-US", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  })}`;
const pct = (n) => `${n >= 0 ? "+" : ""}${Number(n || 0).toFixed(1)}%`;
const value = (v, fallback = 0) => Number(v ?? fallback);


function Sidebar({ page, setPage, profile, collapsed, setCollapsed }) {
  return (
    <aside className="side">
      <div className="side-brand">
        <div className="side-logo"><span style={{ fontWeight: 700 }}>CL</span></div>
        <div className="side-brand-text"><span className="name">Cloud Ledger</span><span className="tag">finops</span></div>
      </div>
      <button className="collapse-btn" onClick={() => setCollapsed((v) => !v)}>{collapsed ? ">" : "<"}</button>
      <nav style={{ flex: 1 }}>
        {NAV.map((g) => (
          <div key={g.group} className="side-group">
            <div className="side-group-label">{g.group}</div>
            {g.items.map((it) => (
              <div key={it} className={`side-item ${page === it ? "active" : ""}`} onClick={() => setPage(it)}>
                <span className="side-item-text">{TITLES[it]}</span>
              </div>
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
        {delta !== undefined ? <span className={`delta ${delta <= 0 ? "pos" : "neg"}`}>{pct(delta)}</span> : <span className="delta flat">—</span>}
        {note ? <span className="delta-note">{note}</span> : null}
      </div>
    </div>
  );
}

function DashboardPage({ profile, period }) {
  const summary = useAsyncData((signal) => api.summary(profile, period, { signal }), [profile, period]);
  const services = useAsyncData((signal) => api.services(profile, period, 8, { signal }), [profile, period]);
  const trend = useAsyncData((signal) => api.trend(profile, period, { signal }), [profile, period]);
  const topResources = useAsyncData((signal) => api.resourcesTop(profile, period, "all", 10, { signal }), [profile, period]);
  if (summary.error) return <div className="loading err">{summary.error}</div>;

  const s = summary.data || {};
  const serviceRows = (services.data?.services || []).slice(0, 6);
  const trendRows = (trend.data?.values || []).map((cost, idx) => ({
    month: trend.data?.labels?.[idx]?.slice(5) || trend.data?.labels?.[idx] || String(idx + 1),
    Spend: value(cost),
  }));
  const spark = trend.data?.values || [];
  const topResourcesRows = (topResources.data?.rows || []).slice(0, 10);
  const topResourceMax = Math.max(...topResourcesRows.map((r) => value(r.cost, 1)), 1);
  const palette = ["#0E9F6E", "#3B5BDB", "#A24DDD", "#DB8E1B", "#11AABE", "#555555"];

  return (
    <div className="page">
      <div className="page-h"><div><h1>Dashboard</h1><div className="sub">{profile} · period={period}</div></div></div>
      <div className="kpi-row">
        <Kpi label="Period spend" valueText={summary.loading ? "..." : usd(s.total_mtd)} delta={value(s.change_pct)} note="vs previous period" />
        <Kpi label="Previous period" valueText={summary.loading ? "..." : usd(s.total_prev)} note="comparison baseline" />
        <Kpi label="Forecast" valueText={summary.loading ? "..." : usd(s.forecast)} note="projected month close" />
        <Kpi label="Top service" valueText={summary.loading ? "..." : s.top_service_name || "-"} note={usd(s.top_service_cost)} />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title"><div><h2>Spend Trend</h2><div className="sub" style={{ marginTop: 4 }}>Selected period trend</div></div></div>
        {trend.loading ? <div className="loading">Loading trend...</div> : trendRows.length >= 2 ? <StackedBars data={trendRows} keys={["Spend"]} /> : <div className="loading">No chart for this period (needs at least 2 points).</div>}
      </div>

      <div className="split" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-title"><div><h2>Service mix</h2><div className="sub" style={{ marginTop: 4 }}>Share of period spend</div></div></div>
          {services.loading ? <div className="loading">Loading service mix...</div> : (
            <Donut data={serviceRows.map((row, idx) => ({
              key: String(idx), name: (row.name || "Unknown").replace("Amazon ", "").replace("AWS ", ""), value: value(row.cost), color: palette[idx % palette.length],
            }))} />
          )}
        </div>

        <div className="tbl-wrap">
          <div className="tbl-head-row"><h2>Top 10 resources</h2></div>
          {topResources.loading ? <div className="loading">Loading resources...</div> : topResources.error ? (
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

function ServicesPage({ profile, period }) {
  const services = useAsyncData((signal) => api.services(profile, period, 0, { signal }), [profile, period]);
  if (services.error) return <div className="loading err">{services.error}</div>;
  return (
    <div className="page">
      <div className="page-h"><h1>Services</h1></div>
      {services.loading ? <div className="loading">Loading services...</div> : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Service</th><th style={{ textAlign: "right" }}>Cost</th><th style={{ textAlign: "right" }}>Share</th><th style={{ textAlign: "right" }}>Vs prior</th></tr></thead>
            <tbody>
              {(services.data?.services || []).map((row) => (
                <tr key={row.name}><td>{row.name}</td><td className="num">{usd(row.cost)}</td><td className="num">{Number(row.pct_of_total || 0).toFixed(1)}%</td><td className="num">{pct(row.change_pct || 0)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ResourcesPage({ profile, period }) {
  const [service, setService] = useState("");
  const debouncedService = useDebounced(service, 300);
  const resources = useAsyncData(
    (signal) => api.resources(profile, period, "all", debouncedService, 0, { signal }),
    [profile, period, debouncedService]
  );
  if (resources.error) return <div className="loading err">{resources.error}</div>;
  const d = resources.data || {};
  return (
    <div className="page">
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
          <div className={`pill-tab ${service === "" ? "dark" : ""}`} onClick={() => setService("")}>All</div>
          {(d.services_summary || []).map((s) => <div key={s.service} className={`pill-tab ${service === s.service ? "dark" : ""}`} onClick={() => setService(s.service)}>{s.service}</div>)}
        </div>
      </div>
      {resources.loading ? <div className="loading">Loading resources...</div> : (
        <div className="tbl-wrap">
          <table className="tbl tbl-res">
            <thead><tr><th>Service</th><th>Resource</th><th>Resource ID</th><th style={{ textAlign: "right" }}>Hours</th><th style={{ textAlign: "right" }}>Cost</th></tr></thead>
            <tbody>
              {(d.rows || []).map((r) => (
                <tr key={`${r.service}-${r.resource_id}`}>
                  <td>{r.service}</td><td>{r.name || "-"}</td><td className="mono">{r.resource_id}</td>
                  <td className="num">{r.hours && Number(r.hours) > 0 ? Number(r.hours).toFixed(1) : "-"}</td>
                  <td className="num">{usd(r.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TrendsPage({ profile, period }) {
  const trend = useAsyncData((signal) => api.trend(profile, period, { signal }), [profile, period]);
  const trendTable = useAsyncData((signal) => api.trendTable(profile, period, { signal }), [profile, period]);
  if (trend.error) return <div className="loading err">{trend.error}</div>;
  const values = trend.data?.values || [];
  const labels = trend.data?.labels || [];
  const total = values.reduce((s, x) => s + value(x), 0);
  const max = Math.max(...values, 0);
  const avg = values.length ? total / values.length : 0;
  const peakI = values.findIndex((x) => x === max);
  return (
    <div className="page">
      <div className="page-h"><div><h1>Trends</h1><div className="sub">Time-series spend analysis</div></div></div>
      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <Kpi label="Period total" valueText={usd(total)} note={`window ${period}`} />
        <Kpi label="Highest point" valueText={usd(max)} note={labels[peakI] || "-"} />
        <Kpi label="Average" valueText={usd(avg)} note="rolling average" />
        <Kpi label="Samples" valueText={String(values.length)} note="points in chart" />
      </div>
      <div className="card">
        <div className="card-title"><h2>Spend trend</h2></div>
        {trend.loading ? (
          <div className="loading">Loading trend...</div>
        ) : values.length >= 1 ? (
          <AreaChart data={values} labels={labels.map((l) => l.slice(5))} />
        ) : (
          <div className="loading">No trend chart data for this period.</div>
        )}
      </div>
      <div className="tbl-wrap">
        <div className="tbl-head-row"><h2>Period breakdown</h2></div>
        {trendTable.loading ? <div className="loading">Loading period breakdown...</div> : (
          <table className="tbl">
            <thead><tr><th>Period</th><th style={{ textAlign: "right" }}>Cost</th></tr></thead>
            <tbody>{(trendTable.data?.points || []).map((p) => <tr key={p.period}><td>{p.period}</td><td className="num">{usd(p.cost)}</td></tr>)}</tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function AuditPage({ profile }) {
  const audit = useAsyncData((signal) => api.audit(profile, "all", { signal }), [profile]);
  const budgets = useAsyncData((signal) => api.budgets(profile, { signal }), [profile]);
  if (audit.error) return <div className="loading err">{audit.error}</div>;
  return (
    <div className="page">
      <div className="page-h"><h1>Audit</h1></div>
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="budget-card">
          <h2 style={{ marginTop: 0 }}>Budgets</h2>
          {budgets.loading ? <div className="loading">Loading budgets...</div> : (budgets.data?.findings || []).map((b, idx) => (
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
      <div className="page-h"><h1>Export</h1></div>
      <div className="card">
        <div className="form-row"><label>Format</label><select className="btn-ctl" value={fmt} onChange={(e) => setFmt(e.target.value)}><option value="pdf">PDF</option><option value="csv">CSV</option><option value="json">JSON</option></select></div>
        <div className="form-row"><label>File name (optional)</label><input type="text" placeholder={`cloud_ledger_report.${fmt}`} value={fileName} onChange={(e) => setFileName(e.target.value)} /></div>
        <button className="btn btn-primary" onClick={runExport} disabled={running}>{running ? "Report is generating..." : "Generate report"}</button>
        {status ? <div style={{ marginTop: 12 }} className={status.startsWith("Failed") ? "err" : ""}>{status}</div> : null}
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [profile, setProfile] = useState("default");
  const [period, setPeriod] = useState("mtd");
  const [collapsed, setCollapsed] = useState(false);
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
    if (page === "trends") return <TrendsPage profile={profile} period={period} />;
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
    </div>
  );
}
