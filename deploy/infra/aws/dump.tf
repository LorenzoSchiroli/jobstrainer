locals {
  dump_s3_key = "demo/jobstrainer.dump"
  dump_s3_uri = "s3://${aws_s3_bucket.dump.id}/${local.dump_s3_key}"
}

resource "aws_s3_bucket" "dump" {
  bucket        = "${var.project}-demo-dumps-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = {
    Name = "${var.project}-demo-dumps"
  }
}

resource "aws_s3_bucket_public_access_block" "dump" {
  bucket = aws_s3_bucket.dump.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "dump" {
  bucket = aws_s3_bucket.dump.id

  rule {
    id     = "expire-demo-dumps"
    status = "Enabled"

    filter {
      prefix = "demo/"
    }

    expiration {
      days = 7
    }
  }
}

data "aws_iam_policy_document" "dump_task" {
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.dump.arn}/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.dump.arn]
  }
}

resource "aws_iam_role" "dump_task" {
  name               = "${var.project}-dump-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy" "dump_task" {
  name   = "${var.project}-dump-task-s3"
  role   = aws_iam_role.dump_task.id
  policy = data.aws_iam_policy_document.dump_task.json
}

resource "aws_cloudwatch_log_group" "dump" {
  name              = "/ecs/${var.project}/dump"
  retention_in_days = 7
}

resource "aws_ecs_task_definition" "dump" {
  family                   = "${var.project}-dump"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.dump_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "pgtools"
      image     = var.pgtools_image
      essential = true
      repositoryCredentials = local.ghcr_repository_credentials
      # Override command to ["dump"] or ["restore"] at RunTask time.
      command = ["dump"]
      environment = [
        {
          name  = "DUMP_S3_URI"
          value = local.dump_s3_uri
        },
        {
          name  = "AWS_DEFAULT_REGION"
          value = var.aws_region
        },
      ]
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = "${aws_secretsmanager_secret.app.arn}:DATABASE_URL::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.dump.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}
