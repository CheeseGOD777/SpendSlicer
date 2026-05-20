/* Chart.js configuration — Obsidian Terminal theme */

const ACU_COLORS = {
  amber:       '#e8ab2c',
  amberBright: '#f0be50',
  amberDim:    'rgba(232,171,44,0.12)',
  emerald:     '#2dd4a2',
  ruby:        '#f05555',
  text1:       '#eaf0f8',
  text2:       '#7a8ca8',
  text3:       '#3c4e68',
  border:      'rgba(255,255,255,0.08)',
  borderDim:   'rgba(255,255,255,0.04)',
  bgCard:      '#0e1422',
};

/* ─── Shared defaults ──────────────────────────────────────────────── */

Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size   = 11;
Chart.defaults.color       = ACU_COLORS.text2;

const sharedTooltip = {
  backgroundColor: '#151d30',
  borderColor:     'rgba(232,171,44,0.3)',
  borderWidth:     1,
  titleColor:      ACU_COLORS.text1,
  bodyColor:       ACU_COLORS.text2,
  titleFont:       { family: "'JetBrains Mono', monospace", size: 12, weight: '600' },
  bodyFont:        { family: "'JetBrains Mono', monospace", size: 11 },
  padding:         { x: 14, y: 10 },
  cornerRadius:    8,
  displayColors:   false,
  callbacks: {
    label: ctx => `  $${ctx.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
  },
};

/* ─── Trend area chart ─────────────────────────────────────────────── */

function buildTrendChart(canvasId, labels, values) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;

  // Destroy previous instance if any
  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();

  const ctx = canvas.getContext('2d');

  // Amber gradient fill
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.offsetHeight || 240);
  gradient.addColorStop(0,   'rgba(232,171,44,0.22)');
  gradient.addColorStop(0.6, 'rgba(232,171,44,0.06)');
  gradient.addColorStop(1,   'rgba(232,171,44,0.00)');

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data:            values,
        borderColor:     ACU_COLORS.amber,
        borderWidth:     2,
        backgroundColor: gradient,
        fill:            true,
        tension:         0.4,
        pointRadius:     0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: ACU_COLORS.amber,
        pointHoverBorderColor:     ACU_COLORS.bgCard,
        pointHoverBorderWidth:     2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 800, easing: 'easeInOutCubic' },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend:  { display: false },
        tooltip: sharedTooltip,
      },
      scales: {
        x: {
          grid:  { color: ACU_COLORS.borderDim, drawBorder: false },
          border: { display: false },
          ticks: { maxRotation: 0, maxTicksLimit: 7, color: ACU_COLORS.text3 },
        },
        y: {
          position: 'right',
          grid:  { color: ACU_COLORS.borderDim, drawBorder: false },
          border: { display: false, dash: [4, 4] },
          ticks: {
            color: ACU_COLORS.text3,
            maxTicksLimit: 5,
            callback: v => '$' + (v >= 1000 ? (v/1000).toFixed(1) + 'k' : v.toFixed(0)),
          },
        },
      },
    },
  });
}

/* ─── Service bar chart ────────────────────────────────────────────── */

function buildServiceChart(canvasId, labels, values) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;

  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();

  const ctx = canvas.getContext('2d');

  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data:            values,
        backgroundColor: 'rgba(232,171,44,0.18)',
        hoverBackgroundColor: 'rgba(232,171,44,0.32)',
        borderColor:     ACU_COLORS.amber,
        borderWidth:     1,
        borderRadius:    4,
        borderSkipped:   false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: 'easeOutQuart' },
      indexAxis: 'y',
      plugins: {
        legend:  { display: false },
        tooltip: sharedTooltip,
      },
      scales: {
        x: {
          grid:  { color: ACU_COLORS.borderDim, drawBorder: false },
          border: { display: false },
          ticks: {
            color: ACU_COLORS.text3,
            callback: v => '$' + (v >= 1000 ? (v/1000).toFixed(1) + 'k' : v.toFixed(0)),
          },
        },
        y: {
          grid:  { display: false },
          border: { display: false },
          ticks: {
            color: ACU_COLORS.text2,
            font:  { family: "'Syne', sans-serif", size: 11 },
            maxRotation: 0,
            callback: (val, idx) => {
              const lbl = labels[idx] || '';
              return lbl.length > 18 ? lbl.slice(0, 17) + '…' : lbl;
            },
          },
        },
      },
    },
  });
}

/* ─── Auto-init on HTMX swap ──────────────────────────────────────── */

document.addEventListener('htmx:afterSwap', (evt) => {
  const trendCanvas = evt.target.querySelector('#trend-chart');
  if (trendCanvas) {
    const url = trendCanvas.dataset.src;
    if (url) {
      fetch(url)
        .then(r => r.json())
        .then(d => {
          if (d.labels && d.values) {
            buildTrendChart('trend-chart', d.labels, d.values);
          }
        })
        .catch(() => {});
    }
  }

  const svcCanvas = evt.target.querySelector('#service-chart');
  if (svcCanvas) {
    try {
      const labels = JSON.parse(svcCanvas.dataset.labels || '[]');
      const values = JSON.parse(svcCanvas.dataset.values || '[]');
      buildServiceChart('service-chart', labels, values);
    } catch(e) {}
  }
});

/* Make builders available globally for inline triggers */
window.buildTrendChart   = buildTrendChart;
window.buildServiceChart = buildServiceChart;
