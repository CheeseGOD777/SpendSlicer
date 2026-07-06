export const meta = {
  name: 'cost-explorer-audit',
  description: 'Audit the AWS cost-explorer subsystem for bugs, vulnerabilities, and large-scale (high resource count) failure modes; adversarially verify each finding',
  phases: [
    { title: 'Find', detail: 'specialized reviewers fan out across dimensions' },
    { title: 'Verify', detail: 'two skeptics adversarially verify each unique finding' },
  ],
}

const ROOT = "/run/media/tirth/OS/Users/Tirth Teraiya/Personal Folder/aws-cost-dashboard"

const FINDINGS_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    findings: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        properties: {
          title: { type: "string", description: "short, specific" },
          file: { type: "string", description: "repo-relative path" },
          line: { type: "string", description: "line or range, e.g. 96 or 96-102" },
          category: { type: "string", enum: ["bug", "vulnerability", "scale", "concurrency", "data-accuracy", "other"] },
          severity: { type: "string", enum: ["critical", "high", "medium", "low"] },
          description: { type: "string", description: "what is wrong, mechanism, why" },
          scenario: { type: "string", description: "concrete trigger; especially behavior when resource/service/line-item counts are very high" },
          suggested_fix: { type: "string" },
        },
        required: ["title", "file", "line", "category", "severity", "description", "scenario", "suggested_fix"],
      },
    },
  },
  required: ["findings"],
}

const VERDICT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    verdict: { type: "string", enum: ["confirmed", "refuted", "uncertain"] },
    adjusted_severity: { type: "string", enum: ["critical", "high", "medium", "low", "none"] },
    reasoning: { type: "string" },
    evidence: { type: "string", description: "file:line citations from the actual code that support or refute the claim" },
  },
  required: ["verdict", "adjusted_severity", "reasoning", "evidence"],
}

const SCALE_NOTE = `CROSS-CUTTING CONCERN: this is a cost dashboard that may point at AWS accounts with VERY LARGE numbers of resources, services, usage types, regions, and CUR line items. For every area you examine, explicitly reason about what happens when those counts are large (thousands of EC2 instances / Lambda fns / S3 buckets, hundreds of services and usage types, dozens of regions, deep CE pagination, huge cached blobs). Unbounded memory, O(n^2) aggregation, thread/connection explosion, N+1 API calls, CE GroupBy cardinality limits, page-cost blowups, and serialization of huge lists are all in scope.`

const COMMON = `You are auditing the cost-explorer subsystem of an AWS cost dashboard (FastAPI backend + React/HTMX frontend). The repo root is:
${ROOT}

Read the files assigned to you in full (use the Read tool with the absolute path = root + "/" + relative path). Trace data flow into and out of them as needed — you may read other files for context, but report findings primarily in your assigned files. Report ONLY real, specific, defensible issues with exact file + line. Do NOT invent issues to fill space; an empty findings list is acceptable if the code is sound. For each finding give a concrete trigger scenario. ${SCALE_NOTE}`

