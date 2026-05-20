/* ========================================================================
   AWS Cost Dashboard — Frontend Logic
   ======================================================================== */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let state = {
    resources: [],
    services: [],
    sortCol: "cost",
    sortDir: "desc",
    searchQuery: "",
    serviceFilter: "",
    view: "resource",       // "resource" | "tag" | "usage" | "account"
    resourceSvc: "EC2",     // EC2 | EIP | EBS | RDS | ELB (only used when view=resource)
    includeCredits: "0",
    lastMeta: null,         // carries ce_total/raw_sum/limitations from /resources-detailed
};

let serviceChart = null;
let dailyChart = null;

const COLORS = [
    "#FF9900", "#1F77B4", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#AEC7E8", "#FFBB78", "#98DF8A", "#FF9896", "#C5B0D5",
    "#C49C94", "#F7B6D2", "#C7C7C7", "#DBDB8D", "#9EDAE5",
];

const VIEW_LABELS = {
    tag:     { col: "Resource Name", detail: "Tag Value" },
    usage:   { col: "Usage Type",    detail: "Raw Usage Type" },
    account: { col: "Account",       detail: "Account ID" },
};

// Column schemas per view. Each column: {key, label, sortable, cls}.
const COLUMNS = {
    resource: [
        { key: "service",  label: "Service",     sortable: true,  cls: "col-svc" },
        { key: "name",     label: "Name",        sortable: true,  cls: "col-name" },
        { key: "type",     label: "Type",        sortable: true,  cls: "col-mono" },
        { key: "state",    label: "State",       sortable: true,  cls: "col-state" },
        { key: "attached", label: "Attached to", sortable: false, cls: "col-attach" },
        { key: "cost",     label: "Cost (USD)",  sortable: true,  cls: "col-cost" },
        { key: "pct",      label: "% of Total",  sortable: false, cls: "col-pct" },
    ],
    tag: [
        { key: "service",       label: "Service",       sortable: true,  cls: "col-svc" },
        { key: "resource_name", label: "Resource Name", sortable: true,  cls: "col-name" },
        { key: "resource_id",   label: "Tag Value",     sortable: true,  cls: "col-mono" },
        { key: "cost",          label: "Cost (USD)",    sortable: true,  cls: "col-cost" },
        { key: "usage_qty",     label: "Usage Qty",     sortable: true,  cls: "col-num" },
        { key: "pct",           label: "% of Total",    sortable: false, cls: "col-pct" },
    ],
    usage: [
        { key: "service",       label: "Service",       sortable: true,  cls: "col-svc" },
        { key: "resource_name", label: "Usage Type",    sortable: true,  cls: "col-name" },
        { key: "resource_id",   label: "Raw",           sortable: true,  cls: "col-mono col-muted" },
        { key: "cost",          label: "Cost (USD)",    sortable: true,  cls: "col-cost" },
        { key: "usage_qty",     label: "Usage Qty",     sortable: true,  cls: "col-num" },
        { key: "pct",           label: "% of Total",    sortable: false, cls: "col-pct" },
    ],
    account: [
        { key: "service",       label: "Service",       sortable: true,  cls: "col-svc" },
        { key: "resource_name", label: "Account",       sortable: true,  cls: "col-name" },
        { key: "resource_id",   label: "Account ID",    sortable: true,  cls: "col-mono" },
        { key: "cost",          label: "Cost (USD)",    sortable: true,  cls: "col-cost" },
        { key: "usage_qty",     label: "Usage Qty",     sortable: true,  cls: "col-num" },
        { key: "pct",           label: "% of Total",    sortable: false, cls: "col-pct" },
    ],
};

