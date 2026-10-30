variable "account_id" {
  description = "The AWS account this environment belongs to; Terraform refuses to run against any other."
  type        = string

  validation {
    condition     = can(regex("^\\d{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account number."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "env_name" {
  description = "Environment name within the account, used in every resource name (serena-<env>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "image_uri" {
  description = "The image the app and the worker run, <repository URL>:<tag> (./serena aws deploy builds and pushes it)."
  type        = string
}

variable "env_label" {
  description = "Which environment this is, shown in the admin app (SERENA_ENV_LABEL)."
  type        = string
  default     = ""
}

variable "running" {
  description = "false stops every service (./serena aws pause) to save money; the data stays."
  type        = bool
  default     = true
}

variable "tenants" {
  description = "The museums this environment serves, each with its CollectionSpace server (without /cspace-services): {pahma = \"https://pahma.qa.collectionspace.org\"}. Each needs backend/serena/museums/<museum>.yaml."
  type        = map(string)

  validation {
    condition     = length(var.tenants) > 0
    error_message = "tenants needs at least one museum."
  }

  validation {
    condition     = alltrue([for m in keys(var.tenants) : contains(["bampfa", "botgarden", "cinefiles", "pahma", "ucjeps"], m)])
    error_message = "Each museum in tenants must be one Serena has a configuration for (backend/serena/museums/): bampfa, botgarden, cinefiles, pahma, ucjeps."
  }

  validation {
    condition     = alltrue([for url in values(var.tenants) : can(regex("^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[a-z]+)?$", url))])
    error_message = "Each server in tenants must be an address, such as https://pahma.qa.collectionspace.org (no trailing /)."
  }

  validation {
    condition     = !var.simulated_cspace || alltrue([for m, url in var.tenants : url == "http://fakecspace.serena-${var.env_name}.internal:8180/${m}"])
    error_message = "With simulated_cspace, each museum's server must be the simulator under its name: http://fakecspace.serena-<env_name>.internal:8180/<museum> (../modules/simulator)."
  }
}

variable "etl_cidrs" {
  description = "Addresses that may reach /etl/ (the ETL servers; ETL_CIDRS, D291). With the simulator, include the NAT gateway's outbound address, which the fake ETL's calls come from."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.etl_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "etl_cidrs must be IPv4 CIDR ranges."
  }
}

variable "admin_cidrs" {
  description = "Addresses that may reach /admin (campus and VPN ranges; ADMIN_CIDRS, D291); they reach the image paths too (TQ6)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.admin_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "admin_cidrs must be IPv4 CIDR ranges."
  }
}

variable "waf" {
  description = "true puts the regional web ACL on the load balancer (D292)."
  type        = bool
  default     = true
}

variable "waf_rate_limit" {
  description = "Requests from one address in 5 minutes before WAF blocks it."
  type        = number
  default     = 3000
}

variable "cdn_keys" {
  description = "true once ./serena aws has made the CloudFront signing key: Terraform reads the public keys from the SSM parameter /serena-<env>/cloudfront-public-keys, and the museums' files are delivered (../modules/files, D200). false: nothing is delivered yet."
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Where alerts and alarms are emailed (ALERT_EMAIL in the uncommitted .local.conf, D201); empty: no email subscription. Confirmed with ./serena aws confirm-alerts."
  type        = string
  default     = ""

  validation {
    condition     = var.alert_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address, or empty."
  }
}

variable "protect_data" {
  description = "true where the data matters (QA, production; D192): tables can't be deleted, destroy won't empty buckets, secrets and the key are kept 30 days. false (personal-dev) lets ./serena aws destroy remove everything."
  type        = bool
  default     = false
}

variable "simulated_cspace" {
  description = "true runs the simulated CollectionSpace in the environment, and every museum uses it, and lets the fake ETL run as a one-off task (devtools.tf, D189). Never with data that matters."
  type        = bool
  default     = false

  validation {
    condition     = !(var.simulated_cspace && var.protect_data)
    error_message = "simulated_cspace can't be used with protect_data: the simulator's data is lost on every restart, and its accounts' passwords are public."
  }
}

variable "devtools_image_uri" {
  description = "The image that runs the simulator and the fake ETL (backend/Dockerfile), <repository URL>:<tag>. Empty without simulated_cspace."
  type        = string
  default     = ""

  validation {
    condition     = !var.simulated_cspace || length(var.devtools_image_uri) > 0
    error_message = "simulated_cspace needs devtools_image_uri."
  }
}

# Task sizes (D188; Fargate allows only some memory values for each cpu value).
variable "web_count" {
  description = "How many app tasks run (2 in QA and production, D188)."
  type        = number
  default     = 2
}

variable "web_cpu" {
  description = "The app's task CPU units (1024 = 1 vCPU)."
  type        = number
  default     = 1024
}

variable "web_memory" {
  description = "The app's task memory in MiB."
  type        = number
  default     = 2048
}

variable "web_disk_gib" {
  description = "The app's task ephemeral storage in GiB, where fetched files are written while they're checked (design: Image fetch)."
  type        = number
  default     = 50
}

variable "worker_cpu" {
  description = "The worker's task CPU units."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "The worker's task memory in MiB."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "How long the app's and the worker's logs are kept (design: Logs and metrics)."
  type        = number
  default     = 30
}

# ---- the split (D289 to D294, D303, D306) ---------------------------------------------------------------------------

variable "apache_cidrs" {
  description = "The outbound addresses of the Apache hosts that proxy the legacy image paths to Serena (APACHE_CIDRS, D290, D306)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.apache_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "apache_cidrs must be IPv4 CIDR ranges."
  }
}

variable "vpc_id" {
  description = "The VPC Operations provides (D303)."
  type        = string
}

variable "app_subnet_ids" {
  description = "The private subnets the tasks run in, behind the VPC's NAT gateway, in at least two zones (D303)."
  type        = list(string)

  validation {
    condition     = length(var.app_subnet_ids) >= 2
    error_message = "app_subnet_ids needs at least two subnets, in different zones."
  }
}

variable "lb_subnet_ids" {
  description = "The public subnets the internet-facing load balancer is in, in at least two zones (D303)."
  type        = list(string)

  validation {
    condition     = length(var.lb_subnet_ids) >= 2
    error_message = "lb_subnet_ids needs at least two subnets, in different zones."
  }
}

variable "create_gateway_endpoints" {
  description = "true adds S3 and DynamoDB gateway endpoints to the app subnets' route tables; false where the VPC has them already (D303)."
  type        = bool
  default     = false
}

variable "domain_name" {
  description = "The app's campus name from DevOps (D293), such as serena-qa.<campus domain>."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.domain_name))
    error_message = "domain_name must be a host name, such as serena-qa.example.edu."
  }
}

variable "certificate_arn" {
  description = "The domain's issued ACM certificate (../registry makes it; ./serena aws passes it once DNS has validated it, D294)."
  type        = string
}
