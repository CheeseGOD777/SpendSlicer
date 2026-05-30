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
  PieChart,
  Pie,
  Cell,
} from "recharts";

// Editorial palette (matches --s1..--s8 in tokens.css). Used for both the
// donut and any stacked-bar series. Single-series spend uses --accent.
export const PALETTE = ["#1C5E3F", "#2D5478", "#9E3B2E", "#A77418", "#1F6E6E", "#5D3A53", "#6E6048", "#847A6E"];

export const SERIES_COLORS = {
  EC2: "#1C5E3F",
  RDS: "#2D5478",
  S3: "#5D3A53",
  Lambda: "#A77418",
  CloudFront: "#1F6E6E",
  Other: "#847A6E",
};

const usdK = (n) => {
  const v = Number(n || 0);
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  if (v >= 1)   return `$${v.toFixed(0)}`;
  return `$${v.toFixed(2)}`;
};

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--line-2)",
  borderRadius: 8,
  boxShadow: "var(--shadow-2)",
  padding: "8px 10px",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  color: "var(--ink)",
};
const tooltipItemStyle = { color: "var(--ink)", padding: 0 };
const tooltipLabelStyle = {
  color: "var(--ink-4)",
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  fontFamily: "var(--font-sans)",
  fontWeight: 700,
  marginBottom: 4,
};
const axisTick = { fill: "var(--ink-4)", fontSize: 11, fontFamily: "var(--font-mono)", letterSpacing: -0.2 };

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

export function StackedBars({ data, keys, height = 300 }) {
  const fillForKey = (k) => SERIES_COLORS[k] || "var(--accent)";
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 4, left: 0, bottom: 4 }} barCategoryGap="22%">
          <CartesianGrid stroke="var(--line)" strokeDasharray="0" vertical={false} />
          <XAxis
            dataKey="month"
            tick={axisTick}
            axisLine={{ stroke: "var(--line-2)" }}
            tickLine={false}
            tickMargin={8}
          />
          <YAxis
            tickFormatter={usdK}
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            tickMargin={6}
            width={48}
          />
          <Tooltip
            cursor={{ fill: "rgba(28, 94, 63, 0.06)" }}
            formatter={(v) => usdK(v)}
            contentStyle={tooltipStyle}
            itemStyle={tooltipItemStyle}
            labelStyle={tooltipLabelStyle}
          />
          {keys.map((k) => (
            <Bar key={k} dataKey={k} stackId="total" fill={fillForKey(k)} radius={[2, 2, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// Kept for API compatibility; renders a minimal bar fallback. Trends page
// is removed, so this is not used by the app in the current build.
export function AreaChart({ data, labels, height = 320 }) {
  if (!data || data.length === 0) return <div style={{ width: "100%", height }} />;
  const rows = data.map((v, i) => ({ label: labels?.[i] || String(i + 1), value: Number(v || 0) }));
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 4, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis dataKey="label" tick={axisTick} axisLine={{ stroke: "var(--line-2)" }} tickLine={false} />
          <YAxis tickFormatter={usdK} tick={axisTick} axisLine={false} tickLine={false} width={48} />
          <Tooltip formatter={(v) => usdK(v)} contentStyle={tooltipStyle} itemStyle={tooltipItemStyle} labelStyle={tooltipLabelStyle} />
          <Bar dataKey="value" fill="var(--accent)" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Donut({ data, size = 240, thickness = 18 }) {
  const total = data.reduce((s, d) => s + Number(d.value || 0), 0) || 1;
  const [hover, setHover] = React.useState(null);
  const segs = data.map((d) => ({ ...d, pct: (Number(d.value || 0) / total) * 100 }));
  const focused = hover !== null ? segs[hover] : null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 32, justifyContent: "flex-start", flexWrap: "wrap" }}>
      <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={segs}
              dataKey="value"
              nameKey="name"
              innerRadius={size / 2 - thickness - 4}
              outerRadius={size / 2 - 4}
              paddingAngle={0.6}
              stroke="var(--surface)"
              strokeWidth={1.5}
              onMouseEnter={(_, i) => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              {segs.map((s, i) => (
                <Cell key={s.key} fill={s.color} fillOpacity={hover === null || hover === i ? 1 : 0.22} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => usdK(v)} contentStyle={tooltipStyle} itemStyle={tooltipItemStyle} labelStyle={tooltipLabelStyle} />
          </PieChart>
        </ResponsiveContainer>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center", pointerEvents: "none" }}>
          <div>
            <div
              style={{
                fontSize: 10,
                color: "var(--ink-4)",
                textTransform: "uppercase",
                letterSpacing: "0.18em",
                fontWeight: 700,
                fontFamily: "var(--font-sans)",
                marginBottom: 4,
              }}
            >
              {focused ? focused.name.slice(0, 18) : "Service mix"}
            </div>
            <div
              style={{
                fontFamily: "var(--font-display)",
                fontSize: 32,
                fontWeight: 700,
                letterSpacing: "-0.03em",
                fontVariantNumeric: "tabular-nums",
                lineHeight: 1,
                color: "var(--ink)",
              }}
            >
              {focused ? usdK(focused.value) : usdK(total)}
            </div>
            <div
              style={{
                marginTop: 6,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--ink-4)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {focused ? `${focused.pct.toFixed(1)}%` : `${data.length} services`}
            </div>
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 240, flex: 1 }}>
        {segs.map((s, i) => (
          <div
            key={s.key}
            style={{
              display: "grid",
              gridTemplateColumns: "8px 1fr auto auto",
              gap: 12,
              alignItems: "center",
              padding: "9px 10px",
              borderRadius: 6,
              background: hover === i ? "var(--surface-2)" : "transparent",
              borderBottom: i < segs.length - 1 ? "1px solid var(--line)" : "none",
              transition: "background 140ms ease",
              cursor: "default",
            }}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
            <span
              style={{
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: 220,
                fontSize: 13,
                color: "var(--ink-2)",
              }}
            >
              {s.name}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--ink-4)",
                fontVariantNumeric: "tabular-nums",
                minWidth: 44,
                textAlign: "right",
              }}
            >
              {s.pct.toFixed(1)}%
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12.5,
                color: "var(--ink)",
                fontVariantNumeric: "tabular-nums",
                fontWeight: 500,
                minWidth: 60,
                textAlign: "right",
              }}
            >
              {usdK(s.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
