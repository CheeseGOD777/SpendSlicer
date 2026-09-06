// frontend/src/components/CostBadge.jsx
import { useEffect, useState } from "react";
import { resetCe, subscribeCe } from "../lib/ceMeter";

// Cost Explorer bills $0.01 per request. This meter is a binding product
// commitment: using the tool costs real money and the UI never hides that.
export function CostBadge() {
  const [total, setTotal] = useState({ calls: 0, costUsd: 0 });
  useEffect(() => subscribeCe(setTotal), []);
  if (total.calls === 0) return null;
  return (
    <div className="meter">
      <button onClick={resetCe} title="Cost Explorer spend this session — click to reset">
        <span className="meter-coin" aria-hidden="true" />
        <span>
          {total.calls} call{total.calls === 1 ? "" : "s"} · ${total.costUsd.toFixed(4)}
        </span>
        <span className="sr-only"> spent on Cost Explorer this session. Activate to reset the meter.</span>
      </button>
    </div>
  );
}
