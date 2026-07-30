# The single box running the whole docker compose stack. See
# docs/infra-guide.md's "AWS building blocks" and "Operating it" sections.

# AWS's own SSM public parameter for the latest AL2023 AMI -- always
# resolves to the current image at apply time rather than a hardcoded,
# eventually-stale AMI ID.
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_eip" "app" {
  domain = "vpc"
  tags   = { Name = "ai-business-os-${var.environment}" }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.instance.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  # No key_name -- no SSH key pair is created or accepted. Shell access is
  # via SSM Session Manager only (granted by the instance role's
  # AmazonSSMManagedInstanceCore attachment in iam.tf):
  #   aws ssm start-session --target <instance-id>

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
    encrypted   = true
  }

  # docker-compose.prod.yml and Caddyfile are embedded straight from the
  # repo (not synced separately by the deploy workflow) -- so editing
  # either one and running `terraform apply` is the only way those files
  # change on the box. `user_data_replace_on_change` below means that
  # apply replaces the instance outright with the new content baked in,
  # which keeps "what's on the box" and "what's in git" from ever
  # drifting apart, at the cost of that one apply causing a swap rather
  # than an in-place update. Anything that changes far more often than
  # this -- application code -- ships through the separate, much faster
  # image-tag-only deploy path in .github/workflows/deploy.yml instead.
  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    aws_region                  = var.aws_region
    ssm_path                    = local.ssm_path
    ecr_account                 = data.aws_caller_identity.current.account_id
    docker_compose_prod_content = file("${path.module}/../docker-compose.prod.yml")
    caddyfile_content           = file("${path.module}/../Caddyfile")
  })

  # Changing user_data on an already-running instance doesn't rerun it
  # (cloud-init only runs on first boot) -- this forces a replacement when
  # the bootstrap script itself changes, which is the correct behavior
  # here since Terraform can't "patch" a box that's already finished
  # booting.
  user_data_replace_on_change = true

  tags = { Name = "ai-business-os-${var.environment}" }
}

data "aws_caller_identity" "current" {}
