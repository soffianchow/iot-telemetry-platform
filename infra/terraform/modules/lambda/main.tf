variable "name" { type = string }
variable "role_arn" { type = string }
variable "table_name" { type = string }
variable "rule_arn" { type = string }
variable "account_id" { type = string }
variable "device_ids" { type = set(string) }
data "archive_file" "processor" {
  type        = "zip"
  source_dir  = "${path.root}/.terraform/lambda-package"
  output_path = "${path.root}/.terraform/telemetry-handler.zip"
}
resource "aws_lambda_function" "processor" {
  function_name                  = var.name
  role                           = var.role_arn
  runtime                        = "python3.12"
  handler                        = "handler.handler"
  architectures                  = ["arm64"]
  filename                       = data.archive_file.processor.output_path
  source_code_hash               = data.archive_file.processor.output_base64sha256
  memory_size                    = 128
  timeout                        = 10
  reserved_concurrent_executions = 2
  environment { variables = { TABLE_NAME = var.table_name, RETENTION_DAYS = "7", DEVICE_IDS = join(",", sort(tolist(var.device_ids))) } }
}
resource "aws_lambda_permission" "iot" {
  statement_id   = "AllowOnlyTelemetryRule"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.processor.function_name
  principal      = "iot.amazonaws.com"
  source_arn     = var.rule_arn
  source_account = var.account_id
}
resource "aws_lambda_function_event_invoke_config" "processor" {
  function_name                = aws_lambda_function.processor.function_name
  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2
}
output "arn" { value = aws_lambda_function.processor.arn }
output "name" { value = aws_lambda_function.processor.function_name }
