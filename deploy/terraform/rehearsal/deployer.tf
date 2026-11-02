# The deployer: a role with only the stage 2 deployer policy (../../iam/serena-deployer-policy.json, D297, D303, D305),
# which ./serena aws assumes for the rehearsal, so that every AccessDenied is the policy's. Only the administrator role
# that applies this root may assume it. Its name doesn't start with serena-: the policy lets the deployer change
# serena-* roles, and the deployer mustn't be able to change its own. The policy goes in as managed policies, split as
# Ops attaches it (../modules/deployer_policy, which the pipeline's build role uses too).

data "aws_iam_session_context" "admin" {
  arn = data.aws_caller_identity.current.arn
}

resource "aws_iam_role" "deployer" {
  name                 = "${local.name}-deployer"
  max_session_duration = 3600 # assumed from an SSO session (role chaining): AWS allows an hour at most
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = data.aws_iam_session_context.admin.issuer_arn }
      Action    = "sts:AssumeRole"
    }]
  })
}

module "deployer_policy" {
  source    = "../modules/deployer_policy"
  name      = "${local.name}-deployer"
  role_name = aws_iam_role.deployer.name
}

# Before the split moved into the module (November 2026).
moved {
  from = aws_iam_policy.deployer
  to   = module.deployer_policy.aws_iam_policy.part
}

moved {
  from = aws_iam_role_policy_attachment.deployer
  to   = module.deployer_policy.aws_iam_role_policy_attachment.part
}
