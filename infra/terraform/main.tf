locals {
  server_name = var.project_name
}

# SSH keys — one entry per item in the ssh_public_keys map.
resource "regcloud_ssh_key" "this" {
  for_each   = var.ssh_public_keys
  name       = "${local.server_name}-${each.key}"
  public_key = each.value
}

# Single application server hosting both stage and prod Compose stacks.
# Disk size is encoded in the size slug (e.g. c4-m8-d80-hp → 80 GB included).
# Firewall rules (SSH, HTTP/HTTPS, node-exporter) are managed by UFW via Ansible
# because the Reg.cloud Terraform provider does not expose a firewall resource.
resource "regcloud_server" "app" {
  name        = local.server_name
  size        = var.server_size
  image       = var.server_image
  region_slug = var.region_slug
  ssh_keys    = [for k in regcloud_ssh_key.this : k.fingerprint]
  backups     = var.server_backups_enabled

  isp_license_size = null

  user_data = templatefile("${path.module}/templates/cloud-init.yaml.tftpl", {
    timezone          = "Europe/Moscow"
    volume_mount_path = var.volume_mount_path
  })
}
