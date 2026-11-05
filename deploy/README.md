# Serena in AWS

`./serena aws` deploys Serena to an AWS account and looks after it (decisions D181 to D206, October 2026). It is
modeled on the BMU's `./bmu aws`, and the commands are the same where they can be.

- **One environment per settings file** in `deploy/environments/`. `personal-dev.conf`, the default, is a
  developer's own account (us-west-2), with the simulator only: its committed profile is Richard's, and anyone else
  sets their own (see "Your own AWS account"). Stage 1 in the UC Berkeley account (CS-9523) has a file too, and so
  does stage 2 while it uses only the simulator (TQ8); with the pipeline, an environment keeps its settings in SSM
  Parameter Store in its account instead (D273). `personal-stage2.conf` rehearses stage 2 in a personal account (see
  "Rehearsing stage 2 in your own account").
- **Infrastructure as code.** Terraform (`deploy/terraform/`) creates everything, so nothing is clicked together in
  the console, and the whole environment can be deleted and created again.
- **No keys or passwords in files.** You sign in with IAM Identity Center (`aws sso login`). Terraform creates
  every secret empty, and `./serena aws` sets them (D191), so no secret is in Terraform's state, a file or the
  shell's history.
- **Who deploys (D268 to D277).** personal-dev and stage 1: `./serena aws` from the deployer's own machine. Stage 2
  and production: only the deploy pipeline (GitHub Actions starts AWS CodeBuild in the account after a reviewer
  approves the plan; see "The deploy pipeline"), with `./serena aws` kept for setting secrets and for break-glass. See
  `docs/design.md`, Infrastructure and operations › Deploys. CI checks the Terraform code with no AWS sign-in.

