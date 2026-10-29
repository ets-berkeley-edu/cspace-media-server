# The shared modules (D302), given this root's network, load balancer and CloudFront pieces.

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

  # Tasks in the public subnets with public addresses, no NAT gateway (D187). Taken from the route table associations,
  # so the services start only once the subnets have their route out, and from the listener, so the app's service is
  # created after it.
  subnet_ids               = aws_route_table_association.public[*].subnet_id
  assign_public_ip         = true
  web_security_group_id    = aws_security_group.web.id
  worker_security_group_id = aws_security_group.worker.id
  target_group_arn         = aws_lb_listener.http.default_action[0].target_group_arn
  load_balancer_arn_suffix = aws_lb.main.arn_suffix
  target_group_arn_suffix  = aws_lb_target_group.web.arn_suffix

  distribution_arn = module.files.distribution_arn
  cdn_base_url     = "https://${module.files.domain_name}"
  delivery         = module.files.delivery
}

module "files" {
  source = "../modules/files"

  name           = local.name
  env_name       = var.env_name
  region         = var.region
  account_id     = local.account_id
  bucket_domains = module.core.bucket_domains
  cdn_keys       = var.cdn_keys

  # Here the distribution is the app's front door too (D183), with the address rules on every path (D185).
  viewer_request_function_arn = aws_cloudfront_function.allowlist.arn
  app_origin = {
    domain_name         = aws_lb.main.dns_name
    vpc_origin_id       = aws_cloudfront_vpc_origin.alb.id
    origin_read_timeout = var.origin_read_timeout
  }
  web_acl_arn = var.waf ? aws_wafv2_web_acl.main[0].arn : null
}

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

  vpc_id                   = aws_vpc.main.id
  subnet_ids               = aws_route_table_association.public[*].subnet_id
  assign_public_ip         = true
  web_security_group_id    = aws_security_group.web.id
  worker_security_group_id = aws_security_group.worker.id
  alb_security_group_id    = aws_security_group.alb.id

  cluster_id            = module.core.cluster_id
  execution_role_arn    = module.core.execution_role_arn
  kms_key_arn           = module.core.kms_key_arn
  etl_token_secret_arns = module.core.etl_token_secret_arns
  app_environment       = module.core.app_environment
}
