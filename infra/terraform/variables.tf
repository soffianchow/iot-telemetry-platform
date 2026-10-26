variable "region" {
  type    = string
  default = "ap-southeast-1"
}
variable "account_id" {
  description = "Target AWS account ID; placeholder supports offline validation. Do not deploy Phase 1."
  type        = string
  default     = "000000000000"
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Provide a 12-digit AWS account ID."
  }
}
variable "project_name" {
  type    = string
  default = "systems-lab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.project_name))
    error_message = "Use 3-30 lowercase letters, numbers, or hyphens, beginning with a letter."
  }
}
variable "device_ids" {
  type    = set(string)
  default = ["device-001", "device-002", "device-003", "device-004", "device-005", "device-006", "device-007", "device-008", "device-009", "device-010"]
  validation {
    condition     = length(var.device_ids) > 0 && alltrue([for id in var.device_ids : can(regex("^[a-zA-Z0-9_-]{1,64}$", id))])
    error_message = "Device IDs must contain 1-64 letters, digits, hyphens, or underscores."
  }
}
