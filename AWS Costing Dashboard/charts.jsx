// charts.jsx — custom SVG charts (no library)
// All charts use currentColor + CSS variables for series colors.

const fmt = {
  usd: (n, dec = 0) => '$' + n.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }),
  usdK: (n) => {
    if (n >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
    return '$' + n.toFixed(0);
  },
  num: (n) => n.toLocaleString('en-US'),
  pct: (n, dec = 1) => (n >= 0 ? '+' : '') + n.toFixed(dec) + '%',
};

const SERIES_COLORS = {
  EC2:        'var(--s1)',
  RDS:        'var(--s2)',
  S3:         'var(--s3)',
  Lambda:     'var(--s4)',
  CloudFront: 'var(--s5)',
  Other:      'var(--s7)',
};

// ── Sparkline ───────────────────────────────────────────────────────────
function Sparkline({ data, color = 'var(--accent)', width = 86, height = 28, fill = true }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const r = Math.max(1, max - min);
  const n = data.length;
  const sx = (i) => (i / (n - 1)) * (width - 2) + 1;
  const sy = (v) => height - 2 - ((v - min) / r) * (height - 4);
  const pts = data.map((v, i) => `${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join(' ');
  const area = `0,${height} ${pts} ${width},${height}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ overflow: 'visible' }}>
      {fill && <polyline points={area} fill={color} opacity="0.10" stroke="none" />}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={sx(n - 1)} cy={sy(data[n - 1])} r="2.2" fill={color} />
    </svg>
  );
}

