# Two identities:
#   1. A GitHub OIDC trust relationship + role that CI assumes to push
#      images and trigger a deploy -- no long-lived AWS access key ever
#      sits in a GitHub secret.
#   2. An EC2 instance profile the box itself assumes, scoped to exactly
#      what it needs: pull from ECR, read/write the existing uploads
#      bucket, read SSM parameters, write CloudWatch logs, and be reachable
#      via SSM Session Manager (no SSH key anywhere).
# See docs/infra-guide.md's OIDC and IAM sections.

# ---- GitHub Actions OIDC ----

data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Restricts to THIS repo, any branch/tag/PR. Tighten to
    # "repo:${var.github_repository}:ref:refs/heads/main" once only
    # main is ever allowed to deploy.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy" {
  name               = "ai-business-os-${var.environment}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    sid       = "PushImages"
    actions   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability", "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload"]
    resources = [aws_ecr_repository.api.arn, aws_ecr_repository.web.arn]
  }

  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this specific action does not support resource-level restriction
  }

  statement {
    sid     = "TriggerDeployViaSsm"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ec2:${var.aws_region}:*:instance/${aws_instance.app.id}",
      "arn:aws:ssm:${var.aws_region}:*:document/AWS-RunShellScript",
    ]
  }

  statement {
    sid       = "ReadDeployCommandStatus"
    actions   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    resources = ["*"] # these read actions target a command ID, not an ARN-addressable resource
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "deploy"
  role   = aws_iam_role.github_actions_deploy.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}

# ---- EC2 instance role ----

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "ai-business-os-${var.environment}-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

# SSM Session Manager (shell access with no open SSH port, no key pair)
# and the ability to run commands pushed by the deploy workflow.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "instance" {
  statement {
    sid       = "PullImages"
    actions   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.api.arn, aws_ecr_repository.web.arn]
  }

  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid     = "ReadDeployConfig"
    actions = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    # Both forms are required -- ssm:GetParametersByPath is called with
    # --path /ai-business-os/prod (no trailing segment), and IAM checks
    # that exact path against the resource ARN literally, which the /*
    # wildcard alone does NOT match (it requires at least one more path
    # segment). GetParameter/GetParameters on individual parameters still
    # need the wildcard form. Discovered when the box's refresh-env.sh
    # failed deploy #1 with AccessDeniedException on exactly this action --
    # see docs/decisions.md.
    resources = [
      "arn:aws:ssm:${var.aws_region}:*:parameter/ai-business-os/${var.environment}",
      "arn:aws:ssm:${var.aws_region}:*:parameter/ai-business-os/${var.environment}/*",
    ]
  }

  statement {
    sid       = "DecryptSecureStringParams"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:*:key/*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }

  # Least-privilege on the EXISTING uploads bucket (created before this
  # Terraform config -- see variables.tf's s3_bucket_name), not a new
  # bucket managed here.
  statement {
    sid       = "ReadWriteUploadsBucket"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.s3_bucket_name}/*"]
  }

  statement {
    sid       = "ListUploadsBucket"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.s3_bucket_name}"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${var.aws_region}:*:log-group:/ai-business-os/${var.environment}*"]
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "app"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "ai-business-os-${var.environment}-instance"
  role = aws_iam_role.instance.name
}
