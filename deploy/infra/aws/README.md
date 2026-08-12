# AWS ECS showcase (OpenTofu)

Managed Fargate stack for the jobstrainer demo. Full operator runbook (prerequisites, apply, DNS flip, destroy) is completed in Task 8.

## Bootstrap (one-shot after first apply)

Run migrations and OpenSearch index setup before serving traffic. The bootstrap task uses the same private networking as ECS services (`assignPublicIp=DISABLED`).

From `deploy/infra/aws`:

```bash
SUBNETS=$(tofu output -json private_subnet_ids | jq -r 'join(",")')
SG=$(tofu output -raw ecs_tasks_security_group_id)

aws ecs run-task \
  --cluster "$(tofu output -raw ecs_cluster_name)" \
  --task-definition "$(tofu output -raw bootstrap_task_definition_arn)" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}"
```

Watch logs in CloudWatch under `/ecs/jobstrainer/bootstrap` (or `${project}/bootstrap` if you changed `var.project`). Re-run only when migrations or bootstrap logic change.

## Ingestion schedule

EventBridge Scheduler runs the ingestion task definition every 2 hours (`cron(0 */2 * * ? *)`), mirroring the local Helm CronJob cadence. The task definition already passes `--hours 2` and reads `OFFER_QUERY` from Secrets Manager; no container overrides are applied at schedule time.
