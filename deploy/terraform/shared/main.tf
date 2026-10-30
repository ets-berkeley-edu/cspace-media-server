# The shared modules (D302), given this root's network, load balancer and function.

module "core" {
  source = "../modules/core"

  name               = local.name
  env_name           = var.env_name
  region             = var.region
  account_id         = local.account_id
  partition          = local.partition
  tenants            = var.tenants
  env_label          = var.env_label
  image_uri          = var.image_uri
  running            = var.running
  protect_data       = var.protect_data
  alert_email        = var.alert_email
  log_retention_days = var.log_retention_days
  web_count          = var.web_count
  web_cpu            = var.web_cpu
  web_memory         = var.web_memory
  web_disk_gib       = var.web_disk_gib
  worker_cpu         = var.worker_cpu
  worker_memory      = var.worker_memory

  # The tasks in Ops's private subnets, out through its NAT gateway (D303). The target group from the listener, so
  # the app's service is created after it.
  subnet_ids               = [for s in data.aws_subnet.app : s.id]
  assign_public_ip         = false
  web_security_group_id    = aws_security_group.web.id
  worker_security_group_id = aws_security_group.worker.id
  target_group_arn         = aws_lb_listener.https.default_action[0].target_group_arn
  load_balancer_arn_suffix = aws_lb.main.arn_suffix
  target_group_arn_suffix  = aws_lb_target_group.web.arn_suffix

  distribution_arn = module.files.distribution_arn
  cdn_base_url     = "https://${module.files.domain_name}"
  delivery         = module.files.delivery
}

# The files and the unavailable images only (D293, D301): no app origin, no address rule (D307), no web ACL (D292).
module "files" {
  source = "../modules/files"

  name                        = local.name
  env_name                    = var.env_name
  region                      = var.region
  account_id                  = local.account_id
  bucket_domains              = module.core.bucket_domains
  cdn_keys                    = var.cdn_keys
  viewer_request_function_arn = aws_cloudfront_function.files.arn
}

# The regional web ACL on the load balancer (D292), with the rate limit by X-Forwarded-For for the Apache hosts (D306).
module "waf" {
  source = "../modules/waf"
  count  = var.waf ? 1 : 0

  name               = local.name
  account_id         = local.account_id
  partition          = local.partition
  scope              = "REGIONAL"
  rate_limit         = var.waf_rate_limit
  apache_cidrs       = var.apache_cidrs
  log_retention_days = var.log_retention_days
}

resource "aws_wafv2_web_acl_association" "alb" {
  count        = var.waf ? 1 : 0
  resource_arn = aws_lb.main.arn
  web_acl_arn  = module.waf[0].web_acl_arn
}

# A simulator museum (D300): stage 2's first phase, and later front-door changes in QA.
module "simulator" {
  source = "../modules/simulator"
  count  = var.simulated_cspace ? 1 : 0

  name               = local.name
  env_name           = var.env_name
  region             = var.region
  account_id         = local.account_id
  partition          = local.partition
  running            = var.running
  devtools_image_uri = var.devtools_image_uri
  log_retention_days = var.log_retention_days

  vpc_id                   = var.vpc_id
  subnet_ids               = [for s in data.aws_subnet.app : s.id]
  assign_public_ip         = false
  web_security_group_id    = aws_security_group.web.id
  worker_security_group_id = aws_security_group.worker.id
  alb_security_group_id    = aws_security_group.alb.id
  alb_port                 = 443

  cluster_id            = module.core.cluster_id
  execution_role_arn    = module.core.execution_role_arn
  kms_key_arn           = module.core.kms_key_arn
  etl_token_secret_arns = module.core.etl_token_secret_arns
  app_environment       = module.core.app_environment
}
