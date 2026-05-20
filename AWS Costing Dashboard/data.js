// data.js — mock AWS FinOps data for the prototype

window.DATA = (() => {
  const profiles = [
    { id: 'prod-main',  alias: 'prod-main',  account: '923847102837' },
    { id: 'staging',    alias: 'staging',    account: '402938716203' },
    { id: 'dev-sandbox',alias: 'dev-sandbox',account: '109283746501' },
    { id: 'data-pipeline', alias: 'data-pipeline', account: '781029384756' },
  ];

  const periods = [
    { id: 'mtd',        label: 'mtd' },
    { id: 'last_month', label: 'last_month' },
    { id: '30d',        label: '30d' },
    { id: '3m',         label: '3m' },
    { id: '6m',         label: '6m' },
    { id: '12m',        label: '12m' },
  ];

  // KPI top row (period spend etc.) - prod-main, MTD
  const kpis = {
    spend:    { value: 184_392.47, delta: -8.4,  spark: [60,62,58,55,57,60,52,48,51,49,46,44,41,38] },
    previous: { value: 201_287.10, delta:  12.1, spark: [44,46,50,52,55,53,58,60,61,63,65,62,68,72] },
    forecast: { value: 287_950.00, delta:  +3.2, spark: [44,48,50,53,55,58,62,65,69,72,75,77,80,82] },
    topSvc:   { value: 'Amazon EC2', share: 38.2, cost: 70_432.18, delta: -4.1 },
  };

  // 6-month stacked trend  (oldest -> newest)
  const months = ['Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May'];
  const trend6m = months.map((m, i) => {
    // base shape — slight rise & then dip
    const k = [0.85, 0.92, 1.05, 1.12, 1.18, 0.94][i];
    return {
      month: m,
      EC2:        Math.round(62_000 * k),
      RDS:        Math.round(31_500 * k),
      S3:         Math.round(18_400 * k),
      Lambda:     Math.round( 9_800 * k),
      CloudFront: Math.round( 7_200 * k),
      Other:      Math.round(22_300 * k),
    };
  });

  // Top services
  const services = [
    { name: 'Amazon EC2',         key: 'EC2',         cost: 70_432.18, share: 38.2, vsPrior: -4.1, mom: [62000, 64500, 68200, 71300, 72100, 70432] },
    { name: 'Amazon RDS',         key: 'RDS',         cost: 31_487.92, share: 17.1, vsPrior:  6.3, mom: [29000, 30100, 31200, 31800, 30900, 31488] },
    { name: 'Amazon S3',          key: 'S3',          cost: 18_204.10, share:  9.9, vsPrior:  2.1, mom: [17500, 17800, 18100, 18300, 18000, 18204] },
    { name: 'AWS Lambda',         key: 'Lambda',      cost:  9_812.45, share:  5.3, vsPrior: 18.7, mom: [ 7600,  8100,  8500,  9100,  9400,  9812] },
    { name: 'Amazon CloudFront',  key: 'CloudFront',  cost:  7_223.50, share:  3.9, vsPrior: -1.2, mom: [ 7100,  7200,  7400,  7350,  7280,  7224] },
    { name: 'Elastic Load Balancing', key: 'ELB',     cost:  6_104.66, share:  3.3, vsPrior:  3.5, mom: [ 5800,  5900,  6000,  6050,  6080,  6105] },
    { name: 'Amazon EBS',         key: 'EBS',         cost:  5_287.31, share:  2.9, vsPrior: -0.8, mom: [ 5300,  5320,  5310,  5290,  5305,  5287] },
    { name: 'Amazon DynamoDB',    key: 'DynamoDB',    cost:  4_602.78, share:  2.5, vsPrior: 11.4, mom: [ 3900,  4100,  4250,  4400,  4500,  4603] },
    { name: 'Amazon ECS',         key: 'ECS',         cost:  3_881.20, share:  2.1, vsPrior:  4.2, mom: [ 3500,  3650,  3750,  3800,  3850,  3881] },
    { name: 'Amazon CloudWatch',  key: 'CloudWatch',  cost:  3_204.55, share:  1.7, vsPrior:  7.8, mom: [ 2800,  2950,  3050,  3100,  3170,  3205] },
    { name: 'Amazon Route 53',    key: 'Route53',     cost:  1_087.40, share:  0.6, vsPrior:  0.4, mom: [ 1050,  1060,  1070,  1080,  1085,  1087] },
    { name: 'Amazon EKS',         key: 'EKS',         cost:  2_487.95, share:  1.4, vsPrior:  9.1, mom: [ 2200,  2280,  2350,  2400,  2450,  2488] },
    { name: 'Amazon SQS',         key: 'SQS',         cost:    402.16, share:  0.2, vsPrior: -3.0, mom: [  410,   415,   420,   408,   406,   402] },
    { name: 'Amazon SNS',         key: 'SNS',         cost:    287.04, share:  0.2, vsPrior:  1.1, mom: [  280,   283,   285,   286,   286,   287] },
    { name: 'Amazon ElastiCache', key: 'ElastiCache', cost:    981.74, share:  0.5, vsPrior:  5.2, mom: [  890,   920,   940,   960,   970,   982] },
    { name: 'Elastic Beanstalk',  key: 'EB',          cost:    412.85, share:  0.2, vsPrior: -7.4, mom: [  450,   445,   430,   425,   418,   413] },
  ];

  // Resources mega table
  const resources = [
    // EC2
    { svc:'EC2', name:'api-gateway-prod-01',           id:'i-0a4b7c2e9f31d2c84', type:'On-Demand · m6i.4xlarge',  state:'running',    hours:744,  cost: 1_487.21, tags:{env:'production',team:'platform'} },
    { svc:'EC2', name:'auth-service-cluster-a',        id:'i-0192cf5481ad7c602', type:'Spot · c6i.2xlarge',       state:'running',    hours:744,  cost:   621.40, tags:{env:'production',team:'identity'} },
    { svc:'EC2', name:'ml-training-gpu-west',          id:'i-087fa3c1e289be4a3', type:'On-Demand · p3.8xlarge',   state:'running',    hours: 312, cost: 3_184.55, tags:{env:'production',team:'ml-research'} },
    { svc:'EC2', name:'staging-web-01',                id:'i-04ab123fc098e2c91', type:'Reserved · m6i.large',     state:'running',    hours:744,  cost:    63.78, tags:{env:'staging',team:'platform'} },
    { svc:'EC2', name:'bastion-host-public',           id:'i-0c1f29384d09a72e1', type:'On-Demand · t3.micro',     state:'running',    hours:744,  cost:     7.62, tags:{env:'production',team:'devops'} },
    { svc:'EC2', name:'jenkins-build-runner-03',       id:'i-0fae29b1c40d8e3f7', type:'Spot · c6i.4xlarge',       state:'stopped',    hours:182,  cost:   154.29, tags:{env:'ci',team:'devops'} },
    { svc:'EC2', name:'legacy-monolith-prod',          id:'i-09a82d3c4b5e6f721', type:'On-Demand · r5.4xlarge',   state:'running',    hours:744,  cost: 2_287.04, tags:{env:'production',team:'core'} },
    // RDS
    { svc:'RDS', name:'orders-primary-pg',             id:'orders-prod-1q9xz7', type:'Aurora PostgreSQL · db.r6g.4xlarge', state:'running', hours:744, cost: 4_287.95, tags:{env:'production',team:'commerce'} },
    { svc:'RDS', name:'orders-replica-eu',             id:'orders-replica-3kf', type:'Aurora PostgreSQL · db.r6g.2xlarge', state:'running', hours:744, cost: 2_143.97, tags:{env:'production',team:'commerce'} },
    { svc:'RDS', name:'analytics-warehouse-pg',        id:'analytics-warehous', type:'PostgreSQL 15 · db.m6i.xlarge',      state:'running', hours:744, cost:   698.32, tags:{env:'production',team:'data'} },
    { svc:'RDS', name:'session-cache-mysql',           id:'session-cache-mysq', type:'MySQL 8 · db.r6g.large',             state:'running', hours:744, cost:   312.40, tags:{env:'production',team:'identity'} },
    // S3
    { svc:'S3',  name:'cl-prod-customer-uploads',      id:'cl-prod-customer-uploads', type:'Standard · 142 TB', state:'running', hours:744, cost: 3_287.40, tags:{env:'production',team:'commerce'} },
    { svc:'S3',  name:'cl-prod-event-logs',            id:'cl-prod-event-logs',       type:'Intelligent-Tiering · 287 TB', state:'running', hours:744, cost: 2_104.55, tags:{env:'production',team:'data'} },
    { svc:'S3',  name:'cl-prod-cdn-static',            id:'cl-prod-cdn-static',       type:'Standard · 28 TB', state:'running', hours:744, cost:   612.18, tags:{env:'production',team:'web'} },
    { svc:'S3',  name:'cl-backup-archive',             id:'cl-backup-archive',        type:'Glacier Deep · 1.4 PB', state:'running', hours:744, cost:   847.99, tags:{env:'production',team:'platform'} },
    // Lambda
    { svc:'Lambda', name:'image-resize-worker',        id:'image-resize-worker',      type:'Node.js 20 · 1024 MB', state:'running', hours:744, cost: 1_287.40, tags:{env:'production',team:'web'} },
    { svc:'Lambda', name:'webhook-dispatcher',         id:'webhook-dispatcher',       type:'Node.js 20 · 512 MB',  state:'running', hours:744, cost:   687.32, tags:{env:'production',team:'commerce'} },
    { svc:'Lambda', name:'log-shipper-cloudwatch',     id:'log-shipper-cloudwatch',   type:'Python 3.12 · 256 MB', state:'running', hours:744, cost:   424.68, tags:{env:'production',team:'platform'} },
    // CloudFront
    { svc:'CloudFront', name:'cdn-prod-edge',          id:'E2QWXY3JK48LZP',            type:'Web Distribution · 14 TB egress', state:'running', hours:744, cost: 1_882.40, tags:{env:'production',team:'web'} },
    { svc:'CloudFront', name:'cdn-marketing-edge',     id:'E1ABC9D8XK24LM',            type:'Web Distribution · 4 TB egress',  state:'running', hours:744, cost:   612.10, tags:{env:'production',team:'marketing'} },
    // EBS
    { svc:'EBS', name:'vol-ml-training-data',          id:'vol-094f3acdc12e8b6f0',    type:'gp3 · 4 TB', state:'running', hours:744, cost:   384.91, tags:{env:'production',team:'ml-research'} },
    { svc:'EBS', name:'vol-orphan-snapshot-legacy',    id:'vol-0a7c1d8b39f4e2af1',    type:'gp2 · 1 TB',  state:'stopped', hours:744, cost:    87.20, tags:{} },
    // ELB
    { svc:'ELB', name:'alb-public-api',                id:'app/api-prod/d1b3c4f5e6a7b8c9', type:'Application LB · 21 LCU', state:'running', hours:744, cost:   312.74, tags:{env:'production',team:'platform'} },
    { svc:'ELB', name:'alb-internal-services',         id:'app/internal/9f8e7d6c5b4a32', type:'Application LB · 14 LCU', state:'running', hours:744, cost:   208.32, tags:{env:'production',team:'platform'} },
    // DynamoDB
    { svc:'DynamoDB', name:'orders-events-stream',     id:'orders-events-stream',     type:'On-Demand · 412M items', state:'running', hours:744, cost:   847.21, tags:{env:'production',team:'commerce'} },
    { svc:'DynamoDB', name:'sessions-active',          id:'sessions-active',          type:'On-Demand · 8M items',   state:'running', hours:744, cost:   287.40, tags:{env:'production',team:'identity'} },
    // ECS
    { svc:'ECS', name:'orders-svc-cluster',            id:'orders-svc-cluster',       type:'Fargate · 12 tasks', state:'running', hours:744, cost: 1_104.55, tags:{env:'production',team:'commerce'} },
    // CloudWatch
    { svc:'CloudWatch', name:'logs-app-ingestion',     id:'logs-app-ingestion',       type:'Logs · 84 GB/d', state:'running', hours:744, cost:   621.40, tags:{env:'production',team:'platform'} },
    // Route 53
    { svc:'Route53', name:'cloudledger.io',            id:'Z2QWXY3JK48LZP1',          type:'Hosted Zone · 14 records', state:'running', hours:744, cost:    12.40, tags:{env:'production',team:'platform'} },
    // EKS
    { svc:'EKS', name:'platform-prod-eks',             id:'platform-prod-eks',        type:'1.29 · 4 nodes', state:'running', hours:744, cost: 1_287.40, tags:{env:'production',team:'platform'} },
    // ElastiCache
    { svc:'ElastiCache', name:'redis-session-store',   id:'redis-session-store-0',    type:'Redis · cache.r6g.large', state:'running', hours:744, cost:   312.40, tags:{env:'production',team:'identity'} },
    // Idle / waste
    { svc:'EC2', name:'forgotten-test-instance',       id:'i-0fa72c9d8e1b4ac35', type:'On-Demand · m5.2xlarge',   state:'running',    hours:744,  cost:   281.04, tags:{env:'dev'} },
    { svc:'RDS', name:'snapshot-old-test-db',          id:'snap-old-test-db-q', type:'PostgreSQL · db.t3.medium', state:'stopped', hours:744, cost:    52.18, tags:{} },
  ];

  // Daily trend (90 days)
  const dailyTrend = (() => {
    const days = 90;
    const arr = [];
    let base = 5200;
    for (let i = 0; i < days; i++) {
      const wave = Math.sin(i/6) * 600;
      const spike = (i === 21 || i === 42 || i === 67) ? 1800 : 0;
      const drift = i * 12;
      const noise = (Math.sin(i * 11.7) + Math.cos(i * 4.3)) * 220;
      arr.push(Math.max(1500, Math.round(base + wave + spike + drift + noise)));
    }
    return arr;
  })();

  // 12-month trend table
  const trend12m = [
    { period:'2024-06', cost: 142_104.20, vsPrior: null },
    { period:'2024-07', cost: 148_293.50, vsPrior:  4.36 },
    { period:'2024-08', cost: 161_240.10, vsPrior:  8.73 },
    { period:'2024-09', cost: 155_812.30, vsPrior: -3.37 },
    { period:'2024-10', cost: 168_437.18, vsPrior:  8.10 },
    { period:'2024-11', cost: 174_209.55, vsPrior:  3.42 },
    { period:'2024-12', cost: 184_120.40, vsPrior:  5.69 },
    { period:'2025-01', cost: 201_287.10, vsPrior:  9.32 },
    { period:'2025-02', cost: 198_412.93, vsPrior: -1.43 },
    { period:'2025-03', cost: 213_487.55, vsPrior:  7.60 },
    { period:'2025-04', cost: 224_198.30, vsPrior:  5.02 },
    { period:'2025-05', cost: 184_392.47, vsPrior:-17.76 }, // MTD partial
  ];

  // Audit: Idle resources
  const idle = [
    { svc:'EC2',     id:'i-0fa72c9d8e1b4ac35', name:'forgotten-test-instance',  reason:'CPU 0.4% avg · 14 days',    waste: 281.04, env:'dev' },
    { svc:'EC2',     id:'i-0792d3a14e8c0b6f5', name:'old-cron-runner',          reason:'No network egress · 21 d',  waste: 142.18, env:'production' },
    { svc:'RDS',     id:'analytics-stage-old', name:'analytics-stage-old',      reason:'0 connections · 30 days',   waste: 312.40, env:'staging' },
    { svc:'EBS',     id:'vol-0a7c1d8b39f4e2af1', name:'vol-orphan-snapshot-legacy', reason:'Unattached · 47 days', waste:  87.20, env:'-' },
    { svc:'EBS',     id:'vol-09e2d4f8c6a1b7e30', name:'vol-old-jenkins',         reason:'Unattached · 92 days',     waste: 124.55, env:'-' },
    { svc:'ELB',     id:'app/legacy-svc/3c4d5e6f7', name:'alb-legacy-frontend', reason:'0 requests · 14 days',      waste: 156.30, env:'production' },
    { svc:'CloudFront', id:'E9XY8WZ7K48LZP', name:'cdn-old-marketing-2022',     reason:'0 requests · 60 days',      waste:  47.62, env:'production' },
    { svc:'Lambda',  id:'lambda-deprecated-cron', name:'deprecated-cron-fn',    reason:'0 invocations · 30 days',   waste:  18.40, env:'production' },
    { svc:'EKS',     id:'eks-staging-ml-old', name:'eks-staging-ml-old',        reason:'1 pod · 30 days',           waste: 184.92, env:'staging' },
  ];

  // Untagged
  const untagged = [
    { svc:'EC2', id:'i-0fae29b1c40d8e3f7', name:'jenkins-build-runner-03', missing:['Owner','Environment'], cost: 154.29 },
    { svc:'S3',  id:'logs-temp-bucket-q1', name:'logs-temp-bucket-q1',     missing:['Owner','CostCenter'],  cost:  47.20 },
    { svc:'EBS', id:'vol-0a7c1d8b39f4e2af1', name:'vol-orphan-snapshot-legacy', missing:['Owner','Environment','CostCenter'], cost: 87.20 },
    { svc:'RDS', id:'analytics-stage-old', name:'analytics-stage-old',     missing:['Owner','CostCenter'],  cost: 312.40 },
    { svc:'EC2', id:'i-0792d3a14e8c0b6f5', name:'old-cron-runner',         missing:['Owner','Environment'], cost: 142.18 },
    { svc:'CloudFront', id:'E1A2B3C4D5E6F7', name:'cdn-experimental-edge', missing:['Owner','Environment','CostCenter'], cost: 88.40 },
    { svc:'Lambda', id:'lambda-untagged-test', name:'lambda-untagged-test', missing:['Owner','Environment'], cost: 4.20 },
  ];

  // Budgets
  const budgets = [
    { name:'Production Spend',  scope:'env=production', spent: 154_211.20, limit: 175_000.00 },
    { name:'Data Team',         scope:'team=data',      spent:  18_421.40, limit:  22_000.00 },
    { name:'ML Research',       scope:'team=ml-research', spent: 32_104.55, limit: 28_000.00 },
    { name:'Non-production',    scope:'env in (staging,dev,ci)', spent: 11_872.30, limit: 18_000.00 },
  ];

  // Settings
  const reconciliation = {
    attributed: 182_184.55,
    ceTotal:    184_392.47,
    drift:        2_207.92,
    driftPct:        1.20,
  };

  return {
    profiles, periods, kpis, months, trend6m, services, resources,
    dailyTrend, trend12m, idle, untagged, budgets, reconciliation
  };
})();