const DIMENSIONS = [
  {
    key: "ce-math",
    label: "CE math & data accuracy",
    files: [
      "aws_cost_ultra/aws/cost_explorer.py",
      "aws_cost_ultra/aws/cost_store.py",
      "aws_cost_ultra/aws/cost_source.py",
      "aws_cost_ultra/core/service_groups.py",
      "aws_cost_ultra/core/provenance.py",
      "aws_cost_ultra/core/time_windows.py",
      "aws_cost_ultra/web/routes/cost.py",
    ],
    focus: `Focus on numerical correctness: double-counting (e.g. summing both Total and Groups in the same period), hardcoded metric keys vs requested metric, aggregation across time buckets, forecast metric mapping and forecast+MTD math, percent-change math, rescaling/normalization factors, rounding, and any place a number could silently diverge from the AWS console. Check timezone handling (UTC vs local) and closed-vs-open window classification.`,
  },
  {
    key: "scale-resources",
    label: "Resource attribution at scale",
    files: [
      "aws_cost_ultra/resources/runner.py",
      "aws_cost_ultra/resources/base.py",
      "aws_cost_ultra/resources/ec2.py",
      "aws_cost_ultra/resources/ebs.py",
      "aws_cost_ultra/resources/rds.py",
      "aws_cost_ultra/resources/s3.py",
      "aws_cost_ultra/resources/lambda_fn.py",
      "aws_cost_ultra/resources/dynamodb.py",
      "aws_cost_ultra/resources/elb.py",
      "aws_cost_ultra/resources/eip.py",
    ],
    focus: `Focus on what breaks when an account has thousands of resources across many regions: nested ThreadPoolExecutors and thread explosion, sequential per-region loops (e.g. EBS), unpaginated or fully-buffered describe calls, N+1 API calls, memory blow-up holding all resources, and the CE-total rescaling factors (factor = pool / raw_sum) — division by near-zero, cost inflation, misattribution when raw_sum is tiny or some resources have zero cost. Also AWS API throttling/rate limits under fan-out.`,
  },
  {
    key: "scale-cache",
    label: "Caching, store & request-counter at scale",
    files: [
      "aws_cost_ultra/web/sqlite_cache.py",
      "aws_cost_ultra/web/deps.py",
      "aws_cost_ultra/aws/cost_store.py",
      "aws_cost_ultra/web/middleware.py",
      "aws_cost_ultra/web/prewarm.py",
    ],
    focus: `Focus on cache + counter behavior under load and large payloads: SQLite connection-per-call churn, WAL/locking/timeout under concurrent writers, full-table LIKE scans on bust, unbounded growth of cache rows and of the per-thread CostExplorerClient dict keyed by id(session) (id reuse after GC -> wrong/dead client), serializing very large matrices/resource lists to JSON in SQLite, closed-window TTL classification using local date vs UTC, SWR refresh-pool saturation across many keys, and whether the contextvar request counter actually propagates into ThreadPoolExecutor worker threads (CE calls made in pool threads).`,
  },
  {
    key: "sec-web",
    label: "Web-layer security",
    files: [
      "aws_cost_ultra/web/routes/cost.py",
      "aws_cost_ultra/web/routes/resources_api.py",
      "aws_cost_ultra/web/routes/pages.py",
      "aws_cost_ultra/web/routes/audit_api.py",
      "aws_cost_ultra/web/render.py",
      "aws_cost_ultra/web/context.py",
      "aws_cost_ultra/web/app.py",
    ],
    focus: `Focus on injection and information disclosure: reflected/stored XSS via values interpolated into inline <script> blocks or HTML (note json.dumps does NOT escape </script>, <, > and user-controlled query params like profile/period reflected into inline scripts), unescaped template rendering, friendly_error leaking stack traces / account IDs / ARNs / internal paths, missing authentication/authorization on routes that hit AWS and spend money, CSRF on POST routes, open CORS, and any path where a query param reaches an eval/exec/HTML sink.`,
  },
  {
    key: "sec-aws",
    label: "AWS input handling, filters & exporters security",
    files: [
      "aws_cost_ultra/web/deps.py",
      "aws_cost_ultra/core/filters.py",
      "aws_cost_ultra/aws/session.py",
      "aws_cost_ultra/web/routes/export_api.py",
      "aws_cost_ultra/exporters/base.py",
      "aws_cost_ultra/exporters/s3_export.py",
      "aws_cost_ultra/exporters/email_export.py",
      "aws_cost_ultra/exporters/slack_export.py",
      "aws_cost_ultra/exporters/scheduler.py",
      "aws_cost_ultra/exporters/pdf_export.py",
      "aws_cost_ultra/exporters/csv_export.py",
    ],
    focus: `Focus on untrusted input flowing into AWS/SDK/filesystem/network: profile and region query params -> boto3 session/client (arbitrary profile selection, unvalidated region), tag_key / service / usage_type substrings -> CE Filter construction (injection or oversized Values arrays vs CE limits), output_dir / filename / name params -> path traversal or arbitrary file write, exporters that send data outward (S3 bucket choice, email recipients, Slack webhook URLs -> SSRF / secret leakage / sending to attacker-controlled destination), credential/secret handling and logging of secrets, and command/template injection in pdf/email/slack rendering.`,
  },
  {
    key: "concurrency",
    label: "Concurrency & thread-safety",
    files: [
      "aws_cost_ultra/web/routes/cost.py",
      "aws_cost_ultra/resources/runner.py",
      "aws_cost_ultra/web/deps.py",
      "aws_cost_ultra/web/middleware.py",
      "aws_cost_ultra/aws/cost_explorer.py",
      "aws_cost_ultra/web/sqlite_cache.py",
    ],
    focus: `Focus on concurrency correctness: contextvars set in middleware/handler NOT propagating to ThreadPoolExecutor worker threads (so get_current_counter() returns a fresh throwaway in pool threads -> undercount AND possible behavioral bugs), reuse of a single boto3 CE client across threads despite "not thread-safe" claim, races in schedule_refresh dedup set, races in SqliteCache lazy-delete / read-modify-write, nested executors deadlock/starvation when the pool is exhausted, shared mutable AttributedResource objects mutated by rescaling while another thread reads, and per-thread caches that leak across requests.`,
  },
  {
    key: "frontend",
    label: "Frontend data layer & rendering",
    files: [
      "frontend/src/api.js",
      "frontend/src/App.jsx",
      "frontend/src/charts.jsx",
      "frontend/src/hooks/useAsyncData.js",
      "frontend/src/hooks/useDebounced.js",
      "frontend/src/lib/swrCache.js",
      "frontend/src/lib/ceMeter.js",
      "frontend/src/components/CostBadge.jsx",
    ],
    focus: `Focus on the browser side: XSS via dangerouslySetInnerHTML / innerHTML / interpolating server strings (service names, resource ids, tags) into markup, unbounded localStorage/sessionStorage growth from the SWR cache (large resource lists cached per key with no eviction -> quota errors), rendering thousands of table rows without virtualization (UI freeze at scale), missing AbortController handling / race conditions between in-flight requests, stale-closure bugs in hooks, and error/empty-state handling when payloads are huge or malformed.`,
  },
]

