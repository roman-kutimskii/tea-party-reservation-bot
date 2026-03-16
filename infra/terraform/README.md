# Terraform Infrastructure

This stack provisions a single Reg.cloud server that hosts both the **stage** and **prod**
Compose stacks side by side.

Provisioned resources:

- one cloud server (disk is part of the size slug; pick a slug large enough for both stacks)
- server-level automatic backups enabled
- SSH keys registered in Reg.cloud
- application data root directory created via cloud-init at `volume_mount_path`
- firewall rules (SSH ingress, HTTP/HTTPS, node-exporter) are enforced by UFW through
  Ansible — the Reg.cloud Terraform provider does not expose a firewall resource

Typical workflow:

```bash
cp server.tfvars.example server.tfvars
# fill in token, ssh_public_keys, and allowed CIDRs
terraform init
terraform plan -var-file=server.tfvars
terraform apply -var-file=server.tfvars
```

Required secrets — pass through environment variables or a gitignored `*.tfvars` file:

- `TF_VAR_token` — API token from Reg.cloud panel → Settings
- alternatively set `token = "..."` in `server.tfvars`

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

Outputs include the server IPv4 address and application data root path.
