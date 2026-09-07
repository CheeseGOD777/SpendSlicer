/* ─── Demo data for the landing page ───────────────────────────────────
   Sample data, not a live account. It is shaped exactly like the payloads
   the FastAPI backend serves, so the demo components are the same shape as
   the real pages.

   The account tells one story on purpose: a retail platform with an edge
   (CloudFront, ALB), an API tier (EC2, ECS), an async spine (SQS, SNS,
   Lambda), a data tier (RDS, OpenSearch, DynamoDB, ElastiCache), and the
   quiet ops services every real account carries. Two rows are deliberately
   awkward because real accounts are: a `ce:` service rollup that CUR cannot
   break down further, and a `ce-remainder:` line for the part of EC2 - Other
   that no single resource owns. A demo without them would be lying by
   omission.

   Every figure reconciles:

     12 daily buckets   = $10,693.09   the Cost Explorer total
     20 service rows   = $10,693.09
     25 named rows      = $7,393.34   attributed
     attributed + drift = $10,693.09
     each composition   = its own service row

   If you change a number, change the ones that depend on it. The asserts at
   the bottom will tell you in the console if you did not.
   ───────────────────────────────────────────────────────────────────── */

export const PROFILE = "meridian-retail-prod";
export const PERIOD = "mtd";

export const CE_TOTAL = 10693.09;
export const ATTRIBUTED = 7393.34;
export const DRIFT = 3299.75;

export const SUMMARY = {
  total_mtd: CE_TOTAL,
  total_prev: 10047.68,
  change_pct: 6.4,
  forecast: 26732.73,
  cost_basis_label: "Pre-credit gross",
};

/* Daily buckets for the month to date. Sum is the Cost Explorer total; the
   last day is deliberately part-billed, the way a month-to-date window is. */
export const TREND = [
  { month: "Sep 1",   Spend: 878.40 },
  { month: "Sep 2",   Spend: 902.15 },
  { month: "Sep 3",   Spend: 741.60 },
  { month: "Sep 4",   Spend: 715.30 },
  { month: "Sep 5",   Spend: 968.25 },
  { month: "Sep 6",   Spend: 1012.70 },
  { month: "Sep 7",   Spend: 823.05 },
  { month: "Sep 8",   Spend: 947.80 },
  { month: "Sep 9",   Spend: 1104.35 },
  { month: "Sep 10",  Spend: 986.40 },
  { month: "Sep 11",  Spend: 1035.90 },
  { month: "Sep 12",  Spend: 577.19 },
];

/* Service totals. Exact, the way Cost Explorer GetCostAndUsage returns them. */
export const SERVICES = [
  { name: "Amazon Elastic Compute Cloud - Compute", cost: 2998.77,  pct_of_total: 28.0,  change_pct: 11.4 },
  { name: "Amazon Relational Database Service",     cost: 2208.54,  pct_of_total: 20.7,  change_pct: -3.2 },
  { name: "Amazon OpenSearch Service",              cost: 1058.52,  pct_of_total: 9.9,   change_pct: 18.6 },
  { name: "Amazon Simple Storage Service",          cost: 887.80,   pct_of_total: 8.3,   change_pct: 6.8 },
  { name: "EC2 - Other",                            cost: 809.93,   pct_of_total: 7.6,   change_pct: 7.9 },
  { name: "Amazon ElastiCache",                     cost: 612.09,   pct_of_total: 5.7,   change_pct: 4.8 },
  { name: "AWS Lambda",                             cost: 475.72,   pct_of_total: 4.4,   change_pct: -8.1 },
  { name: "Amazon CloudFront",                      cost: 421.55,   pct_of_total: 3.9,   change_pct: 22.9 },
  { name: "Amazon Elastic Container Service",       cost: 366.90,   pct_of_total: 3.4,   change_pct: 14.2 },
  { name: "Amazon DynamoDB",                        cost: 288.14,   pct_of_total: 2.7,   change_pct: 2.4 },
  { name: "Elastic Load Balancing",                 cost: 244.73,   pct_of_total: 2.3,   change_pct: 0.6 },
  { name: "Amazon CloudWatch",                      cost: 168.42,   pct_of_total: 1.6,   change_pct: 9.7 },
  { name: "Amazon Simple Queue Service",            cost: 41.28,    pct_of_total: 0.4,   change_pct: 31.5 },
  { name: "Amazon API Gateway",                     cost: 27.85,    pct_of_total: 0.3,   change_pct: -2.8 },
  { name: "Amazon Simple Notification Service",     cost: 22.60,    pct_of_total: 0.2,   change_pct: 6.1 },
  { name: "AWS Secrets Manager",                    cost: 18.94,    pct_of_total: 0.2,   change_pct: 0.0 },
  { name: "Amazon EC2 Container Registry (ECR)",    cost: 14.73,    pct_of_total: 0.1,   change_pct: 12.4 },
  { name: "AWS X-Ray",                              cost: 11.06,    pct_of_total: 0.1,   change_pct: -4.4 },
  { name: "Amazon Route 53",                        cost: 9.40,     pct_of_total: 0.1,   change_pct: 0.0 },
  { name: "AWS Key Management Service",             cost: 6.12,     pct_of_total: 0.1,   change_pct: 1.8 },
];

