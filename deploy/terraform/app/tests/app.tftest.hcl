# terraform test (run from deploy/terraform/app after terraform init -backend=false). Plans against a simulated AWS
# provider: nothing is created and no sign-in is needed.

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

  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-west-2a", "us-west-2b", "us-west-2c"]
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }

  mock_data "aws_ec2_managed_prefix_list" {
    defaults = {
      id = "pl-82a045eb"
    }
  }
}

mock_provider "aws" {
  alias = "us_east_1"
}

variables {
  account_id    = "123456789012"
  region        = "us-west-2"
  env_name      = "dev"
  image_uri     = "123456789012.dkr.ecr.us-west-2.amazonaws.com/serena-dev:abc1234"
  allowed_cidrs = ["203.0.113.7/32"]
  tenants       = { pahma = "https://pahma.qa.collectionspace.org" }
}

run "names_and_sizes" {
  command = plan

  assert {
    condition     = aws_ecs_cluster.main.name == "serena-dev"
    error_message = "The cluster is named serena-<env>; ./serena aws status and logs rely on it."
  }

  assert {
    condition     = length(aws_dynamodb_table.main) == 8 && aws_dynamodb_table.main["servability"].name == "serena-dev-servability"
    error_message = "The eight tables from tables.json, named <SERENA_TABLE_PREFIX>-<table>."
  }

  assert {
    condition     = aws_s3_bucket.museum["pahma"].bucket == "serena-dev-pahma-123456789012-us-west-2"
    error_message = "One bucket per museum, its name including the account and region, so it is unique."
  }

  assert {
    condition     = aws_ecs_service.web.desired_count == 1 && aws_ecs_service.worker.desired_count == 1
    error_message = "One web task and one worker run by default."
  }

  assert {
    condition     = aws_ecs_task_definition.web.cpu == "1024" && aws_ecs_task_definition.web.memory == "2048"
    error_message = "The web task has 1 vCPU and 2 GB by default."
  }

  assert {
    condition     = length(aws_ecs_service.fakecspace) == 0 && length(aws_ecs_task_definition.fake_etl) == 0
    error_message = "Without simulated_cspace there is no simulator and no fake ETL."
  }

  assert {
    condition     = length(aws_wafv2_web_acl.main) == 0
    error_message = "WAF is off by default."
  }

  assert {
    condition     = length(aws_secretsmanager_secret.portal_key) == 0
    error_message = "PAHMA has no signed access, so no portal signing key."
  }

  assert {
    condition     = !output.delivery && length(aws_cloudfront_key_group.cdn) == 0 && length(aws_cloudfront_distribution.main.ordered_cache_behavior) == 3
    error_message = "Without a signing key (cdn_keys = false) nothing is delivered: no key group, and only the admin app's files and the two unavailable-image behaviors."
  }

  assert {
    condition     = length(aws_s3_object.static) == 3 && contains(keys(aws_s3_object.static), "pahma/unavailable.svg") && contains(keys(aws_s3_object.static), "default/placeholder.svg")
    error_message = "The static bucket holds each museum's and the default unavailable image, and the generic placeholder (D199)."
  }

  assert {
    condition     = length(aws_sns_topic_subscription.email) == 0 && aws_cloudwatch_metric_alarm.web_down.actions_enabled
    error_message = "No email subscription without alert_email; the alarms act while the environment runs."
  }

  assert {
    condition     = length(aws_cloudwatch_metric_alarm.unserved) == 3 && aws_cloudwatch_log_metric_filter.unserved["cspace-refused"].pattern == "{ $.message = \"unserved\" && $.reason = \"cspace_refused\" }"
    error_message = "Three alarms on unserved requests, from metric filters on the app's log lines (D202, D203)."
  }
}

