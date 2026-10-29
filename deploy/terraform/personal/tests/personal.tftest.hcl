# terraform test (run from deploy/terraform/personal after terraform init -backend=false). Plans against a simulated
# AWS provider: nothing is created and no sign-in is needed. Resources inside a module are read through its test
# output (terraform test can't address them directly).

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
    condition     = output.cluster_name == "serena-dev"
    error_message = "The cluster is named serena-<env>; ./serena aws status and logs rely on it."
  }

  assert {
    condition     = length(module.core.test.tables) == 9 && module.core.test.tables["servability"].name == "serena-dev-servability"
    error_message = "The nine tables from tables.json, named <SERENA_TABLE_PREFIX>-<table>."
  }

  assert {
    condition     = output.buckets["pahma"] == "serena-dev-pahma-123456789012-us-west-2"
    error_message = "One bucket per museum, its name including the account and region, so it is unique."
  }

  assert {
    condition     = module.core.test.web_desired_count == 1 && module.core.test.worker_desired_count == 1
    error_message = "One web task and one worker run by default."
  }

  assert {
    condition     = module.core.test.web_cpu == "1024" && module.core.test.web_memory == "2048"
    error_message = "The web task has 1 vCPU and 2 GB by default."
  }

  assert {
    condition     = length(module.simulator) == 0 && output.fake_etl == null
    error_message = "Without simulated_cspace there is no simulator and no fake ETL."
  }

  assert {
    condition     = length(aws_wafv2_web_acl.main) == 0
    error_message = "WAF is off by default."
  }

  assert {
    condition     = length(module.core.test.portal_key_museums) == 0
    error_message = "PAHMA has no signed access, so no portal signing key."
  }

  assert {
    condition     = !output.delivery && module.files.test.key_groups == 0 && length(module.files.test.behavior_paths) == 3 && module.files.test.default_origin == "app"
    error_message = "Without a signing key (cdn_keys = false) nothing is delivered: no key group, and only the admin app's files and the two unavailable-image behaviors."
  }

  assert {
    condition     = length(module.files.test.static_files) == 3 && contains(module.files.test.static_files, "pahma/unavailable.svg") && contains(module.files.test.static_files, "default/placeholder.svg")
    error_message = "The static bucket holds each museum's and the default unavailable image, and the generic placeholder (D199)."
  }

  assert {
    condition     = length(module.core.test.email_protocols) == 0 && module.core.test.alarms_enabled["web-down"]
    error_message = "No email subscription without alert_email; the alarms act while the environment runs."
  }

  assert {
    condition     = length(module.core.test.unserved_patterns) == 3 && module.core.test.unserved_patterns["cspace-refused"] == "{ $.message = \"unserved\" && $.reason = \"cspace_refused\" }"
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
    target = module.files.data.aws_ssm_parameter.cdn_keys
    values = {
      insecure_value = "[{\"name\": \"serena-dev-20261020000000\", \"public_key\": \"-----BEGIN PUBLIC KEY-----\\nMOCK\\n-----END PUBLIC KEY-----\\n\"}, {\"name\": \"serena-dev-20261021000000\", \"public_key\": \"-----BEGIN PUBLIC KEY-----\\nMOCK2\\n-----END PUBLIC KEY-----\\n\"}]"
    }
  }

  assert {
    condition     = output.delivery && length(output.cdn_key_ids) == 2 && contains(keys(output.cdn_key_ids), "serena-dev-20261021000000")
    error_message = "Both public keys in the SSM parameter, current and previous, are trusted (D200)."
  }

  assert {
    condition     = length(module.files.test.behavior_paths) == 5 && contains(module.files.test.behavior_paths, "/cinefiles/objects/*")
    error_message = "With a signing key, each museum's files get a behavior of their own (D195)."
  }

  assert {
    condition     = sort(module.files.test.signed_paths) == sort([for p in module.files.test.behavior_paths : p if endswith(p, "/objects/*")]) && length(module.files.test.signed_paths) == 2
    error_message = "A museum's files are delivered only with a signed URL."
  }

  assert {
    condition     = module.core.test.email_protocols == ["email"]
    error_message = "alert_email subscribes one address to the alert topic (D201)."
  }
}

run "paused_alarms_are_silent" {
  command = plan

  variables {
    running = false
  }

  assert {
    condition     = length(module.core.test.alarms_enabled) == 5 && alltrue([for enabled in values(module.core.test.alarms_enabled) : !enabled])
    error_message = "A paused environment sends no alarm (D204)."
  }
}

run "paused" {
  command = plan

  variables {
    running = false
  }

  assert {
    condition     = module.core.test.web_desired_count == 0 && module.core.test.worker_desired_count == 0
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
    condition     = length(module.simulator) == 1 && output.fake_etl.task_definition == "serena-dev-fake-etl"
    error_message = "With simulated_cspace, the simulator runs and the fake ETL's task definition exists."
  }

  assert {
    condition     = module.core.test.portal_key_museums == ["cinefiles"]
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
    condition     = module.core.test.tables["servability"].deletion_protection && !module.core.test.bucket_force_destroy["pahma"]
    error_message = "protect_data turns on deletion protection and keeps the buckets from being emptied."
  }
}
