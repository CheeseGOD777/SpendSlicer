# CUR Terraform

Creates an S3 bucket and a Cost and Usage Report 2.0 (Data Exports) definition that
delivers daily Parquet line-items into the bucket.

## Apply

```bash
cd iac/cur
terraform init
terraform apply \
  -var="bucket_name=costsight-cur-<your-account-id>-<region>"
```

First export arrives within 24h. Once it does, run:

```bash
costsight cur ingest \
  --bucket "$(terraform output -raw bucket)" \
  --prefix "$(terraform output -raw prefix)"
```

## Destroy

```bash
terraform destroy
```

S3 storage cost for a small account is well under $0.01/month.
