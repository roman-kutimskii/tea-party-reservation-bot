variable "project_name" {
  type        = string
  description = "Project name used in resource names."
  default     = "tea-party-reservation-bot"
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
}

variable "location" {
  type        = string
  description = "Hetzner Cloud location."
  default     = "fsn1"
}

variable "server_type" {
  type        = string
  description = "Hetzner server type."
  default     = "cpx21"
}

variable "server_image" {
  type        = string
  description = "Server image slug."
  default     = "ubuntu-24.04"
}

variable "server_backups_enabled" {
  type        = bool
  description = "Enable Hetzner server backups."
  default     = true
}

variable "server_backup_window" {
  type        = string
  description = "Preferred Hetzner backup window."
  default     = "22-02"
}

variable "volume_size_gb" {
  type        = number
  description = "Persistent data volume size in GB."
  default     = 40
}

variable "volume_mount_path" {
  type        = string
  description = "Mount path for the attached volume."
  default     = "/srv/tea-party-reservation-bot"
}

variable "ssh_public_keys" {
  type        = map(string)
  description = "SSH public keys to register in Hetzner Cloud."
}

variable "ssh_allowed_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to SSH to the host."
}

variable "monitoring_allowed_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to scrape node exporter."
  default     = []
}

variable "enable_public_web_ports" {
  type        = bool
  description = "Open 80/443 for future webhook or reverse proxy use."
  default     = false
}

variable "labels" {
  type        = map(string)
  description = "Extra labels applied to resources."
  default     = {}
}
