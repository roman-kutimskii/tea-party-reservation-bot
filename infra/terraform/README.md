# Terraform Infrastructure

This stack targets a single Hetzner Cloud VPS for the long-polling MVP.

Provisioned shape:

- one VPS for `bot`, `worker`, and `postgres`
- one attached volume mounted at `/srv/tea-party-reservation-bot`
- one restrictive firewall with SSH, HTTP/HTTPS, and optional metrics access
- provider-level server backups enabled for daily snapshots of the VM disk
- labels to drive external volume snapshot automation if the team adds it later

Typical workflow:

```bash
cp stage.tfvars.example stage.tfvars
terraform init
terraform plan -var-file=stage.tfvars
terraform apply -var-file=stage.tfvars
```

Required secrets are passed through environment variables, not committed to git:

- `HCLOUD_TOKEN`

Outputs include the server IPv4 address and deployment mount path.
