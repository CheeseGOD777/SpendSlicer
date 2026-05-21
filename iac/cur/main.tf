terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.40" }
  }
}

# CUR / Data Exports API lives in us-east-1 regardless of workload region
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "cur" {
  bucket        = var.bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "cur" {
  bucket = aws_s3_bucket.cur.id
  versioning_configuration { status = "Disabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "cur" {
  bucket = aws_s3_bucket.cur.id
  rule {
    id     = "expire-old-cur"
    status = "Enabled"
    filter {}
    expiration { days = var.retention_days }
  }
}

data "aws_iam_policy_document" "cur_bucket" {
  statement {
    sid     = "AllowBillingPut"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    principals {
      type        = "Service"
      identifiers = ["billingreports.amazonaws.com"]
    }
    resources = ["${aws_s3_bucket.cur.arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
  statement {
    sid     = "AllowBillingList"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl", "s3:GetBucketPolicy"]
    principals {
      type        = "Service"
      identifiers = ["billingreports.amazonaws.com"]
    }
    resources = [aws_s3_bucket.cur.arn]
  }
}

resource "aws_s3_bucket_policy" "cur" {
  bucket = aws_s3_bucket.cur.id
  policy = data.aws_iam_policy_document.cur_bucket.json
}

# CUR 2.0 / Data Exports — Parquet, daily granularity, with resource IDs + tags.
resource "aws_bcmdataexports_export" "cur" {
  provider = aws.us_east_1
  export {
    name = var.export_name
    data_query {
      query_statement = "SELECT * FROM COST_AND_USAGE_REPORT"
      table_configurations = {
        COST_AND_USAGE_REPORT = {
          TIME_GRANULARITY                      = "DAILY"
          INCLUDE_RESOURCES                     = "TRUE"
          INCLUDE_SPLIT_COST_ALLOCATION_DATA    = "FALSE"
          INCLUDE_MANUAL_DISCOUNT_COMPATIBILITY = "FALSE"
        }
      }
    }
    destination_configurations {
      s3_destination {
        s3_bucket = aws_s3_bucket.cur.id
        s3_prefix = var.s3_prefix
        s3_region = aws_s3_bucket.cur.region
        s3_output_configurations {
          overwrite   = "OVERWRITE_REPORT"
          format      = "PARQUET"
          compression = "PARQUET"
          output_type = "CUSTOM"
        }
      }
    }
    refresh_cadence { frequency = "SYNCHRONOUS" }
  }
}
