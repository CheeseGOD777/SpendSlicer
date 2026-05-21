// frontend/src/components/CostBadge.jsx
import { useEffect, useState } from "react";
import { resetCe, subscribeCe } from "../lib/ceMeter";

export function CostBadge() {
  const [total, setTotal] = useState({ calls: 0, costUsd: 0 });
  useEffect(() => subscribeCe(setTotal), []);
  if (total.calls === 0) return null;
  return (
    <div className="cost-badge" title="Cost Explorer spend this session — click to reset">
      <button onClick={resetCe} aria-label="Reset session cost meter">
        CE: {total.calls} call{total.calls === 1 ? "" : "s"} · ${total.costUsd.toFixed(4)}
      </button>
    </div>
  );
}
