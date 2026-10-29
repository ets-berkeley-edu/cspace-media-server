output "url" {
  description = "The simulator's address inside the VPC."
  value       = local.simulator_url
}

output "fake_etl" {
  description = "What ./serena aws etl needs to run the fake ETL once: its task definition, subnets and security group."
  value = {
    task_definition = aws_ecs_task_definition.fake_etl.family
    subnets         = join(",", var.subnet_ids)
    security_group  = aws_security_group.devtools.id
  }
}
