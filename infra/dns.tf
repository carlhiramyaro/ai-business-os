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
