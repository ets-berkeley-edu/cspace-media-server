# Testing Serena

How Serena is tested, from a pull request to a museum's cutover: each testing scheme, what it sets up, the steps in
order, what it proves and what it doesn't. It sits beside `docs/design.md` (the decisions; its Testing section points
here) and `docs/testing-checklist.md` (the checks done by hand, section by section). The automated suites are
described in `serenade/README.md` (local tests, the AWS tests, the access-log replay).

Written October 25, 2026. Schemes 1 to 6 exist; 7 and 8 are planned and not yet decided (see Planned schemes).

## The schemes at a glance

| # | Scheme | Where it runs | CollectionSpace | Servable list from | Who runs it | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | CI | GitHub Actions | The simulator (in the stack) | The backend's tests, the stack's smoke test | GitHub, on every push and pull request | In use |
| 2 | The local stack | Docker on a Mac | The simulator | The fake ETL (`./serena etl`) | Testers and developers | In use |
| 3 | The ETL's own tests | The ETL repository (`cspace-solr-ucb`) | None (stand-ins for Solr and Serena) | Recorded inputs | ETL developers | In use |
| 4 | personal-dev | A personal AWS account | The simulator, in the environment | The fake ETL (`./serena aws etl`) | Richard, signed in | In use |
| 5 | A personal environment on production CollectionSpace | A personal AWS account, its own environment | Production, read-only | A mock ETL over chosen Media records | Richard, signed in | First run October 25, 2026; torn down after each test |
| 6 | Stage 1 (Jira CS-9523) | The UC Berkeley test account | The simulator | The fake ETL | Richard with Ops | Being deployed |
| 7 | QA/Dev, three museums | A Berkeley account, permanent | Simulator; PAHMA QA (test records); production, read-only | Fake ETL; fake ETL; the real ETL | DevOps | Planned |
| 8 | Production, at cutover | The Berkeley production account | Production | The real ETL | DevOps with each museum | Planned |

### The route a change takes

