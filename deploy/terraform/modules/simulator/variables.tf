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

variable "running" {
  description = "false stops the simulator with the other services."
  type        = bool
}

variable "devtools_image_uri" {
  description = "The image that runs the simulator and the fake ETL (backend/Dockerfile)."
  type        = string
}

variable "log_retention_days" {
  description = "How long the simulator's and the fake ETL's logs are kept."
  type        = number
}

variable "vpc_id" {
  description = "The VPC, for the private DNS namespace and the security group."
  type        = string
}

variable "subnet_ids" {
  description = "The subnets the simulator and the fake ETL run in (ready to use: their routes in place)."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "true for tasks in public subnets with no NAT gateway."
  type        = bool
}

variable "web_security_group_id" {
  description = "The app tasks' security group, allowed to reach the simulator."
  type        = string
}

variable "worker_security_group_id" {
  description = "The worker tasks' security group, allowed to reach the simulator."
  type        = string
}

variable "alb_security_group_id" {
  description = "The load balancer's security group, which takes the fake ETL's calls."
  type        = string
}

variable "cluster_id" {
  description = "The ECS cluster (modules/core)."
  type        = string
}

variable "execution_role_arn" {
  description = "The ECS execution role (modules/core): pulls the image, writes the logs."
  type        = string
}

variable "kms_key_arn" {
  description = "Serena's key (modules/core), for the log group and the ETL tokens."
  type        = string
}

variable "etl_token_secret_arns" {
  description = "The museums' ETL token secrets (modules/core), which the fake ETL reads."
  type        = list(string)
}

variable "app_environment" {
  description = "Serena's settings (modules/core), which the fake ETL reads for the museums and their token secrets."
  type        = map(string)
}
