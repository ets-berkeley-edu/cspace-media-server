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
    error_message = "With simulated_cspace, each museum's server must be the simulator under its name: http://fakecspace.serena-<env_name>.internal:8180/<museum> (devtools.tf)."
  }
}

variable "allowed_cidrs" {
  description = "IPv4 addresses or ranges that may reach everything: the admin app, the ETL API and the image paths (D185). In personal-dev, Richard's and his testers' addresses (./serena aws allow-my-ip)."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "allowed_cidrs needs at least one IPv4 CIDR range, such as 203.0.113.7/32 (the distribution is IPv4-only)."
  }
}

variable "etl_cidrs" {
  description = "Addresses that may also reach /etl/ (the ETL servers; ETL_CIDRS, D185). Empty: only allowed_cidrs."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.etl_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "etl_cidrs must be IPv4 CIDR ranges."
  }
}

variable "admin_cidrs" {
  description = "Addresses that may also reach /admin (campus networks; ADMIN_CIDRS, D185). Empty: only allowed_cidrs."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.admin_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "admin_cidrs must be IPv4 CIDR ranges."
  }
}

variable "open_images" {
  description = "true lets anyone request the image paths and /health (production, D185); false limits them to allowed_cidrs too (personal-dev and QA)."
  type        = bool
  default     = false
}

variable "waf" {
  description = "true puts a WAF web ACL on the distribution (D186). Off in personal-dev, which is allowlisted anyway."
  type        = bool
  default     = false
}

variable "waf_rate_limit" {
  description = "Requests from one address in 5 minutes before WAF blocks it."
  type        = number
  default     = 3000
}

variable "origin_read_timeout" {
  description = "Seconds CloudFront waits for Serena's answer (D184): 60 at most without a quota increase, up to 180 with one."
  type        = number
  default     = 60

  validation {
    condition     = var.origin_read_timeout >= 1 && var.origin_read_timeout <= 180
    error_message = "origin_read_timeout must be 1 to 180 seconds."
  }
}

variable "vpc_cidr" {
  description = "The VPC's address range (a /16)."
  type        = string
  default     = "10.41.0.0/16"

  validation {
    condition     = can(regex("^10\\.\\d{1,3}\\.0\\.0/16$", var.vpc_cidr))
    error_message = "vpc_cidr must be a 10.x.0.0/16 range."
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
  description = "How many app tasks run (1 in personal-dev, 2 elsewhere)."
  type        = number
  default     = 1
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
