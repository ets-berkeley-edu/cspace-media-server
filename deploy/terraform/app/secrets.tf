# Serena's secrets (D191), created empty: Terraform never holds a value, so none is in its state. ./serena aws sets
# them (deploy/README.md): cspace-secret <museum> asks for the read-only account; etl-token <museum> and portal-key
# <museum> generate and print a value once. With the simulator, ./serena aws deploy sets every museum's account to the
# simulator's synthetic one and makes the ETL tokens and portal keys itself. The CloudFront signing key comes with
# delivery, in pull request 18 (D194).

resource "aws_secretsmanager_secret" "cspace" {
  for_each    = toset(local.museums)
  name        = "${local.name}/${each.key}/cspace"
  description = "Serena: ${each.key}'s read-only CollectionSpace account {\"username\", \"password\"} (design: Image fetch)."
  kms_key_id  = aws_kms_key.main.arn

  # Where data matters a deleted secret is kept 30 days; elsewhere it goes at once, so the environment can be destroyed
  # and created again under the same name.
  recovery_window_in_days = var.protect_data ? 30 : 0
}

resource "aws_secretsmanager_secret" "etl_tokens" {
  for_each                = toset(local.museums)
  name                    = "${local.name}/${each.key}/etl-tokens"
  description             = "Serena: ${each.key}'s ETL API tokens {\"current\", \"previous\"} (design: The ETL API)."
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.protect_data ? 30 : 0
}

# For museums that serve restricted files with a portal's signed link (signed_access_kinds in their configuration).
resource "aws_secretsmanager_secret" "portal_key" {
  for_each                = toset(local.signed_museums)
  name                    = "${local.name}/${each.key}/portal-signing-key"
  description             = "Serena: ${each.key}'s portal signing keys {\"current\": {\"kid\", \"key\"}, \"previous\"} (design: Signed links)."
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.protect_data ? 30 : 0
}