// ── Stacked Bar Chart (6m trend) ────────────────────────────────────────
function StackedBars({ data, keys, height = 280, onHover }) {
  const W = 760, H = height;
  const PAD_L = 56, PAD_R = 16, PAD_T = 16, PAD_B = 36;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  const totals = data.map(d => keys.reduce((s, k) => s + d[k], 0));
  const max = Math.max(...totals) * 1.15;
  const nice = Math.ceil(max / 50000) * 50000;
  const ticks = 4;
  const tickVals = Array.from({ length: ticks + 1 }, (_, i) => (nice / ticks) * i);

  const barW = Math.min(46, (plotW / data.length) * 0.55);
  const xStep = plotW / data.length;
  const [hover, setHover] = React.useState(null);

  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', overflow: 'visible' }}
           onMouseLeave={() => setHover(null)}>
        <defs>
          {keys.map(k => (
            <linearGradient key={k} id={`barg-${k}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%"   stopColor={SERIES_COLORS[k]} stopOpacity="1" />
              <stop offset="100%" stopColor={SERIES_COLORS[k]} stopOpacity="0.72" />
            </linearGradient>
          ))}
        </defs>
        {/* gridlines */}
        {tickVals.map((t, i) => {
          const y = PAD_T + plotH - (t / nice) * plotH;
          return (
            <g key={i}>
              <line x1={PAD_L} x2={W - PAD_R} y1={y} y2={y} stroke="var(--line)" strokeWidth="1" strokeDasharray={i === 0 ? null : "3 4"} />
              <text x={PAD_L - 10} y={y + 3} fontFamily="var(--font-mono)" fontSize="10.5" fill="var(--ink-4)" textAnchor="end">
                {fmt.usdK(t)}
              </text>
            </g>
          );
        })}

        {/* bars */}
        {data.map((d, i) => {
          const cx = PAD_L + xStep * (i + 0.5);
          let yCursor = PAD_T + plotH;
          const segs = keys.map((k, ki) => {
            const v = d[k];
            const h = (v / nice) * plotH;
            yCursor -= h;
            return { k, v, y: yCursor, h, ki };
          });
          const isHovered = hover === i;
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={cx - xStep / 2} y={PAD_T} width={xStep} height={plotH} fill="transparent" />
              {segs.map((s, si) => (
                <rect key={s.k} x={cx - barW / 2} y={s.y} width={barW} height={Math.max(0, s.h - 2)}
                      rx={si === 0 ? 4 : 0} ry={si === 0 ? 4 : 0}
                      fill={`url(#barg-${s.k})`}
                      opacity={isHovered || hover === null ? 1 : 0.45}
                      style={{ transition: 'opacity .15s' }} />
              ))}
              <text x={cx} y={H - 14} textAnchor="middle"
                    fontFamily="var(--font-mono)" fontSize="11"
                    fill={isHovered ? 'var(--ink)' : 'var(--ink-4)'}
                    fontWeight={isHovered ? 600 : 500}>
                {d.month}
              </text>
              {isHovered && (
                <line x1={cx} x2={cx} y1={PAD_T} y2={PAD_T + plotH} stroke="var(--ink)" strokeWidth="1" strokeDasharray="2 3" opacity="0.4" />
              )}
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hover !== null && (() => {
        const d = data[hover];
        const total = keys.reduce((s, k) => s + d[k], 0);
        const xStep = (W - PAD_L - PAD_R) / data.length;
        const cx = ((PAD_L + xStep * (hover + 0.5)) / W) * 100;
        const place = hover > data.length - 2 ? 'right' : 'left';
        return (
          <div className="chart-tip" style={{
            left: place === 'left' ? `calc(${cx}% + 18px)` : 'auto',
            right: place === 'right' ? `calc(${100 - cx}% + 18px)` : 'auto',
            top: 14
          }}>
            <div className="chart-tip-title">{d.month} 2025</div>
            {keys.map(k => (
              <div key={k} className="chart-tip-row">
                <span className="label"><span className="swatch" style={{ background: SERIES_COLORS[k], width: 8, height: 8, borderRadius: 2, display: 'inline-block' }} />{k}</span>
                <span className="val">{fmt.usd(d[k])}</span>
              </div>
            ))}
            <div className="chart-tip-row chart-tip-total">
              <span className="label" style={{ fontWeight: 600, color: 'var(--ink-2)' }}>Total</span>
              <span className="val">{fmt.usd(total)}</span>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ── Comparison Grouped Bars (Services page) ─────────────────────────────
function GroupedBars({ data, height = 260 }) {
  // data: [{name, this, prior, color}]
  const W = 760, H = height;
  const PAD_L = 56, PAD_R = 16, PAD_T = 16, PAD_B = 44;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const max = Math.max(...data.flatMap(d => [d.this, d.prior])) * 1.15;
  const nice = Math.ceil(max / 10000) * 10000;
  const tickVals = [0, nice * 0.25, nice * 0.5, nice * 0.75, nice];
  const xStep = plotW / data.length;
  const barW = Math.min(18, xStep * 0.32);
  const [hover, setHover] = React.useState(null);

  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', overflow: 'visible' }}
           onMouseLeave={() => setHover(null)}>
        <defs>
          {data.map((d, i) => (
            <linearGradient key={`gb-${i}`} id={`gb-this-${i}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%"   stopColor={d.color || 'var(--accent)'} stopOpacity="1" />
              <stop offset="100%" stopColor={d.color || 'var(--accent)'} stopOpacity="0.72" />
            </linearGradient>
          ))}
          <linearGradient id="gb-prior" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%"   stopColor="var(--ink-5)" stopOpacity="0.55" />
            <stop offset="100%" stopColor="var(--ink-5)" stopOpacity="0.25" />
          </linearGradient>
        </defs>
        {tickVals.map((t, i) => {
          const y = PAD_T + plotH - (t / nice) * plotH;
          return (
            <g key={i}>
              <line x1={PAD_L} x2={W - PAD_R} y1={y} y2={y} stroke="var(--line)" strokeDasharray={i === 0 ? null : "3 4"} />
              <text x={PAD_L - 10} y={y + 3} fontFamily="var(--font-mono)" fontSize="10.5" fill="var(--ink-4)" textAnchor="end">
                {fmt.usdK(t)}
              </text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const cx = PAD_L + xStep * (i + 0.5);
          const hThis = (d.this / nice) * plotH;
          const hPrior = (d.prior / nice) * plotH;
          const isH = hover === i;
          return (
            <g key={d.name} onMouseEnter={() => setHover(i)}>
              <rect x={cx - xStep / 2} y={PAD_T} width={xStep} height={plotH} fill="transparent" />
              <rect x={cx - barW - 2} y={PAD_T + plotH - hPrior} width={barW} height={hPrior}
                    rx="3" fill="url(#gb-prior)" opacity={isH || hover === null ? 1 : 0.55} />
              <rect x={cx + 2} y={PAD_T + plotH - hThis} width={barW} height={hThis}
                    rx="3" fill={`url(#gb-this-${i})`} opacity={isH || hover === null ? 1 : 0.55} />
              <text x={cx} y={H - 22} textAnchor="middle"
                    fontFamily="var(--font-sans)" fontSize="11.5"
                    fill={isH ? 'var(--ink)' : 'var(--ink-3)'}
                    fontWeight={isH ? 600 : 500}>{d.name}</text>
              <text x={cx} y={H - 8} textAnchor="middle"
                    fontFamily="var(--font-mono)" fontSize="10"
                    fill={d.delta >= 0 ? 'var(--neg)' : 'var(--pos)'}>
                {fmt.pct(d.delta)}
              </text>
            </g>
          );
        })}
      </svg>
      {hover !== null && (() => {
        const d = data[hover];
        const cx = ((PAD_L + xStep * (hover + 0.5)) / W) * 100;
        const place = hover > data.length - 2 ? 'right' : 'left';
        return (
          <div className="chart-tip" style={{
            left: place === 'left' ? `calc(${cx}% + 18px)` : 'auto',
            right: place === 'right' ? `calc(${100 - cx}% + 18px)` : 'auto',
            top: 14
          }}>
            <div className="chart-tip-title">{d.name}</div>
            <div className="chart-tip-row">
              <span className="label"><span style={{ width: 8, height: 8, borderRadius: 2, background: d.color, display: 'inline-block' }} />This period</span>
              <span className="val">{fmt.usd(d.this)}</span>
            </div>
            <div className="chart-tip-row">
              <span className="label"><span style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--surface-3)', display: 'inline-block' }} />Prior period</span>
              <span className="val">{fmt.usd(d.prior)}</span>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ── Area Chart (Trends) ─────────────────────────────────────────────────
function AreaChart({ data, height = 320, dayLabels }) {
  const W = 1100, H = height;
  const PAD_L = 60, PAD_R = 20, PAD_T = 20, PAD_B = 36;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const min = 0;
  const max = Math.max(...data) * 1.15;
  const nice = Math.ceil(max / 1000) * 1000;
  const ticks = 5;
  const tickVals = Array.from({ length: ticks + 1 }, (_, i) => (nice / ticks) * i);

  const sx = (i) => PAD_L + (i / (data.length - 1)) * plotW;
  const sy = (v) => PAD_T + plotH - ((v - min) / nice) * plotH;
  const path = data.map((v, i) => `${i === 0 ? 'M' : 'L'} ${sx(i).toFixed(1)} ${sy(v).toFixed(1)}`).join(' ');
  const areaPath = `${path} L ${sx(data.length - 1)} ${PAD_T + plotH} L ${sx(0)} ${PAD_T + plotH} Z`;

  const [hoverI, setHoverI] = React.useState(null);
  const wrapRef = React.useRef(null);

  const onMove = (e) => {
    const r = wrapRef.current.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W;
    const idx = Math.round(((x - PAD_L) / plotW) * (data.length - 1));
    setHoverI(Math.max(0, Math.min(data.length - 1, idx)));
  };

  // X-axis: show every ~ data.length/6 labels
  const labelEvery = Math.max(1, Math.floor(data.length / 6));

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}
         onMouseMove={onMove} onMouseLeave={() => setHoverI(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
        <defs>
          <linearGradient id="areaGrad" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%"   stopColor="var(--grad-a)" stopOpacity="0.38" />
            <stop offset="55%"  stopColor="var(--grad-b)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="var(--grad-c)" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="areaStroke" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%"   stopColor="var(--grad-a)" />
            <stop offset="50%"  stopColor="var(--grad-b)" />
            <stop offset="100%" stopColor="var(--grad-c)" />
          </linearGradient>
        </defs>
        {tickVals.map((t, i) => {
          const y = sy(t);
          return (
            <g key={i}>
              <line x1={PAD_L} x2={W - PAD_R} y1={y} y2={y}
                    stroke="var(--line)" strokeDasharray={i === 0 ? null : "3 4"} />
              <text x={PAD_L - 10} y={y + 3} fontFamily="var(--font-mono)" fontSize="11"
                    fill="var(--ink-4)" textAnchor="end">{fmt.usdK(t)}</text>
            </g>
          );
        })}
        <path d={areaPath} fill="url(#areaGrad)" />
        <path d={path} stroke="url(#areaStroke)" strokeWidth="2.5" fill="none" strokeLinejoin="round" strokeLinecap="round" />
        {dayLabels && dayLabels.map((lbl, i) => (i % labelEvery === 0) && (
          <text key={i} x={sx(i)} y={H - 14} textAnchor="middle"
                fontFamily="var(--font-mono)" fontSize="10.5" fill="var(--ink-4)">{lbl}</text>
        ))}
        {hoverI !== null && (
          <g>
            <line x1={sx(hoverI)} x2={sx(hoverI)} y1={PAD_T} y2={PAD_T + plotH}
                  stroke="var(--ink)" strokeDasharray="3 3" opacity="0.4" />
            <circle cx={sx(hoverI)} cy={sy(data[hoverI])} r="5"
                    fill="#fff" stroke="url(#areaStroke)" strokeWidth="2" />
          </g>
        )}
      </svg>
      {hoverI !== null && (() => {
        const cx = (sx(hoverI) / W) * 100;
        const place = hoverI > data.length * 0.7 ? 'right' : 'left';
        return (
          <div className="chart-tip" style={{
            left: place === 'left' ? `calc(${cx}% + 14px)` : 'auto',
            right: place === 'right' ? `calc(${100 - cx}% + 14px)` : 'auto',
            top: (sy(data[hoverI]) / H) * 100 + '%',
            transform: 'translateY(-50%)'
          }}>
            <div className="chart-tip-title">{dayLabels ? dayLabels[hoverI] : 'Day ' + (hoverI + 1)}</div>
            <div className="chart-tip-row">
              <span className="label">Daily spend</span>
              <span className="val">{fmt.usd(data[hoverI], 2)}</span>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ── Mini Trend (small inline chart) ─────────────────────────────────────
function MiniTrend({ data, width = 64, height = 22 }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const r = Math.max(1, max - min);
  const n = data.length;
  const sx = (i) => (i / (n - 1)) * (width - 2) + 1;
  const sy = (v) => height - 2 - ((v - min) / r) * (height - 4);
  const pts = data.map((v, i) => `${sx(i)},${sy(v)}`).join(' ');
  const trending = data[n - 1] > data[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none"
                stroke={trending ? 'var(--neg)' : 'var(--pos)'}
                strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ── Donut Chart (service mix) ───────────────────────────────────────────
function Donut({ data, size = 240, thickness = 28, label = 'Total' }) {
  // data: [{ key, name, value, color }]
  const total = data.reduce((s, d) => s + d.value, 0);
  const cx = size / 2, cy = size / 2;
  const r = size / 2 - 4;
  const rIn = r - thickness;
  const [hover, setHover] = React.useState(null);

  let acc = 0;
  const segs = data.map((d, i) => {
    const start = (acc / total) * Math.PI * 2 - Math.PI / 2;
    acc += d.value;
    const end = (acc / total) * Math.PI * 2 - Math.PI / 2;
    const large = end - start > Math.PI ? 1 : 0;
    const x1 = cx + Math.cos(start) * r;
    const y1 = cy + Math.sin(start) * r;
    const x2 = cx + Math.cos(end) * r;
    const y2 = cy + Math.sin(end) * r;
    const xi2 = cx + Math.cos(end) * rIn;
    const yi2 = cy + Math.sin(end) * rIn;
    const xi1 = cx + Math.cos(start) * rIn;
    const yi1 = cy + Math.sin(start) * rIn;
    const path = `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${xi2} ${yi2} A ${rIn} ${rIn} 0 ${large} 0 ${xi1} ${yi1} Z`;
    return { ...d, path, pct: (d.value / total) * 100, i };
  });

  const focused = hover !== null ? segs[hover] : null;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 28, justifyContent: 'center', flexWrap: 'wrap' }}>
      <div style={{ position: 'relative', width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          <defs>
            {segs.map((s, i) => (
              <linearGradient key={s.key} id={`donut-${s.key}`} x1="0" x2="1" y1="0" y2="1">
                <stop offset="0%"   stopColor={s.color} stopOpacity="1" />
                <stop offset="100%" stopColor={s.color} stopOpacity="0.7" />
              </linearGradient>
            ))}
          </defs>
          {segs.map((s, i) => (
            <path key={s.key} d={s.path}
                  fill={`url(#donut-${s.key})`}
                  opacity={hover === null || hover === i ? 1 : 0.32}
                  style={{ transition: 'opacity .15s', cursor: 'default' }}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)} />
          ))}
        </svg>
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none', textAlign: 'center'
        }}>
          <div style={{
            fontSize: 10.5, fontWeight: 700, letterSpacing: '0.12em',
            textTransform: 'uppercase', color: 'var(--ink-4)'
          }}>{focused ? focused.name : label}</div>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 600,
            color: 'var(--ink)', marginTop: 4, letterSpacing: '-0.01em'
          }}>
            {focused ? fmt.usdK(focused.value) : fmt.usdK(total)}
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-4)', marginTop: 2
          }}>
            {focused ? focused.pct.toFixed(1) + '%' : data.length + ' services'}
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 200 }}>
        {segs.map((s, i) => (
          <div key={s.key}
               onMouseEnter={() => setHover(i)}
               onMouseLeave={() => setHover(null)}
               style={{
                 display: 'grid',
                 gridTemplateColumns: '12px 1fr auto auto',
                 gap: 10,
                 alignItems: 'center',
                 padding: '5px 8px',
                 borderRadius: 6,
                 background: hover === i ? 'var(--surface-2)' : 'transparent',
                 transition: 'background .12s',
                 cursor: 'default',
                 fontSize: 12.5,
               }}>
            <span style={{
              width: 10, height: 10, borderRadius: 3,
              background: `linear-gradient(135deg, ${s.color}, ${s.color}b3)`
            }} />
            <span style={{ color: 'var(--ink-2)', fontWeight: 500 }}>{s.name}</span>
            <span style={{
              fontFamily: 'var(--font-mono)', color: 'var(--ink-4)',
              fontSize: 11, minWidth: 40, textAlign: 'right'
            }}>{s.pct.toFixed(1)}%</span>
            <span style={{
              fontFamily: 'var(--font-mono)', color: 'var(--ink)',
              fontWeight: 600, minWidth: 64, textAlign: 'right'
            }}>{fmt.usdK(s.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { Sparkline, StackedBars, GroupedBars, AreaChart, MiniTrend, Donut, fmt, SERIES_COLORS });