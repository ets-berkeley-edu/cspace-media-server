# The root checks the settings (deploy/terraform/personal/variables.tf); these take them as given.

variable "name" {
  description = "serena-<env_name>, the prefix of every resource's name."
  type        = string
}

variable "env_name" {
  description = "Environment name within the account."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "account_id" {
  description = "The AWS account."
  type        = string
}

variable "partition" {
  description = "The AWS partition (aws)."
  type        = string
}

variable "tenants" {
  description = "The museums and their CollectionSpace servers."
  type        = map(string)
}

variable "env_label" {
  description = "Which environment this is, shown in the admin app (SERENA_ENV_LABEL)."
  type        = string
}

variable "image_uri" {
  description = "The image the app and the worker run."
  type        = string
}

variable "running" {
  description = "false stops every service and silences the alarms."
  type        = bool
}

variable "protect_data" {
  description = "true where the data matters (D192)."
  type        = bool
}

variable "alert_email" {
  description = "Where alerts and alarms are emailed; empty: no subscription."
  type        = string
}

variable "log_retention_days" {
  description = "How long the app's and the worker's logs are kept."
  type        = number
}

variable "web_count" {
  description = "How many app tasks run."
  type        = number
}

variable "web_cpu" {
  description = "The app's task CPU units."
  type        = number
}

variable "web_memory" {
  description = "The app's task memory in MiB."
  type        = number
}

variable "web_disk_gib" {
  description = "The app's task ephemeral storage in GiB."
  type        = number
}

variable "worker_cpu" {
  description = "The worker's task CPU units."
  type        = number
}

variable "worker_memory" {
  description = "The worker's task memory in MiB."
  type        = number
}

# ---- from the root: the network and the load balancer ----------------------------------------------------------------

variable "subnet_ids" {
  description = "The subnets the app and the worker run in (ready to use: their routes in place)."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "true for tasks in public subnets with no NAT gateway (the personal root, D187)."
  type        = bool
}

variable "web_security_group_id" {
  description = "The app tasks' security group."
  type        = string
}

variable "worker_security_group_id" {
  description = "The worker tasks' security group."
  type        = string
}

variable "target_group_arn" {
  description = "The load balancer's target group for the app (its listener in place)."
  type        = string
}

variable "load_balancer_arn_suffix" {
  description = "The load balancer, for the alarms' dimensions."
  type        = string
}

variable "target_group_arn_suffix" {
  description = "The target group, for the alarms' dimensions."
  type        = string
}

# ---- from modules/files ----------------------------------------------------------------------------------------------

variable "distribution_arn" {
  description = "The distribution that reads the buckets through origin access control (D196)."
  type        = string
}

variable "cdn_base_url" {
  description = "https://<the distribution's address>: the files and the unavailable images (D199, D200)."
  type        = string
}

variable "delivery" {
  description = "Whether the museums' files are delivered (a signing key exists, D200)."
  type        = bool
}
