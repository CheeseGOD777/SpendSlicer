# IAM permissions

CostSight is **strictly read-only**. It issues no `Create*`, `Put*`, `Update*`,
`Modify*`, `Delete*`, or `Terminate*` call anywhere in the codebase. The one
thing it writes is a local SQLite/DuckDB cache on your own disk.

The simplest option is the AWS-managed `ReadOnlyAccess` policy. If you would
rather grant only what is used, the policy below is the exact set.

## Least-privilege policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostAndUsage",
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ce:GetCostForecast"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Identity",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "iam:ListAccountAliases"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ResourceInventory",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeSnapshots",
        "ec2:DescribeAddresses",
        "ec2:DescribeTags",
        "rds:DescribeDBInstances",
        "rds:ListTagsForResource",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
        "elasticloadbalancing:DescribeTags",
        "lambda:ListFunctions",
        "lambda:ListTags",
        "dynamodb:ListTables",
        "dynamodb:DescribeTable",
        "dynamodb:ListTagsOfResource",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "s3:GetBucketTagging"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IdleDetection",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Pricing",
      "Effect": "Allow",
      "Action": [
        "pricing:GetProducts"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Budgets",
      "Effect": "Allow",
      "Action": [
        "budgets:ViewBudget",
        "budgets:DescribeBudgets"
      ],
      "Resource": "*"
    }
  ]
}
```

## What breaks without each permission

CostSight degrades feature by feature rather than failing outright. A missing
permission produces a warning banner on the affected panel; the rest keeps
working.

| Permission | Powers | Missing it means |
| --- | --- | --- |
| `ce:GetCostAndUsage` | Every cost figure | Nothing works. This one is mandatory. |
| `ce:GetCostForecast` | Month-end projection | Forecast tile is blank |
| `sts:GetCallerIdentity` | Resolving which account a profile points at | Profiles can't be validated; the dropdown is unusable |
| `iam:ListAccountAliases` | Friendly account names | Profiles show as bare 12-digit account IDs |
| `ec2:Describe*` | Instance/volume/EIP names, states, waste radar | EC2, EBS and EIP rows lose names and the waste radar goes quiet |
| `rds:Describe*`, `rds:ListTagsForResource` | RDS attribution | RDS shows as an unattributed service total |
| `elasticloadbalancing:Describe*` | Load balancer attribution and idle-ELB detection | ELB shows as an unattributed total |
| `lambda:ListFunctions`, `lambda:ListTags` | Lambda attribution | Lambda shows as an unattributed total |
| `dynamodb:*` (list/describe/tags) | DynamoDB attribution | DynamoDB shows as an unattributed total |
| `s3:ListAllMyBuckets`, `s3:GetBucketLocation` | Per-bucket attribution | S3 shows as an unattributed total |
| `s3:GetBucketTagging` | Bucket tags in the untagged audit | Buckets appear untagged even when they aren't |
| `s3:ListBucket`, `s3:GetObject` on the CUR bucket | CUR ingest (optional) | CUR warehouse can't sync; Cost Explorer path is unaffected |
| `cloudwatch:GetMetricStatistics` | Idle EC2/RDS/ELB detection | Idle detection is skipped |
| `pricing:GetProducts` | Live on-demand rates | Falls back to a built-in rate table, currently `ap-south-1` only |
| `budgets:ViewBudget` | Budget breach alerts | Budgets panel is empty |

## CUR warehouse (optional)

If you enable the CUR warehouse, the ingester additionally needs read access to
the bucket holding the Parquet exports — scoped to that bucket, not `*`:

```json
{
  "Sid": "CurIngest",
  "Effect": "Allow",
  "Action": ["s3:ListBucket", "s3:GetObject"],
  "Resource": [
    "arn:aws:s3:::YOUR-CUR-BUCKET",
    "arn:aws:s3:::YOUR-CUR-BUCKET/*"
  ]
}
```

## Cost Explorer is a paid API

`ce:*` calls bill **$0.01 each**, on the payer account. This is an AWS charge,
not something CostSight adds. Granting these permissions grants the ability to
spend money, which is why the app caches aggressively, reports spend per
response in the `X-CE-Calls-Spent` header, and shows a running session meter.

For the same reason, do not expose a CostSight instance on a network without
setting `COSTSIGHT_AUTH_TOKEN`.

## Multi-account setups

CostSight reads every profile in your AWS config, so the usual patterns work
without any extra support in the app:

- **Organizations** — point one profile at the management account. Cost
  Explorer returns costs for every linked account, and the UI can filter by
  `LINKED_ACCOUNT`.
- **Per-account roles** — define one profile per account with `role_arn` and
  `source_profile`; each appears separately in the dropdown.
- **SSO** — `sso_session` profiles work once `aws sso login` has been run.

Resource-level attribution (names, tags, idle detection) only covers the
account a given profile resolves to, since those `Describe*` calls are
per-account. Cost totals from a management account still cover the whole org.
