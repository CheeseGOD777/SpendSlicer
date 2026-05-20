import React from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
  BarChart,
  Bar,
  AreaChart as RechartsAreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
} from "recharts";

export const SERIES_COLORS = {
  EC2: "#0E9F6E",
  RDS: "#3B5BDB",
  S3: "#A24DDD",
  Lambda: "#DB8E1B",
  CloudFront: "#11AABE",
  Other: "#555555",
};

const usdK = (n) => {
  const v = Number(n || 0);
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
};

export function Sparkline({ data, color = "var(--accent)", width = 86, height = 28 }) {
  if (!data || data.length < 2) return <div style={{ width, height }} />;
  const rows = data.map((v, i) => ({ i, v }));
  return (
    <div style={{ width, height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows}>
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.7} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StackedBars({ data, keys, height = 280 }) {
  const fillForKey = (k) => SERIES_COLORS[k] || "var(--accent)";
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 12, bottom: 4 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" />
          <XAxis dataKey="month" tick={{ fill: "var(--ink-4)", fontSize: 12, fontFamily: "var(--font-mono)" }} />
          <YAxis tickFormatter={usdK} tick={{ fill: "var(--ink-4)", fontSize: 12, fontFamily: "var(--font-mono)" }} />
          <Tooltip
            formatter={(v) => usdK(v)}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--line-2)", borderRadius: 10 }}
          />
          {keys.map((k) => (
            <Bar key={k} dataKey={k} stackId="total" fill={fillForKey(k)} radius={[4, 4, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AreaChart({ data, labels, height = 320 }) {
  if (!data || data.length === 0) return <div style={{ width: "100%", height }} />;
  const rows = data.map((v, i) => ({ label: labels?.[i] || String(i + 1), value: Number(v || 0) }));
  if (rows.length === 1) {
    return (
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" />
            <XAxis dataKey="label" tick={{ fill: "var(--ink-4)", fontSize: 12, fontFamily: "var(--font-mono)" }} />
            <YAxis tickFormatter={usdK} tick={{ fill: "var(--ink-4)", fontSize: 12, fontFamily: "var(--font-mono)" }} />
            <Tooltip formatter={(v) => usdK(v)} contentStyle={{ background: "var(--surface)", border: "1px solid var(--line-2)", borderRadius: 10 }} />
            <Bar dataKey="value" fill="#5B3FC0" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <RechartsAreaChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
          <defs>
            <linearGradient id="trendArea" x1="0" x2="0" y1="0" y2="1">
              <stop offset="5%" stopColor="var(--grad-a)" stopOpacity={0.4} />
              <stop offset="95%" stopColor="var(--grad-c)" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" />
          <XAxis dataKey="label" tick={{ fill: "var(--ink-4)", fontSize: 12, fontFamily: "var(--font-mono)" }} />
          <YAxis tickFormatter={usdK} tick={{ fill: "var(--ink-4)", fontSize: 12, fontFamily: "var(--font-mono)" }} />
          <Tooltip
            formatter={(v) => usdK(v)}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--line-2)", borderRadius: 10 }}
          />
          <Area type="monotone" dataKey="value" stroke="#5B3FC0" fill="url(#trendArea)" strokeWidth={2.2} />
        </RechartsAreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Donut({ data, size = 220, thickness = 26 }) {
  const total = data.reduce((s, d) => s + Number(d.value || 0), 0) || 1;
  const [hover, setHover] = React.useState(null);
  const segs = data.map((d) => ({ ...d, pct: (Number(d.value || 0) / total) * 100 }));
  const focused = hover !== null ? segs[hover] : null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24, justifyContent: "center", flexWrap: "wrap" }}>
      <div style={{ position: "relative", width: size, height: size }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={segs}
              dataKey="value"
              nameKey="name"
              innerRadius={size / 2 - thickness - 6}
              outerRadius={size / 2 - 6}
              paddingAngle={1}
              onMouseEnter={(_, i) => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              {segs.map((s, i) => (
                <Cell key={s.key} fill={s.color} fillOpacity={hover === null || hover === i ? 1 : 0.3} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => usdK(v)} />
          </PieChart>
        </ResponsiveContainer>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>
          <div>
            <div style={{ fontSize: 11, color: "var(--ink-4)", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>
              {focused ? focused.name : "Service mix"}
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 600 }}>
              {focused ? usdK(focused.value) : usdK(total)}
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-4)" }}>
              {focused ? `${focused.pct.toFixed(1)}%` : `${data.length} services`}
            </div>
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 220 }}>
        {segs.map((s, i) => (
          <div
            key={s.key}
            style={{
              display: "grid",
              gridTemplateColumns: "10px 1fr auto auto",
              gap: 10,
              alignItems: "center",
              padding: "6px 8px",
              borderRadius: 8,
              background: hover === i ? "var(--surface-2)" : "transparent",
            }}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color }} />
            <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 180 }}>
              {s.name}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-4)" }}>{s.pct.toFixed(1)}%</span>
            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>{usdK(s.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
