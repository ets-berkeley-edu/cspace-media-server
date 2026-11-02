# The stage 2 deployer policy (../../../iam/serena-deployer-policy.json, D297, D303, D305) as customer managed policies,
# for the rehearsal's deployer (../../rehearsal) and the pipeline's build role (../../pipeline, DP5).
#
# The policy is too long for one managed policy (6,144 characters), so it is split between statements, in order, as Ops
# attaches it (deploy/iam/README.md): a statement goes in the part its end falls in, counting part_size characters a
# part. The precondition below stops the apply if a part is ever too long; then lower part_size.

locals {
  deployer_policy = jsondecode(file("${path.module}/../../../iam/serena-deployer-policy.json"))
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

resource "aws_iam_policy" "part" {
  for_each = local.policy_parts
  name     = "${var.name}-${each.key}"
  policy   = each.value

  lifecycle {
    precondition {
      condition     = length(each.value) <= 6144
      error_message = "Part ${each.key} of the deployer policy is ${length(each.value)} characters, over IAM's 6,144: lower part_size in modules/deployer_policy/main.tf."
    }
  }
}

resource "aws_iam_role_policy_attachment" "part" {
  for_each   = aws_iam_policy.part
  role       = var.role_name
  policy_arn = each.value.arn
}