phase('Find')
log(`Fanning out ${DIMENSIONS.length} dimension reviewers across the cost-explorer subsystem`)

const finderResults = await parallel(DIMENSIONS.map((d) => () =>
  agent(
    `${COMMON}

DIMENSION: ${d.label}
${d.focus}

ASSIGNED FILES (repo-relative):
${d.files.map((f) => "  - " + f).join("\n")}

Read each assigned file fully, then report every real issue you find as a structured finding.`,
    { label: `find:${d.key}`, phase: 'Find', schema: FINDINGS_SCHEMA }
  ).then((r) => ({ dim: d.key, findings: (r && r.findings) || [] }))
))

// Barrier is justified: dedup needs ALL findings together before verification.
const raw = []
for (const fr of finderResults.filter(Boolean)) {
  for (const f of fr.findings) raw.push({ ...f, dims: [fr.dim] })
}

const slug = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40)
const firstLine = (s) => String(s || "").split("-")[0].split(",")[0].trim()
const keyOf = (f) => `${f.file}|${firstLine(f.line)}|${slug(f.title)}`

const byKey = new Map()
for (const f of raw) {
  const k = keyOf(f)
  const existing = byKey.get(k)
  if (existing) {
    for (const d of f.dims) if (!existing.dims.includes(d)) existing.dims.push(d)
    // keep the higher severity description
    const order = { critical: 4, high: 3, medium: 2, low: 1 }
    if ((order[f.severity] || 0) > (order[existing.severity] || 0)) {
      existing.severity = f.severity
      existing.description = f.description
      existing.suggested_fix = f.suggested_fix
    }
  } else {
    byKey.set(k, { ...f })
  }
}
const unique = [...byKey.values()]
log(`Collected ${raw.length} raw findings -> ${unique.length} unique after dedup. Adversarially verifying each.`)

