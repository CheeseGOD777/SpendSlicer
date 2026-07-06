// Shared money/number formatting. Single source of truth for the app,
// charts, and PDF-adjacent UI so credits/negatives render consistently.

export const value = (v, fallback = 0) => Number(v ?? fallback);

export const usd = (n, dec = 3) => {
  let num = Number(n || 0);
  // CE sometimes returns tiny negative floats (-0.00001); clamp to zero before display
  if (num < 0 && Math.abs(num) < 5 * Math.pow(10, -(dec + 1))) num = 0;
  const sign = num < 0 ? "-" : "";
  return `${sign}$${Math.abs(num).toLocaleString("en-US", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  })}`;
};

// Compact form for axis ticks: $1.5k / $2.5M, sign outside the dollar.
export const usdCompact = (v) => {
  const num = Number(v || 0);
  const sign = num < 0 ? "-" : "";
  const abs = Math.abs(num);
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  if (abs >= 1) return `${sign}$${abs.toFixed(0)}`;
  return `${sign}$${abs.toFixed(2)}`;
};

// Tooltip form: always keep cents — a cost tool must not round $45.67 to $46 on hover.
export const usdTip = (v) => usd(v, 2);

export const pct = (n) => `${Number(n || 0) >= 0 ? "+" : ""}${Number(n || 0).toFixed(1)}%`;
