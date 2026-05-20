// icons.jsx — Stroke-based, 1.5px, currentColor. Lucide-flavoured.
// All take a single `s` size prop. Wrap in spans if you need fill bg.

const Icon = ({ children, s = 18, sw = 1.5, ...p }) => (
  <svg width={s} height={s} viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth={sw}
       strokeLinecap="round" strokeLinejoin="round"
       className="ico" {...p}>{children}</svg>
);

const I = {
  Dashboard: (p) => <Icon {...p}><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></Icon>,
  Services: (p) => <Icon {...p}><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><circle cx="7" cy="7" r="0.6" fill="currentColor"/><circle cx="7" cy="17" r="0.6" fill="currentColor"/></Icon>,
  Resources: (p) => <Icon {...p}><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></Icon>,
  Trends: (p) => <Icon {...p}><path d="M3 17l5-6 4 3 7-9"/><path d="M14 5h5v5"/></Icon>,
  Audit: (p) => <Icon {...p}><path d="M9 12l2 2 4-4"/><path d="M20 7v6a8 8 0 0 1-8 8 8 8 0 0 1-8-8V7l8-4 8 4z"/></Icon>,
  Export: (p) => <Icon {...p}><path d="M12 3v12"/><path d="M7 8l5-5 5 5"/><path d="M20 17v3H4v-3"/></Icon>,
  Settings: (p) => <Icon {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></Icon>,
  Chevron: (p) => <Icon {...p}><polyline points="6 9 12 15 18 9"/></Icon>,
  ChevronL: (p) => <Icon {...p}><polyline points="15 18 9 12 15 6"/></Icon>,
  ChevronR: (p) => <Icon {...p}><polyline points="9 18 15 12 9 6"/></Icon>,
  Refresh: (p) => <Icon {...p}><polyline points="23 4 23 10 17 10"/><path d="M20.5 15A9 9 0 1 1 18 5.3L23 10"/></Icon>,
  Search: (p) => <Icon {...p}><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.7" y2="16.7"/></Icon>,
  Info: (p) => <Icon {...p}><circle cx="12" cy="12" r="9"/><line x1="12" y1="16" x2="12" y2="11"/><circle cx="12" cy="8" r="0.8" fill="currentColor" stroke="none"/></Icon>,
  Up: (p) => <Icon {...p}><polyline points="18 15 12 9 6 15"/></Icon>,
  Down: (p) => <Icon {...p}><polyline points="6 9 12 15 18 9"/></Icon>,
  ArrowUp: (p) => <Icon {...p}><line x1="12" y1="19" x2="12" y2="5"/><polyline points="6 11 12 5 18 11"/></Icon>,
  ArrowDown: (p) => <Icon {...p}><line x1="12" y1="5" x2="12" y2="19"/><polyline points="18 13 12 19 6 13"/></Icon>,
  ArrowRight: (p) => <Icon {...p}><line x1="5" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/></Icon>,
  Copy: (p) => <Icon {...p}><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></Icon>,
  Check: (p) => <Icon {...p}><polyline points="20 6 9 17 4 12"/></Icon>,
  X: (p) => <Icon {...p}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></Icon>,
  Filter: (p) => <Icon {...p}><polygon points="22 3 2 3 10 12.5 10 19 14 21 14 12.5 22 3"/></Icon>,
  Plus: (p) => <Icon {...p}><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></Icon>,
  LogOut: (p) => <Icon {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></Icon>,
  Bell: (p) => <Icon {...p}><path d="M18 8A6 6 0 1 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></Icon>,
  Cloud: (p) => <Icon {...p}><path d="M17.5 19a4.5 4.5 0 1 0-1-8.9 6 6 0 0 0-11.6 1.4 4 4 0 0 0 .6 7.9z"/></Icon>,
  Cpu: (p) => <Icon {...p}><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="2" x2="9" y2="4"/><line x1="15" y1="2" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="22"/><line x1="15" y1="20" x2="15" y2="22"/><line x1="2" y1="9" x2="4" y2="9"/><line x1="20" y1="9" x2="22" y2="9"/><line x1="2" y1="15" x2="4" y2="15"/><line x1="20" y1="15" x2="22" y2="15"/></Icon>,
  Database: (p) => <Icon {...p}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></Icon>,
  Coins: (p) => <Icon {...p}><circle cx="9" cy="9" r="6"/><path d="M15 15a6 6 0 1 1-6-6"/></Icon>,
  Wallet: (p) => <Icon {...p}><path d="M20 8H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2z"/><path d="M2 6v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2H4"/><circle cx="17" cy="14" r="1.2"/></Icon>,
  Flame: (p) => <Icon {...p}><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2.4-1.5-3.5C8 7 8 5 8 5s5 1 8 6c1.5 2.4 1 5.5-1.5 7-1 .5-2.5 1-4 1A4.5 4.5 0 0 1 6 14.5C6 13.4 6.5 12.4 7.5 11.5"/></Icon>,
  Wrench: (p) => <Icon {...p}><path d="M14.7 6.3a4 4 0 0 0 5.7 5.7L21 13l-9 9-1.5-.3a4 4 0 0 0-5.7-5.7L4 15 13 6z"/></Icon>,
  Tag: (p) => <Icon {...p}><path d="M20.6 13.4l-7.5 7.5a1.4 1.4 0 0 1-2 0L2 11.8V2h9.8l9.4 9.4a1.4 1.4 0 0 1 0 2z"/><circle cx="7" cy="7" r="1"/></Icon>,
  Server: (p) => <Icon {...p}><rect x="2" y="3" width="20" height="7" rx="1.5"/><rect x="2" y="14" width="20" height="7" rx="1.5"/><line x1="6" y1="6.5" x2="6.01" y2="6.5"/><line x1="6" y1="17.5" x2="6.01" y2="17.5"/></Icon>,
  Alert: (p) => <Icon {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><circle cx="12" cy="17" r="0.8" fill="currentColor" stroke="none"/></Icon>,
  Sparkle: (p) => <Icon {...p}><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></Icon>,
  Workspace: (p) => <Icon {...p}><path d="M3 8l9-5 9 5-9 5z"/><path d="M3 12l9 5 9-5"/><path d="M3 16l9 5 9-5"/></Icon>,
  Box: (p) => <Icon {...p}><path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5"/><line x1="12" y1="13" x2="12" y2="21"/></Icon>,
  Folder: (p) => <Icon {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></Icon>,
  Zap: (p) => <Icon {...p}><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></Icon>,
  Globe: (p) => <Icon {...p}><circle cx="12" cy="12" r="9"/><line x1="3" y1="12" x2="21" y2="12"/><path d="M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></Icon>,
  Activity: (p) => <Icon {...p}><polyline points="3 12 7 12 10 5 14 19 17 12 21 12"/></Icon>,
  Disk: (p) => <Icon {...p}><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/></Icon>,
  Sun: (p) => <Icon {...p}><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4" y1="12" x2="2" y2="12"/><line x1="22" y1="12" x2="20" y2="12"/><line x1="5.6" y1="5.6" x2="4.2" y2="4.2"/><line x1="19.8" y1="19.8" x2="18.4" y2="18.4"/><line x1="5.6" y1="18.4" x2="4.2" y2="19.8"/><line x1="19.8" y1="4.2" x2="18.4" y2="5.6"/></Icon>,
  Moon: (p) => <Icon {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></Icon>,
};

// ─── Cloud Ledger brand mark ────────────────────────────────────────────
// Three ledger bars (entries) of varying width with a single live-status
// dot in the brand accent. Minimal, distinctive, scales cleanly.
const CloudLedgerMark = ({ s = 32, bg = 'var(--ink)', fg = '#fff', dot = 'var(--accent)' }) => (
  <svg width={s} height={s} viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg"
       style={{ display: 'block' }}>
    <rect x="0" y="0" width="32" height="32" rx="8" fill={bg} />
    {/* top ledger bar — short */}
    <rect x="7"  y="9"    width="11" height="2.4" rx="1.2" fill={fg} opacity="0.92" />
    {/* mid ledger bar — long (longest entry) */}
    <rect x="7"  y="14.8" width="18" height="2.4" rx="1.2" fill={fg} />
    {/* bottom ledger bar — medium */}
    <rect x="7"  y="20.6" width="8"  height="2.4" rx="1.2" fill={fg} opacity="0.6" />
    {/* live dot — connects to brand accent */}
    <circle cx="22.5" cy="10.2" r="1.7" fill={dot} />
  </svg>
);

// Wordmark variant (mark + "Cloud Ledger" text inline) — for splash, exports
const CloudLedgerWordmark = ({ s = 26, color = 'var(--ink)' }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, color }}>
    <CloudLedgerMark s={s} bg={color} />
    <span style={{
      fontFamily: 'var(--font-display)',
      fontSize: s * 0.62,
      fontWeight: 600,
      letterSpacing: '-0.028em',
      lineHeight: 1
    }}>Cloud Ledger</span>
  </span>
);

Object.assign(window, { I, Icon, CloudLedgerMark, CloudLedgerWordmark });
