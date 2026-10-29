# The files distribution (D301, D302): CloudFront delivers the museums' files from their buckets with signed URLs,
# and the unavailable images and the generic placeholder from a small static bucket (delivery.tf, D195 to D200). Both
# roots use it. A root may also put the app behind it (app_origin: the personal root, D183); without one, the
# distribution serves only the files (the shared root, D293).

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

locals {
  name       = var.name
  account_id = var.account_id
  museums    = sort(keys(var.bucket_domains))
}
