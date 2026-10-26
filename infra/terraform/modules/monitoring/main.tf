variable "function_name" { type = string }
variable "log_group_name" { type = string }
variable "table_name" { type = string }
resource "aws_cloudwatch_log_group" "processor" {
  name              = var.log_group_name
  retention_in_days = 7
}
resource "aws_cloudwatch_metric_alarm" "lambda" {
  for_each            = toset(["Errors", "Throttles", "AsyncEventsDropped"])
  alarm_name          = "${var.function_name}-${lower(each.value)}"
  alarm_description   = "Inspect processor logs and ingestion backlog; notification destination is deferred."
  namespace           = "AWS/Lambda"
  metric_name         = each.value
  dimensions          = { FunctionName = var.function_name }
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 1
  period              = 300
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"
}
resource "aws_cloudwatch_metric_alarm" "storage" {
  alarm_name          = "${var.table_name}-system-errors"
  namespace           = "AWS/DynamoDB"
  metric_name         = "SystemErrors"
  dimensions          = { TableName = var.table_name, Operation = "PutItem" }
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 1
  period              = 300
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"
}
output "log_group_arn" { value = aws_cloudwatch_log_group.processor.arn }
