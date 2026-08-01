# Declared here (rather than relying solely on docker-compose.prod.yml's
# awslogs-create-group option) so the group has a real retention policy --
# awslogs-create-group alone creates a group that never expires, a slow,
# easy-to-forget cost leak. The IAM instance role already grants
# logs:CreateLogGroup/CreateLogStream/PutLogEvents/DescribeLogStreams on
# this exact name (infra/iam.tf, granted in slice 1 anticipating this).
# See docs/infra-guide.md.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ai-business-os/${var.environment}"
  retention_in_days = 30
}
