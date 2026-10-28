# The deployer's permissions (for Operations)

The IAM policies the person or job running `./serena aws` (Terraform included) needs in a UC Berkeley AWS account.
Nothing here is secret: no account numbers, addresses or keys. Account IDs are wildcards (`*`) and every write is
limited to resources named `serena-*` (or tagged `project=serena`, for the KMS key) wherever AWS allows it.

| File | For | What it covers |
| --- | --- | --- |
| `serena-deployer-policy-mvp.json` | Stage 1 (Jira CS-9523): the `SerenaStage1Deployer` role Ops created in the cspace account | us-west-2 only; no WAF; includes `SimulatorServiceDiscovery` (Cloud Map and a private Route 53 zone), which only an environment running the simulated CollectionSpace needs |
| `serena-deployer-policy.json` | Stage 2 and production (draft) | The stage 1 policy plus AWS WAF and its log delivery in us-east-1 (as CloudFront requires), and Cost Explorer read access (`CostVisibility`) |

**Stage 2's policy is a draft.** It still describes CloudFront in front of everything. Stage 2 and production use the
split (decided October 27, 2026, D301): a public load balancer for the app, CloudFront for the files only. The policy
changes with the Terraform pull request that adds the shared root: it keeps the CloudFront actions for the files and
the path-rewrite function, adds the internet-facing load balancer, ACM and a regional web ACL, drops the VPC origin,
CloudFront's WAF in us-east-1 and the VPC actions (Operations' VPC), and limits writes by the `project=serena` tag
(D297, D303, D305). It changes again for the deploy pipeline (D268–D277: GitHub OIDC and CodeBuild). Stage 1 keeps
CloudFront in front, so its policy is unaffected.

## Where the policies can't be narrower

- CloudFront distributions, origin access controls, key groups, public keys, response headers policies and VPC
  origins are identified by generated IDs, not names, so they need `Resource: "*"`.
- ECS task definitions, KMS key creation, EC2 networking (VPC, subnets, routes, security groups, endpoints), WAF log
  delivery and CloudWatch Logs resource policies have no name-based resource to scope to.
- Read-only `Describe`, `Get` and `List` calls are allowed account-wide: Terraform reads many attributes of each
  resource, the exact list changes with provider versions, and they return only metadata.
- `iam:PassRole` is limited to `serena-*` roles and to ECS tasks; the only managed policy that can be attached is
  `AmazonECSTaskExecutionRolePolicy`.
- The deployer can read and write Serena's own secrets: `./serena aws` sets them (a museum's service account, ETL
  tokens, signing keys) without showing or storing them.

**Size.** Each policy is over 10,240 characters, the limit for a role's inline policies, so on a role it goes in
as two customer managed policies (6,144 characters each at most), split between statements.

If the account requires a permissions boundary on roles that Terraform creates, tell us its name: it's a small change.

## Also needed from Operations, outside the policy

- **Service-linked roles.** If guardrails stop the deployer creating them, create these once:
  `AWSServiceRoleForECS`, `AWSServiceRoleForElasticLoadBalancing`, and CloudFront's for VPC origins
  (`vpcorigin.cloudfront.amazonaws.com`).
- **CloudFront on a new account.** AWS sometimes refuses CloudFront distributions until it has verified a new
  account. If the deploy fails that way, Operations opens the AWS Support case, and the deploy waits for it.

## When a deploy fails with `AccessDenied`

Note the action and resource in `docs/testing-checklist.md` (section 31 for stage 1). The fix goes into the
deployer role (or permission set) and into both files here, in the same pull request.

What the deploy creates is in [`../README.md`](../README.md) ("What it creates") and in `../terraform/`.