const SVC_LABEL = {
    EC2: "EC2 Instance", EIP: "Elastic IP", EBS: "EBS Volume",
    RDS: "RDS Database", ELB: "Load Balancer",
};

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------
function getDateRange() {
    const preset = document.getElementById("datePreset").value;
    const now = new Date();
    // CE end is exclusive: use tomorrow so today's partial charges are included
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);

    let start, end;
    end = fmt(tomorrow);

    switch (preset) {
        case "7":   start = fmt(daysAgo(6)); break;   // 7 days: 6 past + today
        case "14":  start = fmt(daysAgo(13)); break;
        case "30":  start = fmt(daysAgo(29)); break;
        case "month":
            start = fmt(new Date(now.getFullYear(), now.getMonth(), 1)); break;
        case "lastmonth":
            start = fmt(new Date(now.getFullYear(), now.getMonth() - 1, 1));
            end = fmt(new Date(now.getFullYear(), now.getMonth(), 1)); break;
        case "90":  start = fmt(daysAgo(89)); break;
        case "custom":
            start = document.getElementById("startDate").value;
            end = document.getElementById("endDate").value;
            if (!start || !end) { start = fmt(daysAgo(29)); end = fmt(tomorrow); }
            break;
        default: start = fmt(daysAgo(29));
    }
    return { start, end };
}

function fmt(d) { return d.toISOString().split("T")[0]; }
function daysAgo(n) { const d = new Date(); d.setDate(d.getDate() - n); return d; }

function formatCurrency(n) {
    if (n == null) return "--";
    if (n >= 1000) return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (n >= 1) return "$" + n.toFixed(2);
    if (n >= 0.01) return "$" + n.toFixed(3);
    return "$" + n.toFixed(4);
}

function shortService(name) {
    return name
        .replace("Amazon ", "").replace("AWS ", "")
        .replace("Elastic Compute Cloud - Compute", "EC2 Compute")
        .replace("Simple Storage Service", "S3")
        .replace("Relational Database Service", "RDS")
        .replace("Simple Notification Service", "SNS")
        .replace("Simple Queue Service", "SQS");
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------
function showError(msg) {
    document.getElementById("errorText").textContent = msg;
    document.getElementById("errorBanner").style.display = "flex";
}
function hideError() { document.getElementById("errorBanner").style.display = "none"; }

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function apiFetch(endpoint, params = {}) {
    const { start, end } = getDateRange();
    params.start = params.start || start;
    params.end = params.end || end;
    params.credits = state.includeCredits;
    const qs = new URLSearchParams(params).toString();
    const resp = await fetch(`/api/${endpoint}?${qs}`);
    const data = await resp.json();
    if (data.error) {
        showError(data.error);
        if (resp.status === 401) document.getElementById("setupCard").style.display = "block";
    }
    return data;
}

// ---------------------------------------------------------------------------
// Profiles
// ---------------------------------------------------------------------------
async function loadProfiles() {
    try {
        const resp = await fetch("/api/profiles");
        const data = await resp.json();
        const select = document.getElementById("profileSelect");
        select.innerHTML = '';
        const profiles = data.profiles || [];
        profiles.forEach((p) => {
            const opt = document.createElement("option");
            opt.value = p;
            opt.textContent = p;
            if (p === data.current) opt.selected = true;
            select.appendChild(opt);
        });
        // If no profile is currently active, silently set the first one on the backend
        if (!data.current && profiles.length > 0) {
            select.value = profiles[0];
            await fetch("/api/set-profile", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ profile: profiles[0] }),
            });
        }
    } catch { /* ignore */ }
}

async function switchProfile(profile) {
    const badge = document.getElementById("accountBadge");
    badge.textContent = "Switching...";
    badge.style.color = "#FFB84D";
    try {
        const resp = await fetch("/api/set-profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ profile }),
        });
        const data = await resp.json();
        if (data.ok) {
            badge.textContent = `Account: ${data.account}`;
            badge.style.color = "#98DF8A";
            document.getElementById("setupCard").style.display = "none";
            hideError();
            refresh();
        } else {
            badge.textContent = "Connection failed";
            badge.style.color = "#FF6B6B";
            showError(data.error || "Failed to switch profile");
        }
    } catch (e) {
        badge.textContent = "Error";
        badge.style.color = "#FF6B6B";
        showError("Failed to connect: " + e.message);
    }
}

// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------
async function checkHealth() {
    try {
        const resp = await fetch("/api/health");
        const data = await resp.json();
        const badge = document.getElementById("accountBadge");
        if (data.ok) {
            badge.textContent = `Account: ${data.account}`;
            badge.style.color = "#98DF8A";
            return true;
        } else {
            badge.textContent = "Not connected";
            badge.style.color = "#FF6B6B";
            document.getElementById("setupCard").style.display = "block";
            return false;
        }
    } catch {
        document.getElementById("accountBadge").textContent = "Error";
        return false;
    }
}