run "delivery" {
  command = plan

  variables {
    cdn_keys    = true
    alert_email = "alerts@example.org"
    tenants = {
      pahma     = "https://pahma.qa.collectionspace.org"
      cinefiles = "https://cinefiles.qa.collectionspace.org"
    }
  }

  override_data {
    target = data.aws_ssm_parameter.cdn_keys
    values = {
      insecure_value = "[{\"name\": \"serena-dev-20261020000000\", \"public_key\": \"-----BEGIN PUBLIC KEY-----\\nMOCK\\n-----END PUBLIC KEY-----\\n\"}, {\"name\": \"serena-dev-20261021000000\", \"public_key\": \"-----BEGIN PUBLIC KEY-----\\nMOCK2\\n-----END PUBLIC KEY-----\\n\"}]"
    }
  }

  assert {
    condition     = output.delivery && length(aws_cloudfront_public_key.cdn) == 2 && contains(keys(aws_cloudfront_public_key.cdn), "serena-dev-20261021000000")
    error_message = "Both public keys in the SSM parameter, current and previous, are trusted (D200)."
  }

  assert {
    condition     = length(aws_cloudfront_distribution.main.ordered_cache_behavior) == 5 && contains([for b in aws_cloudfront_distribution.main.ordered_cache_behavior : b.path_pattern], "/cinefiles/objects/*")
    error_message = "With a signing key, each museum's files get a behavior of their own (D195)."
  }

  assert {
    condition     = alltrue([for b in aws_cloudfront_distribution.main.ordered_cache_behavior : length(b.trusted_key_groups) == 1 if endswith(b.path_pattern, "/objects/*")])
    error_message = "A museum's files are delivered only with a signed URL."
  }

  assert {
    condition     = length(aws_sns_topic_subscription.email) == 1 && aws_sns_topic_subscription.email[0].protocol == "email"
    error_message = "alert_email subscribes one address to the alert topic (D201)."
  }
}

run "paused_alarms_are_silent" {
  command = plan

  variables {
    running = false
  }

  assert {
    condition     = !aws_cloudwatch_metric_alarm.web_down.actions_enabled && !aws_cloudwatch_metric_alarm.worker_down.actions_enabled && alltrue([for a in aws_cloudwatch_metric_alarm.unserved : !a.actions_enabled])
    error_message = "A paused environment sends no alarm (D204)."
  }
}

run "paused" {
  command = plan

  variables {
    running = false
  }

  assert {
    condition     = aws_ecs_service.web.desired_count == 0 && aws_ecs_service.worker.desired_count == 0
    error_message = "./serena aws pause (running = false) stops both services."
  }
}

run "simulated" {
  command = plan

  variables {
    simulated_cspace   = true
    devtools_image_uri = "123456789012.dkr.ecr.us-west-2.amazonaws.com/serena-dev-devtools:abc1234"
    tenants = {
      pahma     = "http://fakecspace.serena-dev.internal:8180/pahma"
      cinefiles = "http://fakecspace.serena-dev.internal:8180/cinefiles"
    }
  }

  assert {
    condition     = length(aws_ecs_service.fakecspace) == 1 && length(aws_ecs_task_definition.fake_etl) == 1
    error_message = "With simulated_cspace, the simulator runs and the fake ETL's task definition exists."
  }

  assert {
    condition     = length(aws_secretsmanager_secret.portal_key) == 1 && contains(keys(aws_secretsmanager_secret.portal_key), "cinefiles")
    error_message = "Cinefiles has signed access, so it gets a portal signing key."
  }
}

run "simulator_refuses_a_real_server" {
  command = plan

  variables {
    simulated_cspace   = true
    devtools_image_uri = "123456789012.dkr.ecr.us-west-2.amazonaws.com/serena-dev-devtools:abc1234"
  }

  expect_failures = [var.tenants]
}

run "protected" {
  command = plan

  variables {
    protect_data = true
  }

  assert {
    condition     = aws_dynamodb_table.main["servability"].deletion_protection_enabled && !aws_s3_bucket.museum["pahma"].force_destroy
    error_message = "protect_data turns on deletion protection and keeps the buckets from being emptied."
  }
}
