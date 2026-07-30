# Terraform version and provider pins, plus remote state config.
#
# State lives in S3, not on a laptop -- losing tfstate for a
# revenue-bearing environment means Terraform no longer knows what it
# owns, which is a much worse problem than a lost local file normally is.
# See docs/infra-guide.md's Terraform section.
#
# The bucket referenced below must exist BEFORE the first `terraform init`
# (Terraform can't create its own state backend with itself -- a classic
# chicken-and-egg case, hence the one manual `aws s3api create-bucket` +
# `put-bucket-versioning` step in the README before anything else runs).
terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "s3" {
    bucket       = "ai-business-os-tfstate"
    key          = "v0.5/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true # S3-native locking (Terraform >= 1.9) -- no DynamoDB table needed
    encrypt      = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "ai-business-os"
      ManagedBy = "terraform"
      Env       = var.environment
    }
  }
}
