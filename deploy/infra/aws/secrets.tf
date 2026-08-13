resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "opensearch" {
  length  = 32
  special = false
}

resource "random_password" "app_secret_key" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.project}/app"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL             = "postgresql+asyncpg://jobstrainer:${random_password.db.result}@${aws_db_instance.main.address}:5432/jobstrainer"
    OPENSEARCH_URL           = "https://${aws_opensearch_domain.main.endpoint}"
    OPENSEARCH_USER          = "jobstrainer"
    OPENSEARCH_PASSWORD      = random_password.opensearch.result
    SECRET_KEY               = random_password.app_secret_key.result
    GROQ_API_KEY             = var.groq_api_key
    GROQ_MODEL_LARGE         = var.groq_model_large
    GROQ_MODEL_BASE          = var.groq_model_base
    CORS_ORIGINS             = "https://app.${var.domain}"
    OFFER_QUERY              = var.offer_query
    ACCESS_TOKEN_EXPIRE_DAYS = "7"
    ADZUNA_APP_ID            = var.adzuna_app_id
    ADZUNA_APP_KEY           = var.adzuna_app_key
    SERPERDEV_API_KEY        = var.serperdev_api_key
    DDGS_PROXY               = var.ddgs_proxy
  })
}
