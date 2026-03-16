# Terraform Infrastructure

This stack targets a single Reg.cloud VPS for the long-polling MVP.

Provisioned resources:

- one cloud server for `bot`, `worker`, and `postgres` (disk is part of the size slug)
- server-level automatic backups enabled
- SSH keys registered in Reg.cloud
- application data directory created via cloud-init at `volume_mount_path`
- firewall rules (SSH ingress, HTTP/HTTPS, node-exporter) are enforced by UFW through
  Ansible — the Reg.cloud Terraform provider does not expose a firewall resource

Typical workflow:

```bash
cp stage.tfvars.example stage.tfvars
# fill in token, ssh_public_keys, and allowed CIDRs
terraform init
terraform plan -var-file=stage.tfvars
terraform apply -var-file=stage.tfvars
```

Required secrets — pass through environment variables or `terraform.tfvars`, never commit:

- `TF_VAR_token` — API token from Reg.cloud panel → Settings
- alternatively set `token = "..."` in a `*.tfvars` file that is gitignored

API endpoint (`api_url`) defaults to `https://api.cloudvps.reg.ru` and does not need
to be changed under normal circumstances.

Server size slugs follow the pattern `c<cpu>-m<ram>-d<disk>-<tier>`.
Available slugs and regions: https://cloud.reg.ru/panel/terraform

Operational reminders:

- restrict `ssh_allowed_cidrs` to the team CIDR before apply; do not leave it open to the world
- treat Terraform as infrastructure provisioning only; keep application secrets in server env
  files or Ansible vault values
- verify the deployment path matches the Compose and runbook expectations before handing the
  host to CD

Outputs include the server IPv4 address and deployment data directory path.
