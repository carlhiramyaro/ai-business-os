# Parameter Store, not Secrets Manager -- free at this scale, and this
# project needs neither automatic rotation nor cross-account sharing.
# Parameter names deliberately mirror the env var names apps/api/.env.example
# already uses (rather than a translated/kebab-case scheme), so ec2.tf's
# user-data script can fetch everything under one path and write it
# straight into a .env file with zero name-mapping logic to get wrong.
# See docs/infra-guide.md.
#
# `deploy.yml` never touches these; only the box reads them, at boot and
# on each deploy, via the instance role's ssm:GetParametersByPath (iam.tf).

locals {
  ssm_path = "/ai-business-os/${var.environment}"
}

resource "aws_ssm_parameter" "db_host" {
  name  = "${local.ssm_path}/POSTGRES_HOST"
  type  = "String"
  value = aws_db_instance.main.address
}

resource "aws_ssm_parameter" "db_port" {
  name  = "${local.ssm_path}/POSTGRES_PORT"
  type  = "String"
  value = tostring(aws_db_instance.main.port)
}

resource "aws_ssm_parameter" "db_name" {
  name  = "${local.ssm_path}/POSTGRES_DB"
  type  = "String"
  value = var.db_name
}

resource "aws_ssm_parameter" "db_user" {
  name  = "${local.ssm_path}/POSTGRES_USER"
  type  = "String"
  value = var.db_username
}

resource "aws_ssm_parameter" "db_password" {
  name  = "${local.ssm_path}/POSTGRES_PASSWORD"
  type  = "SecureString"
  value = random_password.db.result
}

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "jwt_secret_key" {
  name  = "${local.ssm_path}/JWT_SECRET_KEY"
  type  = "SecureString"
  value = random_password.jwt_secret.result
}

resource "aws_ssm_parameter" "jwt_algorithm" {
  name  = "${local.ssm_path}/JWT_ALGORITHM"
  type  = "String"
  value = "HS256"
}

resource "aws_ssm_parameter" "access_token_expire_minutes" {
  name  = "${local.ssm_path}/ACCESS_TOKEN_EXPIRE_MINUTES"
  type  = "String"
  value = "15"
}

resource "aws_ssm_parameter" "refresh_token_expire_days" {
  name  = "${local.ssm_path}/REFRESH_TOKEN_EXPIRE_DAYS"
  type  = "String"
  value = "30"
}

resource "aws_ssm_parameter" "aws_region" {
  name  = "${local.ssm_path}/AWS_REGION"
  type  = "String"
  value = var.aws_region
}

resource "aws_ssm_parameter" "s3_bucket_name" {
  name  = "${local.ssm_path}/S3_BUCKET_NAME"
  type  = "String"
  value = var.s3_bucket_name
}

resource "aws_ssm_parameter" "domain_name" {
  name  = "${local.ssm_path}/DOMAIN_NAME"
  type  = "String"
  value = var.domain_name
}

resource "aws_ssm_parameter" "allowed_origins" {
  name  = "${local.ssm_path}/ALLOWED_ORIGINS"
  type  = "String"
  value = "https://app.${var.domain_name}"
}

resource "aws_ssm_parameter" "mapping_confidence_threshold" {
  name  = "${local.ssm_path}/MAPPING_CONFIDENCE_THRESHOLD"
  type  = "String"
  value = "0.8"
}

# Real value has no correct default -- Terraform creates the parameter as
# a placeholder so every other piece of automation (the user-data fetch
# script, the IAM policy path) is in place from the first apply, then
# `ignore_changes` stops Terraform from ever fighting the real value once
# it's set by hand:
#   aws ssm put-parameter --name /ai-business-os/prod/OPENAI_API_KEY \
#     --type SecureString --value sk-... --overwrite
resource "aws_ssm_parameter" "openai_api_key" {
  name  = "${local.ssm_path}/OPENAI_API_KEY"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}
