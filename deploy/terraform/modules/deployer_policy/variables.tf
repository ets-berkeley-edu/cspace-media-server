variable "name" {
  description = "The managed policies' names, before -1, -2 …; never serena-*, which the policy itself may change."
  type        = string

  validation {
    condition     = !startswith(var.name, "serena-")
    error_message = "The deployer policy's parts mustn't be named serena-*: the policy lets its holder change those."
  }
}

variable "role_name" {
  description = "The role the parts are attached to."
  type        = string
}
