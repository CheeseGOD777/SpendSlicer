output "bucket" { value = aws_s3_bucket.cur.id }
output "prefix" { value = var.s3_prefix }
output "region" { value = aws_s3_bucket.cur.region }
