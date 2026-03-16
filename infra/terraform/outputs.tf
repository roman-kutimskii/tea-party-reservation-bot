output "server_ipv4" {
  value       = regcloud_server.app.ip_address
  description = "Public IPv4 address of the application host."
}

output "volume_mount_path" {
  value       = var.volume_mount_path
  description = "Expected application data directory path on the server disk."
}

output "ssh_command" {
  value       = "ssh deploy@${regcloud_server.app.ip_address}"
  description = "Suggested SSH command after Ansible bootstrap finishes."
}
