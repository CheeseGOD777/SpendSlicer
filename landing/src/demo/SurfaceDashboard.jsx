/* Dashboard, live. The board itself lives in the hero, so this surface
   carries what sits below it on the real page: the trend, the top
   resources, and the service mix. */

import { Mark, Legend } from "@app/components/Marks.jsx";
import { TrendBars, Donut, PALETTE } from "@app/charts.jsx";
import { usd } from "@app/lib/format.js";
import { TREND, SERVICES, RESOURCES, CE_TOTAL } from "./data";

const shortService = (n) => String(n || "Unknown").replace("Amazon ", "").replace("AWS ", "");

const peak = TREND.reduce((a, b) => (b.Spend > a.Spend ? b : a), TREND[0]);
const average = TREND.reduce((a, b) => a + b.Spend, 0) / TREND.length;

/* Donut needs an explicit colour per slice; the palette is the product's.
   Its legend is a narrow fixed column that ellipsises long names, so the mix
   uses the short forms an AWS engineer reads anyway. */
const ABBREV = {
  "Amazon Elastic Compute Cloud - Compute": "EC2",
  "Amazon Relational Database Service": "RDS",
  "Amazon Simple Storage Service": "S3",
  "Elastic Load Balancing": "ELB",
};
const abbrev = (n) => ABBREV[n] || shortService(n);

const TOP = SERVICES.slice(0, 6);
const mix = TOP
  .map((s, i) => ({ name: abbrev(s.name), value: s.cost, color: PALETTE[i % PALETTE.length] }))
  .concat([{
    name: "Other",
    value: Math.round((CE_TOTAL - TOP.reduce((a, s) => a + s.cost, 0)) * 100) / 100,
    color: PALETTE[7],
  }]);

export function SurfaceDashboard() {
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Spend over the period</h2>
            <p>
              Peak {usd(peak.Spend, 2)} on {peak.label} · average {usd(average, 2)} ·{" "}
              {TREND.length} samples
            </p>
          </div>
          <Mark kind="exact" />
        </div>
        <div className="panel-body">
          <TrendBars data={TREND} keys={["Spend"]} height={248} />
        </div>
      </section>

      <div className="void-lg" />

      <div className="split">
        <section className="tt-wrap">
          <div className="panel-head">
            <div>
              <h2>Top resources</h2>
              <p>Apportioned from usage-type buckets, then rescaled to the service total.</p>
            </div>
            <Mark kind="estimated" />
          </div>
          <div className="tt-scroll">
            <table className="tt">
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>Service</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {RESOURCES.map((r) => (
                  <tr key={r.resource_id}>
                    <td className="tt-lead">{r.name}</td>
                    <td className="tt-quiet col">{shortService(r.service)}</td>
                    <td className="num"><span className="num-strong">{usd(r.cost, 2)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
            <Donut data={mix} size={150} thickness={13} />
          </div>
        </section>
      </div>

      <Legend />
    </>
  );
}
