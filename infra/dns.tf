# The hosted zone itself is created here, but domain REGISTRATION is a
# separate, one-time manual step (registering a domain isn't something
# `terraform apply` should silently do -- it's a real, non-refundable
# purchase). After registering (Route 53 console, or any registrar), if
# registered outside Route 53, delegate the zone by pointing the
# registrar's nameservers at this zone's `name_servers` output.
#
# Caddy (docker-compose.prod.yml) obtains its TLS certificate via ACME
# HTTP-01, which requires these A records to already resolve to the
# instance's Elastic IP -- that's why Caddy's automatic HTTPS cannot work
# for a bare IP with no domain at all. See docs/infra-guide.md.

resource "aws_route53_zone" "main" {
  name = var.domain_name
}

resource "aws_route53_record" "app" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "app.${var.domain_name}"
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

resource "aws_route53_record" "api" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "api.${var.domain_name}"
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

# Clerk production instance (docs/decisions.md's Clerk-migration entries).
# All five are CNAMEs Clerk's dashboard asks for under Domains -> Configure
# -- pasted verbatim from there, not something to hand-derive, since the
# right-hand side values (frontend-api.clerk.services etc.) are Clerk's,
# not ours. Clerk verifies DNS itself and won't issue TLS certificates for
# the Frontend API / account portal until these resolve -- can take up to
# 48h to propagate per Clerk's own docs, though Route 53 is typically far
# faster.
resource "aws_route53_record" "clerk_frontend_api" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "clerk.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = ["frontend-api.clerk.services"]
}

resource "aws_route53_record" "clerk_account_portal" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "accounts.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = ["accounts.clerk.services"]
}

resource "aws_route53_record" "clerk_mail" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "clkmail.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = ["mail.hlitks6cwkws.clerk.services"]
}

resource "aws_route53_record" "clerk_dkim1" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "clk._domainkey.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = ["dkim1.hlitks6cwkws.clerk.services"]
}

resource "aws_route53_record" "clerk_dkim2" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "clk2._domainkey.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = ["dkim2.hlitks6cwkws.clerk.services"]
}
