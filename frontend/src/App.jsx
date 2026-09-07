import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { useAsyncData } from "./hooks/useAsyncData";
import { useDebounced } from "./hooks/useDebounced";
import { Donut, TrendBars, PALETTE } from "./charts";
import { CostBadge } from "./components/CostBadge";
import { Banner, StaleBanner } from "./components/Banner";
import { CueStrip } from "./components/CueStrip";
import { Mark, Legend } from "./components/Marks";
import { Flap } from "./components/Flap";
import { announce, KIND, cuePeriodChanged, cueProfileChanged } from "./lib/cues";
import { usd, pct, value } from "./lib/format";
import {
  Mark as BrandMark, IconBoard, IconServices, IconResources, IconAudit, IconExport,
  IconChevron, IconChevronDown, IconArrowUp, IconArrowDown, IconMinus,
  IconCopy, IconCheck, IconSearch, IconMenu,
} from "./lib/icons";

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

const NAV_ICON = {
  dashboard: IconBoard,
  services: IconServices,
  resources: IconResources,
  audit: IconAudit,
  export: IconExport,
};

const PERIOD_LABEL = {
  mtd: "month to date",
  "30d": "last 30 days",
  "90d": "last 90 days",
  last_month: "previous month",
  "3m": "rolling 3 months",
  "6m": "trailing 6 months",
  "12m": "trailing 12 months",
};
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
// Fall back to a friendly "May 2026" for specific-month periods (YYYY-MM).
const periodLabel = (p) => {
  if (PERIOD_LABEL[p]) return PERIOD_LABEL[p];
  const m = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(p || "");
  if (m) return `${MONTH_NAMES[Number(m[2]) - 1]} ${m[1]}`;
  return p;
};

// Copy text to clipboard with a fallback for insecure contexts (plain HTTP LAN)
// where navigator.clipboard is unavailable or its write promise rejects.
async function copyToClipboard(text) {
  const val = String(text ?? "");
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(val);
      return true;
    }
  } catch {
    // fall through to legacy fallback
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = val;
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
// Bounded limit requested from the backend.
const RESOURCE_FETCH_LIMIT = 200;

const shortService = (n) => String(n || "Unknown").replace("Amazon ", "").replace("AWS ", "");

/* Per-resource figures are estimates unless the CUR warehouse served them.
   The backend now says which; we never guess. */
const resourceMark = (source) => (source === "cur" ? "exact" : "estimated");

/* ── The board announces every change instead of repainting silently ─────── */
function usePageCues(hooks, where) {
  const loading = hooks.some((h) => h.loading);
  const stale = hooks.some((h) => h?.meta?.fromCache === "stale");
  const faulted = hooks.find((h) => h.error || h.backendError);
  const fault = faulted ? faulted.error || faulted.backendError : null;
  useEffect(() => {
    if (loading) return;
    if (fault) announce(KIND.FAULT, "Read failed", `${where} — ${fault}`);
    else if (stale) announce(KIND.STALE, "Serving cached figures", `${where} — could not reach the server for fresh numbers.`);
    else announce(KIND.READY, "Board current", where);
  }, [loading, stale, fault, where]);
}

function Delta({ value: v, note }) {
  if (v == null) return null;
  const n = Number(v);
  // Spend going up is the bad direction; the signal ink is reserved for it.
  const dir = Math.abs(n) < 0.05 ? "flat" : n > 0 ? "up" : "down";
  const Icon = dir === "up" ? IconArrowUp : dir === "down" ? IconArrowDown : IconMinus;
  return (
    <span className={`delta ${dir}`}>
      <Icon size={13} />
      {pct(n)}
      {note ? <span className="sr-only"> {note}</span> : null}
    </span>
  );
}

/* ── Rail ─────────────────────────────────────────────────────────────── */

function RailNav({ page, setPage, onPick }) {
  return (
    <>
      {NAV.map((g, gi) => (
        <div key={g.group} className="rail-sect">
          {gi > 0 && <div className="rail-sect-rule" />}
          {g.items.map((it) => {
            const Icon = NAV_ICON[it];
            return (
              <button
                key={it}
                type="button"
                className={`rail-item ${page === it ? "on" : ""}`}
                onClick={() => { setPage(it); onPick?.(); }}
                aria-current={page === it ? "page" : undefined}
              >
                <Icon size={18} />
                <span className="rail-item-text">{TITLES[it]}</span>
              </button>
            );
          })}
        </div>
      ))}
    </>
  );
}

function Rail({ page, setPage, profile, collapsed, setCollapsed }) {
  return (
    <aside className="rail">
      <div className="rail-brand">
        <span className="rail-mark"><BrandMark /></span>
        <span className="rail-word">
          <span className="name">SpendSlicer</span>
        </span>
      </div>
      <button
        className="rail-toggle"
        onClick={() => setCollapsed((v) => !v)}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
      >
        {collapsed ? <IconChevron size={13} /> : <IconChevron size={13} style={{ transform: "rotate(180deg)" }} />}
      </button>
      <nav style={{ flex: 1 }} aria-label="Sections">
        <RailNav page={page} setPage={setPage} />
      </nav>
      <div className="rail-foot">
        <div className="rail-who">
          <span className="rail-who-mark">{(profile || "p")[0].toUpperCase()}</span>
          <span className="rail-who-text">
            <span className="rail-who-name">{profile}</span>
            <span className="rail-who-role">AWS CLI profile</span>
          </span>
        </div>
      </div>
    </aside>
  );
}

/* Below 900px the rail is hidden, so navigation moves into a sheet. */
function MobileNav({ open, setOpen, page, setPage, profile }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);
  if (!open) return null;
  return (
    <div className="sheet-scrim" onClick={() => setOpen(false)}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="rail-brand">
          <span className="rail-mark"><BrandMark /></span>
          <span className="rail-word">
            <span className="name">SpendSlicer</span>
            <span className="where">{profile}</span>
          </span>
        </div>
        <nav aria-label="Sections">
          <RailNav page={page} setPage={setPage} onPick={() => setOpen(false)} />
        </nav>
      </div>
    </div>
  );
}

