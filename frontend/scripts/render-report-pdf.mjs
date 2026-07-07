import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const [, , inputPath, outputPath] = process.argv;

if (!inputPath || !outputPath) {
  console.error("Usage: node scripts/render-report-pdf.mjs <input-json-path> <output-pdf-path>");
  process.exit(2);
}

const report = JSON.parse(await fs.readFile(inputPath, "utf8"));

const usd = (n, dec = 2) =>
  `$${Number(n || 0).toLocaleString("en-US", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  })}`;

const esc = (v) =>
  String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

const topServices = report.top_services || [];
const topResources = report.top_resources || [];
const trend = report.trend_points || [];
const budgets = report.budget_findings || [];
const topServiceMax = Math.max(...topServices.map((s) => Number(s.cost_usd || 0)), 1);
const topResourceMax = Math.max(...topResources.map((r) => Number(r.cost || 0)), 1);

// Real account-wide counts from the backend; the capped lists are only for
// table layout. Tiles must never present a list cap as a metric.
const servicesCount = Number(report.services_count ?? topServices.length);
const resourcesCount = Number(report.resources_count ?? topResources.length);
const shownServices = topServices.slice(0, 15);
const shownResources = topResources.slice(0, 25);
const ofNote = (shown, total) => (total > shown ? ` (top ${shown} of ${total})` : "");

const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${esc(report.title || "Cloud Ledger Report")}</title>
  <style>
    @page { size: A4; margin: 16mm; }
    body { font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif; color: #0f172a; margin: 0; font-size: 12px; }
    .header { border-bottom: 2px solid #e2e8f0; padding-bottom: 14px; margin-bottom: 16px; }
    .brand { font-size: 26px; font-weight: 700; color: #1e293b; letter-spacing: -0.3px; }
    .subtitle { color: #475569; margin-top: 4px; }
    .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 10px 0 18px; }
    .kpi { border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px; background: #f8fafc; }
    .kpi .l { color: #64748b; font-size: 10px; text-transform: uppercase; letter-spacing: .08em; font-weight: 600; }
    .kpi .v { margin-top: 6px; font-size: 19px; font-weight: 700; color: #0f172a; }
    h2 { margin: 18px 0 10px; font-size: 15px; color: #0f172a; }
    .meta { color: #475569; margin-top: 2px; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th { background: #0f172a; color: #fff; text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; padding: 9px; }
    td { border-bottom: 1px solid #e2e8f0; padding: 8px 9px; font-size: 11px; vertical-align: top; }
    .num { text-align: right; font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .bar-track { width: 100%; height: 8px; border-radius: 999px; background: #e2e8f0; overflow: hidden; }
    .bar-fill { height: 100%; background: linear-gradient(90deg, #4f46e5, #14b8a6); }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .card { border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px; background: #fff; }
    .small { font-size: 10px; color: #64748b; }
  </style>
</head>
<body>
  <div class="header">
    <div class="brand">${esc(report.platform_name || "Cloud Ledger")}</div>
    <div class="subtitle">${esc(report.title || "Cost Report")}</div>
    <div class="meta">Generated: ${esc(report.generated_at || "")} · Account: ${esc(report.account || "")} · Period: ${esc(report.period || "")}</div>
    <div class="meta">${esc(report.cost_basis || "")}</div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="l">Total Cost</div><div class="v">${usd(report.total_cost_usd, 2)}</div></div>
    <div class="kpi"><div class="l">Services with Spend</div><div class="v">${servicesCount}</div></div>
    <div class="kpi"><div class="l">Resources Attributed</div><div class="v">${resourcesCount}</div></div>
    <div class="kpi"><div class="l">Budgets Tracked</div><div class="v">${budgets.length}</div></div>
  </div>

  <h2>Service Cost Breakdown${esc(ofNote(shownServices.length, servicesCount))}</h2>
  <table>
    <thead><tr><th>Service</th><th class="num">Cost (USD)</th><th>Distribution</th></tr></thead>
    <tbody>
      ${shownServices
        .map((s) => {
          const c = Number(s.cost_usd || 0);
          const w = (c / topServiceMax) * 100;
          return `<tr>
            <td>${esc(s.service)}</td>
            <td class="num">${usd(c, 2)}</td>
            <td><div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div></td>
          </tr>`;
        })
        .join("")}
    </tbody>
  </table>

  <h2>Top Resources${esc(ofNote(shownResources.length, resourcesCount))}</h2>
  <table>
    <thead><tr><th>Service</th><th>Resource</th><th>Type</th><th>State</th><th class="num">Cost (USD)</th><th>Distribution</th></tr></thead>
    <tbody>
      ${shownResources
        .map((r) => {
          const c = Number(r.cost || 0);
          const w = (c / topResourceMax) * 100;
          return `<tr>
            <td>${esc(r.service)}</td>
            <td>${esc(r.name || r.resource_id)}</td>
            <td>${esc(r.type || "-")}</td>
            <td>${esc(r.state || "-")}</td>
            <td class="num">${usd(c, 2)}</td>
            <td><div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div></td>
          </tr>`;
        })
        .join("")}
    </tbody>
  </table>

  <h2>Trend + Budgets</h2>
  <div class="grid-2">
    <div class="card">
      <div style="font-weight:700;margin-bottom:6px;">Trend</div>
      ${trend
        .slice(-12)
        .map((t) => `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed #e2e8f0;"><span>${esc(t.period)}</span><span class="num">${usd(t.cost_usd, 2)}</span></div>`)
        .join("")}
    </div>
    <div class="card">
      <div style="font-weight:700;margin-bottom:6px;">Budgets</div>
      ${budgets.length
        ? budgets
            .slice(0, 12)
            .map((b) => `<div style="padding:4px 0;border-bottom:1px dashed #e2e8f0;"><strong>${esc(b.budget_name)}</strong><div class="small">${esc(b.status || "ok")} · limit ${usd(b.limit_amount, 2)} · actual ${usd(b.actual_spend, 2)}</div></div>`)
            .join("")
        : `<div class="small">No budget findings in this report.</div>`}
    </div>
  </div>
</body>
</html>`;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const exists = async (p) => {
  if (!p) return false;
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
};

const launchBrowser = async () => {
  try {
    return await puppeteer.launch({ headless: true });
  } catch {
    const candidates = [
      process.env.PUPPETEER_EXECUTABLE_PATH,
      "/usr/bin/chromium-browser",
      "/usr/bin/chromium",
      "/usr/bin/google-chrome-stable",
      "/usr/bin/google-chrome",
    ];
    for (const p of candidates) {
      if (await exists(p)) {
        return await puppeteer.launch({ headless: true, executablePath: p });
      }
    }
    throw new Error(
      "Chrome executable not found for Puppeteer. Install Chrome for Testing with `npx puppeteer browsers install chrome` or set PUPPETEER_EXECUTABLE_PATH.",
    );
  }
};

const browser = await launchBrowser();
try {
  const page = await browser.newPage();
  await page.setContent(html, { waitUntil: "networkidle0" });
  await page.pdf({
    path: outputPath,
    format: "A4",
    printBackground: true,
    margin: { top: "12mm", right: "10mm", bottom: "12mm", left: "10mm" },
  });
} finally {
  await browser.close();
}

