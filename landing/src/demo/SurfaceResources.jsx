/* Resources, live. The service filter and the copy-ID button both work,
   because a visitor poking at the demo should hit the real interaction and
   not a picture of one. */

import { useMemo, useState } from "react";
import { Mark, Legend } from "@app/components/Marks.jsx";
import { IconCopy, IconCheck } from "@app/lib/icons.jsx";
import { usd } from "@app/lib/format.js";
import { RESOURCES, SERVICES, CE_TOTAL, ATTRIBUTED, DRIFT } from "./data";

const shortService = (n) => String(n || "Unknown").replace("Amazon ", "").replace("AWS ", "");
const round2 = (n) => Math.round(n * 100) / 100;

function CopyIdButton({ resourceId }) {
  const [copied, setCopied] = useState(null); // null | "ok" | "fail"

  const copy = async (e) => {
    e.stopPropagation();
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("no clipboard");
      await navigator.clipboard.writeText(resourceId);
      setCopied("ok");
    } catch {
      setCopied("fail");
    }
    setTimeout(() => setCopied(null), 1400);
  };

  // Same markup as CopyIdButton in App.jsx, so it inherits the same styling.
  return (
    <button
      type="button"
      className="id"
      onClick={copy}
      title={copied === "ok" ? "Copied" : copied === "fail" ? "Copy failed, select the text manually" : "Copy resource ID"}
      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
    >
      {copied === "ok" ? <IconCheck size={13} /> : copied === "fail" ? null : <IconCopy size={13} />}
      {copied === "ok" ? "Copied" : copied === "fail" ? "Copy failed" : resourceId}
    </button>
  );
}

export function SurfaceResources() {
  const [service, setService] = useState(null);

  const rows = useMemo(
    () => (service ? RESOURCES.filter((r) => r.service === service) : RESOURCES),
    [service]
  );

  // Filtering to one service scopes the reconciliation to that service too,
  // the way the real page does. The drift line is never dropped.
  const scoped = useMemo(() => {
    if (!service) return { total: CE_TOTAL, attributed: ATTRIBUTED, drift: DRIFT };
    const svc = SERVICES.find((s) => s.name === service);
    const attributed = round2(rows.reduce((a, r) => a + r.cost, 0));
    return { total: svc.cost, attributed, drift: round2(svc.cost - attributed) };
  }, [service, rows]);

  const withResources = SERVICES.filter((s) => RESOURCES.some((r) => r.service === s.name));

  return (
    <>
      <div className="head">
        <h1>Resources</h1>
        <p>
          Every named resource that carried cost, reconciled against the Cost Explorer total for
          the same window.
        </p>
      </div>

      <div className="xcheck">
        <div className="xcheck-cell">
          <span className="xcheck-k">Attributed <Mark kind="estimated" /></span>
          <span className="xcheck-v">{usd(scoped.attributed, 2)}</span>
        </div>
        <div className="xcheck-op" aria-hidden="true">+</div>
        <div className="xcheck-cell">
          <span className="xcheck-k">Drift <Mark kind="drift" /></span>
          <span className="xcheck-v is-drift">{usd(scoped.drift, 2)}</span>
        </div>
        <div className="xcheck-op" aria-hidden="true">=</div>
        <div className="xcheck-cell">
          <span className="xcheck-k">
            {service ? `${shortService(service)} total` : "Cost Explorer total"} <Mark kind="exact" />
          </span>
          <span className="xcheck-v">{usd(scoped.total, 2)}</span>
        </div>
        <p className="xcheck-note">
          These rows are estimates: usage-type buckets split by running hours and list price, then
          rescaled to the service total. Drift is{" "}
          {((scoped.drift / scoped.total) * 100).toFixed(1)}% of the total and is shown on its own
          line, never spread across the rows.
        </p>
      </div>

      <div className="void-md" />

      <div className="chip-row" role="group" aria-label="Filter by service">
        <button
          type="button"
          className={`chip ${service === null ? "on" : ""}`}
          aria-pressed={service === null}
          onClick={() => setService(null)}
        >
          All services
        </button>
        {withResources.map((s) => (
          <button
            key={s.name}
            type="button"
            className={`chip ${service === s.name ? "on" : ""}`}
            aria-pressed={service === s.name}
            onClick={() => setService(s.name)}
          >
            {shortService(s.name)}
          </button>
        ))}
      </div>

      <div className="void-md" />

      <div className="tt-wrap">
        <div className="panel-head">
          <p>Showing {rows.length} of {rows.length} resources.</p>
        </div>
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
              {rows.map((r) => (
                <tr key={r.resource_id}>
                  <td className="tt-lead">
                    {r.name}
                    <span className="under"><CopyIdButton resourceId={r.resource_id} /></span>
                  </td>
                  <td className="tt-quiet col">{shortService(r.service)}</td>
                  <td className="col-id"><CopyIdButton resourceId={r.resource_id} /></td>
                  <td className="num"><span className="num-strong">{usd(r.cost, 2)}</span></td>
                </tr>
              ))}
              <tr className="tt-drift">
                <td>
                  <strong>Unattributed charges</strong>
                  <div style={{ fontSize: 12.5, marginTop: 3 }}>
                    Most often terminated or deleted resources.
                  </div>
                </td>
                <td className="tt-quiet">-</td>
                <td className="col-id"><span className="id">gap vs CE total</span></td>
                <td className="num"><span className="num-strong">{usd(scoped.drift, 2)}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <Legend />
    </>
  );
}