// ---------------------------------------------------------------------------
// Load summary
// ---------------------------------------------------------------------------
async function loadSummary() {
    showSkeleton("totalCost"); showSkeleton("topService");
    showSkeleton("activeServices"); showSkeleton("forecast");

    const data = await apiFetch("summary");
    if (data.error && !data.total_cost) return;

    document.getElementById("totalCost").textContent = formatCurrency(data.total_cost);

    const changeEl = document.getElementById("totalChange");
    if (data.change_pct !== undefined && data.change_pct !== null) {
        const arrow = data.change_pct > 0 ? "\u25B2" : data.change_pct < 0 ? "\u25BC" : "";
        changeEl.textContent = `${arrow} ${Math.abs(data.change_pct)}% vs previous period`;
        changeEl.className = "card-sub " + (data.change_pct > 0 ? "positive" : data.change_pct < 0 ? "negative" : "");
    } else if (data.change_pct === null) {
        changeEl.textContent = "no data for previous period";
        changeEl.className = "card-sub";
    }

    if (data.top_service) {
        document.getElementById("topService").textContent = shortService(data.top_service.name);
        document.getElementById("topServiceCost").textContent = formatCurrency(data.top_service.cost);
    }

    document.getElementById("activeServices").textContent = data.active_services || 0;
    document.getElementById("forecast").textContent = data.forecast != null ? formatCurrency(data.forecast) : "N/A";
}

// ---------------------------------------------------------------------------
// Services chart
// ---------------------------------------------------------------------------
async function loadServices() {
    const data = await apiFetch("services");
    if (!data.services) return;
    state.services = data.services;

    const select = document.getElementById("serviceFilter");
    const current = select.value;
    select.innerHTML = '<option value="">All Services</option>';
    data.services.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = `${shortService(s.name)} (${formatCurrency(s.cost)})`;
        select.appendChild(opt);
    });
    select.value = current;

    const top10 = data.services.slice(0, 10);
    const otherCost = data.services.slice(10).reduce((sum, s) => sum + s.cost, 0);
    const labels = top10.map((s) => shortService(s.name));
    const values = top10.map((s) => s.cost);
    const colors = top10.map((_, i) => COLORS[i % COLORS.length]);
    if (otherCost > 0.01) { labels.push("Other"); values.push(Math.round(otherCost * 100) / 100); colors.push("#DDD"); }

    const ctx = document.getElementById("serviceChart").getContext("2d");
    if (serviceChart) serviceChart.destroy();
    serviceChart = new Chart(ctx, {
        type: "doughnut",
        data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 1, borderColor: "#fff" }] },
        options: {
            responsive: true, maintainAspectRatio: false, cutout: "60%",
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (c) => `${c.label}: ${formatCurrency(c.raw)}` } },
            },
            onClick: (_, els) => {
                if (els.length && els[0].index < data.services.length) {
                    document.getElementById("serviceFilter").value = data.services[els[0].index].name;
                    filterTable();
                }
            },
        },
    });

    const legendEl = document.getElementById("serviceLegend");
    legendEl.innerHTML = "";
    labels.forEach((label, i) => {
        const item = document.createElement("div");
        item.className = "legend-item";
        item.innerHTML = `<span class="legend-dot" style="background:${colors[i]}"></span><span>${label}</span><span class="legend-cost">${formatCurrency(values[i])}</span>`;
        item.addEventListener("click", () => {
            if (i < data.services.length) { document.getElementById("serviceFilter").value = data.services[i].name; filterTable(); }
        });
        legendEl.appendChild(item);
    });
}

// ---------------------------------------------------------------------------
// Daily trend
// ---------------------------------------------------------------------------
async function loadDaily() {
    const data = await apiFetch("daily");
    if (!data.days) return;

    const labels = data.days.map((d) => {
        const dt = new Date(d.date + "T00:00:00");
        return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    });
    const values = data.days.map((d) => d.cost);
    const ctx = document.getElementById("dailyChart").getContext("2d");
    if (dailyChart) dailyChart.destroy();

    const gradient = ctx.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, "rgba(255,153,0,0.3)");
    gradient.addColorStop(1, "rgba(255,153,0,0.02)");

    dailyChart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Daily Cost", data: values,
                borderColor: "#FF9900", backgroundColor: gradient, fill: true,
                tension: 0.3, pointRadius: values.length > 60 ? 0 : 3,
                pointHoverRadius: 5, pointBackgroundColor: "#FF9900", borderWidth: 2,
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: "index" },
            scales: {
                y: { beginAtZero: true, ticks: { callback: (v) => "$" + v.toFixed(2), font: { size: 11 } }, grid: { color: "rgba(0,0,0,0.05)" } },
                x: { ticks: { font: { size: 11 }, maxTicksLimit: 15 }, grid: { display: false } },
            },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (c) => `Cost: ${formatCurrency(c.raw)}` } },
            },
        },
    });
}

