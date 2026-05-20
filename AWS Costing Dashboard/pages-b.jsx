// pages-b.jsx — Trends, Audit, Export

const Db = window.DATA;

// ═══════════════════════════════════════════════════════════════════════
// TRENDS
// ═══════════════════════════════════════════════════════════════════════
function Trends() {
  const [granularity, setGranularity] = React.useState('daily');

  // For daily — last 90 days. Generate labels: May 16 - 90 = ~Feb 16
  const dayLabels = (() => {
    const end = new Date(2025, 4, 16); // May 16
    const labels = [];
    for (let i = 89; i >= 0; i--) {
      const d = new Date(end);
      d.setDate(d.getDate() - i);
      labels.push(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
    }
    return labels;
  })();

  const monthly = Db.trend12m;
  const maxMonth = Math.max(...monthly.map(m => m.cost));
  const totalAnnual = monthly.reduce((s, m) => s + m.cost, 0);

  return (
    <div className="page">
      <PageHeader
        title="Trends"
        sub={`Time-series spend analysis · ${granularity} granularity`}
        actions={
          <div className="seg">
            <button className={'seg-btn' + (granularity === 'daily' ? ' active' : '')} onClick={() => setGranularity('daily')}>daily</button>
            <button className={'seg-btn' + (granularity === 'weekly' ? ' active' : '')} onClick={() => setGranularity('weekly')}>weekly</button>
            <button className={'seg-btn' + (granularity === 'monthly' ? ' active' : '')} onClick={() => setGranularity('monthly')}>monthly</button>
          </div>
        }
      />

      {/* KPI strip */}
      <div className="kpi-row" style={{ marginBottom: 16 }}>
        <Kpi label="Period total" icon={<I.Wallet s={14} />}
             value={fmt.usd(totalAnnual, 0)} delta={null} note="trailing 12 months" />
        <Kpi label="Highest month" icon={<I.Flame s={14} />}
             value={fmt.usd(maxMonth, 0)} sub="2025-04 · April" />
        <Kpi label="Avg monthly" icon={<I.Coins s={14} />}
             value={fmt.usd(totalAnnual / 12, 0)} delta={null} note="rolling average" />
        <Kpi label="Daily spike peak" icon={<I.Alert s={14} />}
             value={fmt.usd(Math.max(...Db.dailyTrend), 0)} sub="Apr 27 · ml-training cluster"
             delta={null} />
      </div>

      {/* Main chart */}
      <div className="card">
        <div className="card-title">
          <div>
            <h2>{granularity[0].toUpperCase() + granularity.slice(1)} spend</h2>
            <div className="sub" style={{ marginTop: 4 }}>
              {granularity === 'daily' ? '90 days · Feb 16 — May 16, 2025' : '12 months · trailing'}
            </div>
          </div>
          <div className="chart-legend">
            <span><span className="swatch" style={{ background: 'var(--accent)' }} />Total spend</span>
          </div>
        </div>
        <AreaChart data={Db.dailyTrend} dayLabels={dayLabels} />
      </div>

      {/* Period detail table */}
      <div className="tbl-wrap" style={{ marginTop: 16 }}>
        <div className="tbl-head-row">
          <div>
            <h2>Period breakdown</h2>
            <div className="sub">Monthly · row background scales to highest cost month</div>
          </div>
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: '24%' }}>Period</th>
              <th style={{ textAlign: 'right' }}>Cost (USD)</th>
              <th style={{ textAlign: 'right' }}>Vs prior</th>
              <th>Proportional</th>
            </tr>
          </thead>
          <tbody>
            {[...monthly].reverse().map((m) => {
              const w = (m.cost / maxMonth * 100).toFixed(1) + '%';
              return (
                <tr key={m.period} style={{ position: 'relative' }}>
                  <td style={{ position: 'relative' }}>
                    <div style={{
                      position: 'absolute', inset: 0,
                      background: `linear-gradient(to right, var(--accent-soft) ${w}, transparent ${w})`,
                      opacity: 0.5, pointerEvents: 'none', zIndex: 0
                    }} />
                    <span style={{ position: 'relative', zIndex: 1, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                      {m.period}
                    </span>
                    <span style={{ position: 'relative', zIndex: 1, marginLeft: 8, color: 'var(--ink-4)',
                                   fontSize: 11.5 }}>
                      {monthName(m.period)}
                    </span>
                  </td>
                  <td className="num" style={{ fontWeight: 600 }}>{fmt.usd(m.cost, 2)}</td>
                  <td style={{ textAlign: 'right' }}><DeltaSpend value={m.vsPrior} /></td>
                  <td>
                    <div className="cell-bar">
                      <div className="cell-bar-track" style={{ maxWidth: 280 }}>
                        <div className="cell-bar-fill" style={{ width: w }} />
                      </div>
                      <span className="cell-bar-val">{(m.cost / maxMonth * 100).toFixed(0)}%</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function monthName(period) {
  const [y, m] = period.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

// ═══════════════════════════════════════════════════════════════════════
// AUDIT
// ═══════════════════════════════════════════════════════════════════════
function Audit() {
  const [tab, setTab] = React.useState('idle');
  const [selected, setSelected] = React.useState(new Set());
  const items = tab === 'idle' ? Db.idle : Db.untagged;

  const toggle = (id) => {
    const n = new Set(selected);
    if (n.has(id)) n.delete(id); else n.add(id);
    setSelected(n);
  };
  const toggleAll = () => {
    if (selected.size === items.length) setSelected(new Set());
    else setSelected(new Set(items.map(x => x.id)));
  };

  // Reset selection when tab changes
  React.useEffect(() => setSelected(new Set()), [tab]);

  const totalWaste = Db.idle.reduce((s, x) => s + x.waste, 0);
  const untaggedSpend = Db.untagged.reduce((s, x) => s + x.cost, 0);

  return (
    <div className="page">
      <PageHeader
        title="Audit"
        sub="Governance & hygiene · cleanup queue for your infrastructure"
      />

      {/* Top: budgets + summary cards */}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="budget-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600 }}>Budgets</h2>
            <span className="sub" style={{ fontSize: 12, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>4 of 12 tracked</span>
          </div>
          {Db.budgets.map(b => {
            const pct = (b.spent / b.limit) * 100;
            const cls = pct >= 100 ? 'danger' : pct >= 80 ? 'warn' : '';
            return (
              <div key={b.name} className="budget-row">
                <div className="budget-head">
                  <span>
                    <span className="budget-name">{b.name}</span>
                    <span style={{ marginLeft: 8, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ink-4)' }}>{b.scope}</span>
                  </span>
                  <span className="budget-amt"><b>{fmt.usd(b.spent, 0)}</b> / {fmt.usd(b.limit, 0)}</span>
                </div>
                <div className="budget-track">
                  <div className={'budget-fill ' + cls} style={{ width: Math.min(100, pct) + '%' }} />
                </div>
                <div className="budget-foot">
                  <span>{pct.toFixed(1)}% used</span>
                  <span>{pct >= 100 ? `Over by ${fmt.usd(b.spent - b.limit, 0)}` : `${fmt.usd(b.limit - b.spent, 0)} remaining`}</span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="col">
          <div className="card card-tight" style={{ background: 'var(--warn-soft)', borderColor: '#F3E1B8' }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: 'var(--warn)', color: '#fff',
                            display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                <I.Flame s={18} />
              </div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: 0.06, textTransform: 'uppercase', color: '#8A5C0E' }}>Idle resources</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 600, color: 'var(--ink)', marginTop: 2 }}>
                  {fmt.usd(totalWaste, 2)} <span style={{ fontSize: 12, color: 'var(--ink-4)', fontWeight: 500 }}>est. monthly waste</span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--ink-3)', marginTop: 6 }}>
                  {Db.idle.length} findings across {new Set(Db.idle.map(x => x.svc)).size} services
                </div>
              </div>
            </div>
          </div>
          <div className="card card-tight">
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: 'var(--ink)', color: '#fff',
                            display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                <I.Tag s={18} />
              </div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: 0.06, textTransform: 'uppercase', color: 'var(--ink-4)' }}>Untagged spend</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 600, color: 'var(--ink)', marginTop: 2 }}>
                  {fmt.usd(untaggedSpend, 2)} <span style={{ fontSize: 12, color: 'var(--ink-4)', fontWeight: 500 }}>unallocated</span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--ink-3)', marginTop: 6 }}>
                  {Db.untagged.length} resources missing mandatory tags
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabbed findings */}
      <div className="tbl-wrap">
        <div className="tbl-head-row">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div className={'pill-tab' + (tab === 'idle' ? ' active' : '')} onClick={() => setTab('idle')}>
              Idle resources <span className="count">{Db.idle.length}</span>
            </div>
            <div className={'pill-tab' + (tab === 'untagged' ? ' active' : '')} onClick={() => setTab('untagged')}>
              Untagged <span className="count">{Db.untagged.length}</span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {selected.size > 0 && (
              <span style={{ fontSize: 12, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>
                {selected.size} selected
              </span>
            )}
            <button className="btn btn-ghost" disabled={selected.size === 0}
                    style={{ opacity: selected.size === 0 ? 0.5 : 1 }}>
              <I.Export s={14} /> Export list
            </button>
            <button className="btn btn-primary" disabled={selected.size === 0}
                    style={{ opacity: selected.size === 0 ? 0.5 : 1 }}>
              <I.Wrench s={14} /> Remediate
            </button>
          </div>
        </div>

        {tab === 'idle' ? (
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 36 }}>
                  <div className={'check' + (selected.size === items.length ? ' on' : '')} onClick={toggleAll}>
                    {selected.size === items.length && <I.Check s={11} />}
                  </div>
                </th>
                <th>Service</th>
                <th>Resource</th>
                <th>Reason</th>
                <th>Env</th>
                <th style={{ textAlign: 'right' }}>Est. monthly waste</th>
              </tr>
            </thead>
            <tbody>
              {Db.idle.map(r => {
                const on = selected.has(r.id);
                return (
                  <tr key={r.id} onClick={() => toggle(r.id)} style={{ background: on ? 'var(--accent-soft)' : null }}>
                    <td>
                      <div className={'check' + (on ? ' on' : '')}>
                        {on && <I.Check s={11} />}
                      </div>
                    </td>
                    <td><ServiceBadge k={r.svc} /></td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>{r.name}</span>
                        <CopyId value={r.id} />
                      </div>
                    </td>
                    <td style={{ fontSize: 12.5, color: 'var(--ink-3)' }}>{r.reason}</td>
                    <td><span className="badge" style={{ textTransform: 'lowercase' }}>{r.env}</span></td>
                    <td className="num" style={{ fontWeight: 600, color: 'var(--warn)' }}>{fmt.usd(r.waste, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 36 }}>
                  <div className={'check' + (selected.size === items.length ? ' on' : '')} onClick={toggleAll}>
                    {selected.size === items.length && <I.Check s={11} />}
                  </div>
                </th>
                <th>Service</th>
                <th>Resource</th>
                <th>Resource ID</th>
                <th>Missing tags</th>
                <th style={{ textAlign: 'right' }}>Cost (USD)</th>
              </tr>
            </thead>
            <tbody>
              {Db.untagged.map(r => {
                const on = selected.has(r.id);
                return (
                  <tr key={r.id} onClick={() => toggle(r.id)} style={{ background: on ? 'var(--accent-soft)' : null }}>
                    <td>
                      <div className={'check' + (on ? ' on' : '')}>
                        {on && <I.Check s={11} />}
                      </div>
                    </td>
                    <td><ServiceBadge k={r.svc} /></td>
                    <td style={{ fontWeight: 600, fontSize: 13 }}>{r.name}</td>
                    <td><CopyId value={r.id} /></td>
                    <td>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {r.missing.map(m => (
                          <span key={m} className="badge" style={{ color: 'var(--neg)', background: 'var(--neg-soft)', borderColor: 'transparent' }}>
                            {m}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="num" style={{ fontWeight: 600 }}>{fmt.usd(r.cost, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════════════
function ExportPage({ profile, period }) {
  const [format, setFormat] = React.useState('csv');
  const [outDir, setOutDir] = React.useState('~/reports/cloudledger');
  const [includes, setIncludes] = React.useState(new Set(['summary','services','resources']));
  const [running, setRunning] = React.useState(false);
  const [log, setLog] = React.useState([
    { ts: '14:02:18', kind: 'dim', text: 'cloudledger v2.4.1 · ready' },
    { ts: '14:02:18', kind: 'dim', text: `profile=${profile.alias} period=${period} format=csv` },
  ]);

  const toggle = (k) => {
    const n = new Set(includes);
    if (n.has(k)) n.delete(k); else n.add(k);
    setIncludes(n);
  };

  const formats = [
    { id: 'json', label: 'JSON', icon: '{ }', desc: 'Structured · machine-readable · full fidelity' },
    { id: 'csv',  label: 'CSV',  icon: ',,', desc: 'Spreadsheet-ready · one row per resource' },
    { id: 'pdf',  label: 'PDF',  icon: 'PDF', desc: 'Executive summary · charts · printable' },
  ];

  const runExport = () => {
    if (running) return;
    setRunning(true);
    const now = new Date();
    const ts = () => {
      const d = new Date();
      return [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, '0')).join(':');
    };
    const steps = [
      { delay: 200, kind: 'info', text: `▸ Loading profile ${profile.alias} (${profile.account})` },
      { delay: 400, kind: 'dim',  text: `  fetching Cost Explorer data · period=${period}` },
      { delay: 600, kind: 'ok',   text: `✓ Cost Explorer · 184,392.47 USD · ${Db.resources.length + 47} line items` },
      { delay: 400, kind: 'info', text: `▸ Reconciling resource attribution` },
      { delay: 500, kind: 'warn', text: `⚠ drift detected · $2,207.92 (1.20%) · within tolerance` },
      { delay: 300, kind: 'info', text: `▸ Building ${format.toUpperCase()} report` },
      { delay: 500, kind: 'dim',  text: `  sections: ${[...includes].join(', ')}` },
      { delay: 400, kind: 'ok',   text: `✓ Wrote ${outDir}/cloudledger_${profile.alias}_2025-05.${format}` },
      { delay: 100, kind: 'ok',   text: `✓ 1 file · 2.4 MB · done in 2.51s` },
    ];
    let acc = 0;
    steps.forEach((s) => {
      acc += s.delay;
      setTimeout(() => {
        setLog(prev => [...prev, { ts: ts(), kind: s.kind, text: s.text }]);
      }, acc);
    });
    setTimeout(() => setRunning(false), acc + 200);
  };

  return (
    <div className="page">
      <PageHeader
        title="Export"
        sub="Generate offline reports for FinOps reviews and audits"
      />

      <div className="grid-2" style={{ alignItems: 'start' }}>
        <div className="col">
          <div className="card">
            <div className="card-title"><h2>Format</h2></div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {formats.map(f => (
                <div key={f.id} className={'fmt-tile' + (format === f.id ? ' selected' : '')}
                     onClick={() => setFormat(f.id)}>
                  <div className="fmt-icon">{f.icon}</div>
                  <div>
                    <h3>{f.label}</h3>
                    <p>{f.desc}</p>
                  </div>
                  <div className="fmt-check"><I.Check s={11} /></div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-title"><h2>Configuration</h2></div>
            <div className="form-row">
              <label>Output directory</label>
              <input type="text" value={outDir} onChange={e => setOutDir(e.target.value)} />
            </div>
            <div className="form-row" style={{ marginBottom: 0 }}>
              <label>Include sections</label>
              {[
                { id: 'summary',   label: 'Executive summary · KPIs and totals' },
                { id: 'services',  label: 'Per-service breakdown' },
                { id: 'resources', label: 'Resource-level itemization' },
                { id: 'audit',     label: 'Audit findings · idle, untagged, budget' },
                { id: 'trends',    label: 'Trends · 12-month history' },
              ].map(opt => {
                const on = includes.has(opt.id);
                return (
                  <div key={opt.id} className="check-row" onClick={() => toggle(opt.id)}>
                    <div className={'check' + (on ? ' on' : '')}>{on && <I.Check s={11} />}</div>
                    <span>{opt.label}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <button className="btn btn-primary btn-lg" onClick={runExport}
                  style={{ alignSelf: 'flex-start' }}>
            {running ? (
              <React.Fragment>
                <span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.4)',
                               borderTopColor: '#fff', borderRadius: '50%',
                               animation: 'spin .9s linear infinite', display: 'inline-block' }} />
                Generating…
              </React.Fragment>
            ) : (
              <React.Fragment><I.Sparkle s={14} /> Generate report</React.Fragment>
            )}
          </button>
        </div>

        <div className="col">
          <div className="card">
            <div className="card-title">
              <h2>Export summary</h2>
              <span className="sub">based on current context</span>
            </div>
            <table className="tbl" style={{ marginLeft: -22, marginRight: -22, width: 'calc(100% + 44px)' }}>
              <tbody>
                <tr><td style={{ color: 'var(--ink-4)', fontSize: 12 }}>Profile</td><td className="t-mono" style={{ textAlign: 'right' }}>{profile.alias} <span style={{ color: 'var(--ink-4)' }}>· {profile.account}</span></td></tr>
                <tr><td style={{ color: 'var(--ink-4)', fontSize: 12 }}>Period</td><td className="t-mono" style={{ textAlign: 'right' }}>{period}</td></tr>
                <tr><td style={{ color: 'var(--ink-4)', fontSize: 12 }}>Total spend</td><td className="t-mono" style={{ textAlign: 'right', fontWeight: 600 }}>{fmt.usd(Db.reconciliation.ceTotal, 2)}</td></tr>
                <tr><td style={{ color: 'var(--ink-4)', fontSize: 12 }}>Services</td><td className="t-mono" style={{ textAlign: 'right' }}>{Db.services.length}</td></tr>
                <tr><td style={{ color: 'var(--ink-4)', fontSize: 12 }}>Resources</td><td className="t-mono" style={{ textAlign: 'right' }}>{Db.resources.length}</td></tr>
                <tr><td style={{ color: 'var(--ink-4)', fontSize: 12 }}>Estimated file size</td><td className="t-mono" style={{ textAlign: 'right' }}>~2.4 MB</td></tr>
              </tbody>
            </table>
          </div>

          <div className="card" style={{ background: 'transparent', boxShadow: 'none', border: 'none', padding: 0 }}>
            <div className="card-title" style={{ marginBottom: 8 }}>
              <h2 style={{ color: 'var(--ink-2)' }}>Console</h2>
              <span className="sub">stdout · cleared on refresh</span>
            </div>
            <div className="terminal">
              {log.map((l, i) => (
                <div key={i} className="ln">
                  <span className="ts">{l.ts}</span>
                  <span className={l.kind}>{l.text}</span>
                </div>
              ))}
              {running && (
                <div className="ln">
                  <span className="ts">{new Date().toTimeString().slice(0,8)}</span>
                  <span className="pfx">▌</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Trends, Audit, ExportPage });