/* Usage-type composition. This is the layer AWS gives you: a bucket priced
   by the hour, with no machine attached. It is the whole argument. */
export const COMPOSITION = {
  "Amazon Elastic Compute Cloud - Compute": {
    compute: 2802.35, storage: 0.00, "data-transfer": 196.42, network: 0.00, other: 0.00,
    usage_types: [
      { usage_type: "APS3-BoxUsage:m6g.xlarge",    bucket: "compute",        cost: 892.4400 },
      { usage_type: "APS3-BoxUsage:c6g.2xlarge",   bucket: "compute",        cost: 741.1900 },
      { usage_type: "APS3-BoxUsage:t4g.medium",    bucket: "compute",        cost: 468.3000 },
      { usage_type: "APS3-BoxUsage:r6g.large",     bucket: "compute",        cost: 411.8700 },
      { usage_type: "APS3-SpotUsage:c6g.xlarge",   bucket: "compute",        cost: 288.5500 },
      { usage_type: "APS3-DataTransfer-Out-Bytes", bucket: "data-transfer",  cost: 196.4200 },
    ],
  },
  "EC2 - Other": {
    compute: 0.00, storage: 457.67, "data-transfer": 0.00, network: 352.26, other: 0.00,
    usage_types: [
      { usage_type: "APS3-EBS:VolumeUsage.gp3",   bucket: "storage",        cost: 264.5100 },
      { usage_type: "APS3-NatGateway-Hours",      bucket: "network",        cost: 187.2000 },
      { usage_type: "APS3-NatGateway-Bytes",      bucket: "network",        cost: 143.6600 },
      { usage_type: "APS3-EBS:SnapshotUsage",     bucket: "storage",        cost: 118.9400 },
      { usage_type: "APS3-EBS:VolumeIOUsage.gp3", bucket: "storage",        cost: 74.2200 },
      { usage_type: "APS3-ElasticIP:IdleAddress", bucket: "network",        cost: 21.4000 },
    ],
  },
  "Amazon Relational Database Service": {
    compute: 1692.82, storage: 453.53, "data-transfer": 62.19, network: 0.00, other: 0.00,
    usage_types: [
      { usage_type: "APS3-InstanceUsage:db.r6g.xlarge", bucket: "compute",        cost: 1088.6000 },
      { usage_type: "APS3-InstanceUsage:db.r6g.large",  bucket: "compute",        cost: 604.2200 },
      { usage_type: "APS3-RDS:GP3-Storage",             bucket: "storage",        cost: 312.4800 },
      { usage_type: "APS3-RDS:ChargedBackupUsage",      bucket: "storage",        cost: 141.0500 },
      { usage_type: "APS3-DataTransfer-Regional-Bytes", bucket: "data-transfer",  cost: 62.1900 },
    ],
  },
  "Amazon OpenSearch Service": {
    compute: 920.60, storage: 137.92, "data-transfer": 0.00, network: 0.00, other: 0.00,
    usage_types: [
      { usage_type: "APS3-ESInstance:r6g.large.search", bucket: "compute",        cost: 618.4400 },
      { usage_type: "APS3-ESInstance:m6g.large.search", bucket: "compute",        cost: 302.1600 },
      { usage_type: "APS3-ES:GP3-Storage",              bucket: "storage",        cost: 96.3000 },
      { usage_type: "APS3-ES:UltraWarmUsage",           bucket: "storage",        cost: 41.6200 },
    ],
  },
  "AWS Lambda": {
    compute: 359.50, storage: 0.00, "data-transfer": 0.00, network: 0.00, other: 116.22,
    usage_types: [
      { usage_type: "APS3-Lambda-GB-Second",     bucket: "compute",        cost: 288.4100 },
      { usage_type: "APS3-Lambda-Request",       bucket: "other",          cost: 116.2200 },
      { usage_type: "APS3-Lambda-GB-Second-ARM", bucket: "compute",        cost: 71.0900 },
    ],
  },
  "Amazon Simple Storage Service": {
    compute: 0.00, storage: 674.74, "data-transfer": 142.66, network: 0.00, other: 70.40,
    usage_types: [
      { usage_type: "APS3-TimedStorage-ByteHrs",        bucket: "storage",        cost: 486.3000 },
      { usage_type: "APS3-TimedStorage-GlacierByteHrs", bucket: "storage",        cost: 188.4400 },
      { usage_type: "APS3-DataTransfer-Out-Bytes",      bucket: "data-transfer",  cost: 142.6600 },
      { usage_type: "APS3-Requests-Tier1",              bucket: "other",          cost: 48.2200 },
      { usage_type: "APS3-Requests-Tier2",              bucket: "other",          cost: 22.1800 },
    ],
  },
};

/* Named resources. This is the layer SpendSlicer adds, and the sum of it is
   exactly the attributed figure on the board. */