// ---------------------------------------------------------------------------
// Resources table
// ---------------------------------------------------------------------------
async function loadResources() {
    const tbody = document.getElementById("resourceBody");
    const cols = COLUMNS[state.view] || COLUMNS.usage;
    renderThead(cols);

    tbody.innerHTML = `<tr class="loading-row"><td colspan="${cols.length}"><div class="loading-spinner"></div><span>Loading…</span></td></tr>`;

    // Toggle chrome (pills, banner, waste panel) per view
    document.getElementById("servicePills").style.display = state.view === "resource" ? "flex" : "none";
    document.getElementById("tagBanner").style.display = "none";
    document.getElementById("wastePanel").style.display = "none";

    let data;
    if (state.view === "resource") {
        data = await apiFetch("resources-detailed", { service: state.resourceSvc });
        state.resources = (data.resources || []).map(enrichResource);
        state.lastMeta = {
            ce_total: data.ce_total, raw_sum: data.raw_sum,
            factor: data.normalization_factor, limitations: data.limitations || [],
            region: data.region,
        };
        renderWastePanel(state.resources);
    } else {
        data = await apiFetch("resources", { view: state.view });
        state.resources = data.resources || [];
        state.lastMeta = null;
        // Tag activation banner: all (untagged)
        if (state.view === "tag" && state.resources.length > 0 &&
            state.resources.every((r) => (r.resource_name || "").includes("untagged"))) {
            document.getElementById("tagBanner").style.display = "block";
        }
    }

    const infoEl = document.getElementById("tableInfo");
    if (data.error) {
        infoEl.textContent = data.error;
        infoEl.classList.add("visible");
    } else {
        infoEl.classList.remove("visible");
    }

    renderTable();
}

function renderThead(cols) {
    const thead = document.getElementById("resourceThead");
    thead.innerHTML = "<tr>" + cols.map((c) => {
        const classes = [c.sortable ? "sortable" : "", c.cls || ""].filter(Boolean).join(" ");
        const sortedCls = (c.sortable && c.key === state.sortCol) ? ` sorted-${state.sortDir}` : "";
        return `<th class="${classes}${sortedCls}"${c.sortable ? ` data-col="${c.key}"` : ""}>${c.label}${c.sortable ? ' <span class="sort-icon"></span>' : ""}</th>`;
    }).join("") + "</tr>";
    // Re-bind sort handlers
    thead.querySelectorAll("th.sortable").forEach((th) => {
        th.addEventListener("click", () => {
            const col = th.dataset.col;
            if (state.sortCol === col) {
                state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
            } else {
                state.sortCol = col;
                state.sortDir = (col === "cost" || col === "usage_qty") ? "desc" : "asc";
            }
            renderThead(cols);
            renderTable();
        });
    });
}

// Normalize a `/resources-detailed` row into the fields the renderer uses.
function enrichResource(r) {
    const attached = r.attributes?.attached_instance_name
                  || r.attributes?.attached_instance_id
                  || r.attributes?.public_ip
                  || "";
    return {
        ...r,
        service: r.service,
        resource_name: r.name,
        resource_id: r.resource_id,
        attached,
        usage_qty: r.usage?.hours ?? r.usage?.idle_hours ?? r.usage?.gb_hours ?? 0,
    };
}

