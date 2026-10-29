output "distribution_arn" {
  value = aws_cloudfront_distribution.main.arn
}

output "domain_name" {
  description = "The distribution's *.cloudfront.net address."
  value       = aws_cloudfront_distribution.main.domain_name
}

output "delivery" {
  description = "Whether the museums' files are delivered (a signing key exists, D200)."
  value       = local.delivery
}

output "cdn_key_ids" {
  description = "The trusted CloudFront public keys, name => key ID."
  value       = { for name, k in aws_cloudfront_public_key.cdn : name => k.id }
}

# For deploy/terraform/<root>/tests: terraform test reads a module's resources only through its outputs.
output "test" {
  value = {
    key_groups     = length(aws_cloudfront_key_group.cdn)
    default_origin = aws_cloudfront_distribution.main.default_cache_behavior[0].target_origin_id
    behavior_paths = [for b in aws_cloudfront_distribution.main.ordered_cache_behavior : b.path_pattern]
    signed_paths   = [for b in aws_cloudfront_distribution.main.ordered_cache_behavior : b.path_pattern if try(length(b.trusted_key_groups), 0) > 0]
    static_files   = keys(aws_s3_object.static)
  }
}
