locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_labels = merge({
    project     = var.project_name
    environment = var.environment
    managed_by  = "terraform"
    backup      = tostring(var.server_backups_enabled)
  }, var.labels)
}

resource "hcloud_ssh_key" "this" {
  for_each   = var.ssh_public_keys
  name       = "${local.name_prefix}-${each.key}"
  public_key = each.value
  labels     = local.common_labels
}

resource "hcloud_firewall" "app" {
  name   = "${local.name_prefix}-fw"
  labels = local.common_labels

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.ssh_allowed_cidrs
  }

  dynamic "rule" {
    for_each = var.enable_public_web_ports ? ["80", "443"] : []
    content {
      direction  = "in"
      protocol   = "tcp"
      port       = rule.value
      source_ips = ["0.0.0.0/0", "::/0"]
    }
  }

  dynamic "rule" {
    for_each = length(var.monitoring_allowed_cidrs) > 0 ? ["9100"] : []
    content {
      direction  = "in"
      protocol   = "tcp"
      port       = rule.value
      source_ips = var.monitoring_allowed_cidrs
    }
  }

  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "1-65535"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "1-65535"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "icmp"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "app" {
  name        = local.name_prefix
  server_type = var.server_type
  image       = var.server_image
  location    = var.location
  ssh_keys    = values(hcloud_ssh_key.this)[*].name
  backups     = var.server_backups_enabled
  backup_window = var.server_backup_window
  firewall_ids  = [hcloud_firewall.app.id]
  labels        = local.common_labels

  user_data = templatefile("${path.module}/templates/cloud-init.yaml.tftpl", {
    timezone          = "Europe/Moscow"
    volume_mount_path = var.volume_mount_path
    volume_name       = "${local.name_prefix}-data"
  })
}

resource "hcloud_volume" "app_data" {
  name     = "${local.name_prefix}-data"
  size     = var.volume_size_gb
  location = var.location
  labels = merge(local.common_labels, {
    snapshot_policy = "daily"
    snapshot_retention_days = "7"
  })
  automount = false
  format    = "ext4"
}

resource "hcloud_volume_attachment" "app_data" {
  volume_id = hcloud_volume.app_data.id
  server_id = hcloud_server.app.id
  automount = false
}
