variable "bucket_name" {
  type        = string
  description = "S3 bucket that will receive the CUR Parquet exports. Must be globally unique."
}

variable "export_name" {
  type    = string
  default = "costsight-cur"
}

variable "s3_prefix" {
  type    = string
  default = "cur/"
}

variable "retention_days" {
  type    = number
  default = 400
}
