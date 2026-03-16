variable "token" {
  type        = string
  description = "Reg.cloud API token."
  sensitive   = true
}

variable "api_url" {
  type        = string
  description = "Reg.cloud API endpoint."
  default     = "https://api.cloudvps.reg.ru"
}

variable "project_name" {
  type        = string
  description = "Project name used in resource names."
  default     = "tea-party-reservation-bot"
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
}

variable "region_slug" {
  type        = string
  description = "Reg.cloud region slug."
  default     = "openstack-msk1"
}

variable "server_size" {
  type        = string
  description = "Reg.cloud server size slug (format: c<cpu>-m<ram>-d<disk>-<tier>)."
  default     = "c2-m4-d40-hp"
}

variable "server_image" {
  type        = string
  description = "Server OS image slug."
  default     = "ubuntu-24-04-amd64"
}

variable "server_backups_enabled" {
  type        = bool
  description = "Enable automatic server backups."
  default     = true
}

variable "ssh_public_keys" {
  type        = map(string)
  description = "SSH public keys to register in Reg.cloud (map of name => public key string)."
}

variable "ssh_allowed_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to SSH to the host."
}

variable "monitoring_allowed_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to scrape node exporter (informational — enforced by UFW via Ansible)."
  default     = []
}

variable "enable_public_web_ports" {
  type        = bool
  description = "Open 80/443 for future webhook or reverse proxy use (informational — enforced by UFW via Ansible)."
  default     = false
}

variable "volume_mount_path" {
  type        = string
  description = "Mount path for application data on the server disk."
  default     = "/srv/tea-party-reservation-bot"
}

variable "labels" {
  type        = map(string)
  description = "Extra metadata tags applied to resources where supported."
  default     = {}
}
