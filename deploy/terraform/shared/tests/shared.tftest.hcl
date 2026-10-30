# terraform test (run from deploy/terraform/shared after terraform init -backend=false). Plans the shared root (QA and
# production, the split) against a simulated AWS provider (D298): nothing is created and no sign-in is needed.
# Resources inside a module are read through its test output.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_region" {
    defaults = {
      region = "us-west-2"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }

  mock_data "aws_subnet" {
    defaults = {
      vpc_id = "vpc-0123456789abcdef0"
    }
  }

  mock_resource "aws_cloudfront_function" {
    defaults = {
      arn = "arn:aws:cloudfront::123456789012:function/serena-qa-files"
    }
  }
}

variables {
  account_id      = "123456789012"
  region          = "us-west-2"
  env_name        = "qa"
  image_uri       = "123456789012.dkr.ecr.us-west-2.amazonaws.com/serena-qa:abc1234"
  tenants         = { pahma = "https://pahma.qa.collectionspace.org" }
  vpc_id          = "vpc-0123456789abcdef0"
  app_subnet_ids  = ["subnet-0aaaaaaaaaaaaaaa1", "subnet-0aaaaaaaaaaaaaaa2"]
  lb_subnet_ids   = ["subnet-0bbbbbbbbbbbbbbb1", "subnet-0bbbbbbbbbbbbbbb2"]
  domain_name     = "serena-qa.example.edu"
  certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  apache_cidrs    = ["192.0.2.10/32", "192.0.2.11/32"]
  etl_cidrs       = ["198.51.100.5/32"]
  admin_cidrs     = ["203.0.113.0/24", "203.0.114.0/24", "203.0.115.0/24", "203.0.116.0/24"]
  cdn_keys        = true
}

override_data {
  target = module.files.data.aws_ssm_parameter.cdn_keys
  values = {
    insecure_value = "[{\"name\": \"serena-qa-20261029000000\", \"public_key\": \"-----BEGIN PUBLIC KEY-----\\nMOCK\\n-----END PUBLIC KEY-----\\n\"}]"
  }
}

run "the_split" {
  command = plan

  assert {
    condition     = !aws_lb.main.internal && aws_lb.main.idle_timeout == 300
    error_message = "An internet-facing load balancer whose idle timeout lets a first fetch finish (D289, D295)."
  }

  assert {
    condition     = aws_lb_listener.https.protocol == "HTTPS" && aws_lb_listener.https.port == 443 && aws_lb_listener.https.certificate_arn == var.certificate_arn
    error_message = "One HTTPS listener with the ACM certificate (D294); no port 80 (TQ5)."
  }

  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.alb_https) == 7 && alltrue([for r in aws_vpc_security_group_ingress_rule.alb_https : r.from_port == 443])
    error_message = "The load balancer admits HTTPS from the Apache hosts, the ETL server and the campus ranges only (D291)."
  }

  assert {
    condition     = length(aws_lb_listener_rule.allow) == 3 && aws_lb_listener_rule.deny["etl"].action[0].fixed_response[0].status_code == "403" && aws_lb_listener_rule.deny["admin"].priority == 299
    error_message = "/etl/ and /admin reach the app only from their address lists (one rule for the ETL server, two for four campus ranges, at most 5 values a rule); from anywhere else, 403 (D291)."
  }

  assert {
    condition     = module.files.test.default_origin == "static" && length(module.files.test.behavior_paths) == 3 && !contains(module.files.test.behavior_paths, "/admin/assets/*")
    error_message = "CloudFront has only the file paths and the unavailable images: no app origin, no admin app files (D293, D296, D298)."
  }

  assert {
    condition     = module.files.test.signed_paths == ["/pahma/objects/*"]
    error_message = "A museum's files only with a signed URL (D195)."
  }

  assert {
    condition     = !strcontains(aws_cloudfront_function.files.code, "ALLOWED") && strcontains(aws_cloudfront_function.files.code, "(pahma)")
    error_message = "The files' function only removes the museum from the path: no address rule (D307)."
  }

  assert {
    condition     = module.waf[0].test.scope == "REGIONAL" && length(aws_wafv2_web_acl_association.alb) == 1 && contains(module.waf[0].test.rule_names, "rate-limit-per-visitor-through-apache") && contains(module.waf[0].test.rule_names, "rate-limit-per-address")
    error_message = "A regional web ACL on the load balancer (D292) whose rate limit counts the Apache hosts' requests by X-Forwarded-For (D306)."
  }

  assert {
    condition     = module.core.test.web_desired_count == 2 && output.url == "https://serena-qa.example.edu"
    error_message = "Two app tasks (D188), at the campus name (D293)."
  }

  assert {
    condition     = length(aws_vpc_endpoint.s3) == 0 && length(module.simulator) == 0
    error_message = "No gateway endpoints unless asked (D303); no simulator unless asked."
  }
}

run "simulator_museum" {
  command = plan

  variables {
    simulated_cspace         = true
    devtools_image_uri       = "123456789012.dkr.ecr.us-west-2.amazonaws.com/serena-qa-devtools:abc1234"
    tenants                  = { pahma = "http://fakecspace.serena-qa.internal:8180/pahma" }
    create_gateway_endpoints = true
  }

  override_data {
    target = data.aws_route_table.app
    values = {
      id = "rtb-0ccccccccccccccc1"
    }
  }

  assert {
    condition     = length(module.simulator) == 1 && output.load_balancer_url == "https://serena-qa.example.edu"
    error_message = "Stage 2's simulator museum (D300); the fake ETL calls the campus name."
  }

  assert {
    condition     = length(aws_vpc_endpoint.s3) == 1 && aws_vpc_endpoint.s3[0].route_table_ids == toset(["rtb-0ccccccccccccccc1"])
    error_message = "With create_gateway_endpoints, S3 and DynamoDB endpoints on the app subnets' route tables (D303)."
  }
}

run "no_waf" {
  command = plan

  variables {
    waf          = false
    apache_cidrs = []
  }

  assert {
    condition     = length(module.waf) == 0 && length(aws_wafv2_web_acl_association.alb) == 0 && length(aws_vpc_security_group_ingress_rule.alb_https) == 5
    error_message = "WAF can be switched off; without Apache hosts only the ETL and campus ranges are admitted."
  }
}

run "a_subnet_outside_the_vpc" {
  command = plan

  override_data {
    target = data.aws_subnet.lb
    values = {
      vpc_id = "vpc-0ffffffffffffffff"
    }
  }

  expect_failures = [data.aws_subnet.lb]
}
