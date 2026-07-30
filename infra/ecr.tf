# Two repositories: one per image (api/worker/beat share the "api" image --
# see apps/api/Dockerfile's "one image, three commands" note -- and "web").
# Lifecycle policy expires untagged images (left behind by superseded
# builds) so storage doesn't creep; SHA-tagged images that ARE referenced
# by a running deployment are never untagged, so this never touches a live
# image. See docs/infra-guide.md's ECR section.

resource "aws_ecr_repository" "api" {
  name                 = "ai-business-os/api"
  image_tag_mutability = "IMMUTABLE" # a given git-SHA tag can never be silently overwritten

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "web" {
  name                 = "ai-business-os/web"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "expire_untagged" {
  for_each   = { api = aws_ecr_repository.api.name, web = aws_ecr_repository.web.name }
  repository = each.value

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images after 7 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 7
      }
      action = { type = "expire" }
    }]
  })
}
