# Preparation only. No backend, credentials, certificates, or deployment workflow.
locals {
  function_name  = "${var.project_name}-telemetry"
  log_group_name = "/aws/lambda/${local.function_name}"
  rule_name      = "${replace(var.project_name, "-", "_")}_telemetry"
}
module "storage" {
  source = "./modules/dynamodb"
  name   = "${var.project_name}-telemetry"
}
module "iam" {
  source        = "./modules/iam"
  name          = local.function_name
  table_arn     = module.storage.arn
  log_group_arn = module.monitoring.log_group_arn
}
module "processor" {
  source     = "./modules/lambda"
  name       = local.function_name
  role_arn   = module.iam.role_arn
  table_name = module.storage.name
  rule_arn   = "arn:aws:iot:${var.region}:${var.account_id}:rule/${local.rule_name}"
  account_id = var.account_id
  device_ids = var.device_ids
}
module "devices" {
  source     = "./modules/iot"
  name       = var.project_name
  device_ids = var.device_ids
  region     = var.region
  account_id = var.account_id
}
module "routing" {
  source       = "./modules/rules"
  name         = local.rule_name
  function_arn = module.processor.arn
  depends_on   = [module.processor]
}
module "monitoring" {
  source         = "./modules/monitoring"
  function_name  = local.function_name
  log_group_name = local.log_group_name
  table_name     = module.storage.name
}
