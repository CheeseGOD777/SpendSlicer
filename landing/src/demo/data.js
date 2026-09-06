/* ─── Demo data for the landing page ───────────────────────────────────
   Sample data, not a live account. It is shaped exactly like the payloads
   the FastAPI backend serves, so the demo components below are the same
   shape as the real pages.

   Every figure here reconciles, because a cost tool that shows a landing
   page whose numbers do not add up has argued against itself:

     12 daily buckets        = $11,124.39   the Cost Explorer total
     8 service rows          = $11,124.39
     10 named resources      = $ 5,381.38   attributed
     attributed + drift      = $11,124.39
     EC2 usage-type buckets  = $ 4,182.41   the EC2 service row

   If you change a number, change the ones that depend on it. The asserts
   at the bottom of this file will tell you in the console if you did not.
   ───────────────────────────────────────────────────────────────────── */

export const PROFILE = "acme-platform-prod";
export const PERIOD = "mtd";

export const CE_TOTAL = 11124.39;
export const ATTRIBUTED = 5381.38;
export const DRIFT = 5743.01;

export const SUMMARY = {
  total_mtd: CE_TOTAL,
  total_prev: 10455.25,
  change_pct: 6.4,
  forecast: 27810.98,
  cost_basis_label: "Pre-credit gross",
};

/* Daily buckets for the month to date. Sum is the Cost Explorer total.
   TrendBars reads its X axis from `month`, so the key is not negotiable. */
export const TREND = [
  { month: "Sep 1", Spend: 878.40 },
  { month: "Sep 2", Spend: 902.15 },
  { month: "Sep 3", Spend: 741.60 },
  { month: "Sep 4", Spend: 715.30 },
  { month: "Sep 5", Spend: 968.25 },
  { month: "Sep 6", Spend: 1012.70 },
  { month: "Sep 7", Spend: 823.05 },
  { month: "Sep 8", Spend: 947.80 },
  { month: "Sep 9", Spend: 1104.35 },
  { month: "Sep 10", Spend: 986.40 },
  { month: "Sep 11", Spend: 1035.90 },
  { month: "Sep 12", Spend: 1008.49 },
];

/* Service totals. Exact, the way Cost Explorer GetCostAndUsage returns them. */
export const SERVICES = [
  { name: "Amazon Elastic Compute Cloud - Compute", cost: 4182.41, pct_of_total: 37.6, change_pct: 11.4 },
  { name: "Amazon Relational Database Service",     cost: 2914.08, pct_of_total: 26.2, change_pct: -3.2 },
  { name: "Amazon Simple Storage Service",          cost: 1466.73, pct_of_total: 13.2, change_pct: 6.8 },
  { name: "Amazon CloudFront",                      cost: 812.55,  pct_of_total: 7.3,  change_pct: 22.9 },
  { name: "AWS Lambda",                             cost: 604.19,  pct_of_total: 5.4,  change_pct: -8.1 },
  { name: "Amazon DynamoDB",                        cost: 511.36,  pct_of_total: 4.6,  change_pct: 2.4 },
  { name: "Elastic Load Balancing",                 cost: 388.90,  pct_of_total: 3.5,  change_pct: 0.6 },
  { name: "Amazon CloudWatch",                      cost: 244.17,  pct_of_total: 2.2,  change_pct: null },
];

/* Usage-type composition. This is the layer AWS gives you: a bucket priced
   by the hour, with no machine attached to it. It is the whole argument. */
