// Inline status banner used for backend errors, partial-data caveats,
// and stale-cache warnings. Keeps failure states visible instead of
// letting pages silently render $0.000.
const TONES = {
  error: { background: "#9E3B2E", color: "#fff" },
  warn: { background: "#A77418", color: "#fff" },
};

export function Banner({ tone = "warn", onRetry, children }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      style={{
        ...TONES[tone],
        padding: "8px 12px",
        borderRadius: 6,
        marginBottom: 12,
        fontSize: 13,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <span style={{ flex: 1 }}>{children}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          style={{
            background: "rgba(255,255,255,0.18)", color: "inherit", border: "1px solid rgba(255,255,255,0.4)",
            borderRadius: 4, padding: "3px 10px", cursor: "pointer", fontSize: 12,
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

// Convenience: one warning line when any hook on the page served stale cache.
export function StaleBanner({ hooks }) {
  const stale = hooks.some((h) => h?.meta?.fromCache === "stale");
  if (!stale) return null;
  return (
    <Banner tone="warn">
      Showing cached data — couldn't reach the server for fresh figures. These numbers may be stale.
    </Banner>
  );
}
