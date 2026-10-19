# Serena's tables (design: Records), from tables.json, which backend/serena/tables.py generates and a test keeps in
# step: every partition key is the string "pk", a sort key is "sk", each index's key is a string attribute. On-demand,
# encrypted with Serena's key; point-in-time recovery on every table but the admin sessions (D192); a table that
# matters can't be deleted where data is protected.

locals {
  tables = jsondecode(file("${path.module}/tables.json"))
}

resource "aws_dynamodb_table" "main" {
  for_each = local.tables

  name                        = "${local.name}-${each.key}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = each.value.sort_key
  deletion_protection_enabled = var.protect_data

  attribute {
    name = "pk"
    type = "S"
  }

  dynamic "attribute" {
    for_each = each.value.sort_key == null ? [] : [each.value.sort_key]

    content {
      name = attribute.value
      type = "S"
    }
  }

  dynamic "attribute" {
    for_each = toset(values(each.value.indexes))

    content {
      name = attribute.value
      type = "S"
    }
  }

  dynamic "global_secondary_index" {
    for_each = each.value.indexes

    content {
      name            = global_secondary_index.key
      hash_key        = global_secondary_index.value
      projection_type = "ALL"
    }
  }

  dynamic "ttl" {
    for_each = each.value.ttl_attribute == null ? [] : [each.value.ttl_attribute]

    content {
      attribute_name = ttl.value
      enabled        = true
    }
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.main.arn
  }

  point_in_time_recovery {
    enabled = each.key != "admin-sessions"
  }
}
