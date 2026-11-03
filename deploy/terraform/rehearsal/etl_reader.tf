# A stand-in for a museum's ETL server's role (D275, DP15; checklist section 57): ETL_READER_ROLE_ARNS names it, and
# the shared root gives it read access to that museum's ETL token through the secret's policy and the key's. It has no
# policy of its own, so whatever it can read, those two policies allow; in another account the ETL server's role also
# needs its own policy (deploy/README.md). Only the administrator role that applies this root may assume it.

resource "aws_iam_role" "etl_reader" {
  name                 = "${local.name}-etl-reader"
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
