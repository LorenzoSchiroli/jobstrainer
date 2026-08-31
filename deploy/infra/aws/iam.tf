data "aws_iam_policy_document" "ecs_execution_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${var.project}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_execution_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_execution_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_secretsmanager_secret.app.arn],
      aws_secretsmanager_secret.ghcr[*].arn,
    )
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name   = "${var.project}-ecs-execution-secrets"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution_secrets.json
}

# Only created for private GHCR packages; public packages pull anonymously.
resource "aws_secretsmanager_secret" "ghcr" {
  count = var.ghcr_token != "" ? 1 : 0

  name                    = "${var.project}/ghcr"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "ghcr" {
  count = var.ghcr_token != "" ? 1 : 0

  secret_id = aws_secretsmanager_secret.ghcr[0].id
  secret_string = jsonencode({
    username = var.ghcr_username
    password = var.ghcr_token
  })
}

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task" {
  name               = "${var.project}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_ecs" {
  statement {
    actions = ["ecs:RunTask"]
    resources = [
      aws_ecs_task_definition.ingestion.arn,
      "${aws_ecs_task_definition.ingestion.arn_without_revision}:*",
    ]

    condition {
      test     = "ArnLike"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  statement {
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.ecs_execution.arn,
      aws_iam_role.ecs_task.arn,
    ]

    condition {
      test     = "StringLike"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler_ecs" {
  name   = "${var.project}-scheduler-ecs"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_ecs.json
}
