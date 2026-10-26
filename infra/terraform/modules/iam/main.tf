variable "name" { type = string }
variable "table_arn" { type = string }
variable "log_group_arn" { type = string }
resource "aws_iam_role" "processor" {
  name               = "${var.name}-processor"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "processor" {
  name = "telemetry-write-and-logs"
  role = aws_iam_role.processor.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:PutItem"], Resource = var.table_arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${var.log_group_arn}:*" }
  ] })
}
output "role_arn" { value = aws_iam_role.processor.arn }
