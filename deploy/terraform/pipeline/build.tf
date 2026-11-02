# The builds (DP4 to DP7, DP11): two CodeBuild projects, plan and apply, on ARM Linux with Docker (privileged, for the
# ARM images), outside any VPC. Each checks out the public repository at the commit being deployed, with no connection
# or token, and runs its buildspec (deploy/pipeline/), which runs ./serena aws pipeline-plan or pipeline-apply. One
# build at a time per project.

locals {
  state_bucket = "serena-tfstate-${var.account_id}-${var.region}"
  settings_arn = "arn:${local.partition}:ssm:${var.region}:${var.account_id}:parameter/serena-${var.env_name}/settings/*"
}

resource "aws_cloudwatch_log_group" "build" {
  name              = "/pipeline/${var.environment}" # not /serena/...: the deployer policy may delete those
  retention_in_days = 365                            # every plan a reviewer read, and every apply
}

# The saved plans (DP6): written by the plan build, applied by the apply build. They hold the environment's settings
# (addresses, IDs) but no secret (D191). Disposable: deleted after 7 days, and with the bucket.
resource "aws_s3_bucket" "plans" {
  bucket        = "${local.name}-plans-${var.account_id}-${var.region}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "plans" {
  bucket                  = aws_s3_bucket.plans.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "plans" {
  bucket = aws_s3_bucket.plans.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "plans" {
  bucket = aws_s3_bucket.plans.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "plans" {
  bucket = aws_s3_bucket.plans.id
  rule {
    id     = "plans-expire"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
  }
}

resource "aws_s3_bucket_policy" "plans" {
  bucket = aws_s3_bucket.plans.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "OnlyTls"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.plans.arn, "${aws_s3_bucket.plans.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.plans]
}

# The build's role (DP5): the stage 2 deployer policy, and the pipeline's own needs. Only the two projects may use it.
resource "aws_iam_role" "build" {
  name = "${local.name}-build"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.account_id }
        ArnLike      = { "aws:SourceArn" = values(local.project_arn) }
      }
    }]
  })
}

module "deployer_policy" {
  source    = "../modules/deployer_policy"
  name      = "${local.name}-build"
  role_name = aws_iam_role.build.name
}

resource "aws_iam_role_policy" "build" {
  name = "pipeline"
  role = aws_iam_role.build.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ItsLog"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.build.arn}:*"
      },
      {
        Sid      = "SavedPlans"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.plans.arn, "${aws_s3_bucket.plans.arn}/*"]
      },
      {
        Sid      = "ItsSettings"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = local.settings_arn
      },
      {
        # Secret values never pass through a build (D274): it needs only their metadata. Holds whatever a build runs.
        Sid      = "NoSecretValues"
        Effect   = "Deny"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecretVersionStage"]
        Resource = "*"
      },
      {
        # The settings (the real-data confirmation among them) and the CloudFront public keys are an admin's to change.
        Sid      = "NoParameterChanges"
        Effect   = "Deny"
        Action   = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters", "ssm:LabelParameterVersion"]
        Resource = "*"
      },
      {
        # The pipeline's own state, and the rehearsal's, are the administrator's.
        Sid    = "NotTheAdministratorsState"
        Effect = "Deny"
        Action = ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource = [
          "arn:${local.partition}:s3:::${local.state_bucket}/serena/*/pipeline.tfstate*",
          "arn:${local.partition}:s3:::${local.state_bucket}/serena/*/rehearsal.tfstate*",
        ]
      },
    ]
  })
}

resource "aws_codebuild_project" "build" {
  for_each               = local.project_arn
  name                   = "${local.name}-${each.key}"
  description            = "Serena's ${var.environment}: the ${each.key} build (deploy/pipeline/buildspec-${each.key}.yml)."
  service_role           = aws_iam_role.build.arn
  build_timeout          = each.key == "plan" ? 60 : 90
  queued_timeout         = 30
  concurrent_build_limit = 1

  source {
    type            = "GITHUB"
    location        = "https://github.com/${var.repository}.git"
    git_clone_depth = 0 # the whole history: the build checks the commit is on main
    buildspec       = "deploy/pipeline/buildspec-${each.key}.yml"
  }
  source_version = "main"

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type                        = "ARM_CONTAINER"
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = var.codebuild_image
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true # Docker builds the images

    environment_variable {
      name  = "SERENA_AWS_ENV"
      value = var.environment
    }
    environment_variable {
      name  = "PIPELINE_PLANS"
      value = aws_s3_bucket.plans.bucket
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.build.name
      stream_name = each.key
    }
    s3_logs {
      status = "DISABLED"
    }
  }

  depends_on = [aws_iam_role_policy.build]
}
