/* Services, live. Rows expand to the usage types driving them, exactly as
   ServicesPage does. Only the three services with composition data in the
   demo dataset expand; the rest behave as they do before a composition
   fetch resolves. */

import { Fragment, useState } from "react";
import { Mark, Legend } from "@app/components/Marks.jsx";
import { IconChevron } from "@app/lib/icons.jsx";
import { usd, value } from "@app/lib/format.js";
import { SERVICES, COMPOSITION } from "./data";
import { Delta } from "./Board";

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
  if (!buckets) {
    return <div className="loading">No composition data for this service in the demo dataset.</div>;
  }
  const total = COMPOSITION_BUCKETS.reduce((s, k) => s + value(buckets[k]), 0);
  const rows = COMPOSITION_BUCKETS
    .map((k) => ({ key: k, amount: value(buckets[k]), pct: (value(buckets[k]) / total) * 100 }))
    .filter((x) => x.amount > 0)
    .sort((a, b) => b.amount - a.amount);

  // Rank before slicing: an unsorted "8 of 10" preview misstates which usage
  // type is actually driving the bill.
  const usageTypes = [...(buckets.usage_types || [])].sort((a, b) => value(b.cost) - value(a.cost));
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
                  <span
                    className="comp-tag"
                    style={{ background: COMPOSITION_COLORS[u.bucket] || COMPOSITION_COLORS.other }}
                  >
                    {u.bucket}
                  </span>
                </td>
                <td className="id" style={{ width: "100%", wordBreak: "break-all" }}>{u.usage_type}</td>
                <td className="num">{usd(u.cost, 4)}</td>
                <td className="num tt-quiet" style={{ minWidth: 48 }}>
                  {((value(u.cost) / total) * 100).toFixed(1)}%
                </td>
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
    </div>
  );
}

export function SurfaceServices() {
  const [expanded, setExpanded] = useState(SERVICES[0].name);

  return (
    <>
      <div className="head">
        <h1>Services</h1>
        <p>
          Every service billed in this window, exact from Cost Explorer. Open a row to see what is
          driving it: compute, storage, data transfer, network, down to the usage type.
        </p>
      </div>

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
              {SERVICES.map((row) => {
                const isOpen = expanded === row.name;
                const toggle = () => setExpanded(isOpen ? null : row.name);
                return (
                  <Fragment key={row.name}>
                    <tr
                      className={`clickable ${isOpen ? "tt-row-open" : ""}`}
                      onClick={toggle}
                      tabIndex={0}
                      role="button"
                      aria-expanded={isOpen}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
                      }}
                    >
                      <td><span className={`caret ${isOpen ? "open" : ""}`}><IconChevron size={14} /></span></td>
                      <td className="tt-lead col">{row.name}</td>
                      <td className="num"><span className="num-strong">{usd(row.cost, 2)}</span></td>
                      <td className="num tt-quiet">{Number(row.pct_of_total || 0).toFixed(1)}%</td>
                      <td className="num">
                        {row.change_pct == null
                          ? <span className="tt-quiet">new</span>
                          : <Delta value={row.change_pct} />}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="tt-detail">
                        <td colSpan={5}><ServiceComposition buckets={COMPOSITION[row.name]} /></td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <Legend kinds={["exact"]} />
    </>
  );
}
