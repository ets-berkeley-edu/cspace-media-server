variable "name" {
  description = "serena-<env_name>, the prefix of every resource's name."
  type        = string
}

variable "env_name" {
  description = "Environment name within the account."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "account_id" {
  description = "The AWS account."
  type        = string
}

variable "bucket_domains" {
  description = "museum => its bucket's regional domain name (modules/core)."
  type        = map(string)
}

variable "cdn_keys" {
  description = "true once ./serena aws has made the CloudFront signing key (D200): the public keys are read from the SSM parameter /serena-<env>/cloudfront-public-keys."
  type        = bool
}

variable "viewer_request_function_arn" {
  description = "The CloudFront Function run on every request: it removes /<museum> from a file's path (D195), and in the personal root applies the address rules too (D185, D307)."
  type        = string
}

variable "app_origin" {
  description = "The app behind the same distribution, through a VPC origin (the personal root, D183): the load balancer's address, the VPC origin's ID and how long to wait for an answer (D184). null: the distribution serves only the files."
  type = object({
    domain_name         = string
    vpc_origin_id       = string
    origin_read_timeout = number
  })
  default = null
}

variable "web_acl_arn" {
  description = "A CLOUDFRONT-scope web ACL on the distribution (D186); null: none."
  type        = string
  default     = null
}
