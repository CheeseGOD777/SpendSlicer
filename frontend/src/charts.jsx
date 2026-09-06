import React from "react";
import {
  ResponsiveContainer,
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
import { usdCompact, usdTip } from "./lib/format";

// Line liveries — the bounded series set from tokens.css (--line-1..8).
// These appear inside data marks only; never as chrome.
export const PALETTE = [
  "#1B4FC0", "#0B6E5F", "#6E35B8", "#B15400",
  "#00697F", "#9A1758", "#4C5A1E", "#5C6672",
];

const tooltipStyle = {
  background: "var(--panel)",
  border: "1px solid var(--rule-2)",
  borderRadius: 8,
  boxShadow: "var(--lift-2)",
  padding: "9px 11px",
  fontFamily: "var(--face)",
  fontSize: 13,
  fontVariantNumeric: "tabular-nums",
  color: "var(--ink)",
};
const tooltipItemStyle = { color: "var(--ink)", padding: 0 };
const tooltipLabelStyle = {
  color: "var(--ink-4)",
  fontSize: 12,
  fontFamily: "var(--face-col)",
  fontWeight: 600,
  marginBottom: 4,
};
const axisTick = {
  fill: "var(--ink-4)",
  fontSize: 12,
  fontFamily: "var(--face-col)",
};

export function TrendBars({ data, keys, height = 288 }) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 10, right: 4, left: 0, bottom: 2 }} barCategoryGap="26%">
          <CartesianGrid stroke="var(--rule)" strokeDasharray="0" vertical={false} />
          <XAxis
            dataKey="month"
            tick={axisTick}
            axisLine={{ stroke: "var(--rule-2)" }}
            tickLine={false}
            tickMargin={9}
          />
          <YAxis
            tickFormatter={usdCompact}
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            tickMargin={7}
            width={52}
          />
          <Tooltip
            cursor={{ fill: "rgba(15, 19, 24, 0.05)" }}
            formatter={(v) => usdTip(v)}
            contentStyle={tooltipStyle}
            itemStyle={tooltipItemStyle}
            labelStyle={tooltipLabelStyle}
          />
          {keys.map((k) => (
            <Bar
              key={k}
              dataKey={k}
              stackId="total"
              fill="var(--line-1)"
              radius={[2, 2, 0, 0]}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Donut({ data, size = 208, thickness = 17 }) {
  const total = data.reduce((s, d) => s + Number(d.value || 0), 0) || 1;
  const [hover, setHover] = React.useState(null);
  const segs = data.map((d) => ({ ...d, pct: (Number(d.value || 0) / total) * 100 }));
  const focused = hover !== null ? segs[hover] : null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 26, flexWrap: "wrap" }}>
      <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={segs}
              dataKey="value"
              nameKey="name"
              innerRadius={size / 2 - thickness}
              outerRadius={size / 2 - 2}
              paddingAngle={1.5}
              stroke="var(--panel)"
              strokeWidth={2}
              isAnimationActive={false}
              onMouseEnter={(_, i) => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              {segs.map((s, i) => (
                <Cell
                  key={s.key ?? i}
                  fill={s.color}
                  opacity={hover === null || hover === i ? 1 : 0.34}
                />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "grid",
            placeItems: "center",
            pointerEvents: "none",
            textAlign: "center",
            padding: thickness + 6,
          }}
        >
          <div>
            <div
              style={{
                fontFamily: "var(--face-board)",
                fontSize: 27,
                fontWeight: 600,
                lineHeight: 1,
                letterSpacing: "-0.012em",
              }}
            >
              {focused ? `${focused.pct.toFixed(1)}%` : segs.length}
            </div>
            <div
              style={{
                fontFamily: "var(--face-col)",
                fontSize: 12,
                fontWeight: 600,
                color: "var(--ink-4)",
                marginTop: 5,
                maxWidth: size - thickness * 2 - 12,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {focused ? focused.name : "services"}
            </div>
          </div>
        </div>
      </div>

      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 7, minWidth: 0, flex: 1 }}>
        {segs.map((s, i) => (
          <li
            key={s.key ?? i}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            style={{
              display: "grid",
              gridTemplateColumns: "9px 1fr auto",
              alignItems: "center",
              gap: 10,
              fontSize: 13,
              opacity: hover === null || hover === i ? 1 : 0.5,
              transition: "opacity 130ms",
              minWidth: 0,
            }}
          >
            <span style={{ width: 9, height: 9, borderRadius: 2, background: s.color }} />
            <span style={{ color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--face-col)", fontWeight: 500 }}>
              {s.name}
            </span>
            <span style={{ color: "var(--ink-4)", fontVariantNumeric: "tabular-nums", fontSize: 12.5 }}>
              {s.pct.toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
