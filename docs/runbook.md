# Serena recovery runbook

What an admin does when something goes wrong with Serena: each alert, each alarm, a failed refresh, the failures
nothing alerts on, a failed deploy and the break-glass deploy. It follows `docs/design.md` (The daily sequence,
Watchdog and alerts, Admin actions on refreshes, Infrastructure and operations); where they differ, the design
document wins.

**Draft** (November 1, 2026, F2; brought up to date with the deploy pipeline, settings in SSM and the ETL's token
read on November 3, 2026). To review with the DevOps team (F7). Still open: who is told (the Notifications list open
question), and the break-glass permission set, which Operations hasn't made yet (D276).

## The principle

If the ETL job succeeded (a working public core and a valid ETL list), an admin can always bring Serena up to date
(decided October 9, 2026). Serena's part of the daily sequence never stops or undoes the Solr refresh (D71): on a
failed refresh the public core keeps the day's data and Serena keeps serving its last ETL list update, so the two can
differ for up to a day. Nothing below needs a change in CollectionSpace or in the public core. While Serena is
behind, it never serves a file the public core has dropped since: the worst is a newly public file shown as
unavailable until the next update.

Serena fails closed. Whatever goes wrong, a visitor gets the museum's unavailable image, never an error page or a
file Serena couldn't check.

## Where problems show up

- **Alerts** (the watchdog, admin actions and recalls): the admin app's bell and banner until acknowledged on the
  Alerts page, and an email from the environment's alert topic (`ALERT_EMAIL`) for each. A problem that holds is raised
  again the next day, so acknowledging an alert doesn't hide a problem for long.
- **Alarms** (CloudWatch): an email from the same topic when one fires and when it clears. They send nothing while
  the environment is paused.
- **The ETL job's report**, which the ETL team sees. It reports each refresh's outcome.
- **People**: a curator or a portal user reporting a missing image.

**Who is told:** the team's mailing list, once it exists (open question "Notifications list"; until then the alert
email goes to Richard). Whoever acts on an alert acknowledges it on the Alerts page, so the others see it's handled.

## First look

- **Admin app**, Overview: each museum's current and pending refresh. Then the refresh's page (What went wrong, What
  admins did, the check's result), Alerts, and the Audit log for who did what.
- **`./serena aws status --env <env>`**: the running tasks, the image, image delivery, the alert email's subscription,
  the alarms and any firing, each museum's secrets (set or NOT SET) and the ETL server's role that reads its token,
  and whether the pipeline deploys the environment.
- **`./serena aws settings show --env <env>`**: the environment's settings, which a pipeline environment reads from
  SSM Parameter Store, not from the files on your computer (D273). It marks any the files there disagree with.
- **`./serena aws logs web --env <env>`** (or `worker`): the last 30 minutes, then follows. Logs carry no personal
  data, secrets or signed URLs.

Sign in with your own SSO profile for the environment first. In an environment the pipeline deploys, these commands only
read, apart from setting secrets and settings: never deploy from your computer there except as a break-glass deploy
(below).

## Refresh alerts

### Today's refresh isn't finished by the deadline

- **Means:** today's refresh for the museum isn't `updated` or `abandoned` by the museum's deadline (08:00 Pacific to
  start; Settings), including when no refresh started at all.
- **Check:** Overview and Past refreshes. Did a refresh start today? If it's `checking` or `updating`, it may just be
  late: its page reloads every 5 seconds. If none started, the ETL job didn't reach Serena: ask the ETL team for the
  job's report (the Solr refresh, the ETL list script, the call to `/etl/`).