1. **Locally, before a pull request:** the backend and admin app checks (scheme 1's commands, run by hand), then the
   stack (scheme 2) and, for anything a person could notice, the checklist sections the change touches.
2. **The pull request:** CI (scheme 1) must pass. A change that someone could check by hand adds a checklist section
   in the same pull request; a change to a decision updates `docs/design.md`.
3. **Before merging a change to the deployment or delivery:** personal-dev (scheme 4) with `./serena aws test`.
4. **When the question is "does it work with real records?":** a personal environment on production CollectionSpace
   (scheme 5), read-only, then destroyed.
5. **Before a museum's cutover:** QA/Dev (scheme 7), then production (scheme 8), one museum at a time, PAHMA first.

### Rules that apply to every scheme

- **Synthetic data by default.** Schemes 1, 2, 4 and 6 use only the simulator's synthetic records. Logs, screenshots
  and reports from them may be shared and attached to issues.
- **A real CollectionSpace is only read.** Serena never changes CollectionSpace. Where Serena reads production
  (schemes 5, 7c and 8), the tests that change Serena's own state (marked `changes` or `simulator`) are skipped, and
  nothing from those environments goes into an issue, a pull request or the repository: no file, no screenshot of
  a collection image, no log line with a record's details.
- **Never a secret in the repository.** Accounts, tokens and keys go straight to AWS Secrets Manager through
  `./serena aws cspace-secret`, `etl-token`, `portal-key` and `cdn-key`, which ask for them and never show or save
  them. Account numbers, addresses and alert emails go in `deploy/environments/<env>.local.conf`, which git
  ignores.
- **The AWS tests never run in CI** (D229). Whoever runs them is signed in to that account with `aws sso login`.
- **A deployed museum's CollectionSpace server never changes** (`./serena aws` refuses): its servability, recalls and
  cached files belong to that server's records. Testing another server means another environment (scheme 5) or a
  `destroy` first.

---

## 1. CI

**What:** every push and pull request, in `.github/workflows/ci.yml`. A documentation-only change skips the code jobs.

| Job | Checks |
| --- | --- |
| `backend` | `ruff check`, `mypy`, `pytest` (the backend's unit and integration tests: the CollectionSpace simulator and moto in place of AWS) |
| `admin` | Lint, type check and unit tests; the build includes Vuetify's styles |
| `terraform` | `terraform fmt`; `validate` of the image repositories' and the app's configuration; `terraform test` with a mock provider (`deploy/terraform/app/tests/app.tftest.hcl`) |
| `stack` | Starts the Docker stack (`./serena up`), runs the smoke test, prints the logs if it failed |
| `dependencies` | The requirements files match `pyproject.toml`; `pip-audit` finds no known vulnerability in the pinned packages |

Separately: `audit.yml` (a scheduled and manually started dependency audit, Python and npm) and `security.yml`.

**To run the same checks before pushing** (Python 3.11, Node 22):

```
cd backend && python3.11 -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt && pip install --no-deps --no-build-isolation -e .
ruff check . && mypy && pytest -q
```

```
cd admin && npm ci && npm run lint && npm run typecheck && npm test
```

**Proves:** the code, its types, its tests and its dependencies. **Doesn't prove:** anything about AWS, a real
CollectionSpace or the browser checks (those are schemes 2 and 4). `terraform test` covers only the CloudFront front
door until the shared root's test is added (D298).

---

## 2. The local stack

**What:** everything on a Mac in Docker: Serena's web and worker, the admin app, the CollectionSpace simulator
(`backend/fakecspace`, synthetic records for every museum) and moto in place of AWS. No accounts, keys or network
access to AWS or CollectionSpace.

**Setup, once:** Docker Desktop and `git`; for the browser tests, also Python 3.11 and Chrome.

**For trying it out by hand** (the README's Run it locally):

1. `./serena up` builds and starts the stack (a few minutes the first time). Serena is at http://localhost:8300, the
   admin app at http://localhost:5373/admin/ (synthetic accounts `admin`/`admin`, `pahma-admin`/`pahma-admin`,
   `viewer`/`viewer`, which is refused).
2. `./serena etl pahma` runs a daily refresh through the ETL API with synthetic records and prints file addresses to
   open. Any museum works.
3. Work through the checklist sections the change touches; the README's Trying it out lists the ones that make a tour
   (11, 12, 14 to 17, 19, 22, 23).
4. `./serena down` stops it and forgets everything; `./serena down && ./serena up` starts afresh.

**For the automated browser and HTTP tests** (`serenade/tests/`), on a separate test stack (ports 8400, 5473, 8480,
9400) that never touches the one above:

1. `./serena test` starts the test stack afresh, builds the shared dataset (`serenade/dataset.py`) and runs every test,
   headless, in a fixed order (`serenade/conftest.py`'s `FILE_ORDER`): looking first, then changes to one record,
   then changes to a whole museum, each undoing itself.
2. One test with the browser showing: `./serena test -k t3 --headed`.
3. A failed browser test leaves a screenshot and the page's HTML in `serenade/.run/failures/`; the test stack stays up
   to look at.
4. `./serena test-down` stops the test stack.

**Proves:** Serena's behaviour end to end (serving, refreshes, alerts, settings, recalls, Media look up, sign-in) with
synthetic data. **Doesn't prove:** AWS (IAM, CloudFront, signed URLs from a real key), a real CollectionSpace's
answers, or load.

---

## 3. The ETL's own tests

**What:** in the ETL repository (`cspace-solr-ucb`), golden-file tests of its helpers: each case runs a helper on
recorded inputs and compares its output with the expected files. Two cases cover Serena's side (Jira CSW-1027):
`common-make_servable_list` (the servable list from a stand-in Solr) and `common-serena_refresh` (the whole refresh
against a stand-in for Serena's ETL API: a refresh updated, a failed check, Serena busy or unavailable, a timeout, a
token for another museum, no list, a token file others can read, Serena unreachable, a URL that isn't https).

**Steps,** in that repository:

```
tests/run_golden.sh                                   # every case
tests/run_golden.sh common-make_servable_list common-serena_refresh
```

**Proves:** the ETL's servable list and its calls follow Serena's contract (design.md, The servable list and The ETL
API). **Doesn't prove:** that the ETL's rules pick the right records from a museum's real data (scheme 5 checks some;
7c and 8 check all of PAHMA's).

---

## 4. personal-dev: AWS with the simulator

**What:** Serena deployed by `./serena aws` to Richard's personal AWS account (`deploy/environments/personal-dev.conf`),
with the simulated CollectionSpace and a fake ETL running inside the environment. CloudFront is always in front of
everything here (decided October 24, 2026). Image paths, `/etl/` and `/admin` answer only the allowed addresses.

**Setup, once:**

1. An AWS CLI profile for the account (IAM Identity Center): `aws configure sso --profile <profile>`, named as the
   environment's `AWS_PROFILE`.
2. The first `./serena aws deploy` creates `deploy/environments/personal-dev.local.conf` (not committed) and asks for
   the account number, the allowed addresses and the alert email.
3. `./serena aws confirm-alerts` once the subscription email arrives.

**Steps, each session** (from the clone, on the branch being tested):

1. `aws sso login --profile <profile>`, then `./serena aws status`. If it's paused: `./serena aws resume`.
2. If the branch changes the deployment: `./serena aws deploy` (builds and pushes the images, shows Terraform's plan,
   asks before applying). Read the plan before answering.
3. `./serena aws etl pahma` (the simulator forgets its records on every deploy, pause or resume, so run it again
   after each).
4. `./serena aws test`: the 16 AWS tests, T90 to T105 (`serenade/aws/`). They check the status, `/health` and the
   image, the fake ETL's refreshes, a file's 302 to a signed URL and its delivery, bad and missing signatures, the
   bucket refusing direct requests, the unavailable images, the admin app's pages, a recall and its cancellation, and
   no `AccessDenied` in the logs. What they change (a refresh of synthetic records, a recall) they undo.
5. The checklist's AWS sections the change touches (24 to 30 and 32), for what stays by hand: the deploy, plans,
   emails, `cdn-key`, pause and destroy.
6. Optionally, load: the access-log replay (`./serena aws replay`, checklist section 32, `serenade/README.md`): the
   legacy imageserver's busiest hour or minute against the simulator, cold or warm, with the tasks' CPU and memory
   afterwards. Put the servable list back (`./serena aws etl pahma`, overriding the delta threshold) before
   `./serena aws test` again.
7. `./serena aws pause` when done (the data stays; the simulator's records don't).

**Proves:** the deployment, IAM, CloudFront and signed delivery, the alarms, the admin app in AWS, and the tasks'
size under a replayed load. **Doesn't prove:** the split front door (the load balancer in front of the app, used by
stage 2 and production), real records, Apache in front, or WAF.

---

## 5. A personal environment on production CollectionSpace

**What:** a second environment in the same personal account, beside personal-dev, whose museum (PAHMA) reads
production CollectionSpace with a read-only account. A mock ETL builds a servable list from Media records picked by
hand, applying PAHMA's ETL rules, and sends it through the ETL API, as the real ETL will. First run October 25, 2026
(decisions M1 to M25, `serena-mock-servable-list-questions.xlsx`, kept by Richard). Production files are fetched into
the environment's private bucket, so the environment is destroyed after each test (M2).

**The mock ETL** is a script outside this repository (in Richard's rtl folder, `serena/tools/mock-etl/`, with its own
README), to move into `devtools/` if QA/Dev needs it. Python 3.9 or later, standard library only. It imports, unchanged,
the ETL's `make_servable_list.py` (to build and write the list) and `serena_refresh.py` (to send it), from a clone of
`cspace-solr-ucb`.

- `mock_etl.py make <media list>`: the input is a page of `/cspace-services/media?pgSz=100` saved from a browser (XML,
  or the browser's rendering of it). It asks for the server, a user name and a password (hidden; nothing is saved,
  printed or logged), refuses anything but https, and stops at the first 401 or 403. One call at a time, 0.2 s apart
  (about 350 calls and 2 to 4 minutes for 100 records), it reads each Media record, its Blob, its related Objects and
  each Object's field collection place up its broader places, and applies `mergeObjectsAndMediaPAHMA.py`'s public run:
  - not in the public core: Media deleted, no Blob, no related Object (or only deleted ones);
  - withheld (PAHMA's placeholder image instead): not approved for web; an Object status containing "culturally"
    (catalog cards excepted);
  - kind: catalog card, HSR datasheet, Index or Ledger (by description, or Ledger in the file name) is a card; JPEG,
    PNG and TIFF are images; x3d is 3D; MP3, AAC and WAV audio; MP4 video; anything else (PDF, DNG, NEF, PSD, Word)
    isn't listed;
  - an Object collected in the United States whose context of use says burial, whose name says charm stone, or whose
    record says Associated Funerary Objects or Human Remains loses all its images to the placeholder; if its place
    hierarchy can't be read, it counts as the United States (failing closed);
  - an Object with 3D media keeps no placeholder among its images;
  - the placeholder is always listed once.

  One approximation: the ETL searches its whole joined metadata line for those words; the mock searches the Object
  record. It writes `out/servable-list.pahma.<timestamp>.tsv` and a report beside it, one row per Media record: its
  verdict, the rule that decided it, and flags (Human Remains, funerary, burial, charm stone, held in trust, sacred,
  culturally; collected in the United States; place unreadable).
- `mock_etl.py send <servable list>`: every listed record with a flag must be confirmed, one by one, before anything
  is sent (M23); then it asks for Serena's URL and the museum's ETL token (hidden) and runs the ETL's refresh: ping,
  start, upload, check, poll.

**Setup, once per environment:**

1. **A role for your sign-in:** your own production PAHMA account has the `Serena_Admin` role (it carries no
   permissions; Serena only reads that you have it, at sign-in). The admin app and the AWS tests sign in with it.
2. **A read-only service account** for Serena's fetches, not a person's own login.
3. **The environment's settings,** in `deploy/environments/`, neither committed:
   - `<env>.conf`: a copy of `personal-dev.conf` with its own `SERENA_ENV_NAME` (every resource name and the Terraform
     state follow it), `SIMULATED_CSPACE=false`, `CSPACE_TENANTS="pahma=https://<production server>"` and an
     `ENV_LABEL` that says it's production data. Add the file to `.git/info/exclude`.
   - `<env>.local.conf`: the account number, allowed addresses and alert email (git ignores `*.local.conf`).
4. **Deploy and set its secrets,** from the clone, signed in. Each command in its own step; read the plan before
   answering "yes" (it should only create):

   ```
   ./serena aws --env <env> deploy
   ```

   ```
   ./serena aws --env <env> cspace-secret pahma
   ```

   ```
   ./serena aws --env <env> etl-token pahma
   ```

   The ETL token is shown once: keep it for the send. Then `./serena aws --env <env> confirm-alerts` with the link
   from AWS's email.

**Steps, each test:**

1. **Pick the records.** Save a page of the Media list from production, for example
   `/cspace-services/media?pgSz=100&pgNum=10`. The newest page is mostly repatriation documents (PDFs, which aren't
   served), so a page further back gives more images.
2. **Make the list and read the report:** `./mock_etl.py make <saved page>`. Check the counts it prints and the
   reasons for what isn't listed. Make it again with another page if too few are listed.
3. **Send it:** `./mock_etl.py send out/servable-list.pahma.<timestamp>.tsv`. A new environment's first refresh skips
   the delta threshold; a later one with different records fails it, and an admin overrides it on that refresh in the
   admin app.
4. **Check delivery** from an allowed address:

   ```
   ./serena aws --env <env> list pahma --limit 5
   ```

   then, with one of its addresses in `U`: `curl -s -o /dev/null -w '%{http_code}\n' "$U"` (302 to a signed URL; the
   first request makes Serena fetch the file from CollectionSpace), then `curl -sL -o /tmp/test.jpg -w '%{http_code}
   %{content_type}\n' "$U"` (200 and the image) and open the file.
5. **Run the AWS tests;** only the tests that look run against a real CollectionSpace:

   ```
   SERENADE_ADMIN_USER=<your PAHMA user name> ./serena aws --env <env> test
   ```

6. **Look in the admin app:** the Overview's refresh, Past requests (the fetches), Media look up beside
   CollectionSpace.
7. **Destroy it when done** (M2); it removes every file fetched from production and the secrets:

   ```
   ./serena aws --env <env> destroy
   ```

**First run, October 25, 2026:** the newest 100 Media records listed 10 (81 were PDFs with no related Object); a page
further back listed 95 of 100 (90 images, 5 catalog cards, from 36 Objects). Delivery worked (302, then the JPEG), and
the AWS tests passed once the alert email was confirmed and T99 accepted PAHMA's CSIDs, which are shorter than UUIDs
(pull request #93).

**Proves:** Serena fetches, stores and delivers real PAHMA files through a real ETL client and the ETL API; the ETL's
rules, applied to real records, behave as expected on a sample. **Doesn't prove:** the real ETL's full list (a few
hundred thousand rows) or its nightly timing, the split front door, Apache, or parity with the legacy imageserver
(not yet run here; see Not yet covered).

---

## 6. Stage 1 in the UC Berkeley test account (Jira CS-9523)

**What:** Serena with the simulator in the Berkeley test account, deployed by Richard with Ops under the deployer
role Ops created (`deploy/environments/ucb-stage1.conf`, profile `serena-stage1-deploy`, every command with
`--env ucb-stage1`). CloudFront in front of everything, no pipeline (D269).

**Steps:** checklist section 31, which has the setup and every command: steps 1 to 8 with Ops (deploy, status,
secrets, the address rules from campus, the VPN and off campus, the AWS tests); step 9, three replays (about 2½ hours);
step 10, a week of cost data; step 11, destroy. Each `AccessDenied` changes the permission set and the deployer
policy.

**Proves:** Serena deploys and runs in a Berkeley account under its permission set, the address rules hold there, and
what its tasks cost. **Doesn't prove:** the split front door or real records.

---

## Planned schemes

Proposed October 24, 2026, with Richard's answers in `serena-testing-plan-questions.xlsx`; not yet written as
decisions. They depend on a permanent QA/Dev environment with the split front door (stage 2 itself, D300), webapps-qa's
Apache in front of it (Q22), accounts from Lyrasis (Q8, Q10) and the changed ETL (CSW-1027, E1).

### 7. QA/Dev: three museums in one permanent environment

A Berkeley account, the split front door (a load balancer in front of the app; CloudFront for the files), WAF on the
load balancer, behind webapps-qa's Apache, deployed by the pipeline (amending D269; `./serena aws` until then). The
AWS tests are run by hand, never by CI (D229). Its three museums:

**7a. `pahma-sim`: the simulator, for every test.**
The tests that change Serena's state run here (D227 widened to QA/Dev): refreshes, the delta threshold and its
override, recalls. Also the access checks under the split: from webapps-qa's Apache, campus, the VPN and off campus;
WAF limiting per visitor (keyed on `X-Forwarded-For` behind Apache); a slow first fetch answered rather than cut off.

**7b. `pahma-qa`: PAHMA's QA CollectionSpace at Lyrasis, with test records.**
QA has a copy of production's database but not its files, so a copied record's file answers 500; Serena lists only
records the tests create. Each run:

1. Creates its records with a QA account that can create and hard-delete (Q8): Objects and Media whose identification
   numbers start `SERENA-TEST-`, with generated images (and PDFs for Cinefiles) labelled as test files (Q23).
2. Lists only them with the fake ETL and sends the refresh.
3. Follows a record's life: created and listed, served, image replaced, made non-public (approved for web off),
   deleted; plus unusual formats and very large originals.
4. Hard-deletes every record it created, however the run ends (Q19: hard deletes are all the clean-up needed; QA
   reloads are rare and done by Lyrasis on request).

**7c. `pahma`: production CollectionSpace, read-only.**
Its own read-only production account and its own low call limit, an admin setting (Q10 C), so production's agreed
rate stays production's. The real ETL sends it production's servable list every night (Q20, E1). Tests:

1. **Parity with the legacy imageserver** (Q13 B), on a few thousand logged URLs, following Serena's 302: originals
   byte-identical; resized and watermarked images the same content type and dimensions and a perceptual-hash match;
   each mismatch reported with both answers.
2. **The portals:** Glimmer QA and Blacklight QA (which read production Solr, so link to production records) pointed at
   it through webapps-qa's Apache, one museum at a time, PAHMA first (Q22), as a rehearsal of production's cutover and
   rollback.
3. **A cold replay** at real fetch times against production CollectionSpace.

No notice to Lyrasis, Ops or the museums before a test window (Q18).

### 8. Production, at cutover

PAHMA first, the other museums later (Q14); the legacy imageserver keeps running throughout (Q12).

1. Read-only AWS tests against production.
2. The access checks (Apache hosts, campus, VPN, off campus) and WAF.
3. Museum staff check records they name and sign off (Q15).
4. webapps' Apache switches PAHMA's image paths to Serena; rollback is pointing Apache back at the legacy
   imageserver.

---

## Not yet covered

- **Parity now:** scheme 5 could compare its listed images with the legacy imageserver's before QA/Dev exists.
- **The real ETL end to end:** CSW-1027's changed ETL sending to a personal environment or QA/Dev, instead of the
  mock.
- **Failure drills:** CollectionSpace unreachable, the service account's password changed (the `cspace-refused`
  alarm), a CloudFront signing-key rotation, a failed refresh repaired in the admin app, all in AWS.
- **Cinefiles' signed PDF links** with Glimmer QA and its own portal key (Q16).
- **A security scan** of the public paths and the admin app (for example an OWASP ZAP baseline).
- **The split front door in CI:** `terraform test` for each Terraform root (D298), and the AWS tests taking a file
  URL beside the app URL, with read-only tests of the address rules (D299).
