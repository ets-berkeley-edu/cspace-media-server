# GitHub Actions signs in through OIDC (D271): no stored keys. Two roles (DP3): the plan job's, trusted only by the
# GitHub environment <environment>-plan, may start only the plan build; the apply job's, trusted only by <environment>
# (the one with the reviewer), only the apply build. Each reads its builds' status (BatchGetBuilds: the counts the plan
# build exports), never their logs, so the plan stays out of the public Actions logs (D270, DP6).

locals {
  github_oidc = "token.actions.githubusercontent.com"
  github_environment = {
    plan  = "${var.environment}-plan"
    apply = var.environment
  }
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://${local.github_oidc}"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = "https://${local.github_oidc}"
}

resource "aws_iam_role" "github" {
  for_each             = local.github_environment
  name                 = "${local.name}-${each.key}"
  max_session_duration = 7200 # a plan build with the images, or an apply with CloudFront, can pass an hour
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.github_oidc}:aud" = "sts.amazonaws.com"
          # Only a job in this GitHub environment, which takes only main (DP9); never a pull request's.
          "${local.github_oidc}:sub" = "repo:${var.repository}:environment:${each.value}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github" {
  for_each = local.github_environment
  name     = "start-${each.key}-build"
  role     = aws_iam_role.github[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "OnlyItsOwnBuild"
      Effect   = "Allow"
      Action   = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
      Resource = local.project_arn[each.key]
    }]
  })
}
