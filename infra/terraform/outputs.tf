output "server_ipv4" {
  value       = hcloud_server.app.ipv4_address
  description = "Public IPv4 address of the application host."
}

output "volume_mount_path" {
  value       = var.volume_mount_path
  description = "Expected application data mount path."
}

output "ssh_command" {
  value       = "ssh deploy@${hcloud_server.app.ipv4_address}"
  description = "Suggested SSH command after Ansible bootstrap finishes."
}
