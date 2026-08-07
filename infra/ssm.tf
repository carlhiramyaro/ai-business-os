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
resource "aws_ssm_parameter" "environment" {
  name  = "${local.ssm_path}/ENVIRONMENT"
  type  = "String"
  value = var.environment
}

resource "aws_ssm_parameter" "log_level" {
  name  = "${local.ssm_path}/LOG_LEVEL"
  type  = "String"
  value = "INFO"
}

resource "aws_ssm_parameter" "openai_api_key" {
  name  = "${local.ssm_path}/OPENAI_API_KEY"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

# Same placeholder pattern as OPENAI_API_KEY above -- create a Sentry
# project and set the real value once you have one:
#   aws ssm put-parameter --name /ai-business-os/prod/SENTRY_DSN \
#     --type SecureString --value https://...@....ingest.sentry.io/... --overwrite
resource "aws_ssm_parameter" "sentry_dsn" {
  name  = "${local.ssm_path}/SENTRY_DSN"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "sentry_environment" {
  name  = "${local.ssm_path}/SENTRY_ENVIRONMENT"
  type  = "String"
  value = var.environment
}

resource "aws_ssm_parameter" "sentry_traces_sample_rate" {
  name  = "${local.ssm_path}/SENTRY_TRACES_SAMPLE_RATE"
  type  = "String"
  value = "0.0"
}

# Same placeholder pattern as OPENAI_API_KEY/SENTRY_DSN above -- create a
# Langfuse project and set the real values once you have them:
#   aws ssm put-parameter --name /ai-business-os/prod/LANGFUSE_PUBLIC_KEY \
#     --type SecureString --value pk-lf-... --overwrite
#   aws ssm put-parameter --name /ai-business-os/prod/LANGFUSE_SECRET_KEY \
#     --type SecureString --value sk-lf-... --overwrite
resource "aws_ssm_parameter" "langfuse_public_key" {
  name  = "${local.ssm_path}/LANGFUSE_PUBLIC_KEY"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "langfuse_secret_key" {
  name  = "${local.ssm_path}/LANGFUSE_SECRET_KEY"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "langfuse_host" {
  name = "${local.ssm_path}/LANGFUSE_HOST"
  type = "String"
  # US region, not the "https://cloud.langfuse.com" EU default this was
  # originally declared with -- the actual Langfuse project created for
  # this app lives on the US region (its API keys are region-scoped, so
  # this must match). Originally fixed by hand via `aws ssm put-parameter`
  # during the observability slice's production drill; declaring it here
  # too so a future `terraform apply` doesn't silently revert it back to
  # the EU default and break tracing again. See docs/decisions.md.
  value = "https://us.cloud.langfuse.com"
}

resource "aws_ssm_parameter" "langfuse_tracing_enabled" {
  name  = "${local.ssm_path}/LANGFUSE_TRACING_ENABLED"
  type  = "String"
  value = "true"
}

# v0.5 slice 3 (multi-tenant hardening, docs/decisions.md [2026-08-01]):
# rate limiting. Every value here has an in-code default (app/rate_limit.py,
# app/routers/auth.py) -- these entries exist so a limit can be tuned in
# production by changing one value + redeploying, never by editing code.
# A separate logical Redis DB from the Celery broker (db 0) so debugging
# one never resets the other's counters.
resource "aws_ssm_parameter" "rate_limit_enabled" {
  name  = "${local.ssm_path}/RATE_LIMIT_ENABLED"
  type  = "String"
  value = "true"
}

resource "aws_ssm_parameter" "rate_limit_storage_uri" {
  name  = "${local.ssm_path}/RATE_LIMIT_STORAGE_URI"
  type  = "String"
  value = "redis://redis:6379/1"
}

resource "aws_ssm_parameter" "rate_limit_default" {
  name  = "${local.ssm_path}/RATE_LIMIT_DEFAULT"
  type  = "String"
  value = "300/minute"
}

# Auth endpoints (app/routers/auth.py) -- security-motivated, not cost.
resource "aws_ssm_parameter" "rate_limit_register" {
  name  = "${local.ssm_path}/RATE_LIMIT_REGISTER"
  type  = "String"
  value = "5/hour"
}

resource "aws_ssm_parameter" "rate_limit_login_ip" {
  name  = "${local.ssm_path}/RATE_LIMIT_LOGIN_IP"
  type  = "String"
  value = "100/hour"
}

resource "aws_ssm_parameter" "rate_limit_login_email" {
  name  = "${local.ssm_path}/RATE_LIMIT_LOGIN_EMAIL"
  type  = "String"
  value = "10/hour"
}

resource "aws_ssm_parameter" "rate_limit_refresh" {
  name  = "${local.ssm_path}/RATE_LIMIT_REFRESH"
  type  = "String"
  value = "60/hour"
}

# LLM/expensive endpoints -- cost circuit-breakers, not security.
resource "aws_ssm_parameter" "rate_limit_chat" {
  name  = "${local.ssm_path}/RATE_LIMIT_CHAT"
  type  = "String"
  value = "20/minute;300/day"
}

resource "aws_ssm_parameter" "rate_limit_reports" {
  name  = "${local.ssm_path}/RATE_LIMIT_REPORTS"
  type  = "String"
  value = "10/hour"
}

resource "aws_ssm_parameter" "rate_limit_insights" {
  name  = "${local.ssm_path}/RATE_LIMIT_INSIGHTS"
  type  = "String"
  value = "10/hour"
}

resource "aws_ssm_parameter" "rate_limit_uploads" {
  name  = "${local.ssm_path}/RATE_LIMIT_UPLOADS"
  type  = "String"
  value = "30/hour"
}

resource "aws_ssm_parameter" "rate_limit_documents" {
  name  = "${local.ssm_path}/RATE_LIMIT_DOCUMENTS"
  type  = "String"
  value = "60/hour"
}

resource "aws_ssm_parameter" "rate_limit_webhook" {
  name  = "${local.ssm_path}/RATE_LIMIT_WEBHOOK"
  type  = "String"
  value = "120/minute"
}

# v0.6 slice 1 (WhatsApp channel, docs/decisions.md): Meta Cloud API
# credentials. Same REPLACE_ME_MANUALLY placeholder pattern as
# OPENAI_API_KEY/SENTRY_DSN/LANGFUSE_* above -- set the real values once a
# Meta app + WhatsApp product + system-user token exist:
#   aws ssm put-parameter --name /ai-business-os/prod/WHATSAPP_ACCESS_TOKEN \
#     --type SecureString --value EAA... --overwrite
#   aws ssm put-parameter --name /ai-business-os/prod/WHATSAPP_APP_SECRET \
#     --type SecureString --value ... --overwrite
# app/whatsapp.py's is_configured() treats an unset/placeholder value as
# "this channel is off" -- a production deploy with these still at
# REPLACE_ME_MANUALLY runs fine, it just can't send/verify WhatsApp
# messages yet, same story as an unconfigured SENTRY_DSN.
resource "aws_ssm_parameter" "whatsapp_phone_number_id" {
  name  = "${local.ssm_path}/WHATSAPP_PHONE_NUMBER_ID"
  type  = "String"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "whatsapp_access_token" {
  name  = "${local.ssm_path}/WHATSAPP_ACCESS_TOKEN"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "whatsapp_app_secret" {
  name  = "${local.ssm_path}/WHATSAPP_APP_SECRET"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

# Not a secret -- this is the shared-secret CHECK value the app compares
# an inbound GET's hub.verify_token against during Meta's webhook
# subscription handshake (app/routers/webhooks.py), not a credential used
# to authenticate outbound calls. Still SecureString for consistency with
# everything else in this "invented once, pasted into Meta's dashboard"
# category, and because ignore_changes means the cost difference is moot.
resource "aws_ssm_parameter" "whatsapp_verify_token" {
  name  = "${local.ssm_path}/WHATSAPP_VERIFY_TOKEN"
  type  = "SecureString"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "whatsapp_api_version" {
  name  = "${local.ssm_path}/WHATSAPP_API_VERSION"
  type  = "String"
  value = "v21.0"
}

# The human-readable number owners are told to text (Settings page) --
# cosmetic display text, not used for any API call (WHATSAPP_PHONE_NUMBER_ID
# is what actually addresses the Cloud API). Left blank until a real test/
# production number exists; app/routers/channels.py omits it from the
# response when unset.
resource "aws_ssm_parameter" "whatsapp_display_number" {
  name  = "${local.ssm_path}/WHATSAPP_DISPLAY_NUMBER"
  type  = "String"
  value = "REPLACE_ME_MANUALLY"

  lifecycle {
    ignore_changes = [value]
  }
}
