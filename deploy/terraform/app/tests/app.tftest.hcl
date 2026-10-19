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