export const RESOURCES = [
  { name: "checkout-api-01",                      service: "Amazon Elastic Compute Cloud - Compute", resource_id: "i-0f3a9c2b71de4408a",                    cost: 892.44,   state: "running" },
  { name: "checkout-api-02",                      service: "Amazon Elastic Compute Cloud - Compute", resource_id: "i-0b7e14da9c3f2260d",                    cost: 741.19,   state: "running" },
  { name: "catalog-worker-03",                    service: "Amazon Elastic Compute Cloud - Compute", resource_id: "i-04c81fb37ae95d112",                    cost: 411.87,   state: "stopped" },
  { name: "orders-primary",                       service: "Amazon Relational Database Service",     resource_id: "db-MERIDIANORDERS01",                    cost: 1088.60,  state: "available" },
  { name: "orders-replica-1b",                    service: "Amazon Relational Database Service",     resource_id: "db-MERIDIANORDERSRR2",                   cost: 604.22,   state: "available" },
  { name: "catalog-search-prod",                  service: "Amazon OpenSearch Service",              resource_id: "catalog-search-prod",                    cost: 618.44,   state: null },
  { name: "meridian-product-media",               service: "Amazon Simple Storage Service",          resource_id: "meridian-product-media",                 cost: 486.30,   state: null },
  { name: "meridian-cloudtrail",                  service: "Amazon Simple Storage Service",          resource_id: "meridian-cloudtrail-820947116534",       cost: 188.44,   state: null },
  { name: "egress-nat-1a",                        service: "EC2 - Other",                            resource_id: "nat-0d92f4c8a17b3e650",                  cost: 330.86,   state: "available" },
  { name: "checkout-nat-eip-1a",                  service: "EC2 - Other",                            resource_id: "eipalloc-07be13d9c4a82f5e1",             cost: 21.40,    state: "associated" },
  { name: "EC2 - Other \u2014 unattributed remainder", service: "EC2 - Other",                            resource_id: "ce-remainder:EC2 - Other",               cost: 42.44,    state: null },
  { name: "shop.meridian.io",                     service: "Amazon CloudFront",                      resource_id: "E1QW7LXK4PZ9VN",                         cost: 421.55,   state: null },
  { name: "cart-service",                         service: "Amazon Elastic Container Service",       resource_id: "service/meridian-prod/cart-service",     cost: 366.90,   state: "ACTIVE" },
  { name: "cart-sessions",                        service: "Amazon DynamoDB",                        resource_id: "cart-sessions",                          cost: 288.14,   state: null },
  { name: "public-alb",                           service: "Elastic Load Balancing",                 resource_id: "app/public-alb/7c3d1ab99e40f2aa",        cost: 244.73,   state: null },
  { name: "payment-gateway",                      service: "AWS Lambda",                             resource_id: "payment-gateway",                        cost: 188.30,   state: null },
  { name: "inventory-sync",                       service: "AWS Lambda",                             resource_id: "inventory-sync",                         cost: 96.44,    state: null },
  { name: "webhook-dispatcher",                   service: "AWS Lambda",                             resource_id: "webhook-dispatcher",                     cost: 62.18,    state: null },
  { name: "order-receipt-mailer",                 service: "AWS Lambda",                             resource_id: "order-receipt-mailer",                   cost: 41.09,    state: null },
  { name: "order-events",                         service: "Amazon Simple Queue Service",            resource_id: "order-events",                           cost: 28.44,    state: null },
  { name: "order-notifications",                  service: "Amazon Simple Notification Service",     resource_id: "order-notifications",                    cost: 16.22,    state: null },
  { name: "Amazon CloudWatch",                    service: "Amazon CloudWatch",                      resource_id: "ce:Amazon CloudWatch",                   cost: 168.42,   state: null },
  { name: "AWS Secrets Manager",                  service: "AWS Secrets Manager",                    resource_id: "ce:AWS Secrets Manager",                 cost: 18.94,    state: null },
  { name: "Amazon EC2 Container Registry (ECR)",  service: "Amazon EC2 Container Registry (ECR)",    resource_id: "ce:Amazon EC2 Container Registry (ECR)", cost: 14.73,    state: null },
  { name: "AWS X-Ray",                            service: "AWS X-Ray",                              resource_id: "ce:AWS X-Ray",                           cost: 11.06,    state: null },
];

export const EXPLAIN_SERVICE = "Amazon Elastic Compute Cloud - Compute";

const round2 = (n) => Math.round(n * 100) / 100;
export const sum = (rows, key = "cost") => round2(rows.reduce((a, r) => a + Number(r[key] || 0), 0));

/* Guard rails. A demo that stops reconciling is worse than no demo, so say so
   loudly in development rather than shipping a page that argues against its
   own product. */
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
  SERVICES.forEach((s) => {
    const named = sum(RESOURCES.filter((r) => r.service === s.name));
    if (named - s.cost > 0.015) {
      console.error(`[demo data] ${s.name} over-attributed: ${named} > ${s.cost}`);
    }
  });
}
