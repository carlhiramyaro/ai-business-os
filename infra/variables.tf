variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name, used in tags and resource names."
  type        = string
  default     = "prod"
}

variable "domain_name" {
  description = <<-EOT
    Root domain for this deployment (e.g. "example.com"). The web app is
    served at app.<domain_name>, the API at api.<domain_name>. Required --
    Caddy's automatic HTTPS (docker-compose.prod.yml) cannot obtain a
    Let's Encrypt certificate for a bare IP address.
  EOT
  type        = string
  default     = "iamledger.app"
}

variable "instance_type" {
  description = <<-EOT
    EC2 instance type running the whole docker compose stack. t3.medium
    (x86_64) rather than the ~20% cheaper t4g.medium (arm64) so CI's
    linux/amd64 image builds don't need QEMU emulation, which is
    painfully slow for pandas/numpy. Revisit arm64 once the pipeline is
    proven -- see docs/infra-guide.md's "path to ECS" section for the
    same tradeoff.
  EOT
  type        = string
  default     = "t3.medium"
}

variable "root_volume_size_gb" {
  description = "EBS root volume size in GB."
  type        = number
  default     = 30
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "RDS allocated storage in GB."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Default database name created on the RDS instance."
  type        = string
  default     = "ai_business_os"
}

variable "db_username" {
  description = "Master username for RDS."
  type        = string
  default     = "ai_business_os_app"
}

variable "s3_bucket_name" {
  description = <<-EOT
    Existing S3 bucket for CSV/document uploads (created outside
    Terraform, before this project's Docker/AWS work began -- see
    agent-instructions.md's Stack section). Referenced by IAM policy only,
    not managed here, so `terraform destroy` never touches the data in it.
  EOT
  type        = string
  default     = "ai-business-os-uploads-dev"
}

variable "github_repository" {
  description = <<-EOT
    "owner/repo" allowed to assume the CI deploy role via GitHub's OIDC
    provider (e.g. "carlhiramyaro/ai-business-os"). Scopes which
    repository can push images and trigger a deploy -- see iam.tf.
  EOT
  type        = string
  default     = "carlhiramyaro/ai-business-os"
}
