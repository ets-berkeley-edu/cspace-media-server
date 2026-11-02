# The deployer: a role with only the stage 2 deployer policy (../../iam/serena-deployer-policy.json, D297, D303, D305),
# which ./serena aws assumes for the rehearsal, so that every AccessDenied is the policy's. Only the administrator role
# that applies this root may assume it. Its name doesn't start with serena-: the policy lets the deployer change
# serena-* roles, and the deployer mustn't be able to change its own.
#
# The policy is too long for one managed policy (6,144 characters), so it is split between statements, in order, as Ops
# attaches it (deploy/iam/README.md): a statement goes in the part its end falls in, counting part_size characters a
# part. The precondition below stops the apply if a part is ever too long; then lower part_size.

data "aws_iam_session_context" "admin" {
  arn = data.aws_caller_identity.current.arn
}

locals {
  deployer_policy = jsondecode(file("${path.module}/../../iam/serena-deployer-policy.json"))
  statements      = local.deployer_policy.Statement
  part_size       = 6000
  statement_sizes = [for s in local.statements : length(jsonencode(s)) + 1] # with its comma
  statement_ends  = [for i in range(length(local.statements)) : sum(slice(local.statement_sizes, 0, i + 1))]
  statement_parts = [for end in local.statement_ends : floor((end - 1) / local.part_size)]
  policy_parts = {
    for part in distinct(local.statement_parts) : tostring(part + 1) => jsonencode({
      Version   = local.deployer_policy.Version
      Statement = [for i, s in local.statements : s if local.statement_parts[i] == part]
    })
  }
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

resource "aws_iam_policy" "deployer" {
  for_each = local.policy_parts
  name     = "${local.name}-deployer-${each.key}"
  policy   = each.value

  lifecycle {
    precondition {
      condition     = length(each.value) <= 6144
      error_message = "Part ${each.key} of the deployer policy is ${length(each.value)} characters, over IAM's 6,144: lower part_size in deployer.tf."
    }
  }
}

resource "aws_iam_role_policy_attachment" "deployer" {
  for_each   = aws_iam_policy.deployer
  role       = aws_iam_role.deployer.name
  policy_arn = each.value.arn
}
