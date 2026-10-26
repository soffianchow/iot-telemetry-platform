variable "name" { type = string }
variable "device_ids" { type = set(string) }
variable "region" { type = string }
variable "account_id" { type = string }
resource "aws_iot_thing_type" "device" {
  name = "${var.name}-virtual-device"
  properties { description = "Reusable virtual operational telemetry device" }
}
resource "aws_iot_thing" "device" {
  for_each        = var.device_ids
  name            = each.value
  thing_type_name = aws_iot_thing_type.device.name
  attributes      = { environment = "portfolio", simulated = "true" }
}
# One policy per device: a compromised identity cannot impersonate another device.
# Certificates and principal attachments intentionally belong to a later phase.
resource "aws_iot_policy" "device" {
  for_each = var.device_ids
  name     = "${var.name}-${each.value}"
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["iot:Connect"], Resource = "arn:aws:iot:${var.region}:${var.account_id}:client/${each.value}", Condition = { Bool = { "iot:Connection.Thing.IsAttached" = "true" } } },
    { Effect = "Allow", Action = ["iot:Publish"], Resource = "arn:aws:iot:${var.region}:${var.account_id}:topic/iot-ops/devices/${each.value}/telemetry" }
  ] })
}
output "thing_names" { value = [for thing in aws_iot_thing.device : thing.name] }
output "policy_names" { value = [for policy in aws_iot_policy.device : policy.name] }
