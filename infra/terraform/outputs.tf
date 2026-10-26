output "thing_names" { value = module.devices.thing_names }
output "telemetry_table_name" { value = module.storage.name }
output "lambda_function_name" { value = module.processor.name }
output "iot_policy_names" { value = module.devices.policy_names }
