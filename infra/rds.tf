# Managed Postgres for customer data -- backups and point-in-time
# recovery matter here in a way a container-with-a-volume can't provide.
# See docs/infra-guide.md.
#
# The master password is generated once and stored as a Secure SSM
# parameter (ssm.tf), never in a .tf file or state diff shown on screen --
# `random_password` still lands in the state file itself, which is exactly
# why state lives encrypted in S3 (versions.tf), not on a laptop.
resource "random_password" "db" {
  length  = 32
  special = false # avoids characters that need URL-encoding in a DATABASE_URL
}

resource "aws_db_instance" "main" {
  identifier     = "ai-business-os-${var.environment}"
  engine         = "postgres"
  engine_version = "18.4" # matches pgvector/pgvector:pg18 used locally and in CI -- see the plan's "verify before building" note
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # 30, not the RDS default of 7 -- v0.5 slice 3 (multi-tenant hardening,
  # docs/decisions.md [2026-08-01]): 7 days means corruption discovered on
  # day 8 is unrecoverable. Negligible cost difference at this data size.
  backup_retention_period = 30
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:30-mon:05:30"

  # Deliberately on: `terraform destroy` will refuse to remove this
  # instance until it's flipped off, forcing a conscious decision before
  # customer data is deleted. See docs/infra-guide.md.
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "ai-business-os-${var.environment}-final"

  # `vector` (pgvector) is enabled via CREATE EXTENSION inside the DB
  # itself once migrations run -- RDS Postgres 15+ supports it without any
  # extra parameter-group/option-group setup, unlike some other extensions.

  tags = { Name = "ai-business-os-${var.environment}" }
}
