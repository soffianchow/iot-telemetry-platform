variable "name" { type = string }
variable "function_arn" { type = string }
resource "aws_iot_topic_rule" "telemetry" {
  name        = var.name
  description = "Route device telemetry with authoritative topic identity"
  enabled     = false # Enable only in a separately approved cloud phase.
  sql         = "SELECT *, topic(3) AS source_device_id FROM 'iot-ops/devices/+/telemetry'"
  sql_version = "2016-03-23"
  lambda { function_arn = var.function_arn }
}
