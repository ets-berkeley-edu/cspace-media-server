# terraform test (run from deploy/terraform/pipeline after terraform init -backend=false). Plans the deploy pipeline's
# AWS side against a simulated AWS provider: nothing is created and no sign-in is needed.

mock_provider "aws" {
  override_during = plan # the mocked ARNs below are known when the roles' policies are planned

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    }
  }

  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/pipeline-personal-stage2-build"
    }
  }

  mock_resource "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::pipeline-personal-stage2-plans-123456789012-us-west-2"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-west-2:123456789012:log-group:/pipeline/personal-stage2"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/pipeline-personal-stage2-build"
    }
  }
}

variables {
  account_id           = "123456789012"
  region               = "us-west-2"
  environment          = "personal-stage2"
  env_name             = "stage2r"
  create_oidc_provider = true
  github_subject       = "repo:ets-berkeley-edu@283538/cspace-media-server@1410958489"
}

run "only_the_github_environments_may_sign_in" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role.github["plan"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:ets-berkeley-edu@283538/cspace-media-server@1410958489:environment:personal-stage2-plan"
    error_message = "the plan role trusts only the GitHub environment personal-stage2-plan"
  }

  assert {
    condition     = jsondecode(aws_iam_role.github["apply"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:ets-berkeley-edu@283538/cspace-media-server@1410958489:environment:personal-stage2"
    error_message = "the apply role trusts only the GitHub environment personal-stage2, the one with the reviewer"
  }

  assert {
    condition     = alltrue([for r in aws_iam_role.github : jsondecode(r.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"])
    error_message = "both roles require the audience sts.amazonaws.com"
  }

  assert {
    condition     = alltrue([for r in aws_iam_role.github : length(jsondecode(r.assume_role_policy).Statement) == 1 && jsondecode(r.assume_role_policy).Statement[0].Action == "sts:AssumeRoleWithWebIdentity"])
    error_message = "the roles are assumed only through GitHub's OIDC tokens"
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 1 && length(data.aws_iam_openid_connect_provider.github) == 0
    error_message = "with create_oidc_provider, the root makes GitHub's OIDC provider"
  }
}

run "each_role_starts_only_its_own_build" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role_policy.github["plan"].policy).Statement == [{ Sid = "OnlyItsOwnBuild", Effect = "Allow", Action = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"], Resource = "arn:aws:codebuild:us-west-2:123456789012:project/pipeline-personal-stage2-plan" }]
    error_message = "the plan role may only start and look at the plan build: never the apply build, never the logs"
  }

  assert {
    condition     = jsondecode(aws_iam_role_policy.github["apply"].policy).Statement == [{ Sid = "OnlyItsOwnBuild", Effect = "Allow", Action = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"], Resource = "arn:aws:codebuild:us-west-2:123456789012:project/pipeline-personal-stage2-apply" }]
    error_message = "the apply role may only start and look at the apply build"
  }

  assert {
    condition     = alltrue([for k, p in aws_codebuild_project.build : "arn:aws:codebuild:us-west-2:123456789012:project/${p.name}" == local.project_arn[k]])
    error_message = "the roles' policies name the projects that exist"
  }
}

run "no_name_the_deployer_policy_may_change" {
  command = plan

  assert {
    condition = alltrue(concat(
      [for r in aws_iam_role.github : !startswith(r.name, "serena-")],
      [!startswith(aws_iam_role.build.name, "serena-"), !startswith(aws_s3_bucket.plans.bucket, "serena-"),
      !startswith(aws_cloudwatch_log_group.build.name, "/serena/")],
      [for p in module.deployer_policy.test : !startswith(p.name, "serena-")],
    ))
    error_message = "no role, policy, bucket or log group is named serena-* (or /serena/), which the deployer policy may change"
  }

  assert {
    condition     = aws_iam_role.build.name == "pipeline-personal-stage2-build"
    error_message = "the build role is pipeline-<environment>-build"
  }
}

run "the_build_role_never_handles_a_secret_value" {
  command = plan

  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.build.policy).Statement : s if s.Sid == "NoSecretValues"]).Effect == "Deny"
    error_message = "the build role is denied secret values outright (D274, DP5)"
  }

  assert {
    condition     = toset(one([for s in jsondecode(aws_iam_role_policy.build.policy).Statement : s if s.Sid == "NoSecretValues"]).Action) == toset(["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecretVersionStage"])
    error_message = "reading, setting and promoting a secret's value are all denied"
  }

  assert {
    condition     = contains(one([for s in jsondecode(aws_iam_role_policy.build.policy).Statement : s if s.Sid == "NoParameterChanges"]).Action, "ssm:PutParameter")
    error_message = "the build can't change its settings (or the real-data confirmation)"
  }

  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.build.policy).Statement : s if s.Sid == "ItsSettings"]).Resource == "arn:aws:ssm:us-west-2:123456789012:parameter/serena-stage2r/settings/*"
    error_message = "the build reads only its own environment's settings"
  }

  assert {
    condition     = contains(one([for s in jsondecode(aws_iam_role_policy.build.policy).Statement : s if s.Sid == "NotTheAdministratorsState"]).Resource, "arn:aws:s3:::serena-tfstate-123456789012-us-west-2/serena/*/pipeline.tfstate*")
    error_message = "the build can't write the pipeline root's state"
  }

  assert {
    condition     = flatten([for k in sort(keys(module.deployer_policy.test)) : jsondecode(module.deployer_policy.test[k].policy).Statement]) == jsondecode(file("../../iam/serena-deployer-policy.json")).Statement
    error_message = "otherwise the build has the stage 2 deployer policy, every statement, in order"
  }

  assert {
    condition     = toset(jsondecode(aws_iam_role.build.assume_role_policy).Statement[0].Condition.ArnLike["aws:SourceArn"]) == toset(values(local.project_arn))
    error_message = "only the two projects may use the build role"
  }
}

