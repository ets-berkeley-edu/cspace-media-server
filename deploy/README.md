# Serena in AWS

`./serena aws` deploys Serena to an AWS account and looks after it (decisions D181 to D194, October 2026). It is
modeled on the BMU's `./bmu aws`, and the commands are the same where they can be.

- **One environment per settings file** in `deploy/environments/`. `personal-dev.conf` is Richard's personal
  account (us-west-2) and the default. A QA and a production file come with the UC Berkeley account (D182).
- **Infrastructure as code.** Terraform (`deploy/terraform/`) creates everything, so nothing is clicked together in
  the console, and the whole environment can be deleted and created again.
- **No keys or passwords in files.** You sign in with IAM Identity Center (`aws sso login`). Terraform creates
  every secret empty, and `./serena aws` sets them (D191), so no secret is in Terraform's state, a file or the
  shell's history.
- **Only Richard deploys,** from his Mac (D193). CI checks the Terraform code with no AWS sign-in.

What this first round has, and what waits for pull request 18 (D194):

| In pull request 17 | In pull request 18 |
| --- | --- |
| The app and the worker on ECS Fargate, CloudFront (HTTPS, the address rules, WAF where it's on) in front of an internal load balancer, the tables, a bucket per museum, the KMS key, the secrets, the logs. The simulated CollectionSpace and the fake ETL, as an option. | Image delivery: CloudFront behaviors from the museums' buckets with origin access control, the signed-URL key group and its signing key, the unsigned prefix for the unavailable images and the generic placeholder. The SNS topic and its email, and the alarms. |

Until pull request 18, the admin app, the ETL API, the servable list check and servability update, fetching and
storing all work, but a servable file isn't delivered: there is no CloudFront signer yet. Such a request gets the
unavailable image, and Past requests shows the reason "delivery not set up".

## Commands

| Command | What it does |
| --- | --- |
| `./serena aws deploy` | Builds the image (and, with the simulator, the simulator's image) and pushes it, then shows Terraform's plan and, after you type `yes`, applies it and waits until the app and the worker are running. Prints the address and saves it in `deploy/environments/<env>.url`. |
| `./serena aws plan` | Shows what a deploy of the running image would change, without changing anything. |
| `./serena aws status` | The address, the running tasks, the deployed image, the allowed addresses, and each museum with its server and whether each of its secrets is set. |
| `./serena aws url` | Prints the address. |
| `./serena aws logs web` / `worker` / `devtools` | Follows a service's logs, starting with the last 30 minutes. `devtools` (the simulator and the fake ETL) only with the simulator. |
| `./serena aws pause` / `resume` | Stops or starts every service to save money. The data stays. Terraform shows the change and asks first. |
| `./serena aws allow-my-ip` | Adds this computer's current address to the allowlist, and applies it. |
| `./serena aws etl <museum> [--rows N] [--failed]` | With the simulator: runs the fake ETL once, inside the environment, for a whole daily refresh (the same as `./serena etl` on the local stack). Prints the refresh's result and sample image addresses. |
| `./serena aws cspace-secret <museum>` | Sets the museum's read-only CollectionSpace service account. It asks for the user name and password and passes them straight to Secrets Manager. Not with the simulator, whose account deploy sets. |
| `./serena aws etl-token <museum>` | Makes a new random ETL token. The old one becomes "previous" and keeps working until the next rotation. Shows the new token once, for the ETL's token file (Jira CSW-1027). |
| `./serena aws portal-key <museum>` | For a museum with signed access (Cinefiles): makes a new signing key for its signed links, keeping the old one as "previous". Shows the key and its ID once, for the portal (Glimmer). |
| `./serena aws destroy` | Deletes everything in AWS for the environment, data included. It asks for the environment's name first. |
| `./serena aws init` | Points Terraform at the environment's state, to run `terraform` commands yourself. |

**Picking the environment.** Add `--env NAME`, or set `SERENA_AWS_ENV`. The default is `personal-dev`.
`SERENA_AWS_YES=1` applies without Terraform's `yes` prompt.

**Settings** (in `<env>.conf`, or in the uncommitted `<env>.local.conf`, which wins):

| Setting | What it is |
| --- | --- |
| `AWS_PROFILE`, `AWS_REGION` | The AWS CLI profile (IAM Identity Center) and region. personal-dev uses the BMU's profile: the same account, side by side with the BMU. |
| `SERENA_ENV_NAME` | Resource names (`serena-<name>-…`) and the Terraform state's key. |
| `CSPACE_TENANTS` | The museums and their CollectionSpace servers: `"pahma=https://pahma.qa.collectionspace.org"`. Each needs `backend/serena/museums/<museum>.yaml`. |
| `SIMULATED_CSPACE`, `SIMULATED_MUSEUMS` | `true` runs the simulated CollectionSpace for the museums listed (default `pahma`) instead of `CSPACE_TENANTS`. |
| `ALLOWED_CIDRS` | Addresses that may reach everything. The first deploy adds this computer's; `allow-my-ip` adds more. |
| `ETL_CIDRS`, `ADMIN_CIDRS` | Addresses that may also reach `/etl/` (the ETL servers) and `/admin` (campus networks), D185. |
| `OPEN_IMAGES` | `true` lets anyone request the image paths and `/health` (production). `false` limits them to `ALLOWED_CIDRS`. |
| `WAF` | `true` puts a WAF web ACL on the distribution (D186). Off in personal-dev, which is allowlisted anyway. |
| `PROTECT_DATA` | `true` where the data matters (D192): see "Protecting data". |
| `WEB_COUNT` | Web tasks: 1 in personal-dev, 2 elsewhere (D188). |
| `ENV_LABEL` | Shown in the admin app's header. |

**Once deployed, a museum's server never changes.** A museum's servability, recalls and cached files refer to the
records on the server it was deployed for. So `deploy`, `plan`, `pause`, `resume` and `allow-my-ip` stop before
changing anything if a museum's server changed. Either put the setting back, or `./serena aws destroy` first, or
deploy the new server as another environment (a different `SERENA_ENV_NAME` in your `.local.conf`). Adding a museum
is allowed. Removing one asks you to type its name: its bucket (its cached files) and secrets go with it. Never where
data is protected.

## First deploy (personal-dev, with the simulator)

**What you need on the Mac:** Docker Desktop, running; AWS CLI v2; Terraform 1.10 or later
(`brew tap hashicorp/tap && brew install hashicorp/tap/terraform`); python3.

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
   (`backend/Dockerfile`), which runs the simulator and the fake ETL.
5. **Serena.** Terraform lists what it will create and asks; type `yes`. The first time takes about **15–25
   minutes**, mostly CloudFront. It finishes when the app and the worker are running.
6. **Secrets.** With the simulator, deploy sets each museum's secrets once: the simulator's synthetic account, a
   random ETL token and, for a museum with signed access, a random portal key. Nothing is shown.

It prints the address (`https://<something>.cloudfront.net`). The admin app is at `/admin/`: sign in as `admin` /
`admin` (the simulator's synthetic admin, every museum), `pahma-admin` / `pahma-admin`, or `viewer` / `viewer`.

**A daily refresh:** `./serena aws etl pahma` runs the fake ETL as a one-off task inside the VPC. It adds the
day's synthetic Media records to the simulator, then runs the refresh through the ETL API (start, upload, check, poll)
with the museum's ETL token, which it reads from Secrets Manager itself. It takes a minute or two and prints the
refresh's counts. The refresh then shows in the admin app. Run it again with the same `--rows` (the delta threshold
compares with the last one).

**Later deploys.** The same command. Terraform shows only what changed (about 3–5 minutes). Each deploy pushes a new
image tag (commit and time, `-dirty` for uncommitted changes), so `status` shows which code runs.

## Against a real CollectionSpace (QA, then production)

With `SIMULATED_CSPACE=false` and `CSPACE_TENANTS` set, after the first deploy:

1. `./serena aws cspace-secret <museum>` for each museum: its read-only service account.
2. `./serena aws etl-token <museum>`: give the token to whoever runs the ETL, for its token file (CSW-1027). Allow
   the ETL server's addresses with `ETL_CIDRS`.
3. `./serena aws portal-key cinefiles`, once Cinefiles is served: give the key ID and key to Glimmer.

`status` says "NOT SET" for any secret still empty. A token or key rotation keeps the previous one working until
the next rotation, so the ETL or the portal can switch at its own pace.

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
- **Data.** The eight tables (from `deploy/terraform/app/tables.json`, which `backend/serena/tables.py` generates),
  one bucket per museum (versioned, encrypted with the KMS key, Intelligent-Tiering, no rule that deletes), one KMS
  key with yearly rotation, and the secrets: per museum, its CollectionSpace account, its ETL tokens and, with
  signed access, its portal signing key.
- **Logs.** `/serena/<env>/web`, `/worker` (and `/devtools`), kept 30 days, encrypted with the key. The load
  balancer's and CloudFront's access logs are off (design: Infrastructure and operations).
- **IAM.** One role for the app and one for the worker, with only what each needs (`iam.tf` has the table), and one
  for the fake ETL (its museums' ETL tokens only).

## Protecting data (D192)

`PROTECT_DATA=true` (QA and production): tables can't be deleted, `destroy` won't empty the buckets, and deleted
secrets and the key wait 30 days. `false` (personal-dev): `destroy` removes everything. Always, whatever the setting:
point-in-time recovery on every table but the admin sessions, bucket versioning, no rule that deletes, key rotation.

## Terraform

- **Two configurations.** `registry` (the image repositories) and `app` (everything else), applied in turn, with
  the images pushed in between.
- **Versions.** Terraform 1.10 or later (CI uses 1.16.5) and the AWS provider 6.x, pinned by `.terraform.lock.hcl`
  in each folder for Macs and Linux.
- **State** in `s3://serena-tfstate-<account>-<region>/serena/<env>/registry.tfstate` and `app.tfstate`, versioned
  and private, with a lock file beside it.
- **One account only.** Each configuration refuses any account but the environment's. `./serena aws` ignores
  access keys left in the shell.
- **Running Terraform yourself.** `./serena aws init`, then read-only commands such as
  `AWS_PROFILE=bmu-personal terraform -chdir=deploy/terraform/app state list`. Use `./serena aws deploy` for changes.

## Checking the Terraform code

CI's `terraform` job runs `terraform fmt -check`, `validate` for both configurations and `terraform test` (a
simulated AWS provider: `deploy/terraform/app/tests/app.tftest.hcl`), with no AWS sign-in.
`backend/tests/test_deploy.py` checks that the tables and the settings Terraform gives the app match the code. On
your computer, use an empty Terraform folder, since one `./serena aws` initialized points at the state in S3:

```bash
(cd deploy/terraform/app && export TF_DATA_DIR="$(mktemp -d)" &&
  terraform init -backend=false -lockfile=readonly && terraform validate && terraform test)
```

After changing a `.tf` file: `terraform fmt -recursive deploy/terraform`. After changing a table:
`cd backend && python -m serena.tables > ../deploy/terraform/app/tables.json`.

## Cost (personal-dev, rough us-west-2 prices)

| State | Cost | Main items |
| --- | --- | --- |
| Running | About **$2.70 a day** (about $80 a month) | The app's task (about $31 a month, its extra storage included), the worker (about $14), the simulator (about $7), the load balancer (about $16), three public IPv4 addresses (about $11), the KMS key and secrets (about $2). CloudFront, DynamoDB, S3 and the logs cost cents at test volumes. |
| Paused | About **$0.60 a day** | The load balancer, the key and the secrets still bill. |
| Destroyed | Nothing | — |

WAF adds about $15 a month plus Bot Control's fee when it's on. Pause or destroy the environment between test sessions.

## Not in this first round

- **Image delivery, SNS and alarms:** pull request 18 (D194).
- **60-second requests (D184).** CloudFront waits at most 60 seconds for Serena's answer. A first request whose fetch
  takes longer gets a 504; the fetch still finishes and the next request is a hit. AWS raises the limit to 180
  seconds on request: ask before production.
- **No custom domain.**

## If something goes wrong

- **"Not signed in to AWS".** The sign-in (8 hours) expired: `aws sso login --profile <profile>`, then repeat the
  command, which changed nothing.
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
  `./serena aws init` and `AWS_PROFILE=<profile> terraform -chdir=deploy/terraform/app force-unlock <lock ID>`.
