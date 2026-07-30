output "instance_id" {
  description = "EC2 instance ID -- use with `aws ssm start-session --target <id>` for shell access (no SSH key exists)."
  value       = aws_instance.app.id
}

output "elastic_ip" {
  value = aws_eip.app.public_ip
}

output "rds_endpoint" {
  value     = aws_db_instance.main.address
  sensitive = false # a hostname, not a secret -- the password lives only in SSM (ssm.tf)
}

output "ecr_repository_urls" {
  value = {
    api = aws_ecr_repository.api.repository_url
    web = aws_ecr_repository.web.repository_url
  }
}

output "github_actions_role_arn" {
  description = "Put this in the deploy workflow's `role-to-assume` input."
  value       = aws_iam_role.github_actions_deploy.arn
}

output "route53_name_servers" {
  description = "If the domain is registered outside Route 53, point the registrar's nameservers at these."
  value       = aws_route53_zone.main.name_servers
}

output "next_steps" {
  value = <<-EOT
    1. Set the real OpenAI key (Terraform intentionally leaves a placeholder):
       aws ssm put-parameter --name ${local.ssm_path}/OPENAI_API_KEY \
         --type SecureString --value sk-... --overwrite --region ${var.aws_region}
    2. If the domain is registered outside Route 53, delegate it to the
       name servers in the `route53_name_servers` output above.
    3. Add `github_actions_role_arn`'s value to .github/workflows/deploy.yml.
    4. Push to main to run the first real deploy -- it overwrites the
       bootstrap image tag on the box and brings the stack up for real.
  EOT
}
