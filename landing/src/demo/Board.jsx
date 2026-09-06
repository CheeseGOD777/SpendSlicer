/* The board, live. Same markup and same stylesheet as DashboardPage, with
   the fetch replaced by the demo dataset.

   The Flap numerals are the product's signature motion and they earn their
   place here: the headline figure is the one thing a visitor must look at
   first, and the roll puts their eye on it. */

import { Mark } from "@app/components/Marks.jsx";
import { Flap } from "@app/components/Flap.jsx";
import { IconArrowUp, IconArrowDown, IconMinus } from "@app/lib/icons.jsx";
import { usd, pct, value } from "@app/lib/format.js";
import { PROFILE, SUMMARY, SERVICES, CE_TOTAL, ATTRIBUTED, DRIFT } from "./data";

/* The line liveries, read straight off tokens.css. Importing PALETTE from
   charts.jsx would be the same eight colours but would also pull Recharts
   into the first paint, and the hero does not draw a chart. */
const LINE = (i) => `var(--line-${(i % 8) + 1})`;


const shortService = (n) => String(n || "Unknown").replace("Amazon ", "").replace("AWS ", "");

export function Delta({ value: v, note }) {
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

export function Xcheck() {
  return (
    <div className="xcheck">
      <div className="xcheck-cell">
        <span className="xcheck-k">Attributed to resources</span>
        <span className="xcheck-v">{usd(ATTRIBUTED, 2)}</span>
      </div>
      <div className="xcheck-op" aria-hidden="true">+</div>
      <div className="xcheck-cell">
        <span className="xcheck-k">Unattributed drift <Mark kind="drift" /></span>
        <span className="xcheck-v is-drift">{usd(DRIFT, 2)}</span>
      </div>
      <div className="xcheck-op" aria-hidden="true">=</div>
      <div className="xcheck-cell">
        <span className="xcheck-k">Cost Explorer total <Mark kind="exact" /></span>
        <span className="xcheck-v">{usd(CE_TOTAL, 2)}</span>
      </div>
      <p className="xcheck-note">
        Attributed plus drift equals the Cost Explorer total. Drift is charge that could not be
        tied to a named resource, and it is never spread across the rows.
      </p>
    </div>
  );
}

export function Board({ rows = 5 }) {
  const dep = SERVICES.slice(0, rows);

  return (
    <section className="board" aria-label="Period spend board">
      <div className="board-main">
        <div className="board-figure">
          <div className="board-cap">
            {PROFILE} · month to date · {SUMMARY.cost_basis_label}
          </div>
          <div className="board-total">
            <Flap text={usd(SUMMARY.total_mtd, 2)} />
          </div>
          <div className="board-sub">
            <Delta value={SUMMARY.change_pct} note="versus the previous period" />
            <span>vs previous period</span>
            <Mark kind="exact" />
          </div>
        </div>

        <div className="board-aside">
          <div className="board-aside-cell">
            <span className="board-aside-k">Previous period</span>
            <span className="board-aside-v">{usd(SUMMARY.total_prev, 2)}</span>
          </div>
          <div className="board-aside-cell">
            <span className="board-aside-k">Forecast at close</span>
            <span className="board-aside-v">{usd(SUMMARY.forecast, 2)}</span>
          </div>
        </div>
      </div>

      <Xcheck />

      <div className="dep">
        {dep.map((row, i) => {
          const share = (value(row.cost) / CE_TOTAL) * 100;
          return (
            <div
              className="dep-row"
              key={row.name}
              style={{ "--mass": Math.max(0.012, share / 100), "--mass-ink": LINE(i) }}
            >
              <span className="dep-name" title={row.name}>{shortService(row.name)}</span>
              <span className="dep-badge">
                {share.toFixed(0)}%<span className="sr-only"> of period spend</span>
              </span>
              <span className="dep-cost">{usd(row.cost, 2)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
