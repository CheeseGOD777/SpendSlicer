// pages-a.jsx — Dashboard, Services, Resources

const D = window.DATA;

// ═══════════════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════════════
function Dashboard({ period, profile }) {
  const k = D.kpis;
  const topServices = D.services.slice(0, 8);
  const maxSvcCost = Math.max(...topServices.map(s => s.cost));
  const topResources = [...D.resources].sort((a, b) => b.cost - a.cost).slice(0, 10);
  const maxResCost = Math.max(...topResources.map(r => r.cost));

  return (
    <div className="page">
      <PageHeader
        title="Dashboard"
        sub={`Period spend · ${profile.alias} · ${profile.account} · period=${period}`}
        actions={
          <React.Fragment>
            <button className="btn btn-ghost"><I.Filter s={14} /> Filter</button>
            <button className="btn btn-ghost"><I.Export s={14} /> Export</button>
          </React.Fragment>
        }
      />

      {/* KPI cards */}
      <div className="kpi-row">
        <Kpi label="Period spend" icon={<I.Wallet s={14} />}
             value={fmt.usd(k.spend.value, 2)} delta={k.spend.delta}
             note="vs. previous period" spark={k.spend.spark} />
        <Kpi label="Previous period" icon={<I.Coins s={14} />}
             value={fmt.usd(k.previous.value, 2)} delta={k.previous.delta} muted
             note="vs. period -2" spark={k.previous.spark} />
        <Kpi label="Month forecast" icon={<I.Sparkle s={14} />}
             value={fmt.usd(k.forecast.value, 0)} delta={k.forecast.delta}
             note="confidence ±4.2%" spark={k.forecast.spark} forecasted />
        <Kpi label="Top service" icon={<I.Flame s={14} />}
             value={k.topSvc.value} sub={`${k.topSvc.share}% · ${fmt.usd(k.topSvc.cost, 0)}`}
             delta={k.topSvc.delta} note="MoM" />
      </div>

      {/* 6-Month trend chart */}
      <div style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-title">
            <div>
              <h2>6-Month Spend Trend</h2>
              <div className="sub" style={{ marginTop: 4 }}>Stacked by service · Dec 2024 — May 2025 · pre-credit</div>
            </div>
            <div className="chart-legend">
              {['EC2','RDS','S3','Lambda','CloudFront','Other'].map(k => (
                <span key={k}>
                  <span className="swatch" style={{ background: SERIES_COLORS[k] }} />
                  {k}
                </span>
              ))}
            </div>
          </div>
          <StackedBars data={D.trend6m} keys={['EC2','RDS','S3','Lambda','CloudFront','Other']} />
        </div>
      </div>

      {/* Split lower view */}
      <div className="grid-split" style={{ marginTop: 16 }}>
        {/* Service mix — Donut */}
        <div className="card">
          <div className="card-title">
            <div><h2>Service mix</h2><div className="sub" style={{ marginTop: 4 }}>Share of period spend · top 6</div></div>
            <a className="sub" style={{ color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 4 }}>
              All services <I.ArrowRight s={12} />
            </a>
          </div>
          <div style={{ padding: '8px 0 4px' }}>
            <Donut
              data={topServices.slice(0, 6).map(s => ({
                key: s.key, name: s.name.replace('Amazon ', '').replace('AWS ', ''),
                value: s.cost, color: SERIES_COLORS[s.key] || 'var(--ink-5)'
              }))}
              size={220}
              thickness={26}
              label="Period spend"
            />
          </div>
        </div>

        {/* Top Resources */}
        <div className="card">
          <div className="card-title">
            <div><h2>Top 10 resources</h2><div className="sub" style={{ marginTop: 4 }}>Most expensive individual assets</div></div>
            <a className="sub" style={{ color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 4 }}>
              All resources <I.ArrowRight s={12} />
            </a>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {topResources.map((r, i) => (
              <div key={r.id} style={{
                display: 'grid',
                gridTemplateColumns: '74px 1fr auto',
                gap: 12,
                alignItems: 'center',
                padding: '9px 0',
                borderBottom: i < topResources.length - 1 ? '1px solid var(--line)' : 'none'
              }}>
                <ServiceBadge k={r.svc} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: 'var(--ink-2)', fontWeight: 500,
                                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {r.name}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)',
                                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {r.id}
                  </div>
                </div>
                <div className="t-mono" style={{ fontWeight: 600, textAlign: 'right' }}>{fmt.usd(r.cost, 2)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Waste Radar */}
      <WasteRadar />
    </div>
  );
}

// ── KPI Card ───────────────────────────────────────────────────────────
function Kpi({ label, icon, value, sub, delta, note, spark, muted, forecasted }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{icon}<span>{label}</span></div>
      <div className="kpi-value" style={muted ? { color: 'var(--ink-3)' } : null}>
        {typeof value === 'string' && value.startsWith('$') ? (
          <React.Fragment><span className="cur">$</span>{value.slice(1)}</React.Fragment>
        ) : value}
      </div>
      {sub && <div style={{ fontSize: 11.5, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>{sub}</div>}
      <div className="kpi-foot">
        {delta !== undefined && <DeltaSpend value={delta} />}
        {note && <span className="delta-note">{note}</span>}
      </div>
      {spark && (
        <div className="spark">
          <Sparkline data={spark}
                     color={forecasted ? 'var(--info)' : (delta < 0 ? 'var(--pos)' : 'var(--neg)')} />
        </div>
      )}
    </div>
  );
}

// ── Waste Radar ────────────────────────────────────────────────────────
function WasteRadar() {
  const items = [
    { icon: <I.Flame s={16} />, color: 'warn', title: '9 idle resources', body: '$1,184.84 estimated monthly waste', hint: 'Largest: p3.8xlarge GPU idle 14d' },
    { icon: <I.Tag s={16} />, color: 'warn', title: '7 untagged resources', body: '$1,032.30 unallocated · violates tagging policy', hint: 'Missing Owner & CostCenter tags' },
    { icon: <I.Alert s={16} />, color: 'danger', title: 'ML Research budget breached', body: '$32,104 / $28,000 · 114.7% used', hint: 'Triggered May 12 · contact: data-platform@' },
  ];
  return (
    <div style={{ marginTop: 16 }}>
      <div className="card">
        <div className="card-title">
          <div><h2>Waste radar</h2><div className="sub" style={{ marginTop: 4 }}>Anomalies, idle assets, and budget breaches</div></div>
          <a className="sub" style={{ color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 4 }}>
            Open audit <I.ArrowRight s={12} />
          </a>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {items.map((it, i) => (
            <div key={i} style={{
              border: '1px solid ' + (it.color === 'danger' ? '#F4C8CE' : '#F3E1B8'),
              background: it.color === 'danger' ? 'var(--neg-soft)' : 'var(--warn-soft)',
              borderRadius: 12,
              padding: '12px 14px',
              display: 'flex',
              gap: 10,
              alignItems: 'flex-start',
            }}>
              <div style={{
                color: it.color === 'danger' ? 'var(--neg)' : 'var(--warn)',
                marginTop: 2
              }}>{it.icon}</div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 13.5,
                              color: it.color === 'danger' ? 'var(--neg)' : '#A3690B' }}>
                  {it.title}
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, marginTop: 2, color: 'var(--ink-2)' }}>
                  {it.body}
                </div>
                <div style={{ fontSize: 11.5, marginTop: 4, color: 'var(--ink-4)' }}>{it.hint}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════
// SERVICES
// ═══════════════════════════════════════════════════════════════════════
function Services({ setPage, setResourceFilter }) {
  const services = D.services;
  const total = services.reduce((s, x) => s + x.cost, 0);
  const top6 = [...services].slice(0, 6).map(s => ({
    name: s.key,
    this: s.mom[5],
    prior: s.mom[4],
    delta: ((s.mom[5] - s.mom[4]) / s.mom[4]) * 100,
    color: SERIES_COLORS[s.key] || 'var(--ink-5)',
  }));
  const maxShare = Math.max(...services.map(s => s.share));

  return (
    <div className="page">
      <PageHeader title="Services" sub={`47 active services · ${fmt.usd(total, 2)} this period`} />

      {/* Comparison chart */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-title">
          <div>
            <h2>Month over month</h2>
            <div className="sub" style={{ marginTop: 4 }}>Top 6 services · May 2025 vs. Apr 2025</div>
          </div>
          <div className="chart-legend">
            <span><span className="swatch" style={{ background: 'var(--surface-3)' }} />Prior period</span>
            <span><span className="swatch" style={{ background: 'var(--accent)' }} />This period</span>
          </div>
        </div>
        <GroupedBars data={top6} height={240} />
      </div>

      {/* All services table */}
      <div className="tbl-wrap">
        <div className="tbl-head-row">
          <div>
            <h2>All services</h2>
            <div className="sub">Click a service to drill into resources</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <div className="search" style={{ minWidth: 200 }}>
              <I.Search s={14} />
              <input placeholder="Filter services…" />
            </div>
            <button className="btn btn-ghost"><I.Filter s={14} /> Filters</button>
          </div>
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Service</th>
              <th>Share of total</th>
              <th style={{ textAlign: 'right' }}>Vs prior</th>
              <th style={{ textAlign: 'right' }}>
                Cost (USD)
                <I.Info s={11} style={{ display: 'inline', verticalAlign: -1, marginLeft: 4, color: 'var(--ink-5)' }} />
              </th>
              <th style={{ width: 40 }}></th>
            </tr>
          </thead>
          <tbody>
            {services.map(s => (
              <tr key={s.key} onClick={() => { setResourceFilter(s.key); setPage('resources'); }} style={{ cursor: 'default' }}>
                <td><ServiceBadge k={s.key} /></td>
                <td>
                  <div className="cell-bar">
                    <div className="cell-bar-track">
                      <div className="cell-bar-fill" style={{ width: (s.share / maxShare * 100) + '%',
                                                              background: SERIES_COLORS[s.key] || 'var(--ink-5)' }} />
                    </div>
                    <span className="cell-bar-val">{s.share.toFixed(1)}%</span>
                  </div>
                </td>
                <td style={{ textAlign: 'right' }}><DeltaSpend value={s.vsPrior} /></td>
                <td className="num" style={{ fontWeight: 600 }}>{fmt.usd(s.cost, 2)}</td>
                <td><I.ArrowRight s={14} style={{ color: 'var(--ink-5)' }} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════
// RESOURCES
// ═══════════════════════════════════════════════════════════════════════
// region/account hash for ARN synthesis
const REGION_BY_SVC = {
  EC2: 'us-east-1', RDS: 'us-west-2', S3: '', Lambda: 'us-east-1',
  CloudFront: '', ELB: 'us-east-1', EBS: 'us-east-1', DynamoDB: 'us-east-1',
  ECS: 'us-east-1', CloudWatch: 'us-east-1', Route53: '', EKS: 'eu-central-1',
  ElastiCache: 'us-east-1',
};
function resourceArn(r) {
  const svc = r.svc.toLowerCase();
  const reg = REGION_BY_SVC[r.svc] ?? 'us-east-1';
  if (r.svc === 'S3')      return `arn:aws:s3:::${r.id}`;
  if (r.svc === 'Route53') return `arn:aws:route53:::hostedzone/${r.id}`;
  if (r.svc === 'CloudFront') return `arn:aws:cloudfront::123456789012:distribution/${r.id}`;
  return `arn:aws:${svc}:${reg}:123456789012:${r.id}`;
}
function typeKind(t) {
  if (t.includes('Spot'))     return { label: 'Spot',      cls: 'spot' };
  if (t.includes('Reserved')) return { label: 'Reserved',  cls: 'reserved' };
  if (t.includes('On-Demand'))return { label: 'On-Demand', cls: '' };
  if (t.includes('Aurora') || t.includes('PostgreSQL') || t.includes('MySQL'))
                              return { label: 'Reserved',  cls: 'reserved' };
  if (t.includes('Glacier') || t.includes('Standard') || t.includes('Intelligent') || t.includes('TB') || t.includes('PB'))
                              return { label: 'Storage',   cls: 'storage' };
  if (t.includes('Fargate')) return { label: 'Fargate', cls: 'reserved' };
  if (t.includes('Logs') || t.includes('Hosted'))
                             return { label: 'Managed', cls: 'reserved' };
  return { label: 'On-Demand', cls: '' };
}
function ResourceIcon({ svc }) {
  const glyphs = {
    EC2:        <I.Box s={16} />,
    RDS:        <I.Database s={16} />,
    S3:         <I.Folder s={16} />,
    Lambda:     <I.Zap s={16} />,
    CloudFront: <I.Globe s={16} />,
    ELB:        <I.Activity s={16} />,
    EBS:        <I.Disk s={16} />,
    DynamoDB:   <I.Database s={16} />,
    ECS:        <I.Box s={16} />,
    CloudWatch: <I.Activity s={16} />,
    Route53:    <I.Globe s={16} />,
    EKS:        <I.Box s={16} />,
    ElastiCache:<I.Disk s={16} />,
  };
  return <div className={'r-icon r-' + svc}>{glyphs[svc] || <I.Box s={16} />}</div>;
}
function isStorageHours(svc) {
  return svc === 'S3' || svc === 'EBS';
}

function Resources({ resourceFilter, setResourceFilter }) {
  const resources = D.resources;
  const services = [...new Set(resources.map(r => r.svc))];
  const filter = resourceFilter || 'All';
  const filtered = filter === 'All' ? resources : resources.filter(r => r.svc === filter);
  const sorted = [...filtered].sort((a, b) => b.cost - a.cost);

  const recon = D.reconciliation;
  const drift = Math.abs(recon.drift);

  return (
    <div className="page">
      {/* Reconciliation Overview */}
      <div className="recon-card" style={{ marginBottom: 4 }}>
        <div className="recon-head">
          <h2>Reconciliation Overview</h2>
          <p>Live alignment of attributed costs vs. billing engine totals.</p>
        </div>
        <div className="recon-stats">
          <div className="recon-stat">
            <span className="recon-stat-label">Total Attributed</span>
            <span className="recon-stat-val">{fmt.usd(recon.attributed, 0)}</span>
          </div>
          <div className="recon-stat">
            <span className="recon-stat-label">CE Total</span>
            <span className="recon-stat-val">{fmt.usd(recon.ceTotal, 0)}</span>
          </div>
          <div className="recon-stat">
            <span className="recon-stat-label">Drift</span>
            <span className="recon-stat-val drift">{fmt.usd(drift, 0)}</span>
          </div>
        </div>
      </div>

      {/* Services filter */}
      <div className="svc-filter-row">
        <span className="svc-filter-label">Services:</span>
        <div className="pill-tabs" style={{ flex: 1 }}>
          <div className={'pill-tab' + (filter === 'All' ? ' dark' : '')}
               onClick={() => setResourceFilter(null)}>
            All
          </div>
          {services.map(s => (
            <div key={s} className={'pill-tab' + (filter === s ? ' dark' : '')}
                 onClick={() => setResourceFilter(s)}>
              {s}
            </div>
          ))}
        </div>
      </div>

      {/* Resource table */}
      <div className="tbl-wrap">
        <div style={{ overflow: 'auto', maxHeight: '70vh' }}>
          <table className="tbl tbl-res" style={{ minWidth: 1100, width: '100%' }}>
            <thead>
              <tr>
                <th style={{ width: 56 }}>Svc</th>
                <th style={{ minWidth: 240 }}>Resource Name / Tag</th>
                <th style={{ minWidth: 240 }}>Resource ID</th>
                <th style={{ width: 130 }}>Type</th>
                <th style={{ width: 70 }}>State</th>
                <th style={{ width: 90, textAlign: 'right' }}>Hours</th>
                <th style={{ width: 110, textAlign: 'right' }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => {
                const tagEntries = Object.entries(r.tags || {});
                const tag = tagEntries[0];
                const tk = typeKind(r.type);
                const storage = isStorageHours(r.svc);
                return (
                  <tr key={r.id + i}>
                    <td><ResourceIcon svc={r.svc} /></td>
                    <td>
                      <div className="r-name">
                        <span className="nm">{r.name}</span>
                        {tag ? (
                          <span className="tg">{tag[0]}: {tag[1]}</span>
                        ) : (
                          <span className="tg" style={{ color: 'var(--neg)' }}>untagged</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className="arn-id" title={resourceArn(r)}>
                        {truncateArn(resourceArn(r))}
                      </span>
                    </td>
                    <td>
                      <span className={'type-pill ' + tk.cls}>{tk.label}</span>
                    </td>
                    <td>
                      <span className={'state-dot ' + r.state} />
                    </td>
                    <td className="hours-num">
                      {storage ? '–' : r.hours.toFixed(1)}
                    </td>
                    <td className="cost-num">{fmt.usd(r.cost, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function truncateArn(s) {
  if (s.length <= 28) return s;
  return s.slice(0, 26) + '…';
}

Object.assign(window, { Dashboard, Services, Resources });
