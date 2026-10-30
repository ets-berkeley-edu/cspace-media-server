output "web_acl_arn" {
  value = aws_wafv2_web_acl.main.arn
}

# For deploy/terraform/<root>/tests: terraform test reads a module's resources only through its outputs.
output "test" {
  value = {
    scope      = aws_wafv2_web_acl.main.scope
    rule_names = [for r in aws_wafv2_web_acl.main.rule : r.name]
  }
}
