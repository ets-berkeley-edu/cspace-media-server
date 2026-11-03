# terraform test (run from deploy/terraform/rehearsal after terraform init -backend=false). Plans the stage 2
# rehearsal's VPC and deployer against a simulated AWS provider: nothing is created and no sign-in is needed.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_AdministratorAccess_0123456789abcdef/someone"
    }
  }

  mock_data "aws_iam_session_context" {
    defaults = {
      issuer_arn = "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/us-west-2/AWSReservedSSO_AdministratorAccess_0123456789abcdef"
    }
  }

  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-west-2c", "us-west-2a", "us-west-2b"]
    }
  }

  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/rehearsal-stage2r-deployer"
    }
  }
}

variables {
  account_id = "123456789012"
  region     = "us-west-2"
  env_name   = "stage2r"
}

run "a_vpc_like_ops" {
  command = plan

  assert {
    condition     = [for s in aws_subnet.public : s.availability_zone] == ["us-west-2a", "us-west-2b"]
    error_message = "two public subnets, in two zones"
  }

  assert {
    condition     = [for s in aws_subnet.private : s.availability_zone] == ["us-west-2a", "us-west-2b"]
    error_message = "two private subnets, in the same two zones"
  }

  assert {
    condition     = length(setintersection([for s in aws_subnet.public : s.cidr_block], [for s in aws_subnet.private : s.cidr_block])) == 0
    error_message = "the subnets don't overlap"
  }

  assert {
    condition     = one(aws_route_table.private.route).cidr_block == "0.0.0.0/0" && one(aws_route_table.private.route).gateway_id == null
    error_message = "the private subnets go out through the NAT gateway, not the internet gateway"
  }
}

run "a_deployer_with_only_the_stage_2_policy" {
  command = plan

  assert {
    condition     = !startswith(aws_iam_role.deployer.name, "serena-")
    error_message = "the deployer's role isn't serena-*, which its own policy may change"
  }

  assert {
    condition     = jsondecode(aws_iam_role.deployer.assume_role_policy).Statement[0].Principal.AWS == "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/us-west-2/AWSReservedSSO_AdministratorAccess_0123456789abcdef"
    error_message = "only the administrator role that applies this root may assume the deployer"
  }

  assert {
    condition     = length(module.deployer_policy.test) == 3
    error_message = "the deployer policy goes in as three managed policies (deploy/iam/README.md)"
  }

  assert {
    condition     = alltrue([for p in module.deployer_policy.test : length(p.policy) <= 6144])
    error_message = "each part is within IAM's 6,144 characters"
  }

  assert {
    condition     = flatten([for k in sort(keys(module.deployer_policy.test)) : jsondecode(module.deployer_policy.test[k].policy).Statement]) == jsondecode(file("../../iam/serena-deployer-policy.json")).Statement
    error_message = "the parts hold every statement of the policy, in order, and nothing else"
  }
}

run "a_stand_in_for_the_etl_servers_role" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role.etl_reader.assume_role_policy).Statement[0].Principal.AWS == "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/us-west-2/AWSReservedSSO_AdministratorAccess_0123456789abcdef"
    error_message = "only the administrator role that applies this root may assume the stand-in"
  }

  assert {
    condition     = !startswith(aws_iam_role.etl_reader.name, "serena-")
    error_message = "the stand-in isn't serena-*, which the deployer may change"
  }
}
