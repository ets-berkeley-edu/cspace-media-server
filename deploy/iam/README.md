# The deployer's permissions (for Operations)

The IAM policies the person or job running `./serena aws` (Terraform included) needs in a UC Berkeley AWS account.
Nothing here is secret: no account numbers, addresses or keys. Account IDs are wildcards (`*`) and every write is
limited to resources named `serena-*` (or tagged `project=serena`, for the KMS key) wherever AWS allows it.

| File | For | What it covers |
| --- | --- | --- |
| `serena-deployer-policy-mvp.json` | Stage 1 (Jira CS-9523): the `SerenaStage1Deployer` role Ops created in the cspace account | us-west-2 only; no WAF; includes `SimulatorServiceDiscovery` (Cloud Map and a private Route 53 zone), which only an environment running the simulated CollectionSpace needs |
| `serena-deployer-policy.json` | Stage 2 and production (the shared root, D297) | us-west-2 only. The split: an internet-facing load balancer with listener rules, its ACM certificate, a regional web ACL with an IP set; CloudFront for the files only (no VPC origin); security groups and gateway endpoints in Ops's VPC, but no VPC, subnet, route or gateway changes (D303); writes limited by the `project=serena` tag (D305). Also the simulator's service discovery (stage 2's first phase) and Cost Explorer read access |

**Stage 2's policy** follows the shared root (`../terraform/shared`; D297, D303, D305). Before stage 2's first
deploy, Operations can check it with `aws iam simulate-principal-policy` (or the IAM policy simulator) against the
actions in a `terraform plan` of stage 2: the tag conditions (`aws:RequestTag/project` when creating,
`aws:ResourceTag/project` afterwards) are the part most worth checking, since a few services name their tag condition
keys differently. It changes again for the deploy pipeline (D268–D277: GitHub OIDC and CodeBuild). Stage 1 keeps
CloudFront in front, so its policy is unaffected.

## Where the policies can't be narrower

- CloudFront origin access controls, key groups, public keys, response headers policies and functions (and, in the
  stage 1 policy, VPC origins) are identified by generated IDs, not names, so they need `Resource: "*"`. Stage 2's
  distributions are limited by their `project=serena` tag instead.
- Security groups, their rules and gateway endpoints in Operations' VPC have generated IDs too; stage 2's policy
  limits them by tag, and allows creating them in any VPC (the VPC is Operations', so it can't carry Serena's tag).
- ECS task definitions, KMS key creation, EC2 networking (VPC, subnets, routes, security groups, endpoints), WAF log
  delivery and CloudWatch Logs resource policies have no name-based resource to scope to.
- Read-only `Describe`, `Get` and `List` calls are allowed account-wide: Terraform reads many attributes of each
  resource, the exact list changes with provider versions, and they return only metadata.
- `iam:PassRole` is limited to `serena-*` roles and to ECS tasks; the only managed policy that can be attached is
  `AmazonECSTaskExecutionRolePolicy`.
- The deployer can read and write Serena's own secrets: `./serena aws` sets them (a museum's service account, ETL
  tokens, signing keys) without showing or storing them.

**Size.** Each policy is over 10,240 characters, the limit for a role's inline policies, so on a role it goes in
as customer managed policies (6,144 characters each at most, whitespace not counted), split between statements: two
for stage 1's, three for stage 2's (about 15,300 characters).

If the account requires a permissions boundary on roles that Terraform creates, tell us its name: it's a small change.

## Also needed from Operations, outside the policy

- **Service-linked roles.** If guardrails stop the deployer creating them, create these once:
  `AWSServiceRoleForECS`, `AWSServiceRoleForElasticLoadBalancing`, and for stage 1 CloudFront's for VPC origins
  (`vpcorigin.cloudfront.amazonaws.com`).
- **CloudFront on a new account.** AWS sometimes refuses CloudFront distributions until it has verified a new
  account. If the deploy fails that way, Operations opens the AWS Support case, and the deploy waits for it.

## When a deploy fails with `AccessDenied`

Note the action and resource in `docs/testing-checklist.md` (section 31 for stage 1). The fix goes into the
deployer role (or permission set) and into both files here, in the same pull request.

What the deploy creates is in [`../README.md`](../README.md) ("What it creates") and in `../terraform/`.
