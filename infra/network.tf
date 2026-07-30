# A deliberately small VPC: two public subnets (RDS requires a subnet
# group spanning >= 2 AZs even for a single-AZ instance) and nothing
# private. No NAT gateway -- that alone is ~$32/mo saved, and it's safe
# here because the EC2 instance's own security group (security.tf) is what
# actually restricts inbound traffic, not subnet placement. See
# docs/infra-guide.md's "AWS building blocks" section.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "ai-business-os-${var.environment}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "ai-business-os-${var.environment}" }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "ai-business-os-${var.environment}-public-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "ai-business-os-${var.environment}-public" }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_db_subnet_group" "main" {
  name       = "ai-business-os-${var.environment}"
  subnet_ids = aws_subnet.public[*].id

  tags = { Name = "ai-business-os-${var.environment}" }
}