run "the_builds" {
  command = plan

  assert {
    condition     = alltrue([for p in aws_codebuild_project.build : p.environment[0].type == "ARM_CONTAINER" && p.environment[0].privileged_mode])
    error_message = "ARM Linux, with Docker for the images"
  }

  assert {
    condition     = alltrue([for p in aws_codebuild_project.build : length(p.vpc_config) == 0])
    error_message = "outside any VPC"
  }

  assert {
    condition     = alltrue([for k, p in aws_codebuild_project.build : p.source[0].type == "GITHUB" && p.source[0].location == "https://github.com/ets-berkeley-edu/cspace-media-server.git" && p.source[0].buildspec == "deploy/pipeline/buildspec-${k}.yml" && length(p.source[0].auth) == 0])
    error_message = "the public repository, with no credentials, and the buildspec in it"
  }

  assert {
    condition     = alltrue([for p in aws_codebuild_project.build : p.concurrent_build_limit == 1])
    error_message = "one build at a time"
  }
}

run "the_saved_plans" {
  command = plan

  assert {
    condition     = aws_s3_bucket_public_access_block.plans.block_public_acls && aws_s3_bucket_public_access_block.plans.block_public_policy && aws_s3_bucket_public_access_block.plans.ignore_public_acls && aws_s3_bucket_public_access_block.plans.restrict_public_buckets
    error_message = "the bucket of plans is private"
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.plans.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "and encrypted"
  }

  assert {
    condition     = one(one(aws_s3_bucket_lifecycle_configuration.plans.rule).expiration).days == 7
    error_message = "plans are deleted after 7 days"
  }

  assert {
    condition     = jsondecode(aws_s3_bucket_policy.plans.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false"
    error_message = "only over TLS"
  }
}

run "the_account_already_has_the_oidc_provider" {
  command = plan

  variables {
    create_oidc_provider = false
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "where the account has one, the root doesn't make a second (DP2)"
  }

  assert {
    condition     = jsondecode(aws_iam_role.github["apply"].assume_role_policy).Statement[0].Principal.Federated == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    error_message = "the roles trust the account's own provider"
  }
}

run "the_default_subject" {
  command = plan

  variables {
    github_subject = "repo:ets-berkeley-edu/cspace-media-server"
  }

  assert {
    condition     = jsondecode(aws_iam_role.github["plan"].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:ets-berkeley-edu/cspace-media-server:environment:personal-stage2-plan"
    error_message = "a repository without immutable subjects is trusted by its name"
  }
}

run "no_wildcard_in_the_subject" {
  command = plan

  variables {
    github_subject = "repo:ets-berkeley-edu/*"
  }

  expect_failures = [var.github_subject]
}