function renderTable() {
    const cols = COLUMNS[state.view] || COLUMNS.usage;
    let rows = [...state.resources];

    if (state.serviceFilter && state.view !== "resource") {
        rows = rows.filter((r) => r.service === state.serviceFilter);
    }
    if (state.searchQuery) {
        const q = state.searchQuery.toLowerCase();
        rows = rows.filter((r) =>
            Object.values(r).some((v) => typeof v === "string" && v.toLowerCase().includes(q))
        );
    }

    rows.sort((a, b) => {
        let va = a[state.sortCol], vb = b[state.sortCol];
        if (va == null) va = "";
        if (vb == null) vb = "";
        if (typeof va === "string") va = va.toLowerCase();
        if (typeof vb === "string") vb = vb.toLowerCase();
        if (va < vb) return state.sortDir === "asc" ? -1 : 1;
        if (va > vb) return state.sortDir === "asc" ? 1 : -1;
        return 0;
    });

    const total = rows.reduce((s, r) => s + (r.cost || 0), 0);
    const maxCost = rows.length > 0 ? Math.max(...rows.map((r) => r.cost || 0), 0.0001) : 1;
    const tbody = document.getElementById("resourceBody");

    if (rows.length === 0) {
        tbody.innerHTML = `<tr class="loading-row"><td colspan="${cols.length}"><div class="empty-state"><p>No resources found.</p></div></td></tr>`;
        document.getElementById("rowCount").textContent = "0 resources";
        return;
    }

    tbody.innerHTML = rows.map((r) => {
        const pct = total > 0 ? (r.cost / total) * 100 : 0;
        const barWidth = maxCost > 0 ? (r.cost / maxCost) * 80 : 0;
        return "<tr>" + cols.map((c) => renderCell(c, r, pct, barWidth)).join("") + "</tr>";
    }).join("");

    const suffix = state.view === "resource" && state.lastMeta
        ? ` · CE total: ${formatCurrency(state.lastMeta.ce_total)} · region: ${state.lastMeta.region}`
        : "";
    document.getElementById("rowCount").textContent =
        `${rows.length} item${rows.length !== 1 ? "s" : ""} · shown: ${formatCurrency(total)}${suffix}`;
}

function renderCell(col, r, pct, barWidth) {
    switch (col.key) {
        case "service":
            return `<td><span class="service-tag">${escHtml(state.view === "resource" ? (SVC_LABEL[r.service] || r.service) : shortService(r.service))}</span></td>`;
        case "name": {
            const waste = r.waste_reason
                ? ` <span class="waste-badge" title="${escHtml(r.waste_reason)}">${escHtml(r.waste_reason)}</span>`
                : "";
            const sub = r.resource_id && r.resource_id !== r.name
                ? `<div class="row-sub mono">${escHtml(r.resource_id)}</div>` : "";
            return `<td class="${col.cls}"><div class="row-main">${escHtml(r.name || r.resource_id)}${waste}</div>${sub}</td>`;
        }
        case "type":
            return `<td class="${col.cls}">${escHtml(r.type || "")}</td>`;
        case "state": {
            const s = (r.state || "").toLowerCase();
            const cls = s === "running" || s === "available" || s === "active" || s === "associated" ? "ok"
                      : s === "stopped" || s === "unassociated" ? "warn"
                      : "neutral";
            return `<td class="${col.cls}"><span class="state-dot state-${cls}"></span>${escHtml(r.state || "")}</td>`;
        }
        case "attached":
            return `<td class="${col.cls} mono muted">${escHtml(r.attached || "—")}</td>`;
        case "resource_name":
            return `<td class="resource-name ${col.cls || ""}">${escHtml(r.resource_name || "-")}</td>`;
        case "resource_id":
            return `<td class="resource-id ${col.cls || ""}">${escHtml(r.resource_id || "")}</td>`;
        case "cost":
            return `<td class="cost-cell">${formatCurrency(r.cost)}<span class="cost-bar" style="width:${barWidth}px"></span></td>`;
        case "usage_qty":
            return `<td class="num">${(r.usage_qty || 0).toLocaleString(undefined, {maximumFractionDigits: 2})}</td>`;
        case "pct":
            return `<td class="pct-cell">${pct.toFixed(1)}%</td>`;
        default:
            return `<td>${escHtml(r[col.key] ?? "")}</td>`;
    }
}