phase('Verify')

const VERIFY_LENSES = [
  {
    key: "refute",
    instruction: `Adversarial CORRECTNESS lens. Your job is to REFUTE the finding. Open the cited file and read enough surrounding code to decide whether the described mechanism can actually occur. Check for guards, validation, framework behavior, or invariants the finder missed that would prevent the bug. If the trigger genuinely cannot happen as described, return verdict "refuted". Only return "confirmed" if, after a real read of the code, the mechanism clearly holds. When genuinely unsure, return "uncertain". Be skeptical and default toward refuted when the claim is vague or unsupported by the actual code.`,
  },
  {
    key: "impact",
    instruction: `Real-world IMPACT lens. Assume the mechanism might be real; your job is to judge whether it actually causes harm in realistic operation (correctness error users would see, a security boundary actually crossed, or a genuine failure/slowdown at large scale) and to set the true severity. Read the cited code to ground your judgment. If the issue is purely theoretical, already mitigated elsewhere, or harmless in practice, return verdict "refuted" or "uncertain" with adjusted_severity reflecting reality. Otherwise "confirmed" with a calibrated adjusted_severity.`,
  },
]

const verified = await parallel(unique.map((f) => () =>
  parallel(VERIFY_LENSES.map((lens) => () =>
    agent(
      `You are verifying a single audit finding about the cost-explorer subsystem of an AWS cost dashboard. Repo root: ${ROOT}

FINDING
  title: ${f.title}
  file: ${f.file}
  line: ${f.line}
  category: ${f.category}
  claimed severity: ${f.severity}
  description: ${f.description}
  trigger scenario: ${f.scenario}
  proposed fix: ${f.suggested_fix}

Read ${f.file} (absolute = root + "/" + path) around the cited lines, plus any other file needed to judge it.

${lens.instruction}`,
      { label: `verify:${lens.key}:${slug(f.title).slice(0, 24)}`, phase: 'Verify', schema: VERDICT_SCHEMA }
    ).then((v) => ({ lens: lens.key, ...v }))
  )).then((votes) => {
    const v = votes.filter(Boolean)
    const confirmed = v.filter((x) => x.verdict === "confirmed").length
    const refuted = v.filter((x) => x.verdict === "refuted").length
    let status
    if (confirmed >= 1 && refuted === 0) status = "confirmed"
    else if (refuted >= 1 && confirmed === 0 && refuted === v.length) status = "refuted"
    else status = "likely"
    // Use the max adjusted severity among non-refuting verifiers, fall back to claimed.
    const sevOrder = { none: 0, low: 1, medium: 2, high: 3, critical: 4 }
    let adj = f.severity
    for (const x of v) {
      if (x.verdict !== "refuted" && (sevOrder[x.adjusted_severity] || 0) > (sevOrder[adj] || 0)) adj = x.adjusted_severity
    }
    return { ...f, status, adjusted_severity: adj, votes: v }
  })
))

const all = verified.filter(Boolean)
const confirmed = all.filter((f) => f.status === "confirmed")
const likely = all.filter((f) => f.status === "likely")
const refuted = all.filter((f) => f.status === "refuted")

const sevOrder = { critical: 4, high: 3, medium: 2, low: 1, none: 0 }
const sortSev = (arr) => arr.sort((a, b) => (sevOrder[b.adjusted_severity] || 0) - (sevOrder[a.adjusted_severity] || 0))

log(`Verification complete: ${confirmed.length} confirmed, ${likely.length} likely, ${refuted.length} refuted/dropped`)

return {
  stats: {
    raw: raw.length,
    unique: unique.length,
    confirmed: confirmed.length,
    likely: likely.length,
    refuted: refuted.length,
  },
  confirmed: sortSev(confirmed),
  likely: sortSev(likely),
  refuted: refuted.map((f) => ({ title: f.title, file: f.file, line: f.line, why: (f.votes.find((v) => v.verdict === "refuted") || {}).reasoning })),
}
