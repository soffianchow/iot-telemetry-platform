variable "name" { type = string }
resource "aws_dynamodb_table" "telemetry" {
  name                        = var.name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "device_id"
  range_key                   = "event_key"
  deletion_protection_enabled = true
  attribute {
    name = "device_id"
    type = "S"
  }
  attribute {
    name = "event_key"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = false }
  lifecycle { prevent_destroy = true }
}
output "arn" { value = aws_dynamodb_table.telemetry.arn }
output "name" { value = aws_dynamodb_table.telemetry.name }
