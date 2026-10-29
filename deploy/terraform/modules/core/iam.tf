# Separate roles for the app and the worker (design: Infrastructure and operations, Least privilege). Neither can
# create or delete a table, delete an S3 object, or read the other's secrets. What each may do:
#
#                    app                                         worker
#   servability      read                                        read and write (deleting rows included)
#   recalls          read and write                              read, update and delete
#   settings         read and write                              read
#   cache index      read and write (last_served too, D142)      -
#   refreshes        read and write                              read and write
#   alerts           read and write                              read and write
#   audit log        read and add                                read, add and delete (removing ended entries)
#   admin sessions   read and write                              -
#   S3 objects/      read and put (fetched files)                -
#   S3 servable-list put (uploads)                               read and put
#   secrets          its own: CollectionSpace accounts, ETL      -
#                    tokens, portal signing keys, CloudFront key
#   logs             Logs Insights on its own log group (D110)   -
#   alert topic      -                                           publish (D201)
#
# Both use Serena's KMS key (kms.tf) for the buckets and the secrets.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:ecs:${var.region}:${local.account_id}:*"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "ecs_execution_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Lets ECS pull the images and write the logs; the app's own permissions are the task roles below.
resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_execution_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

locals {
  table_read  = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem"]
  table_write = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"]

  # A table and its indexes.
  table_arns = { for t, table in aws_dynamodb_table.main : t => [table.arn, "${table.arn}/index/*"] }

  bucket_arns       = [for b in aws_s3_bucket.museum : b.arn]
  object_arns       = [for b in aws_s3_bucket.museum : "${b.arn}/objects/*"]
  servable_list_arn = [for b in aws_s3_bucket.museum : "${b.arn}/servable-list/*"]
}

data "aws_iam_policy_document" "web" {
  statement {
    sid       = "ServabilityRead"
    actions   = local.table_read
    resources = local.table_arns["servability"]
  }

  statement {
    sid     = "TablesReadWrite"
    actions = concat(local.table_read, local.table_write)
    resources = flatten([for t in ["recalls", "settings", "cache-index", "refreshes", "alerts", "admin-sessions"] :
    local.table_arns[t]])
  }

  # The Past requests page's counts from the cache or CollectionSpace (issue #96); the worker writes them.
  statement {
    sid       = "RequestCountsRead"
    actions   = local.table_read
    resources = local.table_arns["request-counts"]
  }

  statement {
    sid       = "AuditReadAndAdd"
    actions   = concat(local.table_read, ["dynamodb:PutItem"])
    resources = local.table_arns["audit"]
  }

  # ListBucket: without it, a missing object reads as 403, not 404 (fetch.py checks before storing).
  statement {
    sid       = "Buckets"
    actions   = ["s3:ListBucket"]
    resources = local.bucket_arns
  }

  statement {
    sid       = "FetchedFiles"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = local.object_arns
  }

  statement {
    sid       = "ServableListUploads"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = local.servable_list_arn
  }

  statement {
    sid     = "OwnSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat([for s in aws_secretsmanager_secret.cspace : s.arn], [for s in aws_secretsmanager_secret.etl_tokens : s.arn],
    [for s in aws_secretsmanager_secret.portal_key : s.arn], [aws_secretsmanager_secret.cdn_key.arn])
  }

  statement {
    sid       = "Key"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.main.arn]
  }

  statement {
    sid       = "PastRequestsQueries"
    actions   = ["logs:StartQuery"]
    resources = [aws_cloudwatch_log_group.web.arn, "${aws_cloudwatch_log_group.web.arn}:*"]
  }

  # These two take no resource: a query is named by its ID.
  statement {
    sid       = "PastRequestsResults"
    actions   = ["logs:GetQueryResults", "logs:StopQuery"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid     = "TablesReadWrite"
    actions = concat(local.table_read, local.table_write)
    resources = flatten([for t in ["servability", "recalls", "refreshes", "alerts", "audit", "request-counts"] :
    local.table_arns[t]])
  }

  # The daily request counts (issue #96) query the app's log group, as the Past requests page does.
  statement {
    sid       = "RequestCountQueries"
    actions   = ["logs:StartQuery"]
    resources = [aws_cloudwatch_log_group.web.arn, "${aws_cloudwatch_log_group.web.arn}:*"]
  }

  # These two take no resource: a query is named by its ID.
  statement {
    sid       = "RequestCountResults"
    actions   = ["logs:GetQueryResults", "logs:StopQuery"]
    resources = ["*"]
  }

  statement {
    sid       = "SettingsRead"
    actions   = local.table_read
    resources = local.table_arns["settings"]
  }

  statement {
    sid       = "Buckets"
    actions   = ["s3:ListBucket"]
    resources = local.bucket_arns
  }

  statement {
    sid       = "ServableLists"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = local.servable_list_arn
  }

  statement {
    sid       = "Key"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.main.arn]
  }

  statement {
    sid       = "Alerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role" "web" {
  name               = "${local.name}-web"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "web" {
  name   = "serena-web"
  role   = aws_iam_role.web.id
  policy = data.aws_iam_policy_document.web.json
}

resource "aws_iam_role" "worker" {
  name               = "${local.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "serena-worker"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}
