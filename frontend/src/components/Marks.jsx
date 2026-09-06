/* The board's legend vocabulary. Every accuracy mark used anywhere in the
   app is defined here once, and the legend renders from the same source —
   so a mark can never appear without a definition behind it. */

export const MARKS = {
  exact: {
    label: "Exact",
    cls: "mark-exact",
    means: "Ground truth from Cost Explorer GetCostAndUsage, or a real billed CUR line item. Matches the Billing console.",
  },
  estimated: {
    label: "Est.",
    cls: "mark-est",
    means: "Apportioned from usage-type buckets by running hours and list price, then rescaled to the service total. Directionally right, not billed.",
  },
  drift: {
    label: "Drift",
    cls: "mark-drift",
    means: "Spend that could not be tied to a named resource. Shown on its own line and never spread across the rows above it.",
  },
};

export function Mark({ kind, title }) {
  const m = MARKS[kind];
  if (!m) return null;
  return (
    <span className={`mark ${m.cls}`} title={title || m.means}>
      {m.label}
    </span>
  );
}

export function Legend({ kinds = ["exact", "estimated", "drift"] }) {
  return (
    <div className="legend">
      <span className="legend-title">How to read this board</span>
      {kinds.map((k) => (
        <span className="legend-item" key={k}>
          <Mark kind={k} />
          <span>{MARKS[k].means}</span>
        </span>
      ))}
    </div>
  );
}