- **Do:**
  - Started and failed: see the alert for its state below.
  - Never reached Serena: once the ETL job's own problem is fixed, either the ETL team reruns the job, or an admin runs
    the ETL list script on the ETL server and applies its list on Manual refresh (Upload one). Or apply one of the ETL's
    recent lists (Choose from previous), if nothing has changed since. Or wait: the next day's refresh catches up.
  - Refused at the door (the ETL job's report shows a 403 "Not from this address"): the ETL server's address changed
    or isn't in `ETL_CIDRS`. Correct `ETL_CIDRS` with `./serena aws settings push --env <env>`, then run the deploy
    pipeline (Deploys, below).
  - The ETL couldn't read its token: see The ETL can't read its token, below.
- **Escalate:** the ETL team, when the ETL job itself failed or can't reach Serena.

### An ETL list check failed

- **Means:** Serena checked today's ETL list and refused it: nothing changed in what Serena serves.
- **Check:** the refresh's page, What went wrong.
- **Do:**
  - **Only the delta threshold** (the list adds, drops or changes more rows than the threshold allows): find out
    whether the change is expected, for example a museum republished or unpublished many images, a first load, or
    testing. If it is, **Override the delta threshold** on the refresh's page, with why (its kind and your reason).
    The team is emailed. If it isn't expected, don't override: ask the ETL team and the museum what happened in
    CollectionSpace or the public core. The next day's list may look the same.
  - **Anything else** (a malformed list: a wrong header, a line without four fields, a CSID outside Serena's rule, an
    unknown kind or access value, an empty Media CSID, a Blob listed twice): it can't be overridden. The refresh's
    page lists the first 20 problems by line and field. Once the cause is fixed, the ETL team reruns the ETL job, or
    an admin runs the ETL list script again and applies it on Manual refresh. (A list too large, or whose row count
    or checksum doesn't match, is refused at upload: the ETL job's report says so, and the deadline alert follows.)
- **Escalate:** the ETL team for a malformed list.

### An ETL list update failed

- **Means:** the list passed its check, but writing it to the servability table stopped partway. Serena serves some
  of the old list and some of the new, never a file the new list dropped (tighten first, publish last).
- **Check:** the refresh's page ("partly replaced", and when Serena tries again), and `./serena aws logs worker` for
  the cause (DynamoDB throttled or unreachable, a permission).
- **Do:** usually nothing: the worker tries again every 10 minutes for up to 6 hours. Once the cause is fixed, an admin
  can **Retry the ETL list update** at once on the refresh's page. If another admin or the worker got there first, the
  page says so and nothing more is needed. Each try does only what's left.
- **Escalate:** after 6 hours of failures, with the cause in the worker's log: Ops for an AWS problem.

### A refresh was abandoned

- **Means:** a refresh was closed before it finished: a later refresh date's refresh started, or an admin's manual
  refresh replaced it. Its reasons say which.
- **Do:** check that the refresh that replaced it was updated. Nothing else, unless it was replaced by mistake.

### Serena hasn't had an ETL list update in 24 hours

- **Means:** the museum's servability is more than a day old. It follows from the alerts above, or from no refresh at
  all.
- **Do:** as for the deadline alert. It's raised once a day until an ETL list update.

### The placeholder image isn't set

- **Means:** the ETL list lists the museum's placeholder image, but no Media record is named for it on Settings. The
  public sees Serena's generic picture where the museum's placeholder belongs.
- **Do:** on Settings, name the Media record that holds the placeholder image's Blob (Media look up finds it). For
  PAHMA, the record has to exist in CollectionSpace first (issue #166).

### The ETL can't read its token

Where a museum's ETL server reads its token with its own role (D275; `deploy/README.md`, The ETL reads its token with
its own role), a failed read stops the ETL's call to Serena, and the deadline alert follows.

- **Means:** the ETL job's report shows an `AccessDenied` (or `AccessDeniedException`) from Secrets Manager or KMS.
- **Check:**
  - `./serena aws status --env <env>`: is the museum listed with the ETL server's role, and is that the role the
    server runs as (Ops knows)? If it isn't listed, the museum isn't in `ETL_READER_ROLE_ARNS` (`settings show`).
  - If the ETL server is in another AWS account: does the role have its own policy for the two actions, naming the
    secret's and the key's ARNs that `status` prints? Ops checks this in that account.
  - Was the role deleted and made again under the same name? A policy naming the old role no longer matches it. Run
    the deploy pipeline: its plan should show the secret's and the key's policies changing, and applying it names
    the role as it is now.
- **Do:**
  - Correct `ETL_READER_ROLE_ARNS` with `settings push`, then run the deploy pipeline.
  - Until the read works, the ETL can use a token file, the fallback: `./serena aws etl-token <museum> --env <env>
    --show` rotates the token and shows it; give it to the ETL team (CSW-1027), who switch the ETL's token source.
- **A role that is to go:** remove its museum from `ETL_READER_ROLE_ARNS` and deploy before Ops deletes the role. AWS
  refuses a key policy naming a role that no longer exists, so if the role is already gone, every deploy fails until
  the setting is removed.
- **Escalate:** Ops for the ETL server's role; the ETL team for the job.

## Notices of admin actions

These say an admin did something. Nothing to do if it was expected. Otherwise, read the Audit log entry (who, when,
the reason) and ask them.

- **An admin overrode the delta threshold.** Expected only with a reason that explains the change.
- **An admin changed a setting** (the delta threshold or the audit retention).
- **An admin recalled Media records**, **An admin released a recall**, **An admin cancelled a recall**, **A refresh
  ended recalls** (CollectionSpace caught up: no longer listed as public).

### Recalled in Serena, but still public in CollectionSpace

- **Means:** a refresh kept a recall because the ETL list still lists the same Blob as public. Serena keeps serving
  the unavailable image for it, and raises this once per refresh date while it holds.
- **Check:** with the museum's staff, whether the record should be public. At Cinefiles, unpublishing a Media record
  isn't enough: the change reaches the public core only after Lyrasis's denorm job and the next ETL run.
- **Do:** if CollectionSpace should change, the museum's staff change it, and the next refresh ends the recall. If the
  recall was a mistake and CollectionSpace is right, **Release** it on Recalls, with a reason: the file is served again.

## Alarms

| Alarm | Means | Do |
| --- | --- | --- |
| `serena-<env>-web-down`: no healthy app task for 5 minutes | Nothing answers; every request fails at the load balancer | `status` and `logs web`. A deploy that didn't start rolls back by itself. A task that can't start says why in its log (an `AccessDenied`, a missing secret, a bad setting). Escalate to Ops for an AWS problem. |
| `serena-<env>-worker-down`: the worker hasn't run for 10 minutes | No refresh is checked or updated, and the watchdog is silent, so no refresh alerts come | `status` and `logs worker`. The worker's old task stops before a new one starts, so a deploy can fire this briefly. |
| `serena-<env>-web-5xx`: 5 or more 5xx answers in 5 minutes | The app is failing requests | `logs web` for the errors. |
| `serena-<env>-internal-errors`: 5 or more in 15 minutes | Serena couldn't decide (DynamoDB unreachable, say) and served the unavailable image | `logs web`: the `unserved` lines with `internal_error` name the cause. |
| `serena-<env>-cspace-refused`: any, in 15 minutes | CollectionSpace answered 401 or 403, or Serena has no account for the museum: most often the museum's service account's password changed | Get the new password from the account's owner (Lyrasis and the museum), then `./serena aws cspace-secret <museum>`. Misses get the unavailable image meanwhile; files already cached are still served. |
| `serena-<env>-cspace-errors`: 20 or more in 15 minutes | CollectionSpace answered many fetches with an unexpected error, most often a 500 | `logs web`: the `CollectionSpace answered … with an error` lines name the Blob and the status. Many Blobs at once: Lyrasis's status, or ask Lyrasis. In UC Berkeley's QA, a 500 usually means a file that isn't in QA's storage, which needs nothing. Each such file is retried after 10 minutes. |
| `serena-<env>-cspace-unavailable`: 20 or more in 15 minutes | CollectionSpace didn't answer, or answered 429 or 5xx, for many fetches | Lyrasis's status, and `logs web` for the museum. Nothing to fix in Serena; misses get the unavailable image until it answers. Steady 429s mean Lyrasis is limiting Serena's fetches: talk to Lyrasis (the fetch rate, issue #160). |

An alarm that fires during a deploy and clears within minutes needs nothing. The alarms send nothing while the
environment is paused: resume it before relying on them.

## Failures nothing alerts on

- **A missing image.** Someone reports the unavailable image for a file they expect. In the admin app, **Media look
  up** says why Serena serves the file or not, beside the Media record in CollectionSpace. Not listed as public in the last ETL list: it's the ETL's decision (the record isn't
  public in the public core, or the list is a day behind). Recalled: see Recalls. Servable but failing: the Past
  requests page shows the request's reason (`cspace_unavailable`, `cspace_error`, `cspace_refused` and so on).
- **An old image after a replacement.** Staff replaced a Media record's image, and Serena serves the old one: see the
  design's After an image is replaced. The new Blob is served once the ETL list lists it.
- **The alert email stopped.** `status` says whether the subscription is confirmed. A new address needs
  `./serena aws confirm-alerts`.

## Secrets

Secret values never pass through the pipeline or a file. An admin sets each, signed in with their own SSO, and
CloudTrail records it. Each rotation keeps the previous value working until the next one, so the other side can switch
at its own pace.

| Secret | When | Command, then |
| --- | --- | --- |
| A museum's CollectionSpace service account | Its password changed (the `cspace-refused` alarm), or it may have leaked | Ask Lyrasis and the museum to change it, then `./serena aws cspace-secret <museum>` |
| A museum's ETL token | It may have leaked, or the ETL's token file changes | `./serena aws etl-token <museum>`. If the museum's ETL reads its token with its role, the token isn't shown and nothing more is needed: the ETL's next run uses it, and the Audit log shows its calls with `which_key` current. Otherwise `--show` shows it: give it to the ETL team (CSW-1027). Rotate twice to retire the old one at once |
| A museum's portal signing key (Cinefiles) | It may have leaked | `./serena aws portal-key <museum>`; give the key and its ID to Glimmer's team. Rotate twice to retire the old one at once |
| The CloudFront signing key | It may have leaked | `./serena aws cdn-key`. In a pipeline environment it makes the key and stops: run the deploy pipeline, so CloudFront trusts the new key, then `cdn-key` again, so the app signs with it. Rotate twice to retire the old one at once |

## Deploys

An environment with a pipeline is deployed only by it (`deploy/README.md`, The deploy pipeline): Actions › Deploy ›
Run workflow, from `main`. The plan job's summary says what to do next; its link opens the build's log in the AWS
console, where the plan is. A settings change reaches the environment only through a deploy: `settings push`, then a
pipeline run.

| The plan job says | Means | Do |
| --- | --- | --- |
| No changes | The environment matches the commit | Nothing. This is also the check after a break-glass deploy |
| Read the plan … approve | A plan to apply | Read the plan in the build's log. The reviewer, not the person who started the run, approves it if it is what's expected |
| Caution: this plan removes the museum(s) … | The settings no longer name a museum: its bucket (every cached file) and secrets would be deleted | Don't approve unless the museum is really to go. Otherwise correct `CSPACE_TENANTS` with `settings push` and run the deploy again. Where data is protected, Terraform refuses the removal anyway |
| Only the image repositories and certificate change | The registry root changes first | Approve; then run the deploy again for the rest |
| The certificate waits for its DNS validation record | A new name's certificate isn't issued yet | Give DevOps the record from the build's log; run the deploy again once the certificate is issued |
| Unexpected result | The plan build failed | The build's log says why. A missing setting or an `AccessDenied` is fixed in SSM or the deployer's policy (`deploy/iam/`), then the deploy runs again |

When the apply job fails:

- **The plan is of another commit, more than 24 hours old, or gone** (plans are kept 7 days), or Terraform says the
  saved plan is stale (the state changed since it was made): run the deploy again and approve the new plan.
- **The apply stopped partway:** the build's log says where. Terraform's state records what was done, and a deploy that
  doesn't start rolls back to the tasks before it. Once the cause is fixed, run the deploy again: its plan shows only
  what's left.
- **The build ends with "Next: …":** a step only an admin can do, since the build can't set a secret's value
  (`sim-secrets`, `cspace-secret`, `cdn-key`). Do it, signed in with your own SSO.

**Escalate:** Ops for an AWS problem (a quota, a service outage, the deployer's or the build's permissions); GitHub's
status for Actions. If the pipeline itself is broken and a deploy can't wait, use a break-glass deploy.

## Break-glass deploy (D276)

For an urgent deploy when the deploy pipeline is broken. Only in an environment with real data, which the pipeline
otherwise deploys. `./serena aws pause` and `resume` there are break-glass too, and follow the same steps.

1. **Who:** a named admin, with the break-glass permission set, which is separate and time-limited. Tell the team's
   list before you start.
2. **Sign in** with that permission set, as the environment's profile.
3. **From a clean checkout of `main`** (or the commit the fix is on, once reviewed): `./serena aws plan --env <env>`,
   and read the plan. It reads the settings from SSM, as the pipeline does; a setting to change goes in with
   `settings push` first.
4. **`./serena aws deploy --env <env>`.** It asks you to type `break glass`, then, with real data, the account's
   number, to confirm the account is UC Berkeley's. CloudTrail records the session.
5. **Afterwards:** the next pipeline run from `main` must show that the environment matches `main` (a plan with no
   changes, or only the fix once it is merged). Record what was done and why in the incident's notes.

## After an incident

- Acknowledge the alerts it raised, on the Alerts page.
- If an admin action changed what Serena serves (an override, a manual refresh, a release), its reason is in the
  Audit log. Add anything the reason didn't cover to the incident's notes.
- If a step here was wrong or missing, change this runbook in a pull request.
