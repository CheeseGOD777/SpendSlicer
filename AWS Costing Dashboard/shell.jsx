// shell.jsx — Sidebar, TopBar, and shared shell helpers

const { useState, useRef, useEffect, useMemo } = React;

// ── Sidebar ─────────────────────────────────────────────────────────────
function Sidebar({ page, setPage, collapsed, setCollapsed, profile }) {
  const nav = [
    { group: 'Visibility', items: [
      { id: 'dashboard',  label: 'Dashboard',  icon: 'Dashboard' },
      { id: 'services',   label: 'Services',   icon: 'Services' },
      { id: 'resources',  label: 'Resources',  icon: 'Resources' },
      { id: 'trends',     label: 'Trends',     icon: 'Trends' },
    ]},
    { group: 'FinOps', items: [
      { id: 'audit',  label: 'Audit',  icon: 'Audit' },
      { id: 'export', label: 'Export', icon: 'Export' },
    ]},
  ];

  return (
    <aside className="side">
      <div className="side-brand">
        <img className="side-logo-img" src="cloud-ledger-logo.png" alt="Cloud Ledger" />
        <div className="side-brand-text">
          <span className="name">Cloud Ledger</span>
          <span className="tag">finops · v2.4</span>
        </div>
      </div>

      <button className="collapse-btn" onClick={() => setCollapsed(!collapsed)}
              title={collapsed ? 'Expand' : 'Collapse'}>
        {collapsed ? <I.ChevronR s={12} /> : <I.ChevronL s={12} />}
      </button>

      <nav style={{ flex: 1, overflowY: 'auto' }}>
        {nav.map(g => (
          <div key={g.group} className="side-group">
            <div className="side-group-label">{g.group}</div>
            {g.items.map(it => {
              const Ico = I[it.icon];
              return (
                <div key={it.id}
                     className={'side-item' + (page === it.id ? ' active' : '')}
                     onClick={() => setPage(it.id)}>
                  <Ico s={18} />
                  <span className="side-item-text">{it.label}</span>
                </div>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="side-bottom">
        <div className="side-group" style={{ marginTop: 0 }}>
          <div className="side-item"><I.Settings s={18} /><span className="side-item-text">Settings</span></div>
        </div>
        <div className="side-profile" style={{ marginTop: 6 }}>
          <div className="side-avatar">{profile.alias[0].toUpperCase()}</div>
          <div className="side-profile-text">
            <span className="side-profile-name">{profile.alias}</span>
            <span className="side-profile-role">{profile.account}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}

// ── Dropdown menu (used inside top bar) ────────────────────────────────
function useClickOutside(ref, onClose) {
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [ref, onClose]);
}

function Dropdown({ label, value, options, onChange, mono, align = 'right' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useClickOutside(ref, () => setOpen(false));
  return (
    <div className="dropdown" ref={ref}>
      <button className={'btn-ctl' + (mono ? ' is-mono' : '')} onClick={() => setOpen(!open)}>
        {label && <span style={{ color: 'var(--ink-4)', fontWeight: 500 }}>{label}</span>}
        <span>{value}</span>
        <I.Chevron s={14} />
      </button>
      {open && (
        <div className="menu" style={align === 'left' ? { left: 0, right: 'auto' } : null}>
          {options.map(o => (
            <div key={o.value}
                 className={'menu-item' + (mono ? ' is-mono' : '') + (o.value === value ? ' active' : '')}
                 onClick={() => { onChange(o.value); setOpen(false); }}>
              <span>{o.label}</span>
              {o.hint && <span style={{ color: 'var(--ink-5)', fontFamily: 'var(--font-mono)', fontSize: '11.5px' }}>{o.hint}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Profile selector ───────────────────────────────────────────────────
function ProfileSelect({ profile, profiles, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useClickOutside(ref, () => setOpen(false));
  return (
    <div className="dropdown" ref={ref}>
      <button className="btn-ctl" onClick={() => setOpen(!open)}>
        <span className="side-avatar" style={{ width: 22, height: 22, fontSize: 10, borderRadius: 6 }}>
          {profile.alias[0].toUpperCase()}
        </span>
        <span style={{ fontWeight: 600 }}>{profile.alias}</span>
        <span style={{ color: 'var(--ink-4)', fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>{profile.account}</span>
        <I.Chevron s={14} />
      </button>
      {open && (
        <div className="menu" style={{ minWidth: 280 }}>
          <div className="menu-label">AWS CLI Profiles · ~/.aws/credentials</div>
          {profiles.map(p => (
            <div key={p.id}
                 className={'menu-item' + (p.id === profile.id ? ' active' : '')}
                 onClick={() => { onChange(p); setOpen(false); }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="side-avatar" style={{ width: 22, height: 22, fontSize: 10, borderRadius: 6 }}>
                  {p.alias[0].toUpperCase()}
                </span>
                <span>{p.alias}</span>
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--ink-4)' }}>{p.account}</span>
            </div>
          ))}
          <div className="menu-divider" />
          <div className="menu-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><I.Plus s={14} /> Add profile…</span></div>
        </div>
      )}
    </div>
  );
}

// ── Top bar ─────────────────────────────────────────────────────────────
function TopBar({ profile, setProfile, period, setPeriod, costMode, refreshing, onRefresh, profiles, periods, dark, setDark }) {
  const lastSync = useMemo(() => {
    const mins = 2 + Math.floor(Math.random() * 4);
    return `Synced ${mins}m ago`;
  }, []);
  return (
    <div className="topbar">
      <div className="topbar-meta">
        <span className="live-dot" />
        <span className="live-text">Live</span>
        <span className="meta-sep" />
        <span className="meta-text">{lastSync}</span>
      </div>
      <div className="topbar-controls">
        <span className="cost-badge">
          <span className="dot" />
          {costMode}
          <span className="tip">{costMode} · excludes Credit/Refund/Upfront · UTC</span>
        </span>
        <Dropdown
          label="period:"
          value={period}
          mono
          options={periods.map(p => ({ value: p.id, label: p.label }))}
          onChange={setPeriod}
        />
        <ProfileSelect profile={profile} profiles={profiles} onChange={setProfile} />
        <button className="icon-btn" onClick={() => setDark(!dark)} title={dark ? 'Switch to light mode' : 'Switch to dark mode'}>
          {dark ? <I.Sun s={16} /> : <I.Moon s={16} />}
        </button>
        <button className={'icon-btn' + (refreshing ? ' spin' : '')} onClick={onRefresh} title="Refresh data">
          <I.Refresh s={16} />
        </button>
      </div>
    </div>
  );
}

// ── Service badge ──────────────────────────────────────────────────────
function ServiceBadge({ k }) {
  const map = {
    EC2: 'EC2', RDS: 'RDS', S3: 'S3', Lambda: 'λ', CloudFront: 'CF', ELB: 'LB',
    EBS: 'EBS', DynamoDB: 'DDB', ECS: 'ECS', CloudWatch: 'CW', Route53: 'R53',
    EKS: 'EKS', SQS: 'SQS', SNS: 'SNS', ElastiCache: 'EC', EB: 'EB', Other: '∙'
  };
  return (
    <span className="badge svc">
      <span className={'sq svc-' + k}>{map[k] || k.slice(0,2).toUpperCase()}</span>
      <span>{k}</span>
    </span>
  );
}

// ── Copy-to-clipboard button ───────────────────────────────────────────
function CopyId({ value }) {
  const [copied, setCopied] = useState(false);
  const onCopy = (e) => {
    e.stopPropagation();
    try { navigator.clipboard.writeText(value); } catch (e) {}
    setCopied(true);
    setTimeout(() => setCopied(false), 1100);
  };
  return (
    <span className="cell-id">
      <span className="txt" title={value}>{value}</span>
      <button className={'copy-btn' + (copied ? ' copied' : '')} onClick={onCopy} title="Copy resource ID">
        {copied ? <I.Check s={12} /> : <I.Copy s={12} />}
      </button>
    </span>
  );
}

// ── Delta pill ─────────────────────────────────────────────────────────
function Delta({ value, dec = 1, suffix = '%' }) {
  if (value === null || value === undefined) return <span className="delta flat">—</span>;
  const pos = value >= 0;
  const Ar = pos ? I.ArrowUp : I.ArrowDown;
  return (
    <span className={'delta ' + (pos ? 'neg' : 'pos')}>
      <Ar s={10} />
      {Math.abs(value).toFixed(dec)}{suffix}
    </span>
  );
}

// Like Delta but inverts color: down = good (for spend savings)
function DeltaSpend({ value, dec = 1 }) {
  if (value === null) return <span className="delta flat">—</span>;
  const pos = value >= 0;
  const Ar = pos ? I.ArrowUp : I.ArrowDown;
  return (
    <span className={'delta ' + (pos ? 'neg' : 'pos')}>
      <Ar s={10} />
      {Math.abs(value).toFixed(dec)}%
    </span>
  );
}

// ── Page Title ─────────────────────────────────────────────────────────
function PageHeader({ title, sub, actions }) {
  return (
    <div className="page-h">
      <div>
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {actions && <div className="page-h-actions">{actions}</div>}
    </div>
  );
}

Object.assign(window, {
  Sidebar, TopBar, Dropdown, ProfileSelect,
  ServiceBadge, CopyId, Delta, DeltaSpend, PageHeader
});
