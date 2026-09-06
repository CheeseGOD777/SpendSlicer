import { IconAlert } from "../lib/icons";

// Inline status banner used for backend errors, partial-data caveats,
// and stale-cache warnings. Keeps failure states visible instead of
// letting pages silently render $0.000.
export function Banner({ tone = "warn", onRetry, children }) {
  return (
    <div className={`banner banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <IconAlert size={17} />
      <span className="banner-body">{children}</span>
      {onRetry && (
        <button type="button" className="banner-act" onClick={onRetry}>
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
      Showing cached figures — the server could not be reached for fresh numbers. These may be stale.
    </Banner>
  );
}