function renderWastePanel(resources) {
    const wasted = resources.filter((r) => r.waste_reason);
    const el = document.getElementById("wastePanel");
    if (!wasted.length) {
        el.style.display = "none";
        return;
    }
    const groups = {};
    wasted.forEach((r) => {
        const k = r.waste_reason;
        groups[k] = groups[k] || { count: 0, cost: 0, items: [] };
        groups[k].count += 1;
        groups[k].cost += r.cost || 0;
        groups[k].items.push(r);
    });
    const total = wasted.reduce((s, r) => s + (r.cost || 0), 0);
    const chips = Object.entries(groups).map(([reason, g]) =>
        `<div class="waste-chip"><strong>${g.count}</strong> ${escHtml(reason)} · ${formatCurrency(g.cost)}</div>`
    ).join("");
    el.innerHTML = `
        <div class="waste-panel-inner">
            <div class="waste-heading">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                Waste finder · ${formatCurrency(total)} in the selected window
            </div>
            <div class="waste-chips">${chips}</div>
        </div>`;
    el.style.display = "block";
}

function filterTable() {
    state.serviceFilter = document.getElementById("serviceFilter").value;
    state.searchQuery = document.getElementById("searchInput").value;
    renderTable();
}

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------
// Sort binding is now handled inside renderThead().
function setupSorting() {}

// ---------------------------------------------------------------------------
// View toggle
// ---------------------------------------------------------------------------
function setupViewToggle() {
    document.querySelectorAll(".view-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".view-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            state.view = btn.dataset.view;
            state.sortCol = state.view === "resource" ? "cost" : "cost";
            state.sortDir = "desc";
            loadResources();
        });
    });
}

function setupServicePills() {
    document.querySelectorAll("#servicePills .pill").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("#servicePills .pill").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            state.resourceSvc = btn.dataset.svc;
            loadResources();
        });
    });
}

function setupTagBanner() {
    const close = document.getElementById("tagBannerClose");
    if (close) close.addEventListener("click", () => {
        document.getElementById("tagBanner").style.display = "none";
    });
}

// ---------------------------------------------------------------------------
// Cost mode toggle (Gross vs Net)
// ---------------------------------------------------------------------------
function setupCostModeToggle() {
    document.querySelectorAll(".cost-mode-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".cost-mode-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            state.includeCredits = btn.dataset.credits;

            const hint = document.getElementById("costModeHint");
            if (state.includeCredits === "0") {
                hint.textContent = "Showing actual resource consumption costs. Credits/refunds excluded.";
            } else {
                hint.textContent = "Showing net cost after credits, refunds, and discounts are applied.";
            }

            refresh();
        });
    });
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------
function exportCSV() {
    const { start, end } = getDateRange();
    window.open(`/api/export?start=${start}&end=${end}&view=${state.view}&credits=${state.includeCredits}`, "_blank");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function showSkeleton(id) {
    document.getElementById(id).innerHTML = '<span class="skeleton skeleton-text"></span>';
}

function escHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
    document.getElementById("datePreset").addEventListener("change", (e) => {
        document.getElementById("customDates").style.display = e.target.value === "custom" ? "flex" : "none";
        if (e.target.value !== "custom") refresh();
    });
    document.getElementById("startDate").addEventListener("change", refresh);
    document.getElementById("endDate").addEventListener("change", refresh);
    document.getElementById("refreshBtn").addEventListener("click", () => refresh());
    document.getElementById("searchInput").addEventListener("input", filterTable);
    document.getElementById("serviceFilter").addEventListener("change", filterTable);
    document.getElementById("exportBtn").addEventListener("click", exportCSV);
    document.getElementById("errorClose").addEventListener("click", hideError);
    document.getElementById("profileSelect").addEventListener("change", (e) => switchProfile(e.target.value));

    setupSorting();
    setupViewToggle();
    setupServicePills();
    setupTagBanner();

    const _tomorrow = new Date(); _tomorrow.setDate(_tomorrow.getDate() + 1);
    document.getElementById("endDate").value = fmt(_tomorrow);
    document.getElementById("startDate").value = fmt(daysAgo(29));

    await loadProfiles();
    const healthy = await checkHealth();
    if (healthy) refresh();
}

async function refresh() {
    hideError();
    await Promise.all([loadSummary(), loadServices(), loadDaily()]);
    await loadResources();
    document.getElementById("lastUpdated").textContent = "Updated: " + new Date().toLocaleTimeString();
}

document.addEventListener("DOMContentLoaded", init);
