resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${var.project}-db"
  }
}

resource "aws_db_instance" "main" {
  identifier = "${var.project}-postgres"

  engine               = "postgres"
  engine_version       = "16"
  instance_class       = var.rds_instance_class
  allocated_storage    = 20
  max_allocated_storage = 100

  db_name  = "jobstrainer"
  username = "jobstrainer"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  availability_zone   = data.aws_availability_zones.available.names[0]
  multi_az            = false
  publicly_accessible = false

  backup_retention_period = 7
  skip_final_snapshot     = true

  tags = {
    Name = "${var.project}-postgres"
  }
}
