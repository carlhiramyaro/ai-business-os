# Two security groups: one for the EC2 box (public web traffic only), one
# for RDS (reachable only from that box's SG, never from the internet).
# No SSH ingress anywhere -- see ec2.tf's IAM role for SSM Session Manager,
# which replaces key-based SSH entirely.

resource "aws_security_group" "instance" {
  name_prefix = "ai-business-os-${var.environment}-instance-"
  description = "EC2 instance running the docker compose stack"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP (redirects to HTTPS; also ACME HTTP-01 challenge)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "ai-business-os-${var.environment}-instance" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "ai-business-os-${var.environment}-rds-"
  description = "RDS Postgres, reachable only from the app instance"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from the app instance only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.instance.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "ai-business-os-${var.environment}-rds" }

  lifecycle {
    create_before_destroy = true
  }
}