function BoardBar({ page, period, setPeriod, profile, setProfile, context, onMenu }) {
  return (
    <div className="board-bar">
      <button className="ctl only-narrow" onClick={onMenu} aria-label="Open navigation">
        <IconMenu size={17} />
      </button>
      <span className="board-bar-title">{TITLES[page]}</span>
      <span className="board-bar-spacer" />
      <div className="board-bar-ctls">
        <select
          className="ctl"
          aria-label="Billing period"
          value={period}
          onChange={(e) => { cuePeriodChanged(periodLabel(e.target.value)); setPeriod(e.target.value); }}
        >
          {(() => {
            const periods = context?.periods || [];
            // When entries carry a `group` (Ranges / Months), render grouped
            // <optgroup>s so both relative ranges and specific calendar months
            // are offered together; otherwise fall back to a flat list.
            const grouped = periods.some((p) => p.group);
            if (!grouped) {
              return periods.map((p) => <option key={p.value} value={p.value}>{p.label}</option>);
            }
            const order = [];
            const byGroup = {};
            for (const p of periods) {
              const g = p.group || "Other";
              if (!byGroup[g]) { byGroup[g] = []; order.push(g); }
              byGroup[g].push(p);
            }
            return order.map((g) => (
              <optgroup key={g} label={g}>
                {byGroup[g].map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </optgroup>
            ));
          })()}
        </select>
        <select
          className="ctl"
          aria-label="AWS profile"
          value={profile}
          onChange={(e) => { cueProfileChanged(e.target.value); setProfile(e.target.value); }}
        >
          {context?.profile_choices?.map((p) => <option key={p.profile} value={p.profile}>{p.label}</option>)}
        </select>
      </div>
    </div>
  );
}

/* ── Dashboard — the departure board ──────────────────────────────────── */

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

  const pageHooks = [summary, services, trend, topResources];
  usePageCues(pageHooks, `${profile} · ${periodLabel(period)}`);

  const fatal = summary.error || summary.backendError;
  if (fatal) {
    return (
      <div className="page">
        <div className="head"><h1>Dashboard</h1></div>
        <Banner tone="error" onRetry={summary.reload}>{fatal}</Banner>
      </div>
    );
  }

  const s = summary.data || {};
  const r = topResources.data || {};
  const attrSource = r.attribution_source;
  const depRows = (services.data?.services || []).slice(0, 5);
  const serviceRows = (services.data?.services || []).slice(0, 6);
  const grandTotal = value(services.data?.total);

  const trendValues = trend.data?.values || [];
  const trendLabels = trend.data?.labels || [];
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
  const trendMax = Math.max(...trendValues, 0);
  const trendAvg = trendValues.length ? trendValues.reduce((a, b) => a + value(b), 0) / trendValues.length : 0;
  const trendPeakLabel = trendLabels[trendValues.findIndex((x) => x === trendMax)] || "";

  const topResourcesRows = (r.rows || []).slice(0, 10);
  const topResourceMax = Math.max(...topResourcesRows.map((x) => value(x.cost, 1)), 1);

  const reconciles = !topResources.loading && !r.warming && value(r.ce_total) > 0;

  return (
    <div className="page">
      <StaleBanner hooks={pageHooks} />
      {(services.backendError || trend.backendError) && (
        <Banner tone="warn" onRetry={() => { services.reload(); trend.reload(); }}>
          Some panels failed to load: {services.backendError || trend.backendError}
        </Banner>
      )}

      <section className="board" aria-label="Period spend board">
        <div className="board-main">
          <div className="board-figure">
            <div className="board-cap">
              {profile} · {periodLabel(period)} · {s.cost_basis_label || "Pre-credit gross"}
            </div>
            <div className="board-total">
              {summary.loading ? <span className="skel" style={{ display: "inline-block", width: 300, height: 78 }} />
                : <Flap text={usd(s.total_mtd, 2)} />}
            </div>
            <div className="board-sub">
              <Delta value={s.change_pct == null ? null : value(s.change_pct)} note="versus the previous period" />
              <span>vs previous period</span>
              <Mark kind="exact" />
            </div>
          </div>

          <div className="board-aside">
            <div className="board-aside-cell">
              <span className="board-aside-k">Previous period</span>
              <span className="board-aside-v">{summary.loading ? "—" : usd(s.total_prev, 2)}</span>
            </div>
            <div className="board-aside-cell">
              <span className="board-aside-k">Forecast at close</span>
              <span className="board-aside-v">{summary.loading ? "—" : usd(s.forecast, 2)}</span>
            </div>
          </div>
        </div>

        {/* THE CROSS-CHECK — each cell owns one truth, and the row reconciles. */}
        <div className="xcheck">
          <div className="xcheck-cell">
            <span className="xcheck-k">Attributed to resources</span>
            <span className="xcheck-v">{reconciles ? usd(r.total, 2) : "—"}</span>
          </div>
          <div className="xcheck-op" aria-hidden="true">+</div>
          <div className="xcheck-cell">
            <span className="xcheck-k">Unattributed drift <Mark kind="drift" /></span>
            <span className={`xcheck-v ${value(r.unattributed) > 0.01 ? "is-drift" : ""}`}>
              {reconciles ? usd(r.unattributed, 2) : "—"}
            </span>
          </div>
          <div className="xcheck-op" aria-hidden="true">=</div>
          <div className="xcheck-cell">
            <span className="xcheck-k">Cost Explorer total <Mark kind="exact" /></span>
            <span className="xcheck-v">{reconciles ? usd(r.ce_total, 2) : "—"}</span>
          </div>
          <p className="xcheck-note">
            {r.warming
              ? "Resource attribution is still being computed; this row fills in once the scan completes."
              : "Attributed plus drift equals the Cost Explorer total. Drift is charge that could not be tied to a named resource — it is never spread across the rows."}
          </p>
        </div>

        {/* Departures — the queue beneath the headline figure. */}
        <div className="dep">
          {services.loading
            ? [0, 1, 2, 3, 4].map((i) => (
                <div className="dep-row" key={i}><div className="skel skel-row" style={{ gridColumn: "1 / -1" }} /></div>
              ))
            : depRows.length === 0
              ? <div className="loading">No service spend recorded for this period.</div>
              : depRows.map((row, i) => {
                  const share = grandTotal > 0 ? (value(row.cost) / grandTotal) * 100 : 0;
                  return (
                    <div
                      className="dep-row"
                      key={row.name}
                      style={{ "--mass": Math.max(0.012, share / 100), "--mass-ink": PALETTE[i % PALETTE.length] }}
                    >
                      <span className="dep-name" title={row.name}>{shortService(row.name)}</span>
                      <span className="dep-badge">
                        {share.toFixed(0)}%
                        <span className="sr-only"> of period spend</span>
                      </span>
                      <span className="dep-cost">{usd(row.cost, 2)}</span>
                    </div>
                  );
                })}
        </div>

        <CueStrip />
      </section>

      <div className="void-lg" />

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Spend over the period</h2>
            <p>
              {trendValues.length > 0
                ? <>Peak {usd(trendMax, 2)}{trendPeakLabel ? ` on ${shortLabel(trendPeakLabel)}` : ""} · average {usd(trendAvg, 2)} · {trendValues.length} samples</>
                : "Cost Explorer daily or monthly buckets for the selected window."}
            </p>
          </div>
          <Mark kind="exact" />
        </div>
        <div className="panel-body">
          {trend.loading
            ? <div className="skel skel-board" />
            : trendRows.length >= 2
              ? <TrendBars data={trendRows} keys={["Spend"]} />
              : <div className="loading">No chart for this period — a trend needs at least two points.</div>}
        </div>
      </section>

      <div className="void-lg" />

      <div className="split">
        <section className="tt-wrap">
          <div className="panel-head">
            <div>
              <h2>Top resources</h2>
              <p>
                {attrSource === "cur"
                  ? "Real billed line items from your CUR warehouse."
                  : "Apportioned from usage-type buckets, then rescaled to the service total."}
              </p>
            </div>
            {attrSource ? <Mark kind={resourceMark(attrSource)} /> : null}
          </div>
          {topResources.loading ? (
            <div className="panel-body"><div className="skel skel-row" /><div className="skel skel-row" /><div className="skel skel-row" /></div>
          ) : topResources.error || topResources.backendError ? (
            <div className="panel-body">
              <Banner tone="error" onRetry={topResources.reload}>
                Resources unavailable right now: {topResources.error || topResources.backendError}
              </Banner>
            </div>
          ) : r.warming ? (
            <div className="loading">Resource attribution is warming up — this refreshes on its own in a few seconds.</div>
          ) : topResourcesRows.length === 0 ? (
            <div className="empty">
              <h3>Nothing attributed yet</h3>
              <p>No named resource carried cost in this window.</p>
            </div>
          ) : (
            <div className="tt-scroll">
              <table className="tt tt-mass">
                <thead>
                  <tr>
                    <th>Resource</th>
                    <th>Service</th>
                    <th className="num">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {topResourcesRows.map((row) => (
                    <tr
                      key={`${row.service}-${row.resource_id}`}
                      style={{ "--mass": Math.max(0, Math.min(1, value(row.cost) / topResourceMax)) }}
                    >
                      <td className="tt-lead" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {row.name || row.resource_id}
                      </td>
                      <td className="tt-quiet col">{shortService(row.service)}</td>
                      <td className="num"><span className="num-strong">{usd(row.cost, 2)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Service mix</h2>
              <p>Share of spend across the period.</p>
            </div>
            <Mark kind="exact" />
          </div>
          <div className="panel-body">
            {services.loading ? <div className="skel skel-board" /> : (() => {
              const topSum = serviceRows.reduce((a, x) => a + value(x.cost), 0);
              const other = Math.max(0, grandTotal - topSum);
              const segs = serviceRows.map((row, idx) => ({
                key: String(idx),
                name: shortService(row.name),
                value: value(row.cost),
                color: PALETTE[idx % PALETTE.length],
              }));
              if (other > 0.005) segs.push({ key: "other", name: "Other", value: other, color: "var(--line-8)" });
              return segs.length ? <Donut data={segs} /> : <div className="loading">No service spend to chart.</div>;
            })()}
          </div>
        </section>
      </div>

      <Legend />
    </div>
  );
}

/* ── Service composition ──────────────────────────────────────────────── */

const COMPOSITION_BUCKETS = ["compute", "storage", "data-transfer", "network", "other"];
const COMPOSITION_COLORS = {
  compute: "var(--line-1)",
  storage: "var(--line-2)",
  "data-transfer": "var(--line-4)",
  network: "var(--line-5)",
  other: "var(--line-8)",
};

const USAGE_TYPES_PREVIEW = 8;

function ServiceComposition({ buckets }) {
  const [showAll, setShowAll] = useState(false);
  if (!buckets) return <div className="loading">No composition data for this service.</div>;
  const total = COMPOSITION_BUCKETS.reduce((s, k) => s + value(buckets[k]), 0);
  if (total <= 0) return <div className="loading">No composition data for this service.</div>;
  const rows = COMPOSITION_BUCKETS
    .map((k) => ({ key: k, amount: value(buckets[k]), pct: (value(buckets[k]) / total) * 100 }))
    .filter((x) => x.amount > 0)
    .sort((a, b) => b.amount - a.amount);

  // Rank before slicing: an unsorted "8 of 9" preview misstates which usage
  // type is actually driving the bill.
  const usageTypes = (buckets.usage_types || [])
    .filter((u) => value(u.cost) > 0)
    .sort((a, b) => value(b.cost) - value(a.cost));
  const visible = showAll ? usageTypes : usageTypes.slice(0, USAGE_TYPES_PREVIEW);

  return (
    <div className="comp">
      <div className="comp-bar">
        {rows.map((x) => (
          <span
            key={x.key}
            className="comp-seg"
            style={{ width: `${x.pct}%`, background: COMPOSITION_COLORS[x.key] }}
            title={`${x.key}: ${usd(x.amount, 2)} (${x.pct.toFixed(1)}%)`}
          />
        ))}
      </div>
      <ul className="comp-legend">
        {rows.map((x) => (
          <li key={x.key}>
            <span className="comp-dot" style={{ background: COMPOSITION_COLORS[x.key] }} />
            <span className="comp-key">{x.key}</span>
            <span className="comp-amt">{usd(x.amount, 2)}</span>
            <span className="comp-pct">{x.pct.toFixed(1)}%</span>
          </li>
        ))}
      </ul>

      {usageTypes.length > 0 && (
        <div className="comp-ut">
          <div className="comp-ut-head">
            <span>Exact usage types</span>
            <span>{usageTypes.length}</span>
          </div>
          <table className="comp-ut-tbl">
            <tbody>
              {visible.map((u) => (
                <tr key={u.usage_type}>
                  <td style={{ width: 1 }}>
                    <span className="comp-tag" style={{ background: COMPOSITION_COLORS[u.bucket] || COMPOSITION_COLORS.other }}>
                      {u.bucket}
                    </span>
                  </td>
                  <td className="id" style={{ width: "100%", wordBreak: "break-all" }}>{u.usage_type}</td>
                  <td className="num">{usd(u.cost, 4)}</td>
                  <td className="num tt-quiet" style={{ minWidth: 48 }}>{((value(u.cost) / total) * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {usageTypes.length > USAGE_TYPES_PREVIEW && (
            <button type="button" className="link-btn" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show fewer" : `Show all ${usageTypes.length} usage types`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Services — the timetable ─────────────────────────────────────────── */

function ServicesPage({ profile, period }) {
  const services = useAsyncData((signal) => api.services(profile, period, 0, { signal }), [profile, period]);
  // Composition is a multi-MB map of every service's usage-type breakdown and
  // exceeds the SWR cache size cap (so it's never cached). Don't fetch it on
  // mount — only once the user actually expands a row to view a breakdown.
  const [compNeeded, setCompNeeded] = useState(false);
  const composition = useAsyncData(
    (signal) => (compNeeded ? api.servicesComposition(profile, period, { signal }) : Promise.resolve({ services: {} })),
    [profile, period, compNeeded],
  );
  const [expanded, setExpanded] = useState(null);
  const [visible, setVisible] = useState(RESOURCE_PAGE_SIZE);
  usePageCues([services], `${profile} · ${periodLabel(period)}`);

  if (services.error || services.backendError) {
    return (
      <div className="page page-dense">
        <div className="head"><h1>Services</h1></div>
        <Banner tone="error" onRetry={services.reload}>{services.error || services.backendError}</Banner>
      </div>
    );
  }
  const compMap = composition.data?.services || {};
  const allRows = services.data?.services || [];
  const rows = allRows.slice(0, visible);

  return (
    <div className="page page-dense">
      <div className="head">
        <h1>Services</h1>
        <p>Every service billed in this window, exact from Cost Explorer. Open a row to see what is driving it — compute, storage, data transfer, network — down to the usage type.</p>
      </div>
      <StaleBanner hooks={[services]} />

      {services.loading ? (
        <div className="tt-wrap"><div className="panel-body"><div className="skel skel-row" /><div className="skel skel-row" /><div className="skel skel-row" /></div></div>
      ) : allRows.length === 0 ? (
        <div className="tt-wrap"><div className="empty"><h3>No services billed</h3><p>Nothing was charged in this window for this profile.</p></div></div>
      ) : (
        <div className="tt-wrap">
          <div className="tt-scroll">
            <table className="tt">
              <thead>
                <tr>
                  <th style={{ width: 34 }}><span className="sr-only">Expand</span></th>
                  <th>Service</th>
                  <th className="num">Cost</th>
                  <th className="num">Share</th>
                  <th className="num">Vs prior</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const isOpen = expanded === row.name;
                  const toggle = () => { setCompNeeded(true); setExpanded(isOpen ? null : row.name); };
                  return (
                    <Fragment key={row.name}>
                      <tr
                        className={`clickable ${isOpen ? "tt-row-open" : ""}`}
                        onClick={toggle}
                        tabIndex={0}
                        role="button"
                        aria-expanded={isOpen}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
                      >
                        <td><span className={`caret ${isOpen ? "open" : ""}`}><IconChevron size={14} /></span></td>
                        <td className="tt-lead col">{row.name}</td>
                        <td className="num"><span className="num-strong">{usd(row.cost, 2)}</span></td>
                        <td className="num tt-quiet">{Number(row.pct_of_total || 0).toFixed(1)}%</td>
                        <td className="num">
                          {row.change_pct == null
                            ? <span className="tt-quiet">new</span>
                            : <Delta value={value(row.change_pct)} />}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="tt-detail">
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
          </div>
          {visible < allRows.length && (
            <div className="panel-body" style={{ borderTop: "1px solid var(--rule)" }}>
              <button type="button" className="btn btn-quiet" onClick={() => setVisible((v) => v + RESOURCE_PAGE_SIZE)}>
                Show more ({allRows.length - visible} more)
              </button>
            </div>
          )}
        </div>
      )}

      <Legend kinds={["exact"]} />
    </div>
  );
}

/* ── Resources — the timetable, per machine ───────────────────────────── */

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
  return (
    <button
      className="id"
      onClick={onCopy}
      title={copied === "ok" ? "Copied" : copied === "fail" ? "Copy failed — select the text manually" : "Copy resource ID"}
      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
    >
      {copied === "ok" ? <IconCheck size={13} /> : copied === "fail" ? null : <IconCopy size={13} />}
      {copied === "ok" ? "Copied" : copied === "fail" ? "Copy failed" : resourceId}
    </button>
  );
}

function ResourcesPage({ profile, period }) {
  const [service, setService] = useState("");
  const [limit, setLimit] = useState(RESOURCE_FETCH_LIMIT);
  const [visible, setVisible] = useState(RESOURCE_PAGE_SIZE);
  const debouncedService = useDebounced(service, 300);
  // Change the service filter AND reset the grown fetch-limit + visible count
  // together (one batched update). Resetting limit synchronously here — rather
  // than in an effect that runs AFTER the fetch effect — avoids firing a wasted
  // large-limit request for the new filter before the limit reset lands.
  const selectService = (s) => {
    setService(s);
    setLimit(RESOURCE_FETCH_LIMIT);
    setVisible(RESOURCE_PAGE_SIZE);
  };
  const resources = useAsyncData(
    (signal) => api.resources(profile, period, "all", debouncedService, limit, { signal }),
    [profile, period, debouncedService, limit]
  );
  // Reset client-side pagination only when the filter changes — NOT when the
  // fetch limit grows, so "Load more from server" doesn't collapse the user's
  // scroll position back to the first page.
  useEffect(() => { setVisible(RESOURCE_PAGE_SIZE); }, [debouncedService]);
  usePageCues([resources], `${profile} · ${periodLabel(period)}`);

  if (resources.error || resources.backendError) {
    return (
      <div className="page page-dense">
        <div className="head"><h1>Resources</h1></div>
        <Banner tone="error" onRetry={resources.reload}>{resources.error || resources.backendError}</Banner>
      </div>
    );
  }
  const d = resources.data || {};
  const allRows = d.rows || [];
  const shownRows = allRows.slice(0, visible);
  const totalCount = Number(d.total_count ?? allRows.length);
  // How many rows the server actually returned (bounded by the requested limit).
  const fetchedCount = allRows.length;
  const kind = resourceMark(d.attribution_source);
  const drifting = value(d.unattributed) > 0.01;

  return (
    <div className="page page-dense">
      <div className="head">
        <h1>Resources</h1>
        <p>Every named resource that carried cost, reconciled against the Cost Explorer total for the same window.</p>
      </div>

      {/* The reconciliation is the page's thesis, so it leads. */}
      <section className="panel">
        <div className="xcheck" style={{ borderTop: 0 }}>
          <div className="xcheck-cell">
            <span className="xcheck-k">Attributed <Mark kind={kind} /></span>
            <span className="xcheck-v">{usd(d.total, 2)}</span>
          </div>
          <div className="xcheck-op" aria-hidden="true">+</div>
          <div className="xcheck-cell">
            <span className="xcheck-k">Drift <Mark kind="drift" /></span>
            <span className={`xcheck-v ${drifting ? "is-drift" : ""}`}>{usd(d.unattributed, 2)}</span>
          </div>
          <div className="xcheck-op" aria-hidden="true">=</div>
          <div className="xcheck-cell">
            <span className="xcheck-k">Cost Explorer total <Mark kind="exact" /></span>
            <span className="xcheck-v">{usd(d.ce_total, 2)}</span>
          </div>
          <p className="xcheck-note">
            {kind === "exact"
              ? "These rows are real billed CUR line items, so they are exact."
              : "These rows are estimates: usage-type buckets split by running hours and list price, then rescaled to the service total."}
            {" "}Drift is {Number(d.unattributed_pct || 0).toFixed(1)}% of the total and is shown on its own line, never spread across the rows.
          </p>
        </div>
      </section>

      {(d.incomplete || (d.warnings || []).length > 0) && (
        <div style={{ marginTop: 18 }}>
          <Banner tone="warn" onRetry={resources.reload}>
            {(d.warnings || []).join(" ") || "Attribution incomplete — attributed totals may be understated."}
          </Banner>
        </div>
      )}
      <div className="void-md" />
      <StaleBanner hooks={[resources]} />

      <div className="chip-row" style={{ marginBottom: 16 }}>
        <button type="button" className={`chip ${service === "" ? "on" : ""}`} onClick={() => selectService("")}>
          All services
        </button>
        {/* Cap the pill row: services_summary is sorted by cost desc, so the
            top 15 are the ones worth one-click filtering. Beyond that, a
            select avoids rendering hundreds of buttons. */}
        {(d.services_summary || []).slice(0, 15).map((x) => (
          <button
            key={x.service}
            type="button"
            className={`chip ${service === x.service ? "on" : ""}`}
            onClick={() => selectService(x.service)}
          >
            {shortService(x.service)}
          </button>
        ))}
        {(d.services_summary || []).length > 15 && (
          <select
            className="ctl"
            aria-label="More services"
            value={(d.services_summary || []).slice(0, 15).some((x) => x.service === service) ? "" : service}
            onChange={(e) => { if (e.target.value) selectService(e.target.value); }}
          >
            <option value="" disabled>More services…</option>
            {(d.services_summary || []).slice(15).map((x) => (
              <option key={x.service} value={x.service}>{x.service}</option>
            ))}
          </select>
        )}
      </div>

      {resources.loading ? (
        <div className="tt-wrap"><div className="panel-body"><div className="skel skel-row" /><div className="skel skel-row" /><div className="skel skel-row" /></div></div>
      ) : allRows.length === 0 ? (
        <div className="tt-wrap">
          <div className="empty">
            <IconSearch size={26} style={{ color: "var(--ink-5)", marginBottom: 10 }} />
            <h3>No resources attributed for this window</h3>
            <p>
              If you just enabled CUR, data takes about 24 hours to arrive. Run <code>spendslicer cur status</code> to check.
            </p>
          </div>
        </div>
      ) : (
        <div className="tt-wrap">
          {totalCount > fetchedCount && (
            <div className="panel-head">
              <p>Showing {Math.min(visible, fetchedCount)} of {totalCount} resources.</p>
            </div>
          )}
          <div className="tt-scroll">
            <table className="tt tt-res">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Service</th>
                  <th>Resource ID</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {shownRows.map((x) => (
                  <tr key={`${x.service}-${x.resource_id}`}>
                    <td className="tt-lead">
                      {x.name || x.resource_id}
                      {/* Narrow screens drop the ID column; it rides under the name. */}
                      <span className="under">
                        {String(x.resource_id).startsWith("aggregate:")
                          ? <span className="id faint">{x.resource_id}</span>
                          : <CopyIdButton resourceId={x.resource_id} />}
                      </span>
                    </td>
                    <td className="tt-quiet col">{shortService(x.service)}</td>
                    <td className="col-id">
                      {String(x.resource_id).startsWith("aggregate:")
                        ? <span className="id faint">{x.resource_id}</span>
                        : <CopyIdButton resourceId={x.resource_id} />}
                    </td>
                    <td className="num"><span className="num-strong">{usd(x.cost, 2)}</span></td>
                  </tr>
                ))}
                {!service && drifting && visible >= fetchedCount && (
                  <tr className="tt-drift">
                    <td>
                      <strong>Unattributed charges</strong>
                      <div style={{ fontSize: 12.5, marginTop: 3 }}>Most often terminated or deleted resources.</div>
                    </td>
                    <td className="tt-quiet">—</td>
                    <td className="col-id"><span className="id">gap vs CE total</span></td>
                    <td className="num"><span className="num-strong">{usd(d.unattributed, 2)}</span></td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="panel-body" style={{ borderTop: "1px solid var(--rule)", display: "flex", gap: 12, flexWrap: "wrap" }}>
            {visible < fetchedCount && (
              <button type="button" className="btn btn-quiet" onClick={() => setVisible((v) => v + RESOURCE_PAGE_SIZE)}>
                Show more ({fetchedCount - visible} more loaded)
              </button>
            )}
            {visible >= fetchedCount && totalCount > fetchedCount && (
              <button type="button" className="btn btn-quiet" onClick={() => setLimit((l) => l + RESOURCE_FETCH_LIMIT)}>
                Load more from server ({totalCount - fetchedCount} not yet loaded)
              </button>
            )}
          </div>
        </div>
      )}

      <Legend />
    </div>
  );
}

/* ── Audit — the notice board ─────────────────────────────────────────── */

const NOTICE_PREVIEW = 12;

function NoticeList({ items, emptyWhat }) {
  const [showAll, setShowAll] = useState(false);
  if (!items.length) {
    return (
      <div className="empty">
        <h3>Nothing flagged</h3>
        <p>{emptyWhat}</p>
      </div>
    );
  }
  const shown = showAll ? items : items.slice(0, NOTICE_PREVIEW);
  return (
    <>
      {shown.map((f, i) => (
        <div className="notice" key={`${f.resource_id || f.arn || i}-${i}`}>
          <div style={{ minWidth: 0 }}>
            <div className="notice-name">{f.resource_name || f.resource_id || "Unnamed resource"}</div>
            <div className="notice-why">
              {f.reason
                || (f.missing_tags?.length ? `Missing required tags: ${f.missing_tags.join(", ")}` : "")
                || "Flagged by the audit scan."}
            </div>
            <div className="notice-why">
              <span className="id">{f.resource_id}</span>
              {f.region ? <> · {f.region}</> : null}
              {f.service ? <> · {f.service}</> : null}
            </div>
          </div>
          <span className="notice-cost">
            {f.estimated_monthly_cost_usd == null ? "—" : `${usd(f.estimated_monthly_cost_usd, 2)}/mo`}
          </span>
        </div>
      ))}
      {items.length > NOTICE_PREVIEW && (
        <div className="panel-body" style={{ borderTop: "1px solid var(--rule)" }}>
          <button type="button" className="link-btn" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show all ${items.length}`}
          </button>
        </div>
      )}
    </>
  );
}

function AuditPage({ profile }) {
  const audit = useAsyncData((signal) => api.audit(profile, "all", { signal }), [profile]);
  const budgets = useAsyncData((signal) => api.budgets(profile, { signal }), [profile]);
  usePageCues([audit, budgets], `${profile} · waste scan`);

  if (audit.error) {
    return (
      <div className="page">
        <div className="head"><h1>Audit</h1></div>
        <Banner tone="error" onRetry={audit.reload}>{audit.error}</Banner>
      </div>
    );
  }

  const a = audit.data || {};
  const summary = a.summary || {};
  const idle = a.idle || [];
  const untagged = a.untagged || [];
  const waste = value(summary.estimated_waste_usd_monthly);
  const budgetRows = budgets.data?.findings || [];

  return (
    <div className="page">
      <div className="head">
        <h1>Audit</h1>
        <p>Resources that are billing without earning it, plus budget status. Waste figures are monthly estimates from list price, not billed amounts.</p>
      </div>

      {audit.backendError && (
        <Banner tone="warn" onRetry={audit.reload}>{audit.backendError} — the counts below may be incomplete.</Banner>
      )}
      {(budgets.error || budgets.backendError) && (
        <Banner tone="warn" onRetry={budgets.reload}>Budgets: {budgets.error || budgets.backendError}</Banner>
      )}
      <StaleBanner hooks={[audit, budgets]} />

      <section className="board" aria-label="Recoverable spend board">
        <div className="board-main">
          <div className="board-figure">
            <div className="board-cap">
              Estimated recoverable, per month · {Number(summary.regions_scanned || 0)} region{Number(summary.regions_scanned) === 1 ? "" : "s"} scanned
            </div>
            <div className="board-total">
              {audit.loading ? <span className="skel" style={{ display: "inline-block", width: 240, height: 78 }} />
                : <Flap text={usd(waste, 2)} />}
            </div>
            <div className="board-sub">
              <Mark kind="estimated" />
              <span>list price, not billed amounts</span>
            </div>
          </div>
        </div>
        <div className="xcheck">
          <div className="xcheck-cell">
            <span className="xcheck-k">Idle and orphaned</span>
            <span className="xcheck-v">{audit.loading ? "—" : idle.length}</span>
          </div>
          <div className="xcheck-cell">
            <span className="xcheck-k">Untagged</span>
            <span className="xcheck-v">{audit.loading ? "—" : untagged.length}</span>
          </div>
          <div className="xcheck-cell">
            <span className="xcheck-k">Budgets tracked</span>
            <span className="xcheck-v">{budgets.loading ? "—" : budgetRows.length}</span>
          </div>
          <p className="xcheck-note">
            Every finding below carries the reason it was flagged and what it is costing you each month.
          </p>
        </div>
        <CueStrip />
      </section>

      <div className="void-lg" />

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Budgets</h2>
            <p>AWS Budgets for this account, with current utilisation.</p>
          </div>
        </div>
        <div className="panel-body">
          {budgets.loading ? (
            <><div className="skel skel-row" /><div className="skel skel-row" /></>
          ) : budgetRows.length === 0 ? (
            <div className="empty">
              <h3>No budgets configured</h3>
              <p>Nothing to track. AWS Budgets set on this account will appear here automatically.</p>
            </div>
          ) : budgetRows.map((b) => {
            const state = b.status === "breached" ? "stop" : b.status === "warning" ? "warn" : "";
            return (
              <div className="budget-row" key={b.budget_name}>
                <div className="budget-head">
                  <span className="budget-name">{b.budget_name}</span>
                  <span className="budget-amt">
                    {b.actual_spend == null ? "—" : usd(value(b.actual_spend), 2)} of {b.limit_amount == null ? "—" : usd(value(b.limit_amount), 2)}
                    {" · "}{Number(b.utilization_pct || 0).toFixed(0)}%
                  </span>
                </div>
                <div
                  className="budget-track"
                  role="progressbar"
                  aria-valuenow={Math.round(value(b.utilization_pct, 0))}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${b.budget_name} budget utilisation`}
                >
                  <div className={`budget-fill ${state}`} style={{ "--fill": Math.min(1, value(b.utilization_pct, 0) / 100) }} />
                </div>
                {b.breach_reason && <div className="notice-why" style={{ marginTop: 6 }}>{b.breach_reason}</div>}
              </div>
            );
          })}
        </div>
      </section>

      <div className="void-lg" />

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Idle and orphaned</h2>
            <p>Stopped instances still paying for storage, unattached volumes, unassociated addresses.</p>
          </div>
        </div>
        {audit.loading
          ? <div className="panel-body"><div className="skel skel-row" /><div className="skel skel-row" /></div>
          : <NoticeList items={idle} emptyWhat="No idle or orphaned resources found in the scanned regions." />}

        <div className="panel-head" style={{ borderTop: "1px solid var(--rule)" }}>
          <div>
            <h2>Untagged</h2>
            <p>Resources carrying cost that cannot be allocated to an owner.</p>
          </div>
        </div>
        {audit.loading
          ? <div className="panel-body"><div className="skel skel-row" /><div className="skel skel-row" /></div>
          : <NoticeList items={untagged} emptyWhat="Every resource carries the required tags." />}
      </section>

      {(a.errors || []).length > 0 && (
        <>
          <div className="void-md" />
          <Banner tone="warn">
            {(a.errors || []).length} region{(a.errors || []).length === 1 ? "" : "s"} could not be scanned completely; findings may be understated.
          </Banner>
        </>
      )}

      <Legend kinds={["estimated"]} />
    </div>
  );
}

/* ── Export — issue a copy ────────────────────────────────────────────── */

const FORMATS = [
  { id: "csv", name: "CSV", what: "One row per resource. Opens in a spreadsheet.", everywhere: true },
  { id: "json", name: "JSON", what: "Full payload including provenance records.", everywhere: true },
  { id: "pdf", name: "PDF", what: "Formatted report. Renders through Puppeteer.", everywhere: false },
];

function ExportPage({ profile, period }) {
  const [fmt, setFmt] = useState("csv");
  const [fileName, setFileName] = useState("");
  const [status, setStatus] = useState(null); // null | {ok: boolean, msg: string}
  const [running, setRunning] = useState(false);
  const runExport = async () => {
    setRunning(true);
    setStatus({ ok: true, msg: "Generating…" });
    announce(KIND.WORKING, "Export started", `Generating a ${fmt.toUpperCase()} for ${periodLabel(period)}.`);
    try {
      const res = await api.downloadExport(profile, period, fmt, fileName);
      setStatus({ ok: true, msg: `Downloaded ${res.filename}` });
      announce(KIND.READY, "Export ready", `Downloaded ${res.filename}.`);
    } catch (err) {
      const msg = err.message || "Export failed";
      setStatus({ ok: false, msg });
      announce(KIND.FAULT, "Export failed", msg);
    } finally {
      setRunning(false);
    }
  };

  const picked = FORMATS.find((f) => f.id === fmt);

  return (
    <div className="page">
      <div className="head">
        <h1>Export</h1>
        <p>Issue a copy of this window — {profile}, {periodLabel(period)} — for sharing or archiving. The file is written by your own machine; nothing is uploaded.</p>
      </div>

      <section className="panel" style={{ maxWidth: 760 }}>
        <div className="panel-head">
          <div>
            <h2>Issue a report</h2>
            <p>The file is written by your own machine. Nothing is uploaded.</p>
          </div>
        </div>

        <div className="panel-body">
          <div className="field">
            <label htmlFor="fmt">Format</label>
            <select id="fmt" value={fmt} onChange={(e) => setFmt(e.target.value)}>
              {FORMATS.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            <span className="field-note">{picked?.what}</span>
          </div>

          <div className="field">
            <label htmlFor="fname">File name <span style={{ fontWeight: 400 }}>(optional)</span></label>
            <input
              id="fname"
              type="text"
              placeholder={`spendslicer_report.${fmt}`}
              value={fileName}
              onChange={(e) => setFileName(e.target.value)}
            />
          </div>

          {fmt === "pdf" && (
            <Banner tone="warn">
              PDF rendering needs Node.js on this machine. It does not work in the packaged desktop
              builds or a bare <code>pip install</code>. CSV and JSON work everywhere.
            </Banner>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={runExport} disabled={running}>
              {running ? "Generating…" : `Generate ${picked?.name || ""}`}
            </button>
            {status && (
              <span role="status" style={{ fontSize: 13.5, color: status.ok ? "var(--ink-3)" : "var(--signal)" }}>
                {status.msg}
              </span>
            )}
          </div>
        </div>

        <div className="panel-head" style={{ borderTop: "1px solid var(--rule)" }}>
          <div>
            <h2>What ends up in the file</h2>
          </div>
        </div>
        <div className="panel-body">
          <ul className="plain-list">
            <li>Service totals, exact from Cost Explorer.</li>
            <li>Per-resource rows, marked exact or estimated the same way they are on screen.</li>
            <li>Unattributed drift as its own line, never folded into the rows above it.</li>
            <li>The provenance record for each figure: which API produced it, over what window, with what filters.</li>
          </ul>
        </div>
      </section>

      <Legend />
    </div>
  );
}

/* ── Shell ────────────────────────────────────────────────────────────── */

const readUrlState = () => {
  const q = new URLSearchParams(window.location.search);
  return { page: q.get("page"), profile: q.get("profile"), period: q.get("period") };
};

export default function App() {
  const urlInit = readUrlState();
  const [page, setPage] = useState(urlInit.page && TITLES[urlInit.page] ? urlInit.page : "dashboard");
  // Falls back to the literal "default" profile, which is what the AWS CLI
  // calls an unnamed profile — never an empty string, which the backend
  // cannot resolve and which surfaces as "credentials not found".
  const [profile, setProfile] = useState(() => urlInit.profile || localStorage.getItem("acu:profile") || "default");
  const [period, setPeriod] = useState(() => urlInit.period || localStorage.getItem("acu:period") || "mtd");
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
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

  const contextState = useAsyncData((signal) => api.context(profile, period, { signal }), [profile, period]);

  // Snap an unknown profile or period onto something the backend actually
  // offers. `profiles` is the flat list of valid names; there is no
  // `context.profile` key, and reading one leaves the profile unset.
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
      <Rail page={page} setPage={setPage} profile={profile} collapsed={collapsed} setCollapsed={setCollapsed} />
      <MobileNav open={menuOpen} setOpen={setMenuOpen} page={page} setPage={setPage} profile={profile} />
      <div className="main">
        <BoardBar
          page={page}
          period={period}
          setPeriod={setPeriod}
          profile={profile}
          setProfile={setProfile}
          context={contextState.data}
          onMenu={() => setMenuOpen(true)}
        />
        <div className="scroll">{pageNode}</div>
      </div>
      <CostBadge />
    </div>
  );
}