What it builds: the app and the worker on ECS Fargate, CloudFront (HTTPS, the address rules, WAF where it's on) in
front of an internal load balancer, the tables, a bucket per museum, the KMS key, the secrets and the logs (pull
request 17); image delivery from the museums' buckets with signed URLs, the unavailable images, and the alert email
and alarms (pull request 18). The simulated CollectionSpace and the fake ETL, as an option.

## Commands

| Command | What it does |
| --- | --- |
| `./serena aws deploy` | Builds the image (and, with the simulator, the simulator's image) and pushes it, then shows Terraform's plan and, after you type `yes`, applies it and waits until the app and the worker are running. Prints the address and saves it in `deploy/environments/<env>.url`. |
| `./serena aws plan` | Shows what a deploy of the running image would change, without changing anything. |
| `./serena aws status` | The address, the running tasks, the deployed image, the allowed addresses, whether files are delivered (and the trusted signing keys), the alert email and whether it's confirmed, the alarms (and any firing), and each museum with its server and whether each of its secrets is set. |
| `./serena aws url` | Prints the address. |
| `./serena aws logs web` / `worker` / `devtools` | Follows a service's logs, starting with the last 30 minutes. `devtools` (the simulator and the fake ETL) only with the simulator. |
| `./serena aws pause` / `resume` | Stops or starts every service to save money, and switches the alarms' emails off or on (D204). The data stays. Terraform shows the change and asks first. |
| `./serena aws allow-my-ip` | Adds this computer's current address to the allowlist, and applies it. |
| `./serena aws etl <museum> [--rows N] [--failed] [--json]` | With the simulator: runs the fake ETL once, inside the environment, for a whole daily refresh (the same as `./serena etl` on the local stack). Prints the refresh's result and sample image addresses; `--json` prints only its summary, as JSON. `--sizes BAND:COUNT,...` in place of `--rows` gives the records files of about a real file's size, for the replay (D283). |
| `./serena aws replay --log <month>.tsv.gz --busiest hour` | With the simulator only (D279): replays a slice of a cleaned access log against the environment, then prints the web and worker services' CPU and memory from CloudWatch for the run (D278 to D288). `--busiest minute`, or `--from 2026-09-30T19:00 --minutes 60`; `--speed 5` for five times the real rate; `--follow N` to follow one redirect in N; `--first-row N` for new, uncached records (a cold run again). `--dry-run` sends nothing: it prints the slice and the `./serena aws etl … --sizes …` command to run first. See `serenade/README.md`, The access-log replay. |
| `./serena aws test [pytest options]` | The AWS tests (`serenade/aws/`, T90 to T105) against the running environment, after a deploy or resume: about 5 to 10 minutes. Against a real CollectionSpace only the tests that look; set `SERENADE_ADMIN_USER` and it asks for the password. See `serenade/README.md`, The AWS tests. |
| `./serena aws list <museum> [--limit N] [--kind KIND]` | What Serena may serve for the museum, from its servability table (the last updated refresh's servable list): each file's kind, access and Media CSID, with its address. The first 25, or N (`--limit 0` for all); `--kind image` (or `pdf`, `3D` ...) for one kind. Only reads. With the simulator, a deploy or pause empties the simulator but not this table, so a listed file not cached yet can't be fetched until `./serena aws etl` runs again. |
| `./serena aws cspace-secret <museum>` | Sets the museum's read-only CollectionSpace service account. It asks for the user name and password and passes them straight to Secrets Manager. Not with the simulator, whose account deploy sets. |
| `./serena aws etl-token <museum> [--show]` | Makes a new random ETL token. The old one becomes "previous" and keeps working until the next rotation. Shows the new token once, for the ETL's token file (Jira CSW-1027). Where the museum's ETL server reads its token with its own role (`ETL_READER_ROLE_ARNS`), the token isn't shown unless `--show`. |
| `./serena aws portal-key <museum>` | For a museum with signed access (Cinefiles): makes a new signing key for its signed links, keeping the old one as "previous". Shows the key and its ID once, for the portal (Glimmer). |
| `./serena aws cdn-key` | Makes a new CloudFront signing key for the museums' files (D200): the private key goes straight to Secrets Manager, CloudFront is told to trust the new public key (Terraform shows a small plan), then the app signs with it within 5 minutes. The key before it stays trusted until the next rotation. Nothing is shown. The first deploy makes the first key. |
| `./serena aws confirm-alerts` | Confirms the alert email's subscription (D201): paste the link from AWS's "Subscription Confirmation" email. Don't click the link: confirmed here, unsubscribing needs an AWS sign-in. |
| `./serena aws destroy` | Deletes everything in AWS for the environment, data included. It asks for the environment's name first. |
| `./serena aws init` | Points Terraform at the environment's state, to run `terraform` commands yourself. |
| `./serena aws rehearsal-vpc [destroy]` | For a stage 2 rehearsal in your own account only (`REHEARSAL=true`): makes, as the account's administrator, what Ops provides for stage 2 (a VPC and a deployer role with only the stage 2 policy), and a stand-in for an ETL server's role, or deletes them once the environment is destroyed. See "Rehearsing stage 2 in your own account". |
| `./serena aws pipeline [destroy]` | As the account's administrator (`ADMIN_PROFILE`), for an environment on the shared root with `SETTINGS=ssm`: makes (or deletes) its deploy pipeline, `terraform/pipeline`. Checks its GitHub environments first, asks for the account's number where there is real data, shows Terraform's plan and asks, then offers to set the GitHub environments' secrets with `gh`. See "The deploy pipeline". |
| `./serena aws sim-secrets` | With the simulator, in an environment the pipeline deploys: sets what `deploy` sets itself from a laptop (the simulator's account, random ETL tokens and portal keys), where they aren't set. Nothing is shown. |
| `./serena aws pipeline-plan` / `pipeline-apply` | Only in the pipeline's builds (`pipeline/`): they refuse to run anywhere else. |
| `./serena aws settings push` / `show` / `delete` | For an environment with `SETTINGS=ssm` (D273): puts its settings in SSM Parameter Store from its files, showing what changes and asking first (always, even with `SERENA_AWS_YES=1`); lists them, marking any the files on this computer disagree with; or, once the environment is destroyed, deletes them (it asks for the environment's name). See "Settings in SSM Parameter Store". |

**Picking the environment.** Add `--env NAME`, or set `SERENA_AWS_ENV`. The default is `personal-dev`.
`SERENA_AWS_YES=1` applies without Terraform's `yes` prompt.

**Settings in SSM Parameter Store (D273, DP10).** With `SETTINGS=ssm` in the environment's `.conf` or `.local.conf`,
`./serena aws` reads every setting below from SSM in the environment's account, one String parameter each under
`/serena-<SERENA_ENV_NAME>/settings/`, except `AWS_PROFILE`, `AWS_REGION`, `SERENA_ENV_NAME` and
`ADMIN_PROFILE` (the account administrator's profile), which say how to reach the
account. The files then matter only to `./serena aws settings
push`, which puts them there; a command whose files disagree with SSM says so and uses SSM's. Changing a setting is:
edit the file, `settings push`, then deploy (or, with the pipeline, run it). Commands that save a setting
(`rehearsal-vpc`, `allow-my-ip`) save it in SSM and in the `.local.conf`, so the files stay a whole copy and a later
push doesn't undo it. The `settings`, `rehearsal-vpc` and `pipeline` commands run as
`ADMIN_PROFILE` where the environment has one, since they come before the deployer role exists (or make it).
`REAL_DATA_ACCOUNT` is in SSM only: `./serena aws pipeline` writes it, and `settings push` leaves
it alone. The deploy pipeline's environments keep
their settings this way (it reads them in the build); personal-dev keeps its files (D277).

**Settings** (in `<env>.conf`, or in the uncommitted `<env>.local.conf`, which wins; with `SETTINGS=ssm`, in SSM):

| Setting | What it is |
| --- | --- |
| `AWS_PROFILE`, `AWS_REGION` | The AWS CLI profile (IAM Identity Center) and region. personal-dev uses the BMU's profile (Richard's): the same account, side by side with the BMU. Anyone else sets their own in `personal-dev.local.conf` (see "Your own AWS account"). |
| `SERENA_ENV_NAME` | Resource names (`serena-<name>-…`) and the Terraform state's key. |
| `ADMIN_PROFILE` | The account administrator's profile, where it isn't `AWS_PROFILE`: `settings`, `rehearsal-vpc` and `pipeline` run as it (personal-stage2: `bmu-personal`). It was `REHEARSAL_ADMIN_PROFILE`. |
| `CSPACE_TENANTS` | The museums and their CollectionSpace servers: `"pahma=https://<PAHMA's CollectionSpace server>"`. Each needs `backend/serena/museums/<museum>.yaml`. |
| `SIMULATED_CSPACE`, `SIMULATED_MUSEUMS` | `true` runs the simulated CollectionSpace for the museums listed (default `pahma`) instead of `CSPACE_TENANTS`. |
| `ALLOWED_CIDRS` | Addresses that may reach everything. The first deploy adds this computer's; `allow-my-ip` adds more. |
| `ETL_CIDRS`, `ADMIN_CIDRS` | Addresses that may also reach `/etl/` (the ETL servers) and `/admin` (campus networks), D185. |
| `OPEN_IMAGES` | `true` lets anyone request the image paths and `/health` (production). `false` limits them to `ALLOWED_CIDRS`. |
| `WAF` | `true` puts a WAF web ACL on the distribution (D186). Off in personal-dev, which is allowlisted anyway. |
| `PROTECT_DATA` | `true` where the data matters (D192): see "Protecting data". |
| `WEB_COUNT` | Web tasks: 1 in personal-dev, 2 elsewhere (D188). |
| `ENV_LABEL` | Shown in the admin app's header. |
| `ALERT_EMAIL` | Where alerts and alarms are emailed (D201). Only in the uncommitted `.local.conf`, so no address is in the repository: in personal-dev, your own; in QA and production, the team's mailing list. Empty: no email. After the deploy that subscribes it, `./serena aws confirm-alerts`. |

**Once deployed, a museum's server never changes.** A museum's servability, recalls and cached files refer to the
records on the server it was deployed for. So `deploy`, `plan`, `pause`, `resume` and `allow-my-ip` stop before
changing anything if a museum's server changed. Either put the setting back, or `./serena aws destroy` first, or
deploy the new server as another environment (a different `SERENA_ENV_NAME` in your `.local.conf`). The one exception
is a museum moving from the simulator to a real server (stage 2, November 5, 2026): the simulator's records are
synthetic, its rows are replaced by the museum's first ETL list, and its cached files are keyed by Blob CSIDs a real
CollectionSpace doesn't have. Adding a museum
is allowed. Removing one asks you to type its name: its bucket (its cached files) and secrets go with it. Never where
data is protected.

## First deploy (personal-dev, with the simulator)

**What you need on the Mac:** Docker Desktop, running; AWS CLI v2; Terraform 1.10 or later
(`brew tap hashicorp/tap && brew install hashicorp/tap/terraform`); python3. In another developer's account, first set
your own profile (see "Your own AWS account" below) and use it in place of `bmu-personal`.

```bash
aws sso login --profile bmu-personal
./serena aws deploy
./serena aws etl pahma
```

1. **Account check.** The first time, it shows the account the profile is signed in to and asks whether it's the
   right one. It saves the answer in `deploy/environments/personal-dev.local.conf` (not committed) and from then on
   refuses any other account. If the account already has a Serena environment with the same name, it asks whether
   it's yours.
2. **Allowlist.** It adds this computer's public address. Everyone else gets a 403 from CloudFront.
3. **State bucket.** It creates `serena-tfstate-<account>-<region>`, once per account.
4. **Image repositories** (about a minute), then **the images**, built for ARM and pushed: Serena's
   (`deploy/Dockerfile`: the app and the built admin app, D190) and, with the simulator, the local stack's
   (`backend/Dockerfile`), which runs the simulator and the fake ETL. Both take their Python base image from Amazon
   ECR Public; for `backend/Dockerfile` the deploy swaps it in with a named build context, since CI and the local
   stack build that file from Docker Hub (ECR Public refuses GitHub's shared runners).
5. **Serena.** Terraform lists what it will create and asks; type `yes`. The first time takes about **15–25
   minutes**, mostly CloudFront. It finishes when the app and the worker are running.
6. **Secrets.** With the simulator, deploy sets each museum's secrets once: the simulator's synthetic account, a
   random ETL token and, for a museum with signed access, a random portal key. Nothing is shown.
7. **Image delivery.** The first time, it makes the CloudFront signing key (as `./serena aws cdn-key` does): Terraform
   shows a second, smaller plan, which adds the key group and the museums' file paths to the distribution (a few
   minutes). From then on a servable file is delivered with a signed URL.
8. **Alert email.** With `ALERT_EMAIL` set, AWS emails that address a confirmation link. Don't click it: run
   `./serena aws confirm-alerts` and paste it there. The link expires after 3 days.

It prints the address (`https://<something>.cloudfront.net`). The admin app is at `/admin/`: sign in as `admin` /
`admin` (the simulator's synthetic admin, every museum), `pahma-admin` / `pahma-admin`, or `viewer` / `viewer`.

**A daily refresh:** `./serena aws etl pahma` runs the fake ETL as a one-off task inside the VPC. It adds the
day's synthetic Media records to the simulator, then runs the refresh through the ETL API (start, upload, check, poll)
with the museum's ETL token, which it reads from Secrets Manager itself. It takes a minute or two and prints the
refresh's counts. The refresh then shows in the admin app. Run it again with the same `--rows` (the delta threshold
compares with the last one).

**Later deploys.** The same command. Terraform shows only what changed (about 3–5 minutes). Each deploy pushes a new
image tag (commit and time, `-dirty` for uncommitted changes), so `status` shows which code runs.

## Your own AWS account

Any developer can deploy Serena with the simulator to an AWS account they can sign in to: a UC Berkeley sandbox account
or their own (EN2). Your own environment runs only the simulator and the fake ETL (D277), and UC Berkeley data never
goes into a personal account (see the next section). The steps are those of the first deploy above, with your own
profile:

1. Make an IAM Identity Center profile for the account: `aws configure sso` (give it any name, for example
   `serena-mine`), then `aws sso login --profile serena-mine`. The profile needs administrator access in that account,
   as personal-dev's does.
2. Create `deploy/environments/personal-dev.local.conf` (not committed) with the line `AWS_PROFILE=serena-mine`. It
   overrides the committed `bmu-personal`, which is Richard's. Add `ALERT_EMAIL=<your address>` there too if you
   want the alarms' emails.
3. `./serena aws deploy`, then `./serena aws etl pahma`. The first deploy asks you to confirm the account and saves its
   number in the same `.local.conf`; from then on it refuses any other account.

Everything else in `personal-dev.conf` stays as it is. Pause or destroy the environment between sessions (see Cost).

## Against a real CollectionSpace (QA, then production)

**UC Berkeley data only in a UC Berkeley AWS account.** An environment with a real CollectionSpace, production or QA
(Lyrasis's QA tenants hold a copy of production's database), copies the museums' files into its account. It may run
only in a UC Berkeley AWS account, never in a personal one; a personal account is for the simulator only. Every
`./serena aws deploy` of such an environment shows this rule and goes ahead only once you type the account's number.

With `SIMULATED_CSPACE=false` and `CSPACE_TENANTS` set, after the first deploy:

1. `./serena aws cspace-secret <museum>` for each museum: its read-only service account.
2. The ETL's token. Where the ETL server has an IAM role, it reads the token itself (below); otherwise
   `./serena aws etl-token <museum>`, and give the token to whoever runs the ETL, for its token file (CSW-1027).
   Either way, allow the ETL server's addresses with `ETL_CIDRS`.
3. `./serena aws portal-key cinefiles`, once Cinefiles is served: give the key ID and key to Glimmer.

`status` says "NOT SET" for any secret still empty. A token or key rotation keeps the previous one working until
the next rotation, so the ETL or the portal can switch at its own pace.

## The ETL reads its token with its own role (D275)

Where the ETL server has an IAM role (an EC2 instance profile), it reads its museum's token from Serena's Secrets
Manager on each run, so no person sees or copies the token, and a rotation needs no change on the ETL server
(`docs/design.md`, Infrastructure and operations › Deploys; DP15). Shared root only. The ETL's side is CSW-1027's
token source setting, decided in the CSpace ETL Process project.

1. **The role first.** AWS refuses a policy naming a role that doesn't exist, so Ops makes the ETL server's role
   before Serena's deploy names it. Add a museum only once its ETL actually reads with the role: from then on,
   `etl-token` doesn't show its token.
2. **The setting,** in the environment's settings (SSM, `./serena aws settings push`): `ETL_READER_ROLE_ARNS`, each
   museum with its ETL server's role, like `CSPACE_TENANTS`:
   `ETL_READER_ROLE_ARNS="pahma=arn:aws:iam::<account>:role/<name> cinefiles=arn:aws:iam::<account>:role/<name>"`.
   One role may read several museums' tokens; each museum is named.
3. **A deploy** (the pipeline). For each museum named, the museum's `etl-tokens` secret gets a policy allowing that
   role `secretsmanager:GetSecretValue` and nothing else, and Serena's KMS key's policy lets the role use
   `kms:Decrypt` only through Secrets Manager (`kms:ViaService`) and only for that secret
   (`kms:EncryptionContext:SecretARN`). Not another museum's token, not the CollectionSpace account, not a change.
4. **In another AWS account,** the role also needs its own policy allowing the same two actions. `./serena aws
   status` prints the secret's and the key's ARNs for it, under each museum:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "secretsmanager:GetSecretValue",
         "Resource": "<the museum's etl-tokens secret's ARN>"
       },
       {
         "Effect": "Allow",
         "Action": "kms:Decrypt",
         "Resource": "<Serena's KMS key's ARN>",
         "Condition": {"StringEquals": {"kms:ViaService": "secretsmanager.us-west-2.amazonaws.com"}}
       }
     ]
   }
   ```

   In Serena's own account, nothing more is needed.
5. **What the ETL reads:** the secret's value, `{"current": "<token>", "previous": "<token or null>"}`; it sends
   `current`. After a rotation (`./serena aws etl-token <museum>`, which then shows nothing), its next run uses the new
   one: the admin app's audit log shows the ETL's calls with `which_key` current. `--show` shows the token for a
   token file, the fallback.

To stop a role reading, remove its museum from `ETL_READER_ROLE_ARNS` and deploy: the secret's policy and the key's
statement go. Do that before the role is deleted: AWS refuses a key policy naming a role that no longer exists, so the
next deploy would fail until the setting is removed.

Proven in the same account on personal-stage2 (`docs/testing-checklist.md`, section 57), with a stand-in role that has
no policy of its own; across accounts, on stage 2.

## The simulated CollectionSpace and the fake ETL (D189)

- **The simulator** runs as its own service, reachable only by the app, the worker and the fake ETL, at
  `http://fakecspace.serena-<env>.internal:8180` (a private DNS name). Each museum's server is that address with
  the museum's name after it (`…:8180/pahma`); the simulator tells the museums apart by that path.
- **Its data is in memory.** A pause, a deploy or a restart starts it empty, while Serena keeps its tables and
  files. `./serena aws etl` adds the records it lists every time, so a refresh after a restart works.
- **The fake ETL** refuses to run unless the environment runs the simulator (`SERENA_SIMULATED_CSPACE=true`, set
  only there) and every museum's server is the simulator, so it can never send a servable list to a museum with
  real data.
- Never with `PROTECT_DATA=true`.

## A shared environment (stage 2, QA, production)

`TERRAFORM_ROOT=shared` in the environment's settings (`deploy/environments/ucb-stage2.conf`). Its `.local.conf` holds
what Ops and DevOps provide: `VPC_ID`, `APP_SUBNET_IDS` (private, behind the NAT gateway), `LB_SUBNET_IDS` (public),
`CREATE_GATEWAY_ENDPOINTS`, `DOMAIN_NAME`, `APACHE_CIDRS`, `ETL_CIDRS` and `ADMIN_CIDRS` (D303, D293, D290, D291).

1. `./serena aws deploy` makes the image repositories and the certificate for `DOMAIN_NAME`, prints the certificate's
   DNS validation record and stops (TQ4). DevOps adds the record in campus DNS once; ACM renews the certificate after.
2. Once the certificate is issued, `./serena aws deploy` builds the rest and prints the load balancer's own name:
   DevOps points `DOMAIN_NAME` at it.
3. With the simulator, the fake ETL calls the campus name from the private subnets, so its calls come from the NAT
   gateway's outbound address: list it in `ETL_CIDRS`.

An ETL server with its own IAM role reads its museum's token itself: `ETL_READER_ROLE_ARNS` ("The ETL reads its token
with its own role", above).

`./serena aws deploy` refuses a shared environment with a real CollectionSpace: the pipeline deploys it (D268). As a
break-glass deploy (D276) it goes ahead once you type "break glass" and then the account's number.

## Rehearsing stage 2 in your own account

`deploy/environments/personal-stage2.conf` deploys the shared root in a personal account, with only the simulator
museum, as a role that has only the stage 2 deployer policy (`iam/serena-deployer-policy.json`), so that every
`AccessDenied` is the policy's and Ops gets a policy that has been seen to work (`docs/testing-checklist.md`, section
54). It needs a DNS zone you control for the certificate, such as a cheap domain registered in Route 53.

1. `./serena aws rehearsal-vpc --env personal-stage2`, signed in as the account's administrator
   (`ADMIN_PROFILE`, `bmu-personal`). It applies `terraform/rehearsal`: what Ops provides for stage 2, a VPC
   with two public and two private subnets in two zones and a NAT gateway (no gateway endpoints, and nothing tagged
   `project=serena`), and the role `rehearsal-stage2r-deployer`, which only that administrator role may assume, with
   the stage 2 policy as three managed policies; and `rehearsal-stage2r-etl-reader`, a stand-in for an ETL server's
   role with no policy of its own (section 57). It saves the subnets, the NAT gateway's address (`ETL_CIDRS`) and
   this computer's address (`ADMIN_CIDRS`, if empty) in `personal-stage2.local.conf`, and prints the deployer's
   profile for `~/.aws/config` (`serena-rehearsal-deploy`: the role, from `bmu-personal`), and the stand-in's.
2. Add `DOMAIN_NAME` (for example `stage2r.<your domain>`) and `ALERT_EMAIL` to `personal-stage2.local.conf`.
3. Section 50's steps with `--env personal-stage2`, as the deployer. You add the certificate's validation record and
   the name for the load balancer in your own zone, as DevOps will in campus DNS.
4. `./serena aws destroy --env personal-stage2`, as the deployer (deleting is part of the rehearsal), then
   `./serena aws rehearsal-vpc --env personal-stage2 destroy`, which refuses while the environment still exists.

The role takes AWS's one-hour limit for a role assumed from a sign-in session; the AWS CLI and Terraform renew it as
they go. The NAT gateway bills while paused: about $5 a day running, so destroy it between sessions.

## The deploy pipeline

An environment on the shared root is deployed by its pipeline (D268 to D277, DP1 to DP17; `docs/design.md`,
Infrastructure and operations › Deploys): `.github/workflows/deploy.yml` starts AWS CodeBuild in the environment's
account, and Terraform runs only there, so its plans and logs never reach the public repository's Actions logs.

1. **GitHub environments** (repository Settings › Environments; an admin of the repository): `<env>-plan`, deployments
   from `main` only, no reviewer; and `<env>`, from `main` only, with required reviewers and "Prevent self-review".
   A QA or dev environment may leave "Prevent self-review" unchecked if its committed `.conf` says
   `ALLOW_SELF_REVIEW=true` (D308; `ucb-stage2` does). Production never.
   They come first: the roles trust them, and GitHub makes an environment without rules the first time a job names it.
2. **Settings in SSM:** `SETTINGS=ssm` in the environment's files, then `./serena aws settings push --env <env>`.
3. **The pipeline**, as the account's administrator: `./serena aws pipeline --env <env>`. It applies
   `terraform/pipeline` (state `serena/<SERENA_ENV_NAME>/pipeline.tfstate`): GitHub's OIDC provider, if the account
   has none; the roles `pipeline-<env>-plan` and `-apply`, which only the GitHub environments `<env>-plan` and `<env>`
   may assume (the command reads from GitHub's API how its OIDC tokens name the repository), and which may only start
   their own build and read its status; the CodeBuild projects `pipeline-<env>-plan` and `-apply`; the build's role
   `pipeline-<env>-build`, with the stage 2 deployer policy
   (`iam/`) and a deny of secret values and of SSM changes; the log group `/pipeline/<env>`; and the bucket of saved
   plans. Then each GitHub environment needs the secret `AWS_ROLE_ARN` (its role's ARN) and the variable `AWS_REGION`;
   the command offers to set them with `gh`, or prints the commands.
4. **A deploy:** Actions › Deploy › Run workflow, from `main`, choosing the environment. The plan job starts the plan
   build (`pipeline/buildspec-plan.yml`: `./serena aws pipeline-plan`), which builds and pushes the images tagged with
   the commit, plans the registry and the root, and saves the plans. The job's summary shows only the counts and a
   link to the build in the AWS console: sign in and read the plan in its log. A reviewer other than the person who
   started the run approves, and the apply job starts the apply build (`./serena aws pipeline-apply`), which applies
   exactly those plans. A run with no changes ends after the plan.
5. **What stays an admin's** (the build can't read or set a secret's value, D274, DP12): `./serena aws sim-secrets`
   after the first deploy with the simulator; `cspace-secret`, `etl-token` and `portal-key`; and the CloudFront signing
   key: `./serena aws cdn-key` makes it and stops, the next pipeline run has CloudFront trust it, and `cdn-key` again
   has the app sign with it. Until then the app answers files with the unavailable image.

Once an environment has a pipeline, `./serena aws deploy`, `pause` and `resume` from a laptop are break-glass
deploys (D276): they ask you to type "break glass". `./serena aws pipeline --env <env> destroy` deletes the pipeline
(not the environment); then delete the two GitHub environments.

## Diagrams

The personal root (`deploy/terraform/personal/`, with the shared modules in `deploy/terraform/modules/`; D302)
builds personal-dev, other developers' environments and stage 1, and the shared root (`deploy/terraform/shared/`)
stage 2, QA, production and the stage 2 rehearsal; within a root, the settings file decides which parts exist and who can reach them. These two diagrams show
the two kinds of environment, read from that Terraform. The table after them lists every difference.

### personal-dev: Richard's personal AWS account

The simulated CollectionSpace and the fake ETL, synthetic data only, reachable only from Richard's addresses. Each
developer's own environment in their own account looks the same.

```mermaid
flowchart LR
  subgraph callers["Richard's addresses only (ALLOWED_CIDRS)"]
    browser["Richard's browser: the admin app, test images"]
    mac["Richard's Mac: ./serena aws (Terraform, AWS CLI)"]
  end

  subgraph edge["CloudFront (global)"]
    cf["Distribution, HTTPS at its *.cloudfront.net address"]
    fn["CloudFront Function: allows only Richard's addresses"]
  end

  subgraph account["Richard's personal AWS account, us-west-2 (beside the BMU's personal-dev)"]
    subgraph vpc["VPC across two availability zones"]
      subgraph private["Private subnets"]
        alb["Internal load balancer"]
      end
      subgraph public["Public subnets: no NAT; inbound only from the load balancer"]
        web["ECS Fargate service: the app (FastAPI), 1 task"]
        worker["ECS Fargate service: the worker"]
        sim["ECS Fargate service: simulated CollectionSpace (synthetic files and accounts)"]
        fake["ECS Fargate task: fake ETL (./serena aws etl)"]
      end
      gw["Gateway endpoints: S3, DynamoDB"]
    end
    subgraph data["Data: synthetic only, throwaway (PROTECT_DATA=false)"]
      ddb[("DynamoDB: nine tables")]
      museum[("S3: a private bucket per museum")]
      static[("S3: static bucket")]
      secrets["Secrets Manager: ETL tokens, signing keys"]
    end
    subgraph ops["Also in the account"]
      logs["CloudWatch: logs and alarms"]
      sns["SNS: alert email to Richard"]
      kms["KMS key"]
      ecr["ECR: the images"]
    end
  end

  browser --> cf
  cf --- fn
  cf -->|"VPC origin"| alb
  alb --> web
  cf -->|"signed URLs only"| museum
  cf -->|"unavailable images"| static
  web --> gw
  worker --> gw
  gw --> ddb
  gw --> museum
  web --> secrets
  web -->|"Media service calls"| sim
  fake -->|"ETL API"| alb
  fake -->|"adds synthetic records"| sim
  logs -->|"alarms"| sns
  mac -.->|"deploys, sets secrets"| account
```

### The UC Berkeley AWS account: stage 2 (shared QA), then production

The shared root (`deploy/terraform/shared/`, D302): the split (D289 to D301). Stage 2 is the first build of the shared QA
environment (EN1), in Ops's VPC (D303). It starts with only the simulator museum, deployed by `./serena aws` as the
stage 2 deployer (D300, TQ8; checklist section 50), and then gets PAHMA's QA records (Lyrasis's QA tenant) through the
deploy pipeline (D268), with data protection on. Production has the same shape, with PAHMA's production CollectionSpace
and the production ETL (Jira CSW-1027). Stage 1 (CS-9523) ran in the UC Berkeley test account from the personal root,
like the personal-dev diagram above, and was destroyed on October 31, 2026.

```mermaid
flowchart LR
  subgraph callers["Callers"]
    visitors["Visitors: Glimmer pages and browsers"]
    apache["Apache on webapps-qa: proxies the legacy image paths (APACHE_CIDRS)"]
    testers["Testers and admins, on campus networks or the VPN (ADMIN_CIDRS)"]
    etl["The ETL server (ETL_CIDRS)"]
    deployer["./serena aws while only the simulator museum; then the deploy pipeline (D268); admins set secrets"]
  end

  dns["Campus name from DevOps (D293)"]

  subgraph edge["CloudFront (global): the files only (D293)"]
    cf["Files distribution, HTTPS at its *.cloudfront.net address"]
    fn["CloudFront Function: only removes /museum from a file's path (D307)"]
  end

  subgraph lyrasis["Lyrasis"]
    cspace["PAHMA's QA CollectionSpace (production's, in production)"]
  end

  subgraph account["UC Berkeley AWS account, us-west-2"]
    subgraph vpc["Ops's VPC across two availability zones (D303)"]
      subgraph public["Public subnets"]
        alb["Internet-facing load balancer: HTTPS only, ACM certificate; listener rules for /etl/ and /admin (D291)"]
        waf["Regional WAF web ACL (D292, D306)"]
        nat["Ops's NAT gateway"]
      end
      subgraph private["Private subnets: inbound only from the load balancer"]
        web["ECS Fargate service: the app (FastAPI), 2 tasks"]
        worker["ECS Fargate service: the worker"]
        sim["Simulated CollectionSpace and fake ETL: the simulator museum only (D300)"]
      end
      gw["Gateway endpoints: S3, DynamoDB (Ops's, or Serena's if missing)"]
    end
    subgraph data["Data: protected once it holds real records (PROTECT_DATA=true)"]
      ddb[("DynamoDB: nine tables")]
      museum[("S3: a private bucket per museum")]
      static[("S3: static bucket")]
      secrets["Secrets Manager: read-only CollectionSpace account, ETL tokens, signing keys"]
    end
    subgraph ops["Also in the account"]
      logs["CloudWatch: logs and alarms"]
      sns["SNS: alert email to the team's list"]
      kms["KMS key"]
      ecr["ECR: the images"]
    end
  end

  visitors -->|"legacy image paths"| apache
  apache --> dns
  testers --> dns
  etl -->|"/etl/: daily servable list"| dns
  dns --> alb
  waf --- alb
  alb --> web
  visitors -->|"302 to a signed URL"| cf
  cf --- fn
  cf -->|"signed URLs only"| museum
  cf -->|"unavailable images"| static
  web --> gw
  worker --> gw
  gw --> ddb
  gw --> museum
  web --> secrets
  web -->|"HTTPS, read-only account"| nat
  nat --> cspace
  web --> sim
  sim -->|"fake ETL: /etl/ through the NAT gateway"| nat
  logs -->|"alarms"| sns
  deployer -.->|"deploys, sets secrets"| account
```

In both, the app's signed URLs send a visitor's browser to `/<museum>/objects/*` on CloudFront (in personal-dev the
app's own distribution, in the shared root the files distribution), which reads the museum's bucket directly, and the
worker never calls CollectionSpace. The Terraform state bucket (`serena-tfstate-<account>-<region>`) is left out:
`./serena aws` creates it once per account.

### What differs between environments

personal-dev and stage 1 are built by the personal root, stage 2 (the first build of the shared QA environment, EN1)
and production by the shared root (D302); within a root, only the settings differ.

| | personal-dev | UC Berkeley, stage 1 (CS-9523) | UC Berkeley, stage 2: shared QA |
| --- | --- | --- | --- |
| Terraform (`TERRAFORM_ROOT`) | personal | personal | shared |
| AWS account | Richard's personal account, beside the BMU's personal-dev | UC Berkeley test account | UC Berkeley account, in Ops's VPC (D303) |
| Front door | CloudFront in front of an internal load balancer | The same | A public load balancer on a campus name (D293, HTTPS only); CloudFront for the files only |
| CollectionSpace | The simulator (`SIMULATED_CSPACE=true`) | The simulator | First the simulator museum only (D300); then PAHMA's QA records |
| ETL | Fake ETL (`./serena aws etl`) | Fake ETL | Fake ETL for the simulator museum; then the ETL (Jira CSW-1027) |
| WAF (`WAF`) | Off | Off | On, on the load balancer (D292, D306) |
| Data protection (`PROTECT_DATA`) | Off: throwaway | Off: destroyed when stage 1 passes | Off with the simulator only; on with real data |
| App tasks (`WEB_COUNT`) | 1 | 2 | 2 (D188) |
| Who can reach it | Richard's addresses (`ALLOWED_CIDRS`) | Campus networks and the VPN | The Apache hosts (`APACHE_CIDRS`), the ETL servers for `/etl/` (`ETL_CIDRS`), campus and VPN for `/admin` (`ADMIN_CIDRS`); all of them for the image paths (TQ6) |
| Alerts (`ALERT_EMAIL`) | Richard | Richard | The team's mailing list |
| Settings | `deploy/environments/personal-dev.conf` and `.local.conf` | `deploy/environments/ucb-stage1.conf` and `.local.conf` (`--env ucb-stage1`) | `deploy/environments/ucb-stage2.conf` and `.local.conf` (`--env ucb-stage2`); SSM Parameter Store with the pipeline (D273) |
| Deployed by | `./serena aws` from Richard's Mac | `./serena aws`, no pipeline (D269) | `./serena aws` while it uses only the simulator; then the deploy pipeline (D268 to D272), or a break-glass deploy (D276) |

## What it creates

- **Network (D187).** A VPC across two zones. The tasks run in public subnets with public addresses and no NAT
  gateway; their security groups take traffic only from the load balancer, so nothing can connect in. The
  internal load balancer is in private subnets. Free gateway endpoints for S3 and DynamoDB.
- **CloudFront (D183).** HTTPS at CloudFront's own address, through a VPC origin to the internal load balancer.
  Nothing is cached but the admin app's built files. A CloudFront Function checks the visitor's address (D185):
  `ALLOWED_CIDRS` reach everything, `ETL_CIDRS` `/etl/` too, `ADMIN_CIDRS` `/admin` too, and the rest (the image
  paths, `/health`) is open with `OPEN_IMAGES=true`. A domain later is an alternate name and a certificate on the
  same distribution.
- **WAF (D186), with `WAF=true`.** AWS's common rule set, known bad inputs, the IP reputation list and a rate limit
  per address, with Bot Control in count mode. The common rule set's body-size rule counts instead of blocking, so
  a servable list can be uploaded. Its logs redact the path and the query string.
- **ECS (D188).** The app (1 vCPU, 2 GB, 50 GB of ephemeral storage for fetches) and the worker (0.5 vCPU, 1 GB),
  on ARM, from one image. A deploy replaces the app's tasks one by one, stops the old worker before the new one
  starts, and rolls back if they don't start.
- **Data.** The nine tables (from `deploy/terraform/modules/core/tables.json`, which `backend/serena/tables.py` generates),
  one bucket per museum (versioned, encrypted with the KMS key, Intelligent-Tiering, no rule that deletes), one KMS
  key with yearly rotation, and the secrets: per museum, its CollectionSpace account, its ETL tokens and, with
  signed access, its portal signing key.
- **Image delivery (D195 to D200).** Once the signing key exists, a behavior per museum, `/<museum>/objects/*`, to its
  bucket through origin access control, for a valid signed URL only (the key group trusts the current key and the
  one before it). The allowlist function removes `/<museum>` from the path. Each bucket's policy lets only this
  distribution read, and only `objects/`; the key's policy lets CloudFront decrypt for this distribution only.
  CloudFront caches the files at its edges and adds `Cache-Control: private, max-age=900`. The public keys are in the
  SSM parameter `/serena-<env>/cloudfront-public-keys`, the private key in the secret `serena-<env>/cloudfront-signing-key`.
- **The unavailable images (D199).** A static bucket, `serena-<env>-static-…` (S3-managed encryption), holds each
  museum's `unavailable.svg`, the default one and the generic `placeholder.svg`, uploaded by Terraform from
  `backend/serena/static/`; served without a signature, with a Content-Security-Policy that stops a script.
- **Alerts and alarms (D201 to D204).** The SNS topic `serena-<env>-alerts`, encrypted with the key, with
  `ALERT_EMAIL` subscribed. The worker emails the watchdog's alerts to it. Six alarms email it when they fire and when
  they clear: no healthy app task for 5 minutes; the worker not running for 10 minutes; 5 or more 5xx answers in 5
  minutes; and, from metric filters on the app's log, 5 or more internal errors, any refusal by CollectionSpace (most
  often a changed password), or 20 or more fetches CollectionSpace didn't answer, each in 15 minutes. Paused, they
  send nothing.
- **Logs.** `/serena/<env>/web`, `/worker` (and `/devtools`), kept 30 days, encrypted with the key. The load
  balancer's and CloudFront's access logs are off (design: Infrastructure and operations).
- **IAM.** One role for the app and one for the worker, with only what each needs (`iam.tf` has the table), and one
  for the fake ETL (its museums' ETL tokens only). Whoever deploys also needs SSM Parameter Store (the public keys)
  and SNS, besides what pull request 17 needed.

## Protecting data (D192)

`PROTECT_DATA=true` (QA and production): tables can't be deleted, `destroy` won't empty the buckets, and deleted
secrets and the key wait 30 days. `false` (personal-dev): `destroy` removes everything. Always, whatever the setting:
point-in-time recovery on every table but the admin sessions, bucket versioning, no rule that deletes, key rotation.

## The deployer's permissions

The IAM policies `./serena aws` needs in a UC Berkeley account are in [`iam/`](iam/README.md): stage 1's permission
set (`serena-deployer-policy-mvp.json`) and stage 2's draft (`serena-deployer-policy.json`), with what else Operations
provides (service-linked roles, CloudFront verification on a new account). personal-dev runs as an administrator.

## Terraform

- **The roots.** `registry` (the image repositories and, for the shared root, the certificate), then `personal` or
  `shared` (everything else), applied in turn with the images pushed in between. Applied by an account's
  administrator only: `rehearsal` (a stage 2 rehearsal's VPC and deployer) and `pipeline` (the deploy pipeline).
  `modules/deployer_policy` splits the stage 2 deployer policy into managed policies for the last two.
- **Versions.** Terraform 1.10 or later (CI uses 1.16.5) and the AWS provider 6.x, pinned by `.terraform.lock.hcl`
  in each folder for Macs and Linux.
- **State** in `s3://serena-tfstate-<account>-<region>/serena/<env>/registry.tfstate` and `personal.tfstate`, versioned
  and private, with a lock file beside it.
- **One account only.** Each configuration refuses any account but the environment's. `./serena aws` ignores
  access keys left in the shell.
- **Running Terraform yourself.** `./serena aws init`, then read-only commands such as
  `AWS_PROFILE=bmu-personal terraform -chdir=deploy/terraform/personal state list`. Use `./serena aws deploy` for changes.

## Checking the Terraform code

CI's `terraform` job runs `terraform fmt -check`, and `validate` and `terraform test` for each root (a simulated AWS
provider: `deploy/terraform/<root>/tests/*.tftest.hcl`, which read the modules' resources through their `test`
outputs), with no AWS sign-in. The pipeline root's test checks the roles' trust (each GitHub environment exactly),
that each role starts only its own build, the build role's denies, and the bucket of saved plans.
`backend/tests/test_deploy.py` checks that the tables and the settings Terraform gives the app match the code. On
your computer, use an empty Terraform folder, since one `./serena aws` initialized points at the state in S3:

```bash
(cd deploy/terraform/personal && export TF_DATA_DIR="$(mktemp -d)" &&
  terraform init -backend=false -lockfile=readonly && terraform validate && terraform test)
```

After changing a `.tf` file: `terraform fmt -recursive deploy/terraform`. After changing a table:
`cd backend && python -m serena.tables > ../deploy/terraform/modules/core/tables.json`.

## Cost (personal-dev, rough us-west-2 prices)

| State | Cost | Main items |
| --- | --- | --- |
| Running | About **$2.75 a day** (about $82 a month) | The app's task (about $31 a month, its extra storage included), the worker (about $14), the simulator (about $7), the load balancer (about $16), three public IPv4 addresses (about $11), the KMS key and secrets (about $2), six alarms (about $0.60). CloudFront, DynamoDB, S3, SNS and the logs cost cents at test volumes. |
| Paused | About **$0.60 a day** | The load balancer, the key and the secrets still bill. |
| Destroyed | Nothing | — |

WAF adds about $15 a month plus Bot Control's fee when it's on. Pause or destroy the environment between test sessions.

Measured in stage 1 (UC Berkeley test account, two web tasks, October 27–30, 2026): ECS about $2.50 a day, about 10%
below the estimate above. The account's other workloads hid the rest, so stage 1's total, about $3.60 a day, adds the
load balancer and public addresses at list price. With the `project` tag active, Cost Explorer can measure this
directly.

## Not yet

- **CORS (D205).** Delivered files carry no `Access-Control-Allow-Origin`. If a portal's JavaScript viewer (3D, PDF)
  needs it in QA, it's a small change.
- **A cost alert (D206).** Not in Terraform; cost tracking is for the UC Berkeley account's ops ticket.
- **60-second requests (D184).** CloudFront waits at most 60 seconds for Serena's answer. A first request whose fetch
  takes longer gets a 504; the fetch still finishes and the next request is a hit. AWS raises the limit to 180
  seconds on request: ask before production.
- **No custom domain.**

## If something goes wrong

These are problems with `./serena aws` itself. For a deployed Serena's alerts, alarms and failed refreshes, see the
recovery runbook, `docs/runbook.md`.

- **"Not signed in to AWS".** The sign-in (8 hours) expired: `aws sso login --profile <profile>`, then repeat the
  command, which changed nothing.
- **"The new signing key … isn't trusted by CloudFront yet".** The apply after `cdn-key` didn't finish:
  `./serena aws deploy` (or `cdn-key`) again finishes it, without making another key.
- **Alarm emails while you work.** Pausing switches them off. A deploy's restart can fire "web down" or "worker down"
  briefly; they clear on their own and email when they do.
- **"Docker isn't running".** Start Docker Desktop and deploy again.
- **The first creation fails.** Terraform stops at the resource that failed and keeps the rest; `./serena aws
  deploy` again continues. A brand-new account sometimes fails once while AWS creates its service roles, and
  CloudFront may refuse distributions until AWS has verified a new account (AWS Support).
- **403 "open only to listed addresses".** Your address changed: `./serena aws allow-my-ip`.
- **A task doesn't start.** `./serena aws logs web` (or `worker`) and `./serena aws status`. An `AccessDenied` in the
  logs means a permission `iam.tf` lacks: note the action and resource for the fix (and for the ops ticket's policy).
- **`./serena aws etl` fails.** Its output is the fake ETL's log. "is the worker running?" means the refresh waited
  past its timeout: check `./serena aws logs worker`. A delta-threshold failure means the last updated refresh had
  a different `--rows`.
- **`destroy` stops at the VPC.** CloudFront removes its VPC origin's network interfaces in the background: run
  `./serena aws destroy` again a few minutes later.
- **"Error acquiring the state lock".** An earlier run was interrupted. Check nothing else is running, then
  `./serena aws init` and `AWS_PROFILE=<profile> terraform -chdir=deploy/terraform/personal force-unlock <lock ID>`.
