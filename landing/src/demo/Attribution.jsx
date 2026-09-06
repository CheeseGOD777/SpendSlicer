/* ─── The attribution explainer ────────────────────────────────────────
   The one thing on this page that has to teach rather than display.

   Pick a service. Both columns add up to the same dollar. The left column
   is what AWS hands you: usage-type buckets priced by the hour, with no
   machine attached. The right column is the same money against named
   resources, with the part that could not be tied to one shown on its own
   line instead of smeared across the rows.

   Every figure is drawn from the shared demo dataset, so the two columns
   cannot silently disagree. */

import { useMemo, useState } from "react";
import { Mark } from "@app/components/Marks.jsx";
import { usd, value } from "@app/lib/format.js";
import { SERVICES, COMPOSITION, RESOURCES } from "./data";

const COMPOSITION_COLORS = {
  compute: "var(--line-1)",
  storage: "var(--line-2)",
  "data-transfer": "var(--line-4)",
  network: "var(--line-5)",
  other: "var(--line-8)",
};

const CHOICES = Object.keys(COMPOSITION);
const shortService = (n) => String(n || "").replace("Amazon ", "").replace("AWS ", "");
const round2 = (n) => Math.round(n * 100) / 100;

export function Attribution() {
  const [service, setService] = useState(CHOICES[0]);

  const view = useMemo(() => {
    const svc = SERVICES.find((s) => s.name === service);
    const usage = [...(COMPOSITION[service].usage_types || [])]
      .sort((a, b) => value(b.cost) - value(a.cost));
    const named = RESOURCES.filter((r) => r.service === service)
      .sort((a, b) => value(b.cost) - value(a.cost));
    const attributed = round2(named.reduce((a, r) => a + r.cost, 0));
    return { svc, usage, named, attributed, drift: round2(svc.cost - attributed) };
  }, [service]);

  const { svc, usage, named, attributed, drift } = view;

  return (
    <div className="xp">
      <div className="chip-row" role="group" aria-label="Choose a service">
        {CHOICES.map((name) => (
          <button
            key={name}
            type="button"
            className={`chip ${service === name ? "on" : ""}`}
            aria-pressed={service === name}
            onClick={() => setService(name)}
          >
            {shortService(name)}
          </button>
        ))}
      </div>

      <p className="xp-sum">
        <span>{shortService(service)} billed</span>
        <b>{usd(svc.cost, 2)}</b>
        <Mark kind="exact" />
        <span className="xp-sum-note">in this window. Both columns below add up to it.</span>
      </p>

      <div className="xp-cols">
        {/* ── What AWS gives you ── */}
        <section className="xp-col" aria-labelledby="xp-aws">
          <header className="xp-head">
            <h3 id="xp-aws">What AWS gives you</h3>
            <p>Usage types, priced by the hour. No machine attached.</p>
          </header>
          <table className="comp-ut-tbl xp-tbl">
            <tbody>
              {usage.map((u) => (
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
                  <td className="num">{usd(u.cost, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="xp-foot">
            {usage.length} usage types, and not one of them names the resource behind
            the charge.
          </p>
        </section>

        {/* ── What SpendSlicer gives you ── */}
        <section className="xp-col xp-col-ours" aria-labelledby="xp-ours">
          <header className="xp-head">
            <h3 id="xp-ours">What SpendSlicer gives you</h3>
            <p>The same money, against named resources.</p>
          </header>
          <table className="tt xp-tbl xp-tbl-res">
            <tbody>
              {named.map((r) => (
                <tr key={r.resource_id}>
                  <td className="tt-lead">
                    {r.name}
                    {r.state ? <span className="xp-state">{r.state}</span> : null}
                  </td>
                  <td className="col-id"><span className="id">{r.resource_id}</span></td>
                  <td className="num"><span className="num-strong">{usd(r.cost, 2)}</span></td>
                </tr>
              ))}
              <tr className="tt-drift">
                <td>
                  <strong>Unattributed drift</strong>
                  <div style={{ fontSize: 12.5, marginTop: 3 }}>
                    Most often terminated or deleted resources.
                  </div>
                </td>
                <td className="col-id"><span className="id">gap vs CE total</span></td>
                <td className="num"><span className="num-strong">{usd(drift, 2)}</span></td>
              </tr>
            </tbody>
          </table>
          <p className="xp-foot">
            {named.length} named {named.length === 1 ? "resource" : "resources"} at{" "}
            {usd(attributed, 2)} <Mark kind="estimated" />, plus {usd(drift, 2)} that could not be
            tied to one. Shown, not hidden.
          </p>
        </section>
      </div>
    </div>
  );
}