export const COMPOSITION = {
  "Amazon Elastic Compute Cloud - Compute": {
    compute: 2611.40,
    storage: 903.21,
    "data-transfer": 402.90,
    network: 188.60,
    other: 76.30,
    usage_types: [
      { usage_type: "APS3-BoxUsage:t4g.small",      bucket: "compute",       cost: 884.2140 },
      { usage_type: "APS3-BoxUsage:m6g.xlarge",     bucket: "compute",       cost: 712.0602 },
      { usage_type: "APS3-BoxUsage:c6g.2xlarge",    bucket: "compute",       cost: 601.9310 },
      { usage_type: "APS3-EBS:VolumeUsage.gp3",     bucket: "storage",       cost: 480.1188 },
      { usage_type: "APS3-BoxUsage:r6g.large",      bucket: "compute",       cost: 413.1948 },
      { usage_type: "APS3-DataTransfer-Out-Bytes",  bucket: "data-transfer", cost: 402.9044 },
      { usage_type: "APS3-EBS:SnapshotUsage",       bucket: "storage",       cost: 226.4471 },
      { usage_type: "APS3-EBS:VolumeIOUsage.gp3",   bucket: "storage",       cost: 196.6402 },
      { usage_type: "APS3-NatGateway-Hours",        bucket: "network",       cost: 188.6019 },
      { usage_type: "APS3-CW:MetricMonitorUsage",   bucket: "other",         cost: 76.2976 },
    ],
  },
  "Amazon Relational Database Service": {
    compute: 2088.44, storage: 611.32, "data-transfer": 118.05, network: 0, other: 96.27,
    usage_types: [
      { usage_type: "APS3-InstanceUsage:db.r6g.xlarge", bucket: "compute",       cost: 1244.3020 },
      { usage_type: "APS3-InstanceUsage:db.r6g.large",  bucket: "compute",       cost: 844.1380 },
      { usage_type: "APS3-RDS:GP2-Storage",             bucket: "storage",       cost: 424.9100 },
      { usage_type: "APS3-RDS:ChargedBackupUsage",      bucket: "storage",       cost: 186.4100 },
      { usage_type: "APS3-DataTransfer-Regional-Bytes", bucket: "data-transfer", cost: 118.0500 },
      { usage_type: "APS3-RDS:PIOPS",                   bucket: "other",         cost: 96.2700 },
    ],
  },
  "Amazon Simple Storage Service": {
    compute: 0, storage: 1104.62, "data-transfer": 288.44, network: 0, other: 73.67,
    usage_types: [
      { usage_type: "APS3-TimedStorage-ByteHrs",   bucket: "storage",       cost: 862.5500 },
      { usage_type: "APS3-DataTransfer-Out-Bytes", bucket: "data-transfer", cost: 288.4400 },
      { usage_type: "APS3-TimedStorage-GlacierByteHrs", bucket: "storage",  cost: 242.0700 },
      { usage_type: "APS3-Requests-Tier1",         bucket: "other",         cost: 73.6700 },
    ],
  },
};

/* Named resources. This is the layer SpendSlicer adds, and the sum of it
   is exactly the attributed figure on the board. */
export const RESOURCES = [
  { name: "prod-api-green-03",   service: "Amazon Elastic Compute Cloud - Compute", resource_id: "i-0a91f3c77be21d4e8",            cost: 918.44, state: "running" },
  { name: "orders-primary",      service: "Amazon Relational Database Service",     resource_id: "db-PRODUCTIONCLUSTER01",         cost: 844.10, state: "available" },
  { name: "prod-api-green-01",   service: "Amazon Elastic Compute Cloud - Compute", resource_id: "i-0c4471aa9de10b552",            cost: 712.06, state: "running" },
  { name: "cx-media-archive",    service: "Amazon Simple Storage Service",          resource_id: "cx-media-archive-ap-south-1",    cost: 604.88, state: null },
  { name: "batch-worker-lg-02",  service: "Amazon Elastic Compute Cloud - Compute", resource_id: "i-0be22d9f1c7a4e38b",            cost: 512.73, state: "stopped" },
  { name: "analytics-replica",   service: "Amazon Relational Database Service",     resource_id: "db-ANALYTICSREPLICA02",          cost: 488.19, state: "available" },
  { name: "cdn.spendslicer.dev", service: "Amazon CloudFront",                      resource_id: "E2QW1LXH9PZ7VN",                cost: 401.62, state: null },
  { name: "cx-eventlog-raw",     service: "Amazon Simple Storage Service",          resource_id: "cx-eventlog-raw",                cost: 366.05, state: null },
  { name: "sessions-prod",       service: "Amazon DynamoDB",                        resource_id: "sessions-prod",                  cost: 288.41, state: null },
  { name: "prod-alb",            service: "Elastic Load Balancing",                 resource_id: "app/prod-alb/9f2c1ab77e40d3aa",  cost: 244.90, state: null },
];

/* The three EC2 usage-type rows above, next to the three EC2 machines that
   actually incurred them. The two columns of the attribution explainer. */
export const EXPLAIN_SERVICE = "Amazon Elastic Compute Cloud - Compute";

const round2 = (n) => Math.round(n * 100) / 100;
export const sum = (rows, key = "cost") => round2(rows.reduce((a, r) => a + Number(r[key] || 0), 0));

/* Guard rails. A demo that stops reconciling is worse than no demo, so say
   so loudly in development rather than shipping a page that argues against
   its own product. */
if (import.meta.env?.DEV) {
  const check = (label, got, want) => {
    if (Math.abs(got - want) > 0.015) {
      console.error(`[demo data] ${label} is ${got}, expected ${want}`);
    }
  };
  check("trend total", sum(TREND, "Spend"), CE_TOTAL);
  check("service total", sum(SERVICES), CE_TOTAL);
  check("resource total", sum(RESOURCES), ATTRIBUTED);
  check("attributed + drift", round2(ATTRIBUTED + DRIFT), CE_TOTAL);
  Object.entries(COMPOSITION).forEach(([name, b]) => {
    const svc = SERVICES.find((s) => s.name === name);
    const buckets = round2(b.compute + b.storage + b["data-transfer"] + b.network + b.other);
    check(`${name} buckets`, buckets, svc.cost);
    check(`${name} usage types`, sum(b.usage_types), svc.cost);
  });
}
