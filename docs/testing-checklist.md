# Serena testing to do (checks by hand)

These are things Claude couldn't test, to be checked by hand. The list was started on October 8, 2026, when the
repository was set up. Tick an item when it's done, and note anything odd under it.

Change this file through pull requests, like `docs/design.md`. When a pull request needs checks by hand, add a
section here in the same pull request.

**Testing a pull request locally.** The checks and the code change together, so take both from the pull request's
branch, in the same clone:

```
git switch <the pull request's branch> && git pull && ./serena down && ./serena up
```

Then read this file in that clone (or on GitHub on that branch, never on `main`). `./serena up` prints the branch and
commit it built, and the admin app's header shows them beside "Local · simulator", for example
"Local · simulator · feature/x @ 1a2b3c4". If they don't name the pull request's branch and latest commit, you're
testing other code: run the line above again. "+ local changes" means the clone has changes not yet committed.

## 1. A replaced image is served on a cache miss (10 minutes, once Serena is in QA)

Replacing a Media record's image creates a new Blob. Until the next daily update, clients still request the old
Blob CSID. On a cache miss Serena checks only that the Media record exists and isn't deleted, then fetches through the
Media service, which returns the record's current image (decided October 9, 2026).

Set up, on a test tenant: pick a Blob CSID that the last updated servable list has as public and that isn't in
Serena's cache yet. After the daily update, replace the image on its Media record in CollectionSpace. Don't wait for
the next daily update.

- [ ] Request the old Blob at its legacy URL (`…/<tenant>/imageserver/blobs/<blob CSID>/derivatives/<size>/content`).
  Expect the new image, not the old one and not an error.
- [ ] In Serena's log, expect the light check for that Media record, then a fetch through the Media service
  (`media/<media CSID>/blob/derivatives/<size>/content`), and no request by the old Blob CSID.
- [ ] After the next daily update, expect the old Blob's URL to get the museum's unavailable image, and the new
  Blob's URL to get the new image.

## 2. A soft-deleted Media record isn't served on a cache miss (10 minutes, once Serena is in QA)

The Media service returns soft-deleted Media records and their files, so Serena's light check must catch them.

Set up, on a test tenant: pick a Blob CSID that the last updated servable list lists as public and that isn't cached, and
soft-delete its Media record in CollectionSpace.

- [ ] Request the Blob at its legacy URL. Expect the museum's unavailable image.
- [ ] In Serena's log, expect the light check finding the record deleted, the reason `media_deleted`, and no fetch.
- [ ] Expect nothing new in Serena's bucket for that Blob.

## 3. A Media record with no image gets the unavailable image (10 minutes, once Serena is in QA)

Set up, on a test tenant: pick a Blob CSID that the last updated servable list lists as public and that isn't cached, and
remove the image from its Media record in CollectionSpace.

- [ ] Request the Blob at its legacy URL. Expect the museum's unavailable image, not an error.
- [ ] In Serena's log, expect the light check to pass and the Media service's fetch to fail, with the reason
  `no_file`. Note the status CollectionSpace returned; if it isn't 404, the reason will be `cspace_refused`, and the
  fetch's handling of that status needs a second look.

## 4. The ETL API with each museum's real token (15 minutes, once Serena is deployed to QA)

Serena's tests use tokens made up at run time and moto in place of AWS. These checks need the QA deployment, each
museum's token secret in Secrets Manager, and a call from the ETL server (the only place the load balancer accepts
`/etl/` from).

- [ ] From the ETL server, `GET /etl/v1/ping` with each museum's token. Expect `200` and `{"museum": "<that museum>"}`.
- [ ] With one museum's token on another museum's path (`POST /etl/v1/museums/<other>/refreshes`), expect `403`.
- [ ] Start a refresh, then upload a real day's servable list (gzip). Expect `received`, with the row count the ETL
  reports, and the file in the museum's bucket under `servable-list/<refresh ID>/`, encrypted with the museum's KMS key.
- [ ] Rotate one museum's token (new one in `current`, old one in `previous`). Within 5 minutes both work; after
  `previous` is cleared, only the new one.
- [ ] In CloudWatch, search Serena's logs for the tokens: expect no match.

## 5. A whole daily refresh through the worker, in QA (30 minutes, once Serena and the ETL change are in QA)

The tests run whole refreshes against moto with synthetic servable lists. These checks use a real servable list, DynamoDB and S3.

- [ ] Run one museum's ETL job against QA. Expect the refresh to go `started`, `received`, `checking`,
  `updating`, `updated`, after the Solr refresh, and the servability table to hold exactly the servable list's rows for that museum.
- [ ] On the ETL server, compare the servable list's row count with the number of `blobmedia_ss` values in the
  museum's public core: expect them equal.
- [ ] Note how long the servable list check and the servability update took for the largest museum (PAHMA), and the worker's memory.
- [ ] The next day, expect the servable list check's added, removed and changed counts to match a diff of the two files.
- [ ] Stop the worker's task during a servability update; a new task starts. Expect the servability update to start again after about
  5 minutes and end `updated`, with the table matching the servable list.
- [ ] Upload a file with 10% of the rows removed: expect `check_failed`, the delta as a percentage, and the table
  unchanged.

## 6. Alerts by email, in QA (15 minutes, once Serena and its SNS topic are in QA)

The tests use moto's SNS. These checks need the real topic and the team's mailing list subscribed to it.

- [ ] Set a museum's deadline a few minutes ahead in the admin app (or its Settings item) and start no refresh for it.
  Expect one email to the mailing list within 5 minutes after the deadline, naming the museum, the refresh date and what
  to do, and one alert record. Expect no second email on the next passes.
- [ ] Make a servable list check fail (upload a servable list with a bad kind). Expect an email titled "A servable list check failed" with the refresh ID
  and the reason.
- [ ] Check the email has no personal data and no link with a token or signature in it.
- [ ] Make a servable list check fail only on the delta threshold, then override it in the admin app. Expect an email
  titled "An admin overrode the delta threshold" within 5 minutes (the web app records the alert; the worker sends it
  on its next pass), with the refresh ID and the reason. Do it again on a second refresh: expect a second email.
- [ ] Try to unsubscribe from the email's link without signing in to AWS: expect it to be refused (the subscription
  requires authentication to unsubscribe).

## 7. Signed URLs through CloudFront, in QA (15 minutes, once Serena is in QA)

The tests check the signature against a key made at run time and serve files through the local stand-in.

- [ ] Request a cached image at its legacy URL. Expect a 302 to `<CloudFront>/<tenant>/objects/<sha256>?Expires=…`,
  with `Cache-Control: private, max-age` of 15 to 30 minutes, and the image from CloudFront.
- [ ] Request the same URL without its query string, and with a changed `Signature`. Expect 403 from CloudFront.
- [ ] Request it again after `Expires`. Expect 403.
- [ ] Two requests in the same 15-minute window get the same URL; the second is served from CloudFront's edge cache
  (`X-Cache: Hit from cloudfront`), which checks that the signature's parameters are left out of the cache key.
- [ ] Take the image's Media record down in the admin app. Expect the legacy URL to get the unavailable image at once,
  and the signed URL already handed out to stop working when it expires.
- [ ] Rotate the CloudFront signing key (new key in the key group and the secret). Within 5 minutes, new URLs use the
  new key pair ID and work.

## 8. Each museum's CollectionSpace service account (10 minutes per museum, once the accounts exist)

The tests run against the CollectionSpace simulator, which can't show whether a real tenant's account works, whether
its soft-delete states are the ones Serena looks for, or what a real Media service returns for each kind.

Set up: the museum's read-only service account exists, and its secret (`{"username": ..., "password": ...}`) is in
Secrets Manager. Run these from a shell with the AWS profile set, without printing the secret.

- [ ] Light check on a public Media record. Expect it reported as existing.
- [ ] Light check on a soft-deleted Media record, and on a made-up Media CSID. Expect deleted, then gone. Note the
  `workflowState` value the soft-deleted record shows.
- [ ] Fetch a derivative and the original of an image, and a file of each other kind the museum has. Expect 200 and
  the content type for each; note any that differ from the kinds in the design.
- [ ] Change the secret's password to a wrong one for a moment, then back. Within 5 minutes expect a 401 that isn't
  retried, and nothing about the password in the log.

## 9. Cinefiles' restricted PDFs through Glimmer's signed links, in QA (20 minutes, once Glimmer signs its links in QA and Serena is in QA)

The tests check the signature with synthetic keys and links. This checks that Glimmer and Serena agree on real ones.

Set up: the QA signing key is in Serena's secret and Glimmer's credentials, with matching fingerprints (the
operations task). Pick a restricted PDF (a Cinefiles document whose access code isn't World) and a public one. Use a
test reader's Glimmer account.

- [ ] Signed in to Glimmer, open the restricted document's PDF ("view full size" and the embedded viewer). Expect the
  PDF, and the redirect sent with `Cache-Control: no-store`.
- [ ] Copy the PDF link, remove its query string, and open it in a private window. Expect the unavailable image.
- [ ] Change one digit of `uid` in the link. Expect the unavailable image; Serena records `signature_invalid`.
- [ ] Wait past the link's lifetime (or use a link from a page left open that long). Expect the unavailable image and
  `signature_expired`; reloading Glimmer's page gives a working link.
- [ ] Signed out, open the public document's PDF. Expect the PDF.
- [ ] Take the restricted PDF's Media record down in the admin app. Expect the unavailable image even with a fresh
  signed link; then unlock it.
- [ ] In Serena's log, find the served entry: it shows `signed` and the key ID, and no `uid`, `sig` or `exp`. In the
  webapps host's Apache access log, expect no `uid` or `sig` values.
- [ ] Rotate the QA key in the order the design gives. Links signed before and after the switch both work during the
  hour that follows.

## 10. Real files on a cache miss, in QA (30 minutes, once Serena is in QA)

The tests use the simulator's small synthetic files. This checks what the museums' real files look like.

- [ ] For each museum, request a derivative and (where served) the original of a few images that aren't cached.
  Expect each served, and a `fetched` log entry with its size and time.
- [ ] Request a 3D file at each museum that has them. Note the content type CollectionSpace sends (Serena's log shows
  it on a `wrong_content_type` refusal). If real 3D files arrive as a type Serena doesn't allow, such as
  `application/octet-stream`, stop and decide whether to allow it.
- [ ] Request a few Cinefiles public PDFs, old and new. Expect each served; any `wrong_content_type` means a PDF
  without `%PDF-` in its first 1024 bytes: note it.
- [ ] Note whether any museum has JPEG 2000 (`image/jp2`) originals. Serena refuses them as `wrong_content_type`.
- [ ] Request the largest original image you can find (a TIFF of several hundred MB). Note how long the first
  request takes. It must finish within the load balancer's 300 seconds and within the proxy timeout of Apache on the
  webapps host (Apache's own default is 60 seconds; DevOps raises it to match). The second request is a hit.
- [ ] Request a file that isn't cached from two browsers at the same moment. Expect one `fetched` log entry, and both
  served.
- [ ] Request a Blob whose Media record is soft-deleted, twice within 10 minutes. Expect one light check in
  CollectionSpace's access log, not two.

## 11. The local stack on a Mac (15 minutes, before merging pull request 10)

CI's `stack` job runs the stack on Linux. This checks it where the team develops.

- [ ] With Docker Desktop running, from the repository's root: `./serena up`. Expect "Serena (Local · simulator) is up"
  within a couple of minutes, and nothing else on ports 8300, 8380 or 9300. If the BMU's stack is running, both run.
- [ ] `./serena etl pahma`. Expect `updated`, one servable list check warning (PAHMA's first servability update, so the delta threshold
  doesn't apply), and sample addresses for an image and a catalog card. Open the image one in a browser: expect a grey
  square. Open it again: expect the same, now from Serena's store (`./serena logs --no-follow web | grep '"fetched"'`
  shows one fetch).
- [ ] `./serena etl cinefiles`. Open the `pdf` sample: expect a one-page PDF. Open the `pdf (restricted)` sample:
  expect the unavailable image (no signed link).
- [ ] `./serena etl bampfa --failed`. Expect a note that Serena wasn't called, and no new BAMPFA refresh in Serena.
- [ ] `./serena smoke`, after the refreshes above. Expect "Smoke test passed".
- [ ] `./serena etl pahma --rows 3`. Expect `check_failed`, with the threshold explained: 17 of PAHMA's 21 rows (its 20
  plus the placeholder image) would be removed, 80.95%, more than its 5% threshold. This is the servable list check protecting the servability table, not a fault.
- [ ] `./serena down`, then `./serena up` and `./serena etl pahma` again: everything starts afresh.
- [ ] Note the digest of each base image under this item, so a later pull request can pin them by digest too:

  ```
  docker buildx imagetools inspect python:3.11-slim | grep -m1 Digest
  docker image inspect --format '{{index .RepoDigests 0}}' motoserver/moto:5.2.3
  docker image inspect --format '{{index .RepoDigests 0}}' node:22-alpine
  ```

  `python:3.11-slim` is the base of the image built from `backend/Dockerfile`; Docker Desktop keeps it as build cache,
  not as a named image, so its digest comes from Docker Hub (or `docker pull` it first and use `docker image inspect`).
  The other two are the `moto` and `admin` containers' images. Each line ends in `sha256:…`, the digest to pin.

## 12. The admin app, locally (15 minutes, before merging a pull request that changes the admin app's sign-in)

The unit tests stub the API, and CI doesn't run a browser. This checks the app in Chrome.

- [ ] `./serena up`, then open http://localhost:5373/admin/. Expect the sign-in page with the five museums.
- [ ] Sign in to PAHMA as `admin` (password `admin`). Expect PAHMA's overview, and the museum menu in the header.
- [ ] Open "API documentation". Expect Swagger UI listing the ETL API's endpoints, with no "Try it out" button, and
  nothing in the browser's console about the Content-Security-Policy.
- [ ] Open "Audit log". Expect the sign-in, with `admin` and the time.
- [ ] From the museum menu, sign in to BAMPFA as well, as `admin`. Expect both in the menu, and switching between them.
- [ ] Sign out of PAHMA. Expect BAMPFA still signed in.
- [ ] Two sign-ins that must be refused. The simulator's accounts have their name as their password: `admin` is a
  Serena admin of every museum, `pahma-admin` of PAHMA only, and `viewer` of none. Go to
  http://localhost:5373/admin/sign-in and:
  - sign in to BAMPFA as `pahma-admin` (password `pahma-admin`). Expect it refused, with a message naming the
    `Serena_Admin` role;
  - sign in to PAHMA as `viewer` (password `viewer`). Expect the same.

  Expect the museum menu unchanged: BAMPFA still signed in as `admin`, and PAHMA not signed in.
- [ ] `./serena ui`. Expect 2 passed (needs Chrome and python3.11).

## 13. Admin sign-in against a real museum, in QA (15 minutes per museum, once Serena is in QA)

Set up: the museum's CollectionSpace administrators have created the `Serena_Admin` role in QA and given it to you.

- [ ] Sign in to the museum with your own QA account. Expect the overview.
- [ ] In Serena's log, find the sign-in: the museum, and no username or password. In the audit log, your username.
- [ ] Sign in with a wrong password. Expect "don't work", and nothing in the audit log.
- [ ] Have the role removed from your account, then sign everyone out from another admin's session. Expect your
  next request to need a new sign-in, which is refused with the role named.
- [ ] Check the cookies in the browser's developer tools: `serena_admin_<museum>`, HttpOnly, Secure, SameSite Strict,
  path `/admin`.

## 14. Refreshes and alerts in the admin app, locally (20 minutes, before merging a pull request that changes them)

The API's tests cover each action, and the pages were checked in a headless browser in Claude's workspace. This
checks them in Chrome on a Mac. Start afresh: `./serena down && ./serena up`, then open http://localhost:5373/admin/
and sign in to PAHMA as `admin` (password `admin`).

About alerts: the watchdog runs in the worker every 5 minutes. Past 08:00 Pacific, its first pass raises "Today's refresh
isn't finished by the deadline" for every museum, because no refresh has started: acknowledge PAHMA's. A failed
servable list check raises its own alert at once, from the worker. The app checks for new alerts on every page change and
every minute, so an alert appears within a minute of being raised: the bell at the top right gets a red badge with the
number of unacknowledged alerts, and a one-line banner under the top bar names the newest one, with "Open alerts". Both
go once every alert is acknowledged on the Alerts page (the bell opens it).

- [ ] In a terminal: `./serena etl pahma`. Expect `pahma-<today>-1: updated`, one servable list check warning
  (PAHMA's first servability update, so the delta threshold doesn't apply), and the counts: `servable list: 21 rows`
  (the 20 synthetic rows plus PAHMA's placeholder image) and `servability update: 21 written, 0 deleted, 0
  unchanged`. In the app, open "Past refreshes": expect that refresh, `Updated`, with 21 in the Rows column.
- [ ] In a terminal: `./serena etl pahma --rows 3`. Expect `check_failed` and `servable list: 4 rows; 0 added, 17
  removed, 0 changed (80.95% of the last servability update's 21 rows)`. In the app, open "Past refreshes", then the
  refresh: expect "Servable list check failed", the problem (80.95% of the rows would change; the threshold is 5%), and
  a red button, "Override the delta threshold". Within a minute, expect the banner, and the Alerts page (the bell), to show
  "A servable list check failed" for that refresh.
- [ ] Click that button. A dialog opens with a Reason box. Its red button, "Override the delta threshold", says "Give
  a reason first." under the Reason box if you click it without one (section 21). Type one and click it. Expect:
  - the banner, with "2 alerts: An admin overrode the delta threshold" ("A servable list check failed" stays until
    acknowledged), and the bell's badge showing 2 (or one more, if the deadline alert is still waiting);
  - after reloading the page, the same refresh `Updated`, with no red button, its reasons naming the override and
    its check's warnings saying the delta threshold was skipped.
- [ ] Click "Open alerts" in the banner and acknowledge each alert. Expect the banner and the badge gone once none is
  left, and the alerts with your name and the time.
- [ ] In a terminal: `./serena etl pahma`. Expect `pahma-<today>-3: check_failed` and `servable list: 21 rows; 17 added,
  0 removed, 0 changed (425.0% of the last servability update's 4 rows)`: after the override, Serena serves the
  3-row list (4 rows with the placeholder image), so the default 20 rows are far over the delta threshold. This is
  on purpose: leave the refresh `check_failed` (open), and the admin refresh below repairs it.
- [ ] In a terminal: `./serena etl pahma --rows 3 --file-only > /tmp/pahma-servable-list.tsv` (the stand-in for running
  the servable list script on the ETL server). In the app, open "Start a refresh". Choose the file (in the Mac
  file picker, press Cmd+Shift+G, type `/tmp/pahma-servable-list.tsv` and press Return). The refresh date starts as
  today, with a calendar picker; leave it. Type a reason, tick "This servable list was made from the live public core"
  and click "Start the refresh" (clicked too soon, it says what's missing under each field: section 21). Expect the new refresh's page, "an admin refresh, with
  the servable list for <today>", and, after reloading the page, `Updated`. On "Past refreshes", expect the `check_failed`
  refresh now `Abandoned`, its reasons naming the admin refresh.
- [ ] Open "Audit log". Expect the override, each acknowledgement and the admin refresh, each with `admin`. Expect the
  ETL's calls too, by `ETL (pahma)`, which key `current`: for each `./serena etl pahma`, an `etl_refresh_start`, an
  `etl_servable_list_upload` (with its rows) and an `etl_check_request`; and each refresh's outcome, by `refresh
  pahma-<today>-<n>`: `refresh_outcome` with `updated` or `check_failed`, and `abandoned` for the one the admin
  refresh closed. Nothing for the fake ETL's polls.
- [ ] In a terminal: `./serena logs --no-follow web | grep threshold_overridden`. Expect the override's alert, logged
  once by the web app, which records it; the worker emails it, and locally there's no email topic. Then
  `./serena logs --no-follow worker | grep '"threshold_overridden": true'`: expect one line, the
  override's "servable list check done".

## 15. Settings, sorting and the audit log in the admin app, locally (20 minutes, before merging a pull request that changes them)

The API's tests cover each setting, its bounds, the alerts, the export and the daily removal of old audit entries. This
checks the pages in Chrome. Start afresh from the pull request's branch (see the top of this file), open
http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`).

- [ ] Open Settings (the gear at the top right, left of the museum menu). Expect the title "PAHMA Settings", and six cards: Watchdog (deadline 08:00), The ETL job (poll
  interval 15, step timeout 1800), Servable list check (delta threshold 5), Size limits (image 500, catalog card 500, 3D
  model 1024, PDF 200), Audit log (90 days) and Placeholder image ("none: the generic picture"; section 22), each "default value".
- [ ] Click "Change" beside the step timeout. Type `10` and a reason, and click "Save". Expect "Give a whole number
  from 60 to 7,200." under the field, the dialog still open (section 29); click "Cancel": the value unchanged. Click "Change" again, type `900` and a reason, and save. Expect 900, "changed; default value
  1800", and a "Use default" button.
- [ ] Open "Audit log". Expect a "settings change" entry for `etl_step_timeout_seconds` with Before 1800, After 900 and
  your reason.
- [ ] Back on "Settings", click "Use default" beside the step timeout, give a reason and confirm. Expect 1800 and
  "default value" again.
- [ ] Change the delta threshold to `12.5`, with a reason. Within a minute, expect the banner: "An admin changed a
  setting", naming the delta threshold, from 5.0 to 12.5, and your reason. Set it back with "Use default"
  (another alert). Acknowledge both.
- [ ] Change the audit log's retention: the choices are 90 days and 6, 12, 18, 24 and 36 months. Choose 6 months, give
  a reason and save. Expect "6 months" and an alert as above. (A fresh stack has no entries older than 90 days, so no
  warning about entries to be removed appears.)
- [ ] In a terminal, make some refreshes: `for i in $(seq 30); do ./serena etl pahma > /dev/null; done` (about a minute).
  Open "Past refreshes". Expect 25 rows, newest first, and, at the foot of the table, "Items per page" (10, 25, 50, 100)
  and the pages. Click "Last change" in the header: expect the oldest refresh first, taken from all 30, not only the
  page on screen; click again for newest first, and a third time for oldest first again (a column is always sorted, one
  way or the other; there's no unsorted state). Choose 100 per page: expect all 30 on one page.
- [ ] Expect every page's title but the Overview's to start with "PAHMA" (for example "PAHMA Past refreshes", "PAHMA:
  Start a refresh", "PAHMA Media look up", "PAHMA refresh pahma-<today>-1").
- [ ] Open Alerts (the bell) and "Audit log": expect the same sorting by any column's name (on the Audit log, every column but
  Details), and the same choice of page sizes.
- [ ] On "Audit log", click "Export CSV". Expect a file `serena-audit-pahma-<today>.csv`. Open it in Excel: expect
  the columns time (UTC), admin, action, target and details, oldest first, and nothing run as a formula. Reload the
  page: expect an "audit export" entry at the top, with the number of entries.

## 16. The Past requests page, locally (15 minutes, before merging a pull request that changes it)

The API's tests cover the four queries, the museum filter, the one-minute cache, a slow or failed query and the CSV
export. Locally the page reads a log file inside the app's container in place of CloudWatch, so this checks the page
and the log lines; the CloudWatch queries themselves are checked once Serena is in QA (see design.md, Open questions).
Start afresh from the pull request's branch (see the top of this file).

- [ ] In a terminal, in your clone, paste these lines as they are. They run the smoke test (a refresh, then one image
  fetched from the simulator: "served", cache miss), pick its image's path out of the last line, and ask for three more:
  the same image again ("served", cache hit), a CSID that isn't in PAHMA's servable list, and a bad CSID with a signed
  link's `uid` and `sig` (both "unserved", not listed):
  ```
  path="$(./serena smoke | sed -n 's|.*and \(/pahma/[^ ]*\) fetched.*|\1|p')" && [ -n "$path" ] && echo "Image: $path" &&
  curl -s -o /dev/null "http://localhost:8300$path" &&
  curl -s -o /dev/null http://localhost:8300/pahma/imageserver/blobs/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b/content &&
  curl -s -o /dev/null "http://localhost:8300/pahma/imageserver/blobs/not-a-csid/content?uid=12345&sig=abc" &&
  echo "Done: 2 served, 2 unserved"
  ```
  Expect "Image: /pahma/imageserver/blobs/<CSID>/derivatives/Medium/content" and "Done: 2 served, 2 unserved". If
  neither appears, the smoke test failed (its message is above them): start afresh with `./serena down && ./serena up`.
- [ ] Open http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`). Open "Past requests" (in the menu,
  under Media records). Expect a spinner and "Reading Serena's log…" for a moment, then the title "PAHMA Past requests" and
  "Last 24 hours" chosen.
- [ ] Under "By day", expect today with 2 served and 2 unserved ("not listed 2"). Under "Most requested", expect your
  path with 2 requests at the top.
- [ ] In the table, expect four lines, newest first: two "unserved" with the reason "not listed" (their paths with no
  `?uid=…` or `sig=…`), then your path twice, "served", kind "image", cache "hit" (newer) and "miss" (older: the
  smoke test's first fetch).
- [ ] Expect each path as its Blob CSID, shortened (`<first 8>…<last 6>`), with its size in the Size column. Hover
  over the CSID: expect the path.
- [ ] Click "Time" in the header: expect the oldest first; click again for newest first.
- [ ] Choose Outcome "Unserved": expect the two unserved lines. Choose Reason "not listed": still two. Choose Outcome
  "Served": expect your two lines, and the Reason filter cleared and greyed out.
- [ ] With Outcome "Unserved", click "Export CSV". Expect a file `serena-requests-pahma-<today>.csv` with the columns
  time (UTC), outcome, reason, path, kind, cache and signed link, and the two unserved lines only.
- [ ] Click "Last hour", then "Last 7 days": each shows the spinner, then the same counts (everything happened today).
- [ ] Open "Overview": expect "What Serena served and couldn't serve is on the Past requests page; "Media look up" says
  why for any one file."
- [ ] Sign in to BAMPFA as well (the menu at the top, "Sign in to another museum") and open its "Past requests": expect "No
  requests in this range." under By day and Most requested, 0 served and 0 unserved, and "No requests match." in the
  table; PAHMA's requests never appear.

## 17. Recalls and Media look up, locally (25 minutes, before merging a pull request that changes them)

The API's tests cover how Serena finds each CSID, CollectionSpace being unreachable, the summary, the recall, every
case of how a recall ends (too early, no longer listed, a new Blob, restricted, still public), Release, the
thumbnails and the lookup. This checks the pages in Chrome. Start afresh from the pull request's branch (see the top of
this file), open http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`).

- [ ] In a terminal, run `./serena etl pahma`. Among the files it prints, copy the image's URL (it ends
  `/derivatives/Medium/content`) and open it in Chrome: expect a synthetic grey image.
- [ ] In the admin app, open "Media look up" (in the menu, under Media records). Expect the title "PAHMA Media look up".
  Paste the URL and click "Look up". Expect "Served", "Every check passes for the Medium size", and "Serena has a
  cached copy" (you opened it); at the foot, the refresh you just ran named as the last servability update. Open "In
  Serena" Details: expect "Media CSID" then "Blob CSID" (in that order, as in the "In CollectionSpace now" Details),
  and the checks In the servable list, Kind (image), Access (public) and Recall (No recall). Copy the Media CSID.
- [ ] Paste the Media CSID alone and look it up again: expect a row for the original and each of PAHMA's sizes
  (Thumbnail, Small, Medium, FullHD, OriginalJpeg), each served "Yes"; Medium with a cached copy, the others "—".
- [ ] Add a Media record to the simulator that isn't in PAHMA's servable list (a file not published yet; synthetic
  CSIDs):
  ```
  curl -s -X POST http://localhost:8380/_fake/media -H 'Content-Type: application/json' \
    -d '{"csid": "1a2b3c4d-0000-4000-8000-000000000001", "blob": "0f1e2d3c-0000-4000-8000-000000000001"}'
  ```
- [ ] Open "Recalls". Expect the title "PAHMA Recalls", no active recalls, and nothing ended. Click "Recall…".
  In the box, paste four lines: your image's Blob CSID (from the URL in the first step), your image's Media CSID (you
  copied it in the second step), `0f1e2d3c-0000-4000-8000-000000000001` (the Blob of the Media record you just added)
  and `not-a-csid!`. Click "Preview recall". Expect two Media records:
  - yours, with both CSIDs under "You gave" (they're the same record), kind image, served today "yes", found in Serena;
  - `1a2b3c4d-0000-4000-8000-000000000001`, kind "not known", served today "no", found in "CollectionSpace (not served
    today)";

  each with a thumbnail. Below them, "Not recalled: not-a-csid!: Not a CSID." (The "!" makes it one. Any 1 to 64
  letters, digits and hyphens have a CSID's shape and are looked up, so a word such as `cow` is "Not found" instead;
  anything with a slash is read as a path, section 21.)
- [ ] Click your record's thumbnail: expect the full-size image in a window. Close it.
- [ ] Click "Recall 2 Media records" without a reason: expect nothing recalled and "Give a reason first." under the
  Reason field (section 21). Type a reason and click it again. Expect both in
  "Active recalls", by `admin`, with your reason, and "Waiting for a later refresh". Within a minute, expect the
  bell's badge and the banner, "An admin recalled Media records"; click "Open alerts": expect the alert naming 2 and
  your reason.
- [ ] Reload the image's URL in Chrome (a fresh tab, or after clearing the cache): expect the unavailable image.
  Look it up again: expect "Not served: recalled", with your name and reason, "Open Recalls", and every size served
  "No", why not "recalled".
- [ ] Open "Audit log": expect two "recall" entries, one per Media record, each with your reason.
- [ ] Click "Recall…" again, paste your Media CSID and click "Preview recall": expect it greyed, served
  today "already recalled", and no "Recall" button. Cancel.
- [ ] In the box, paste 13 CSIDs (any text, one per line) and click "Preview recall": expect "More than
  12 CSIDs: use a text file instead." Save the same 13 lines as a `.txt` file, clear the box, choose the file and
  click again: expect the summary, every line "Not found" or "Not a CSID". Cancel.
- [ ] **Today's refresh leaves the recalls alone.** Run `./serena etl pahma` again. Open "Recalls": expect both recalls
  still under "Active recalls", "Waiting for a later refresh", each with a "Cancel recall" button and no "Release"
  button. Open the alerts (the bell): expect no new alert.

  Why: a refresh can end a recall only when its refresh date is later than the recall's day. This refresh's date is
  today (Pacific), the same day as your recalls. Its servable list was made from CollectionSpace before staff could act
  on a recall, so Serena doesn't use it to end one.
- [ ] **Cancel a recall made by mistake.** Click "Cancel recall" for the simulator's record
  (`1a2b3c4d-0000-4000-8000-000000000001`). Expect the dialog "Cancel a recall"; "Cancel recall" without a reason says "Give a
  reason first." under the Reason box. Type one and click "Cancel recall". Expect the record gone from "Active recalls" and listed under
  "Ended in the last 30 days" as "Cancelled", by `admin`, with your reason; within a minute, the alert "An admin
  cancelled a recall"; and on "Audit log", a `recall_cancel` entry. Your image's recall stays.
- [ ] **Optional, tomorrow: a later refresh keeps your image's recall.** Leave the stack running overnight. Tomorrow
  (Pacific), run `./serena etl pahma` and open "Recalls". Expect:
  - **your image's record:** still under "Active recalls", now "Still public in CollectionSpace", with a "Release"
    button and no "Cancel recall". The servable list still lists your image as public; in a real museum, staff
    haven't hidden it in CollectionSpace yet;
  - **a new alert:** "Recalled in Serena, but still public in CollectionSpace".

  Click "Release" for your image, give a reason and confirm. Reload the image's URL in a fresh tab: expect the image,
  not the unavailable image. (The tests cover every way a recall ends, a refresh ending one included, so this step
  is optional.)

## 18. The admin app's layout and the recall words, locally (10 minutes, before merging a pull request that changes the layout)

What it checks: the layout from the UI review (October 13, 2026, D134 to D138): the menu's three groups, the alert bell
and the one-line banner, the Settings gear, and "recall" in place of the old word. Run it on the pull request's branch,
after `./serena up --build` (or `./serena down` and `./serena up` if the stack was running).

- [ ] Open http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`). Expect the menu on the left
  in three groups, their headings in bold capitals: DAILY REFRESH (Overview, Start a refresh, Past refreshes), MEDIA
  RECORDS (Past requests, Media look up, Recalls) and ADMIN (Audit log, API documentation). Expect no Alerts or
  Settings in the menu.
- [ ] Expect, at the top right, a bell, a gear, then "PAHMA · admin". Hover over the gear: expect "PAHMA settings".
  Click it: expect the title "PAHMA Settings".
- [ ] If it's past 08:00 Pacific, the watchdog has raised "Today's refresh isn't finished by the deadline" within 5
  minutes of the stack starting: expect a red badge on the bell with 1, and under the top bar one line, "1 alert:
  Today's refresh isn't finished by the deadline", with "Open alerts". (Before 08:00, run `./serena etl pahma --rows 3`
  for a failed servable list check instead, and expect "A servable list check failed".)
- [ ] Click "Open alerts": expect the title "PAHMA Alerts". Acknowledge the alert. Expect the badge and the banner gone
  (at once, or within a minute), and the bell still there; click it: expect the Alerts page again.
- [ ] Open each page in the menu: expect the titles "PAHMA Past refreshes", "PAHMA: Start a refresh", "PAHMA Past
  requests", "PAHMA Media look up", "PAHMA Recalls", "PAHMA Audit log" and "PAHMA ETL API documentation".
- [ ] On "Recalls", expect "Recall…", "Active recalls" and "Ended in the last 30 days", and nowhere the word
  "takedown". Recall one of the simulator's Media records (section 17's steps), then open "Past requests" after
  requesting its image: expect the reason `recalled`. Open "Audit log": expect the action `recall`.

## 19. Media look up beside CollectionSpace, and the file dialogs, locally (20 minutes, before merging a pull request that changes them)

What it checks: Media look up's layout from the UI review (October 13, 2026, D139 to D145): Serena's answer beside
what CollectionSpace says now, last served and first cached, and the dialogs that open a file from Past requests and
Recalls. The API's tests cover each CollectionSpace case; this checks the pages in Chrome. Start afresh from the pull
request's branch, run `./serena etl pahma`, open http://localhost:5373/admin/ and sign in to PAHMA as `admin`
(password `admin`). The simulator's synthetic records are changed with `curl` against http://localhost:8380.

- [ ] Open the image's Medium URL that `./serena etl pahma` printed, in Chrome, twice. In the admin app, open "Media
  look up" and look up that URL. Expect:
  - under the field, the heading "Media 2026.1.<n>" (the simulator's synthetic identification number) and, beside it,
    "Media CSID" with the record's CSID;
  - "Served", with "Serena has a cached copy";
  - under it, "Last served" and "First cached in Serena" with today's date, and in the sizes table the Medium row with
    its cached copy (image/png), Last served and First cached;
  - two panels on the left: "In Serena" with the cached Medium, and "In CollectionSpace now" with CollectionSpace's
    file, neither picture captioned (a caption appears only when there's no picture, saying why, or for a
    soft-deleted file); each with a collapsed "Details". Open both: In Serena lists Media CSID, Blob CSID, kind,
    access and the checks; In CollectionSpace now lists Media CSID, State "Exists", the same Blob CSID, "Approved for
    web: Yes" and Last changed;
  - "Serena and CollectionSpace": the Media CSID, Blob CSID, Access and As of rows, none marked "differs", and "What
    the next refresh will do: Nothing has changed in CollectionSpace since the last refresh."
- [ ] Copy the page's address (it ends `?q=` and the URL) into a new tab: expect the same answer.
- [ ] Take the record off the web in the simulator, with the Media CSID from the heading (`<media>` below; a Blob CSID
  gets a 404 that says so):
  `curl -s -X POST http://localhost:8380/_fake/approve/<media> -H 'Content-Type: application/json' -d '{"approved": false}'`.
  Look it up again: expect still "Served" (Serena's answer comes from the last refresh), "Approved for web: No", the As
  of row marked "differs", and "The Media record changed in CollectionSpace after the last refresh. The next refresh
  shows whether it's still public."
- [ ] Replace its image: `curl -s -X POST http://localhost:8380/_fake/replace/<media>`. Look it up again: expect the
  Blob CSID row and the Blob CSID in "In CollectionSpace now" marked "differs", a darker picture there than Serena's
  cached copy, and "The Media record has a new Blob in CollectionSpace since the last refresh. The next refresh lists
  the new Blob and drops this one; …".
- [ ] Soft-delete it: `curl -s -X POST http://localhost:8380/_fake/delete/<media>`. Look it up by its Media CSID:
  expect "Served (cached sizes only)", Medium served "Yes", every other size "No", why not "media deleted", State
  "Soft-deleted", "Soft-deleted in CollectionSpace" under its picture, and "The Media record is soft-deleted in
  CollectionSpace. The next refresh drops this Blob; …".
- [ ] Put the record back as it was: `curl -s -X POST http://localhost:8380/_fake/undelete/<media>`,
  `curl -s -X POST http://localhost:8380/_fake/restore/<media>` (its file and Blob CSID before the replace) and the
  approve step above with `{"approved": true}`. Look it up again: expect "Served", every size served, and the Blob CSID
  row no longer marked "differs" (As of still differs: undoing a change is a change in CollectionSpace too).
- [ ] Look up `9f9f9f9f-0000-4000-8000-000000000000` (synthetic, unknown): expect "Not served: not in the servable
  list", "Not in CollectionSpace", "CollectionSpace has no Blob or Media record with this CSID either.", and no
  heading. Look up PAHMA's placeholder image, `59a733dd-d641-4e1a-8552`: expect the heading "Placeholder image" and
  "Nothing to compare: this image has no Media record".
- [ ] Switch on an outage in the simulator (its records are kept):
  `curl -s -X POST http://localhost:8380/_fake/unreachable -H 'Content-Type: application/json' -d '{"on": true}'`.
  Look up the URL again (it takes a few seconds: Serena retries CollectionSpace first): expect Serena's answer, the
  notice "CollectionSpace can't be reached, so there's nothing to compare with", "CollectionSpace can't be reached" in
  the right-hand panel, and the heading "Media <Media CSID>" (no identification number without CollectionSpace).
  Switch the outage off with `{"on": false}` in the same command.
- [ ] Open "Past requests" with "Last hour". Hover over a Blob CSID: expect it underlined, as a link. Click your
  image's Medium request: expect a dialog with the path, the picture, "This request, <time>: served.", "Media look up"
  and "Dismiss". Click "Media look up": expect Media look up on that path. Back on Past requests, expect a bad CSID
  (if any) not to be a link.
- [ ] On "Recalls", recall your image's Media record (with a reason). Open its row in "Active recalls" (▸): its Media
  CSID and Blob CSID, each followed by "View file". Click "View file" after the Blob CSID: expect the dialog, titled
  "Blob CSID", with the picture (admins see a recalled file), "Media look up" and "Dismiss"; click "Dismiss". Click
  "View file" after the Media CSID, then "Media look up": expect "Not served: recalled".

## 20. The UI review's changes, locally (20 minutes, before merging a pull request that changes them)

What it checks: the mockup review of October 13, 2026 (D154 to D165): copy buttons, column help, links, the Recalls
layout, the button rule, Media look up's sync heading and `/blobs/<CSID>` URLs, the file dialog's reasons, the Audit
log's "By", and what happens when a session ends; and Richard's review of October 14, 2026: Recalls by identification
number with rows that open, Past requests' shorter paths, "← Back to …", list pages that keep their place, and the
failed check's alert in words. The mockup, `docs/mockup/serena-admin-mockup.html`, shows the same pages. A few steps
were updated for Richard's later changes of October 14, 2026 (section 21): Past requests' Blob CSID and Size columns,
and no ⧉ on values shown whole. Start afresh from the pull request's branch, run `./serena etl pahma`, open the image's Medium URL
it printed once in Chrome, then open http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`).

- [ ] On "Overview", expect "Past requests" and "Media look up" in the sentence as links; click each.
- [ ] On "Past requests", hover over a column's name (they have a dotted underline): expect a description, which
  stays while you move the pointer onto it and closes with Esc. Tab to one with the keyboard: expect the same. Expect
  each Blob path as its Blob CSID, shortened (for example `0f1e2d3c…3f4a5b`), with ⧉ at its end, and its size in the
  Size column; hover over the CSID: the path; click ⧉, expect "Copied" for a moment, and paste somewhere: expect the
  path. Expect no "Signed link" column (only Cinefiles has one), and the table within the window. Expect a time to
  break only between its date and its clock time when the window is narrow.
- [ ] Recall your image's Media record on "Recalls": expect "Preview recall" and "Cancel" both as buttons with
  outlines ("Preview recall" filled blue), the summary's Media CSID and Blob CSID shortened with ⧉, and its thumbnail
  a fixed size. Click "Change CSIDs": expect the form again, with your CSID still in it; "Preview recall" again, then
  confirm with a reason ("Recall 1 Media record" is filled red). In "Active recalls", expect the first column,
  "Identification number", to show the record's number (`2026.1.<n>`) without ⧉, a blue tag "Waiting for a later
  refresh", and "Cancel recall…" in its own column at the right. Click the row's ▸: expect its Media CSID and Blob
  CSID, whole, each followed by "View file" (click it: its file), and "Media look up"; ▾ closes it. Click "Cancel recall…": expect
  "Keep the recall" outlined and "Cancel recall" filled red. Keep the recall.
- [ ] Request the recalled image again in Chrome, then on "Past requests" expect its line's Kind "image" (an unserved
  line has the kind when Serena knows the file); an unknown file's Kind stays blank.
- [ ] Make a refresh fail its check: run `./serena etl pahma --rows 3`. Then open "Alerts" and find the new alert,
  "A servable list check failed". Expect its text to say "Refresh <refresh ID> failed its servable list check: <n>
  problems in the servable list. Its page says more." (no "check_failed"), and:
  - the refresh ID in the alert's text (for example `pahma-2026-10-14-2`) shown as a link. Click it: it opens that
    refresh's page;
  - if the About column also shows a refresh ID, that's a link to the same page.
- [ ] **Optional, tomorrow** (only a refresh on a later day decides a recall): after section 17's overnight step,
  expect on "Recalls" the tag "Still public in CollectionSpace", "kept by <refresh ID>" as a link to that refresh's
  page, and "Release…" in the right-hand column.
- [ ] On "Audit log", expect the column "By": "admin", "ETL (pahma)" and "Serena" (the refresh's outcome). Expect a
  Media CSID target shortened with ⧉ (it opens Media look up), refresh IDs as links, an acknowledged alert's target
  linking to "Alerts", and the servable list upload's SHA-256 shortened with ⧉. "Export CSV": expect the column `by`.
- [ ] On "Media look up", look up your image's Medium URL (the failed check above didn't change the simulator's records:
  it keeps a record it already has): expect "Serena and CollectionSpace ✓ (No differences)" in green, the
  identification number in the heading without ⧉, and the comparison's CSIDs shortened with ⧉. Take the
  record off the web (section 19's `curl`) and look it up again: expect "⚠ (1 difference: As of)" in amber.
- [ ] Look up the same URL without `/derivatives/Medium/content` (it ends with the Blob CSID): expect "This URL isn't
  one Serena serves …", reason "unknown path", then the Blob's answer with every size.
- [ ] On "Past requests", click a path whose file Serena can't show: look up `9f9f9f9f-0000-4000-8000-000000000000`
  first on Media look up, then request `/pahma/imageserver/blobs/9f9f9f9f-0000-4000-8000-000000000000/content` in
  Chrome and click its Blob CSID: expect "Nothing to show: Serena has no cached copy, and CollectionSpace has no file with
  this CSID." and no "Open it in a new tab". The dialog's path has ⧉.
- [ ] **Keeping your place.** On "Past requests", choose "Last 7 days" and the outcome "Unserved", click "Reason" to
  sort by it, and scroll down. Expect the address to hold them (`?range=7d&outcome=unserved&sort=reason.asc`). Click a
  Blob CSID, then "Media look up" in its dialog: expect "← Back to Past requests" above the title. Click it: expect
  Past requests as you left it, the same range, filter, sort and scroll position, without the spinner. Open the file
  again, then use the browser's Back button instead: expect the same. Copy the address into a new tab: expect the same
  range, filter and sort.
- [ ] From "Alerts", click a refresh ID: expect "← Back to Alerts" on the refresh's page. From the "Audit log", click a
  Media CSID target: expect "← Back to Audit log" on Media look up. Then open "Media look up" from the menu on the
  left: expect no "← Back to …" (the menu starts a new task).
- [ ] Open the admin app in a second tab, and there click "Sign everyone out of PAHMA" on "Overview", then confirm. In
  the first tab, click "Audit log" (or reload): expect the sign-in page saying "Your PAHMA session ended …"; sign in:
  expect "Audit log" (the page you were going to), not the Overview.
- [ ] Stop the backend (`docker compose -p serena stop web`), click "Sign everyone out of PAHMA" and confirm: expect
  the dialog to stay open and say why it failed. Start it again (`docker compose -p serena start web`).
- [ ] Last (skip it if you'll do the optional step tomorrow, which needs the recall): on "Recalls", click "Cancel
  recall…" on your recall, give a reason and confirm. Expect it under "Ended in the last 30 days" by its
  identification number, "Cancelled", with ▸ for its CSIDs. Open "Alerts" and find "An admin cancelled a recall". Expect its
  About column to show the Media CSID shortened (`20349bfa…3f0b98`) with ⧉ beside it:
  - click ⧉, then paste somewhere: you get the whole CSID;
  - click the CSID: it opens Media look up for that record.

## 21. Richard's follow-ups of October 14, 2026, locally (25 minutes, before merging a pull request that changes them)

What it checks: the changes Richard asked for while testing section 20, as mockup version 36
(`docs/mockup/serena-admin-mockup.html`) shows them: Past requests' Blob CSID and Size columns and the served
requests by size; ⧉ only on shortened values; the Recalls page's "Recall…" button; paths and URLs in the recall form;
a recall alert that names its record; buttons that need a reason are never disabled; Media look up's forgiving paths,
folding sizes table and size links; errors that keep their code; and the plain "Not found.". Start afresh from the
pull request's branch, run `./serena etl pahma`, and open the image's Medium URL it printed once in Chrome. Then open
http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`). Below, `<BLOB>` is that image's Blob
CSID (in its URL) and `<MEDIA>` its Media CSID (on Media look up).

- [ ] In Chrome, also open the same URL with `Thumbnial` in place of `Medium`, and
  `http://localhost:8300/pahma/imageserver/media/<MEDIA>/content` (a /media/ shape Serena doesn't serve; section 23
  checks the ones it does).
- [ ] On "Past requests", expect a "Served" card with a count and "by size: Medium 1", and an "Unserved" card with its
  reasons. In the table, expect the column "Blob CSID" (not "Path") with each Blob path's CSID shortened and ⧉, and a
  "Size" column: "Medium", and "Thumbnial (invalid)" with "(invalid)" in grey. The /media/ request shows its path,
  shortened in the middle, with ⧉ and "(not a Blob path)", and no size. Click "Size" to sort: expect Medium before
  Thumbnial (invalid), and the /media/ line last; hover over "Size": its help says what "(invalid)" means. Hover over
  "Blob CSID": its help says "path", not "whole path". "Most requested" has the same two columns.
- [ ] On "Recalls", expect "Recall…" under the page's explanation, on the left, before the tables, outlined in red.
  Click it. Paste the image's whole Medium URL (with `http://localhost:8300`) into the box: expect it replaced by
  `<BLOB>` at once. Type, on a new line, `/cinefiles/imageserver/blobs/<BLOB>/content`, then click "Preview recall".
  Expect your image's record, "You gave" showing its path shortened in the middle, and under "Not recalled" the
  Cinefiles path with "That's a Cinefiles path; you're recalling PAHMA's files."
- [ ] Click "Recall 1 Media record" without a reason: expect nothing recalled, "Give a reason first." under the Reason
  field, the cursor in it, and the hint "Required. Recorded in the audit log and the alert emailed to the team. No
  personal data, please." Give a reason and click it again: expect the recall.
- [ ] Open "Alerts": expect "An admin recalled Media records" with the text "An admin recalled Media record 2026.1.<n>
  (<Media CSID start…end>) for PAHMA. Reason: …", and its About the shortened Media CSID with ⧉, which opens Media
  look up.
- [ ] Back on "Recalls", expect the identification number without ⧉; click it once: the whole number is selected.
  Open the row (▸): expect its Media CSID and Blob CSID, whole, each followed by "View file"; click a CSID once: all of
  it is selected (not just the part between hyphens). Click "View file": its file. Click "Cancel recall…" and then
  "Cancel recall" without a reason: expect the same message under the field. Keep the recall.
- [ ] On "Settings", click "Change" on any setting, then "Save" without a reason: expect "Give a reason first." and the
  cursor in the Reason field; click "Cancel". On "Start a refresh", click "Start the refresh" with nothing filled in:
  expect a message under the file, the Reason field and the confirmation, and nothing started.
- [ ] On "Media look up", look up `<MEDIA>`: expect "Media 2026.1.<n>" with no ⧉ (one click selects the number; the
  Media CSID beside it too), and under the stamps one line, "Sizes (6): none served (recalled) · cached: Medium",
  closed. Open it: expect the sizes table. Click "Medium": expect its file in a dialog with its path and ⧉, "Dismiss"
  and no "Media look up" button; press Esc to close it. Look up another record and back: the box stays open.
- [ ] Look up `pahma/imageserver/blobs/<BLOB>/derivatives/Medium/content` (no leading slash), then
  `blobs/<BLOB>/derivatives/Medium/content`: expect each looked up as `/pahma/imageserver/blobs/<BLOB>/derivatives/Medium/content`,
  with one size and no box. Look up `/cinefiles/imageserver/blobs/<BLOB>/content`: expect "That's a Cinefiles path;
  you're looking up PAHMA's files." Look up the /media/ URL you opened above: expect "This URL isn't one Serena serves
  (it needs /blob/content or /blob/derivatives/<size>/content) …", reason "unknown path", then the record's answer
  with every size.
- [ ] Stop the backend (`docker compose -p serena stop web`), then click "Media look up" again: expect "Serena can't be
  reached right now. Try again in a minute. (502)" (or 503 or 504, from the dev server). Start it again (`docker
  compose -p serena start web`).
- [ ] Open http://localhost:8300/nowhere and http://localhost:8300/local-cdn/pahma: expect the plain text "Not found."
  (not JSON). http://localhost:8300/admin/v1/nowhere still answers JSON.
- [ ] Last: on "Recalls", cancel your recall with a reason.

## 22. The placeholder image's Media record, locally (15 minutes, before merging a pull request that changes it)

What it checks: decisions D166 to D173 of October 14, 2026. PAHMA's placeholder image comes from a Media record named
on the Settings page; until one is named, Serena serves its generic "Image restricted" picture. `./serena etl pahma`
lists the placeholder (Blob `59a733dd-d641-4e1a-8552`, no Media CSID) and adds a synthetic Media record holding it to
the simulator: `9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a`, identification number "Placeholder". Start afresh from the pull
request's branch, run `./serena etl pahma`, then open http://localhost:5373/admin/ and sign in to PAHMA as `admin`
(password `admin`).

- [ ] In Chrome, open
  http://localhost:8300/pahma/imageserver/blobs/59a733dd-d641-4e1a-8552/derivatives/Medium/content: expect the generic
  picture (a lock and "Image restricted"), at `/placeholder.svg`. On "Past requests", expect the line unserved,
  reason "placeholder not set".
- [ ] On "Media look up", look up `59a733dd-d641-4e1a-8552`: expect "Not served: Serena's generic picture instead",
  the Placeholder image check saying no Media record is named, and "Name the placeholder image's Media record on the
  Settings page."
- [ ] On "Settings", expect a "Placeholder image" card, its help, and "Placeholder image (Media CSID)" as "none: the
  generic picture". Click "Change", type `9f9f9f9f-0000-4000-8000-000000000000` (synthetic, unknown), give a reason and
  save: expect "CollectionSpace has no Media record with this CSID." under the field, and the dialog still open.
- [ ] Type `9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a` and save (it takes a few seconds: Serena fetches every size). Expect
  the row to show the CSID, "Media Placeholder" and a thumbnail, and "changed; default value none: the generic
  picture". On "Audit log", expect the settings change with the Media CSID before (none) and after, the
  identification number and the six sizes fetched.
- [ ] Open the Medium URL above again: expect the simulator's picture now (a grey square), not the generic one. Media
  look up on `59a733dd-d641-4e1a-8552`: expect "Served" and every size cached.
- [ ] Back on "Settings", click "Use default" on the row, give a reason and confirm: expect "none: the generic
  picture" again; within a minute, the Medium URL gives the generic picture again.
- [ ] On "Alerts" (the watchdog runs every few minutes), expect one "The placeholder image isn't set", from before you
  named the record, naming the refresh and the Blob and saying the public sees the generic picture. Acknowledge it.
  It comes again only for a later refresh date while no record is named.

## 23. Media URLs, locally (15 minutes, before merging a pull request that changes them)

What it checks: decisions D174 to D180 of October 14, 2026. A request for `…/media/<Media CSID>/blob/content` or
`…/blob/derivatives/<size>/content` is answered as a request for the Media record's listed Blob, with the same checks,
shares that Blob's cache entries, serves public files only, and is logged as requested. Start afresh from the pull
request's branch, run `./serena etl pahma`, then open http://localhost:5373/admin/ and sign in to PAHMA as `admin`
(password `admin`). Below, `<BLOB>` is the image's Blob CSID (in the Medium URL `./serena etl pahma` printed) and
`<MEDIA>` its Media CSID (Media look up on `<BLOB>` shows it).

- [ ] In Chrome, open http://localhost:8300/pahma/imageserver/media/<MEDIA>/blob/derivatives/Medium/content: expect
  the image. Then open the Blob's Medium URL: expect the same image. On "Media look up", look up `<BLOB>`: expect
  Medium cached once (one fetch for both URLs).
- [ ] Open http://localhost:8300/pahma/imageserver/media/<MEDIA>/blob/content: expect the original file, or the
  unavailable image with reason "original not served" if PAHMA doesn't serve originals of its kind (as for the Blob URL).
- [ ] Open the Medium URL with an unknown Media CSID, `9f9f9f9f-0000-4000-8000-000000000000` (synthetic): expect the
  unavailable image, and on "Past requests" reason "not listed".
- [ ] On "Past requests", expect the Media URLs in the "Blob CSID" column as "Media <shortened Media CSID>" with ⧉,
  their sizes ("Medium", "original") in the "Size" column, and no "(not a Blob path)"; hover: the whole path as
  requested (`/media/…`, not rewritten to `/blobs/…`). Click "Media …" on the Medium line: expect the file in a
  dialog, titled "Medium", with the request's outcome. Export the CSV: the paths are as requested.
- [ ] On "Media look up", paste the Media URL for Medium: expect it answered like the Blob's URL (one size, "Served"),
  with no note about /media/ URLs, and the Media record beside CollectionSpace.
- [ ] On "Recalls", recall `<MEDIA>` with a reason. Open the Media Medium URL again: expect the unavailable image,
  and on "Past requests" reason "recalled". Cancel the recall with a reason; within a minute the URL serves again.

## 24. The first AWS environment, personal-dev with the simulator (about 1 hour, mostly waiting; before merging pull request 17)

What it checks: decisions D181 to D194. `./serena aws` deploys Serena to Richard's personal account with the
simulated CollectionSpace, the fake ETL runs a daily refresh inside the environment, and the address rules hold.
Image delivery waits for pull request 18 (D194), so a servable file is fetched and stored but not delivered.
From the pull request's branch on the Mac, signed in (`aws sso login --profile bmu-personal`):

Checked by Richard on October 19, 2026, at commit `3f12afd`.

*Automated since section 30* (`./serena aws test`): `status` (T90); the fake ETL's refreshes, again and
`--failed` (T92 to T94); the admin app's header and Refreshes (T100), Past requests (T101); a sample address
fetched and stored (T95, T96; delivered since pull request 18) and Media look up (T102); the recall and its
cancellation in the audit log (T103, T104); no `AccessDenied` (T105). Still by hand: the deploy, Settings saving a
change (it emails since pull request 18; T29 to T35 locally), the 403 from another network and `allow-my-ip`, pause
and resume.


- [x] `./serena aws deploy`: confirm the account, check the plan, type `yes`. Expect it to finish in about 15–25
  minutes and print the address; `<URL>/health` answers `ok`.
- [x] `./serena aws status`: expect web, worker and fakecspace "running 1 of 1", the image's tag ending in the
  commit, and for PAHMA its CollectionSpace account and ETL token "set".
- [x] `./serena aws etl pahma`: expect "updated" with its counts and sample addresses, in a minute or two. Run it
  again: "updated" with 0 written, 0 deleted.
- [x] `./serena aws etl pahma --failed`: expect "Failed refresh" and nothing sent to Serena.
  - Its repair hint named `./serena etl … --file-only` without saying it needs the local stack; in AWS it now says
    so (the file's CSIDs depend only on the museum and `--rows`, so it matches the environment's simulator).
- [x] In Chrome, open `<URL>/admin/` and sign in to PAHMA as `admin` (password `admin`): expect the header to show
  "AWS · personal dev · simulator" and the image tag. "Refreshes" lists the two updated refreshes; "Settings" saves
  a change; "Past requests" lists requests (it reads CloudWatch Logs Insights).
- [x] Open a sample address the fake ETL printed: expect a fetch (`./serena aws logs web` shows it stored in the
  museum's bucket) and, until pull request 18, the unavailable image, not an error page. On "Past requests", expect
  the reason "delivery not set up" (not "internal error"), and on "Media look up" the size cached.
- [x] Recall the sample's Media record on "Recalls", then cancel it: both are in the audit log.
- [x] From another network (a phone without Wi-Fi), open `<URL>/health` and `<URL>/admin/`: expect 403 "open only to
  listed addresses". On the Mac again, after `./serena aws allow-my-ip` from that network, both answer.
  - Both 403s seen from a phone. `allow-my-ip` from the phone's network was skipped: a carrier's address changes
    too often to be worth listing; `allow-my-ip` itself was checked on the Mac's two networks.
- [x] Note: the fake ETL calls the internal load balancer directly, not through CloudFront. Uploading a large
  servable list through CloudFront and WAF (D184, D186) is checked when the real ETL first calls the QA environment.
- [x] `./serena aws pause`: expect no running tasks and `<URL>/health` failing; `./serena aws resume` brings it back.
  Then `./serena aws etl pahma` again: "updated" (the simulator lost its records, the fake ETL adds them again).
- [x] Look for `AccessDenied` in `./serena aws logs web` and `worker`: there should be none. Note any for `iam.tf`.
  - None in the web, worker and devtools logs over the day of testing.
- [x] Moved to pull request 18: personal-dev is kept, paused between sessions (`./serena aws pause`), so pull
  request 18 can add image delivery to it. Its checks end with `./serena aws destroy` (section 25).

## 25. Image delivery, alerts and alarms, personal-dev with the simulator (about 1 hour; before merging pull request 18)

What it checks: decisions D195 to D206. personal-dev gets image delivery (signed URLs to files in the museums'
buckets, D195 to D200), the unavailable images from the static bucket, the alert email (D201) and the alarms. Each
step below says what to run, where, and what you should see. If you see something else, write it under the step.
Since section 30, the steps marked *Automated* are `./serena aws test`'s: after the deploy (step 1) and the alert
email (step 2), run it once in place of them, then do the rest by hand.

**Before you start** (once per terminal window, in the clone on the Mac):

1. Take the code and this checklist from pull request 18's branch:
   `git switch feature/deploy-delivery && git pull`.
2. Sign in to AWS: `aws sso login --profile bmu-personal`.
3. Open `deploy/environments/personal-dev.local.conf` (not committed) and check that it has the line
   `ALERT_EMAIL="<your address>"`. Add it if it's missing.
4. Set a shell variable for the address, which the commands below use: `URL="$(./serena aws url)"`.
   `echo "$URL"` should print `https://<something>.cloudfront.net`. If it says "isn't deployed", do step 1 below
   first, then set `URL` again.
5. Every plain `aws` command below has `--profile bmu-personal --region us-west-2`. Keep both: without them the AWS
   CLI may use a region named `default` and fail with "Could not connect to the endpoint URL:
   https://sns.default.amazonaws.com/". `./serena aws` commands set the profile and region themselves.

**The steps:**

- [ ] **1. Deploy.** Run `./serena aws deploy`.
  1. The first time, it prints "Profile bmu-personal is signed in to AWS account …" and asks whether that's the
     account for personal-dev: check that it's your personal account and answer `y`. Later it checks the saved
     account number itself and doesn't ask.
  2. It builds and pushes two images, then shows Terraform's plan. Read the plan before typing `yes`:
     - The first time this branch is deployed onto section 24's environment, expect only additions ("will be
       created") and in-place changes ("will be updated in-place"): the static bucket and its files, the origin
       access control, the alert topic and its email subscription, the metric filters and alarms, the KMS key's
       policy as its own resource (`aws_kms_key_policy.main` created), the buckets' policies, the distribution and
       the ECS services.
     - **`aws_kms_key.main` must not be replaced.** If the plan says it "must be replaced", type `no` and stop:
       replacing the key would make the encrypted tables and files unreadable.
     - The only resources that may say "must be replaced" are the four task definitions (`web`, `worker`,
       `fakecspace`, `fake_etl`). That's normal: a new image means a new task definition.
     - On a later deploy of the same branch, expect a much smaller plan: the task definitions and anything changed
       since (for example a new address in the allowlist function).
  3. Type `yes`. The first time, it then prints "Image delivery: the first CloudFront signing key" and shows a
     second, smaller plan (the public key, the key group and the museum's file behavior). Type `yes` again.
  4. Expect it to end with "Checking `<URL>`/health", the address, and
     "Next: ./serena aws confirm-alerts". The first deploy takes 15–25 minutes (CloudFront); later ones about 5.

- [ ] **2. Confirm the alert email.**
  1. Look in your inbox (and Spam) for an email from `no-reply@sns.amazonaws.com` with the subject
     "AWS Notification - Subscription Confirmation".
  2. **Don't click its link** (clicking would confirm it without requiring an AWS sign-in to unsubscribe). Right-click
     "Confirm subscription" and copy the link.
  3. Run `./serena aws confirm-alerts`, paste the link at "The link:" and press Return. Expect "Confirmed: alerts
     and alarms now go to `<your address>`; unsubscribing needs an AWS sign-in."
  - No email? AWS sends it only when the subscription is created, which may have been an earlier deploy, and the
    link expires after 3 days.
    1. Find the topic: in the deploy's output, `alert_topic_arn` (`arn:aws:sns:us-west-2:<account>:serena-dev-alerts`).
       Set it: `TOPIC="<that ARN>"`.
    2. See whether the subscription is confirmed:
       ```
       aws --profile bmu-personal --region us-west-2 sns list-subscriptions-by-topic --topic-arn "$TOPIC" \
         --query 'Subscriptions[].SubscriptionArn' --output text
       ```
       An ARN ending in a long ID means it's confirmed: tick this step. `PendingConfirmation` means it isn't.
    3. If it isn't, have AWS send a new email:
       ```
       aws --profile bmu-personal --region us-west-2 sns subscribe --topic-arn "$TOPIC" \
         --protocol email --notification-endpoint "<your address>"
       ```
       Then do 1 to 3 above with the new email.
  - The alerts recorded before there was a topic (the placeholder image's, the recalls') are sent on the worker's
    first pass, before you confirm, so they never arrive. That's expected.
  - If it's already confirmed, `confirm-alerts` says "Already confirmed: alerts and alarms go to `<your address>`"
    without asking for the link.
  - Note (October 20, 2026): `confirm-alerts` failed with "Invalid JSON received" on macOS; fixed in `e5b8297`. Run
    again on a confirmed subscription, it said "Not confirmed" (AWS refuses a link already used); fixed after.

- [ ] **3. Check the status.** *Automated:* T90 (`./serena aws test`, section 30). Run `./serena aws status`. Expect, among its lines:
  - `web: running 1 of 1`, `worker: running 1 of 1`, `fakecspace: running 1 of 1`.
  - `Image delivery: on; signing keys trusted: serena-dev-<date and time> (the newest signs)`, with one key.
  - `Alert email: <your address>`, with no "NOT CONFIRMED".
  - `Alarms: on`, with no "firing:" after it.
  - If "Alarms: on; firing: serena-dev-web-down" (or `worker-down`) appears because the services restarted during
    the deploy: expect an ALARM email, then within 10 minutes an OK email, and `status` again shows no "firing:".

- [ ] **4. Load the simulator's records.** *Automated:* T92 (`./serena aws test`, section 30). A deploy restarts the simulator, which loses its records. Run
  `./serena aws etl pahma`. Expect, in a minute or two, a line with "updated" and its counts, then sample
  addresses, one per kind of file, like
  `image   https://<…>.cloudfront.net/pahma/imageserver/blobs/<Blob CSID>/derivatives/Medium/content`.
  Copy the `image` line's address and set it in the terminal: `SAMPLE="<that address>"`.
  `./serena aws list pahma` lists every file Serena may serve for PAHMA, with its address (`--limit 0` for all).

- [ ] **5. An image in the browser.** *Automated:* T96, T101 (`./serena aws test`, section 30). In Chrome, open the `$SAMPLE` address. Expect the image itself (not the "no
  image" picture, not an error). Then in the admin app (`<URL>/admin/`, sign in to PAHMA as `admin`, password
  `admin`), open "Past requests": expect the request listed as served, with cache "miss". Open the address again
  and reload "Past requests": the new line says cache "hit".

- [ ] **6. The redirect and the signed address.** *Automated:* T95, T96 (`./serena aws test`, section 30).
  1. Run `curl -sI "$SAMPLE"`. Expect:
     - `HTTP/2 302`
     - `location: <URL>/pahma/objects/<64 hex characters>?Expires=<number>&Signature=<…>&Key-Pair-Id=<…>`
     - `cache-control: private, max-age=<a number from 900 to 1800>`
  2. Save the signed address, the file's SHA-256 (the 64 hex characters after `/objects/`) and the key's ID; steps
     7, 8, 10 and 11 use them:
     ```
     SIGNED="$(curl -sI "$SAMPLE" | awk 'tolower($1) == "location:" {print $2}' | tr -d '\r')"
     SHA="${SIGNED##*/objects/}"; SHA="${SHA%%\?*}"
     KEY_ID="${SIGNED##*Key-Pair-Id=}"
     echo "$SIGNED"; echo "$SHA"; echo "$KEY_ID"
     ```
     Expect the signed address, then 64 characters of 0–9 and a–f, then an ID like `K3EK0MNYL92FBO`.
  3. Run `curl -sI "$SIGNED"` twice. Expect both times `HTTP/2 200`, `content-type: image/png` and
     `cache-control: private, max-age=900`. Expect `x-cache: Miss from cloudfront` the first time and
     `x-cache: Hit from cloudfront` the second (the signature isn't part of the cache key, D197).
  - This also checks that CloudFront checks the signature against the address as requested, before its function
    removes `/pahma` from the path. If `$SIGNED` gets a 403 instead, write it here.

- [ ] **7. A bad or missing signature is refused.** *Automated:* T97 (`./serena aws test`, section 30).
  1. Copy `$SIGNED`, change one character in the middle of the `Signature=` value, and run `curl -sI "<that>"`.
     Expect `HTTP/2 403`.
  2. Run `curl -sI "${SIGNED%%\?*}"` (the address without its query string). Expect `HTTP/2 403`.
  - Each 403 carries `cache-control: private, max-age=900` (the files' response headers policy applies to errors
    too). That's expected and harmless: see the design doc, Signed URLs (D198).

- [ ] **8. The bucket can be reached only through CloudFront (D196).** *Automated:* T98 (`./serena aws test`, section 30).
  1. Find the bucket's name and set it:
     ```
     BUCKET="$(aws --profile bmu-personal --region us-west-2 s3api list-buckets \
       --query "Buckets[?starts_with(Name, 'serena-dev-pahma-')].Name" --output text)"
     ```
     `echo "$BUCKET"` should print `serena-dev-pahma-<account>-us-west-2`.
  2. Run `curl -sI "https://$BUCKET.s3.us-west-2.amazonaws.com/objects/$SHA"`. Expect
     `HTTP/1.1 403 Forbidden`.
  3. Run `curl -sI "$URL/pahma/servable-list/x"`. Expect no file: only `/pahma/objects/…` goes to the bucket, so
     this path goes to Serena, which doesn't serve it. Expect `HTTP/2 404` with `content-type: text/plain` and
     `cache-control: no-store` (Serena's answer; S3's would be `application/xml`). Seen on October 20, 2026.

- [ ] **9. The unavailable image.** *Automated:* T99 (`./serena aws test`, section 30).
  1. Copy `$SAMPLE` and change one character of its Blob CSID (for example a `1` to a `2`), so it's a Blob CSID the
     fake ETL didn't list. Run `curl -sI "<that>"`. Expect `HTTP/2 302` with `location: <URL>/pahma/unavailable.svg`.
  2. Open that changed address in Chrome. Expect the "no image" picture.
  3. Run `curl -sI "$URL/pahma/unavailable.svg"` and `curl -sI "$URL/default/placeholder.svg"`. Expect each:
     `HTTP/2 200`, `content-type: image/svg+xml` and
     `content-security-policy: default-src 'none'; style-src 'unsafe-inline'`.

- [ ] **10. A recall stops the old address at once, but not a signed address already handed out.** *Automated:* T103, T104 (`./serena aws test`, section 30).
  1. In the admin app, on "Recalls", start a recall and paste `$SAMPLE` (the form takes addresses as well as
     CSIDs). Check that the preview names one Media record, give any reason, and recall it.
  2. Run `curl -sI "$SAMPLE"`. Expect `HTTP/2 302` to `<URL>/pahma/unavailable.svg`.
  3. Run `curl -sI "$SIGNED"`. Expect `HTTP/2 200`: a signed address keeps working until its `Expires` (at most 30
     minutes after step 6). If step 6 was more than 30 minutes ago, expect 403 instead and note it.
  4. Cancel the recall on "Recalls". Run `curl -sI "$SAMPLE"` again: expect the 302 to a signed address again.

- [ ] **11. A new CloudFront signing key.**
  1. Run `./serena aws cdn-key`. Expect "Making the CloudFront signing key serena-dev-<date and time>…", a small plan
     with one public key added (type `yes`), "Terraform now adds it to the key group CloudFront trusts", and a
     line saying Serena signs the museums' files with the new key within 5 minutes.
  2. Run `./serena aws status`. Expect "signing keys trusted:" to list two keys, the new one last.
  3. Wait 5 minutes, then run `curl -sI "$SAMPLE"`. Expect a `location` whose `Key-Pair-Id` differs from `$KEY_ID`
     (`echo "$KEY_ID"`), saved in step 6.
  4. Run `curl -sI "$SIGNED"` (signed with the old key). Expect `HTTP/2 200` until its `Expires`.

- [ ] **12. An alert by email.**
  1. In the admin app, on "Settings", note PAHMA's delta threshold, change it, give a reason and save.
  2. Within 5 minutes expect an email whose subject is "An admin changed a setting" and whose text says which
     setting, from what to what (the worker sends it).
  3. Put the threshold back and save. (A second email for that change is expected.)

- [ ] **13. An alarm by email.**
  1. Run:
     ```
     aws --profile bmu-personal --region us-west-2 cloudwatch set-alarm-state \
       --alarm-name serena-dev-cspace-refused --state-value ALARM --state-reason "testing by hand"
     ```
  2. Within a minute or two expect an email that says the alarm `serena-dev-cspace-refused` is in ALARM.
  3. Within about 15 minutes, when the alarm next looks at its numbers, expect a second email that it's OK again.

- [ ] **14. Unsubscribing needs an AWS sign-in (D201).** In one of the alert emails from steps 12 or 13, click the
  "unsubscribe" link at the bottom, in a browser where you aren't signed in to AWS. Expect a page saying the request
  was refused (an error, not "You have been unsubscribed"). Then `./serena aws status` still shows
  `Alert email: <your address>`.

- [ ] **15. Pausing turns the alarms off.**
  1. Run `./serena aws pause`. Expect "Paused: no tasks run".
  2. Run `./serena aws status`. Expect `Alarms: off while paused`.
  3. Wait 15 minutes. Expect no "web-down" or "worker-down" email.
  4. Run `./serena aws resume` (expect "Running: `<URL>`"), then `./serena aws etl pahma` (the simulator lost its
     records again): expect "updated".

- [ ] **16. No permission errors in the logs.** *Automated:* T105 (`./serena aws test`, section 30). Run this once for each of `web`, `worker` and `devtools`
  (it searches the last 24 hours):
  ```
  aws --profile bmu-personal --region us-west-2 logs filter-log-events --log-group-name /serena/dev/web \
    --start-time $(( ($(date +%s) - 86400) * 1000 )) \
    --filter-pattern '?AccessDenied ?AccessDeniedException ?"not authorized"' \
    --query 'events[].message' --output text
  ```
  (Change `/serena/dev/web` to `/serena/dev/worker`, then `/serena/dev/devtools`.) Expect no output from each. If
  there is any, copy the line here: it means `iam.tf` is missing a permission.

- [ ] **17. Note for QA (D205), nothing to do here:** whether the portals' 3D and PDF viewers need CORS headers is
  checked in QA, with the real portals.

- [ ] **18. Take personal-dev down** (moved here from section 24), when every step above is done:
  1. Run `./serena aws destroy`. When it asks, type `personal-dev`.
  2. Expect it to finish with everything destroyed. If it stops with an error about the VPC (its network
     interfaces take a few minutes to go away), run `./serena aws destroy` again.
  3. The next day, in the AWS console, open Billing and Cost Management → Cost Explorer for your personal account:
     expect no new costs for the day after the destroy.

## 26. Quieter plans (15 minutes, at the next personal-dev deploy)

What it checks: the task definitions write out what ECS fills in (`hostPort`, `mountPoints`, `volumesFrom`,
`systemControls`, and an empty `environment` or `portMappings` where there are none), so Terraform stops replacing
them when nothing in them changed. A deploy always builds a new image tag (the commit and the time), so a deploy still
replaces the task definitions; the commands that apply again with the running images (`plan`, `pause`, `resume`,
`allow-my-ip`, `cdn-key`) shouldn't. From this pull request's branch on the Mac, signed in
(`aws sso login --profile bmu-personal`):

- [x] **1. (Dropped.)** This pull request first moved `backend/Dockerfile`'s base image to ECR Public too. Checked
  by Richard on October 20, 2026, but CI's `stack` job then failed twice with `429 Too Many Requests - Data limit
  exceeded` from public.ecr.aws (GitHub's runners share addresses), so the change was taken out and the local stack
  and the devtools image stay on Docker Hub.
- [ ] **2. Deploy.** Run `./serena aws deploy`. In the plan, the four task definitions "must be replaced" (a new
  image), and in each one's `container_definitions` the only changes are `image` and `SERENA_BUILD`: no
  `- hostPort`, `- mountPoints = []`, `- volumesFrom = []`, `- systemControls = []`, `- portMappings = []` or
  `- environment = []` lines. Type `yes`.
- [ ] **3. A plan with the running images changes nothing.** Run `./serena aws plan`. Expect "No changes. Your
  infrastructure matches the configuration." If it still shows a task definition to replace, copy its
  `container_definitions` lines here.
- [ ] **4. Pausing replaces no task definition.** Run `./serena aws pause`. Expect a plan with only the services'
  `desired_count` (and the alarms' actions) changing, and no task definition replaced. Type `yes`. Then
  `./serena aws resume`, the same, and `./serena aws etl pahma` (the simulator lost its records).
- [ ] When done, `./serena aws destroy` (type `personal-dev`), or `./serena aws pause` if personal-dev is kept for
  the next pull request.

## 27. The devtools image's base from ECR Public in AWS only (10 minutes, at the next personal-dev deploy)

What it checks: `./serena aws deploy` builds the simulator's and fake ETL's image (`backend/Dockerfile`) with its
Python base image from Amazon ECR Public, by a named build context, while the local stack and CI still build the
same file from Docker Hub (ECR Public refused CI's shared runners: section 26, step 1). From this pull request's
branch on the Mac, signed in (`aws sso login --profile bmu-personal`):

- [ ] **1. The local stack is unchanged.** Run `./serena down && ./serena up`. Expect it to start as before, and the
  build's output to name `docker.io/library/python:3.11-slim` (not `public.ecr.aws`).
- [ ] **2. The AWS build uses ECR Public.** Run `./serena aws deploy` (or `./serena aws resume` first if
  personal-dev is paused). Under "== 2/3 The simulator's and fake ETL's image", expect a line like
  `[context python:3.11-slim] load metadata for public.ecr.aws/docker/library/python:3.11-slim`, and no
  `docker.io/library/python`. Type `yes` at the plan.
- [ ] **3. The devtools image still works.** *Automated:* T92 (`./serena aws test`, section 30). Run `./serena aws etl pahma`. Expect "updated" and sample addresses (the
  fake ETL runs from that image, and the simulator it fills does too).
- [ ] When done, `./serena aws pause` (or `./serena aws destroy`, type `personal-dev`).

## 28. Acknowledge all, and finding the waiting alerts, locally (15 minutes, before merging the pull request that adds them)

What it checks: decisions D207 to D218 (October 20, 2026). On the Alerts page, "All · Waiting (<n>)" and a red bar on
waiting rows; the bell and the banner open Waiting; "Acknowledge all (<n>)" asks first, listing the alerts (each a link
to its row), and acknowledges exactly those. serenade's T84, T85 and T87 to T89 check the same on BAMPFA. On the
local stack, from this pull request's branch (see "Testing a pull request locally" above), signed in to PAHMA as
`admin` (password `admin`) at http://localhost:5373/admin/.

**Before you start:** make four alerts wait. On **Settings** (the gear), under "Servable list check", change "Delta
threshold (%)" (not another setting: only it and the audit retention raise an alert) to 12.5 (any
reason), then **Use default** (any reason): that's two "An admin changed a setting" alerts. Do the same once more for a
third and fourth. Leave any older alerts as they are.

- [ ] **1. The bell and the banner open Waiting (D213).** Expect the bell's red badge to count the waiting alerts and
  the banner to name the newest. Click the banner's **Open alerts**. Expect the address to end with `?show=waiting`,
  **Waiting (<n>)** to be chosen, and the table to list only the waiting alerts, each with its Acknowledge button.
  Go to **Overview**, then click the bell: the same.
- [ ] **2. All, and the waiting rows' bar (D212, D214).** Click **All**. Expect `show=waiting` to leave the address,
  every alert of the last 30 days listed, and each waiting alert's row to have a red bar down its left edge (the
  acknowledged ones none). Sort by **Acknowledged**, change "Items per page" to 10 and go to page 2: the choice of
  All stays. Open **Audit log** from the menu, then press the browser's Back: All again, on page 2, as it was (All and
  Waiting change the address in place, like sorting and paging, so Back right after one leaves Alerts). Click
  **Waiting**: back to page 1, only the waiting ones, the sort and "Items per page" kept.
- [ ] **3. Opened another way, All (D213).** On the **Audit log**, click an "alert acknowledge" entry's target (an
  alert of the last 30 days): expect Alerts on **All**, not Waiting, even while alerts wait.
- [ ] **4. Acknowledge all asks first (D207 to D209).** With 2 or more waiting, expect **Acknowledge all (<n>)** at
  the right, above the table (with only 1 waiting, there's none: its row's button does it). Click it. Expect
  "Acknowledge <n> alerts?", the alerts listed newest first, all of them even if they're on other pages of the table,
  and the reminder that a problem still there is raised again the next day; no reason field; **Cancel** and
  **Acknowledge <n>**. Each line reads like "An admin changed a setting · delta_threshold_percent · 22:45 UTC" (the
  date too for an alert not raised today) (D217). Make the window short enough that the list doesn't fit: only the
  list scrolls, and the title, the reminder and the buttons stay in view (D216). Click **Cancel**: nothing changes.
  (More than 500 waiting, D218, is checked by the admin app's tests: a local stack won't have that many.)
- [ ] **5. A listed alert is a link (D215).** Click **All**, click the **Raised** header once (oldest first), and set
  "Items per page" to 10. The waiting alerts, the newest, are now on the last page; if All fits on one page, do "Before
  you start" again until it holds more than 10 alerts. Open **Acknowledge all** and click the first listed alert (the
  newest). Expect the dialog to close, the table to move to the page that holds it, that row marked (shaded) and in
  view, and nothing acknowledged (the badge's count unchanged).
- [ ] **6. Acknowledge them (D207, D210, D211).** Open **Acknowledge all** again and click **Acknowledge <n>**. Expect
  every row acknowledged by "admin" with the time, the button, the badge and the banner gone, and **Waiting (0)**
  showing "No alerts waiting.". On the **Audit log**, expect one "alert acknowledge" entry per alert. The banner never
  had its own Acknowledge all (D211).
- [ ] **7. One acknowledged meanwhile is skipped.** Make two alerts wait again (step "Before you start"). Open
  **Acknowledge all** and leave the dialog open; in a second tab, acknowledge one of them with its row's button. Back
  in the first tab, click **Acknowledge 2**: expect no error, both acknowledged (the second tab's by its own click),
  and one audit entry for each, not two for the one.

## 29. A setting's value checked on Save, locally (10 minutes, before merging the pull request that adds it)

What it checks: decisions D219 to D221 (October 20, 2026). The Settings page's Change dialog checks a value when you
click Save, before sending it, and says what's wrong under the field in words, with the dialog left open; a value
Serena refuses anyway is said the same way. serenade's T30 and T86 check the same on BAMPFA. On the local stack, from
this pull request's branch (see "Testing a pull request locally" above), signed in to PAHMA as `admin` (password
`admin`) at http://localhost:5373/admin/, on **Settings** (the gear).

- [ ] **1. The hints.** Click **Change** beside each setting in turn (then **Cancel**). Expect the hint under the field:
  00:00 to 23:59, Pacific; 5 to 300; 60 to 7,200 (2 hours); 0.1 to 100; 1 to 2,048 for each size limit; and the
  placeholder's "The Media CSID of a record in this museum's CollectionSpace".
- [ ] **2. Not a value (D219, D221).** Change **Delta threshold (%)** to `5d`, give a reason, click **Save**. Expect
  "Give a number from 0.1 to 100." in red under the field, the cursor in the field, the dialog open, and no red
  message on the page. Type `12.5` instead: the message goes as you type. **Cancel**.
- [ ] **3. Out of bounds, and whole numbers.** The same with **ETL poll interval** `12.5` and `301` ("Give a whole
  number from 5 to 300."), **Largest PDF file fetched** `4096` ("… from 1 to 2,048."), and the **Deadline** `8am`
  ("Give a time as HH:MM, from 00:00 to 23:59."). The order doesn't matter: without a reason, a bad value is named
  first; with a good value and no reason, "Give a reason first.".
- [ ] **4. Nothing was sent.** Open **Audit log**: no "settings change" entry from steps 2 and 3, and no alert on the
  bell.
- [ ] **5. A good value still saves.** Change **ETL poll interval** to `30` with a reason: saved, "changed; default
  value 15". Then **Use default** (any reason).

## 30. The AWS tests, personal-dev with the simulator (about 30 minutes, mostly waiting; before merging the pull request that adds them)

What it checks: decisions D222 to D231 (October 21, 2026). `./serena aws test` runs serenade's AWS tests, T90 to
T105 (`serenade/aws/`), against personal-dev: the steps of sections 24, 25 and 27 marked *Automated*. You run it,
signed in; it changes only what it undoes (two fake ETL refreshes and a recall it cancels). From this pull request's
branch on the Mac (`git switch <the branch> && git pull`), signed in (`aws sso login --profile bmu-personal`), with
Chrome installed:

Checked by Richard on October 21, 2026: steps 1 to 4, 6 and 7 at commit `a856b05` (`16 passed` twice, in about 4
minutes each; step 4 by the second run, whose T103 could recall again only because T104 had cancelled the first
run's recall), and step 5 at `348b090`.

- [x] **1. Deploy this branch.** personal-dev is paused: `./serena aws resume`, then `./serena aws deploy` (T91
  checks the running image is this branch's commit). Type `yes` at the plan: expect only the four task definitions
  replaced.
- [x] **2. The fake ETL's summary as JSON.** Run `./serena aws etl pahma --json`. Expect "Running the fake ETL …" and
  the task's ID, then one line of JSON starting `{"refresh_id":` with `"state": "updated"`. Run
  `./serena aws etl pahma --json 2>/dev/null`: only the JSON line. `./serena aws etl pahma` without `--json` prints as
  before.
- [x] **3. The tests.** Run `./serena aws test`. Expect it to name the environment, its address, the image and
  "museum pahma", then pytest: `16 passed` in about 5 to 10 minutes (T101 waits for Logs Insights, up to 5
  minutes). A failed browser test's screenshot is in `serenade/.run/failures/`. If T90 fails with "firing:
  serena-dev-web-down" just after the deploy, wait 10 minutes and run it again.
- [x] **4. It leaves nothing behind.** In the admin app (`<URL>/admin/`, PAHMA, `admin`/`admin`), "Recalls" shows no
  active recall; "Ended" has "serenade T104: an AWS test cancel"; the Audit log has the recall and its
  cancellation. Run `./serena aws test` again: `16 passed`.
- [x] **5. One test.** `./serena aws test -k t99 --headed`: expect `1 passed, 15 deselected` in about a minute (it runs
  the fake ETL first, for its sample address; T99 needs no browser, so none opens). `./serena aws test -k t100
  --headed`: Chrome shows the sign-in and Past refreshes, and `1 passed`. A test that builds on an earlier one (T101
  to T104) is skipped when run alone, as in the local suite: give `-k` both, for example `-k "t96 or t101"`.
  - Note (October 21, 2026): T100 alone was skipped at `a856b05`, because it waited for T95 without needing it. At
    `1c4f2eb` it ran but failed: alone, it made its refresh after Past refreshes had loaded, so the list didn't show
    it. Both fixed after.
- [x] **6. Only through `./serena aws test`.** Run `serenade/.venv/bin/python -m pytest serenade/aws`. Expect "The AWS
  tests run only through ./serena aws test (SERENADE_AWS_ENV isn't set)." and no test run.
- [x] **7. Not while paused.** `./serena aws pause` (type `yes`), then `./serena aws test`. Expect "'personal-dev' is
  paused: ./serena aws resume first." and no test run. Leave personal-dev paused.

## 31. Stage 1 in the UC Berkeley account, with the simulator (about half a day, spread over a week; before stage 1 is destroyed)

What it checks: that Serena deploys and runs in the UC Berkeley test account under the deployer role Ops created for
Jira CS-9523 (`deploy/iam/serena-deployer-policy-mvp.json`; see `deploy/iam/README.md`), that only campus networks and the
campus VPN reach it, and how big its tasks need to be (design.md, Compute). Stage 1 passes when every step below is
ticked; then it's destroyed (step 11) and stage 2 is asked for. The settings are in
`deploy/environments/ucb-stage1.conf`. Every `./serena aws` command here takes `--env ucb-stage1`.

**Before you start** (once):

1. From Ops (CS-9523): the account number and the deployer role (`SerenaStage1Deployer`, with
   `deploy/iam/serena-deployer-policy-mvp.json`), assumed from your existing cspace SSO profile; the campus network
   and campus VPN address ranges; any tags the account requires (D251); and whether Serena should create its own VPC
   (`10.41.0.0/16`, public subnets, no NAT gateway) or use the account's shared dev/QA VPC.
   Also from Ops: the service-linked roles, if the role can't create them (`AWSServiceRoleForECS`,
   `AWSServiceRoleForElasticLoadBalancing`, CloudFront's for VPC origins), and, if the account is new, whether AWS has
   verified it for CloudFront (if a deploy is refused for that, Ops opens the AWS Support case and step 1 waits).
2. Add the profile Ops gave in CS-9523 to `~/.aws/config`, named `serena-stage1-deploy`, with `source_profile` set
   to your existing cspace SSO profile. Sign in with `aws sso login --profile <your cspace profile>`, then check with
   `aws sts get-caller-identity --profile serena-stage1-deploy` (expect the `SerenaStage1Deployer` role). The role's
   sessions last an hour; the AWS CLI and Terraform should renew them from the SSO sign-in during a long run (if
   one stops with an expired-token error, sign in again and rerun it).
3. In the clone on the Mac, on `main` (`git switch main && git pull`), create
   `deploy/environments/ucb-stage1.local.conf` (not committed) with three lines:
   `ACCOUNT_ID="<account number>"`, `ALERT_EMAIL="<your address>"` and
   `ALLOWED_CIDRS="<campus ranges>,<VPN ranges>"` (comma-separated, IPv4 only).

**The steps:**

- [ ] **1. Deploy under Ops's deployer role.** Run `./serena aws deploy --env ucb-stage1`. Confirm the account,
  check the plan, type `yes`. Expect it to finish in about 15–25 minutes and print the address; `<URL>/health`
  answers `ok`. If any step fails with `AccessDenied`, note the action and resource here: the role needs
  it, and so does the stage 2 policy (`deploy/iam/serena-deployer-policy.json`): change both files in one pull request.
- [ ] **2. Confirm the alert email.** Run `./serena aws confirm-alerts --env ucb-stage1` and paste the link from
  AWS's "Subscription Confirmation" email (don't click it).
- [ ] **3. Status.** Run `./serena aws status --env ucb-stage1`. Expect web "running 2 of 2", worker and fakecspace
  "running 1 of 1", the image's tag ending in `main`'s commit, the allowed addresses from your `.local.conf`, the alert
  email confirmed, and for PAHMA its CollectionSpace account and ETL token "set".
- [ ] **4. The AWS tests.** Run `./serena aws test --env ucb-stage1`. Expect `16 passed` (section 30). In the admin
  app, the header shows "AWS · UC Berkeley stage 1 · simulator".
- [ ] **5. Campus and VPN only.**
  1. On a campus network (not the VPN): open `<URL>/health`, `<URL>/admin/` and a sample address the fake ETL
     printed (`./serena aws etl pahma --env ucb-stage1`). Expect `ok`, the sign-in page and the image.
  2. Off campus, on the campus VPN: the same three. Expect the same.
  3. Off campus without the VPN (a phone without Wi-Fi): the same three. Expect 403 "open only to listed addresses"
     for each.
- [ ] **6. Someone else.** Ask a colleague on campus or the VPN to open a sample address and the admin app's sign-in
  page. Expect both to work for them, with nothing set up on their side.
- [ ] **7. An alert and an alarm by email.** As section 25, steps 12 and 13, with the alarm
  `serena-stage1-cspace-refused` and `--profile serena-stage1-deploy`. Expect both emails at `ALERT_EMAIL`, and the
  alarm's "OK" email about 15 minutes later.
- [ ] **8. Two web tasks.** Run `./serena aws logs web --env ucb-stage1` while opening a few sample addresses. Expect
  requests answered by both tasks (two different task IDs in the log stream names), and no errors.
- [ ] **9. Task sizes.** Replay the busiest hour and a typical hour of the cleaned access logs (`./serena aws replay`,
  section 32 and `serenade/README.md`; `LOG=~/dev/src/rtl/serena/tools/access-logs/out/clean/2026-09.tsv.gz`, or a
  later month). Each run ends with the web and worker services' CPU and memory; note them here, with the run's
  `sent`, `late` and `statuses`. Expect no 5xx answers other than a 504 on a first request whose fetch takes over 60
  seconds (D184), and few or no `late` requests (many means the Mac or the VPN couldn't keep up: note it).
  1. The busiest hour, cold: `./serena aws replay --env ucb-stage1 --log $LOG --busiest hour --dry-run`, then the
     `./serena aws etl …` command it prints (override the delta threshold on that refresh if its check fails, as in
     section 32, step 3), then the same replay without `--dry-run` (about an hour). Expect `answers` all `served`.
  2. The same hour, warm and five times faster: add `--speed 5 --follow 100` (about 12 minutes; the followed ones
     answer 200).
  3. A typical hour, cold: `--from 2026-09-10T14:00 --minutes 60 --first-row 20000` (3,046 requests in September
     2026): its dry run, the `./serena aws etl … --first-row 20000` command it prints (its servable list check fails
     on the delta threshold, as every row is new: override the threshold on that refresh on the Refreshes page; don't
     run the fake ETL again), then the replay.
  4. Note the highest CPU and memory of each service at each run. The task sizes in design.md (Compute) and
     Terraform are then set from them, in their own pull request.
- [ ] **10. Cost.** After about a week, in the AWS console, Billing and Cost Management → Cost Explorer, filtered by
  the tag `project = serena` (or ask Ops if the role can't see it): note the daily cost here. It helps
  size stage 2 (WAF on, two web tasks, all day).
- [ ] **11. Take stage 1 down**, when every step above is ticked and its notes are committed:
  1. Run `./serena aws destroy --env ucb-stage1`. When it asks, type `ucb-stage1`.
  2. Expect it to finish with everything destroyed. If it stops with an error about the VPC, run it again.
  3. Tell Ops on CS-9523 that stage 1 is done, and ask for stage 2.

## 32. The access-log replay, personal-dev with the simulator (about 1 hour; before merging the pull request that adds it)

What it checks: decisions D278 to D288 (October 22, 2026). `./serena aws replay` replays a slice of a cleaned access
log against personal-dev, after the fake ETL has made records with files of about the logged sizes (`--sizes`, D283),
and reads the services' CPU and memory from CloudWatch. From this pull request's branch on the Mac
(`git switch <the branch> && git pull`), signed in (`aws sso login --profile bmu-personal`), with
`LOG=~/dev/src/rtl/serena/tools/access-logs/out/clean/2026-09.tsv.gz`:

Checked by Richard on October 22, 2026, at commit `63f4f36`: every step, as noted under each. The report's `answers`
and `latency` fields, the fake ETL's override hint, and the override wording in steps 3 and 7 came after, from what
the run showed: at `63f4f36` the report had `first_requests` and `repeats` (first in that run, so a warm run's hits
were counted as first requests too), and a 302 to the unavailable image looked like a served one.

- [x] **1. Deploy this branch.** `./serena aws resume`, then `./serena aws deploy`. At the plan, expect the
  simulator's task definition replaced (`cpu` 512, `memory` 2048), with the four task definitions as usual.
- [x] **2. A dry run.** `./serena aws replay --log $LOG --busiest minute --dry-run`. Expect, with nothing sent and no
  AWS call: "Slice: 2026-09-18T13:40:00-07:00 for 1 minutes: 1128 requests for 1128 files
  (100KB:1069,1MB:17,5MB:41,20MB:1)" and "records it needs, first: ./serena aws etl pahma --env personal-dev --sizes
  100KB:1069,1MB:17,5MB:41,20MB:1".
- [x] **3. The records.** Run the printed `./serena aws etl …` command. After a refresh with other records (personal-dev's
  last had 21 rows), expect `check_failed` on the delta threshold, with the hint to override it. Override the delta
  threshold on that refresh on the admin app's Refreshes page, with a reason: it goes to `checking`, then `updated`
  (1,108 written). Don't run the fake ETL again: its records are already in the simulator. (A refresh with the same
  options as the last updated one passes without an override.)
  - `pahma-2026-10-22-1`: 1,129 rows, 1,108 added (5,276% of the last 21 rows); overridden, then updated.
- [x] **4. The busiest minute, cold.** `./serena aws replay --log $LOG --busiest minute`. Expect "Replaying against
  https://…", then a JSON summary: `sent` 1128, `late` 0 or close, `statuses` all `302`, `answers` all `served` (not
  `unavailable`: that would mean the records aren't servable, as when step 3's override wasn't done); then, after 3
  minutes, four lines of CPU and memory (web and worker). Count the files fetched; expect 1,128:
  `aws --profile bmu-personal --region us-west-2 logs filter-log-events --log-group-name /serena/dev/web --start-time "$(( $(date +%s) - 900 ))000" --filter-pattern '"fetched"' --query 'length(events)'`.
  - 1,128 sent in 60.2 seconds, none late, all 302; latency p50 0.107 s, p95 0.275, p99 0.683, max 1.315. Web CPU
    average 11.8%, busiest minute 18.9%, highest 33.6%; memory under 7%. Worker idle (CPU 0.1%, memory 6.2%).
    1,128 "fetched" lines.
- [x] **5. Warm, faster, following some redirects.** `./serena aws replay --follow 50 --speed 5 --busiest minute --log
  $LOG`. Expect the run in about 12 seconds, the latencies lower than in step 4 (every file is cached now), and 22
  `200`s among the `statuses` (one redirect in 50, delivered by CloudFront).
  - Without `--follow`: 12.1 seconds, none late, p50 0.040 s, max 0.568; web CPU busiest minute 3.4%, highest 10.2%.
    No new "fetched" lines (all hits). With `--follow 50`: 22 `200`s and 1,106 `302`s; web CPU busiest minute 15.4%,
    highest 46.2% (one short spike: the followed requests don't reach the task).
- [x] **6. Files of about the logged size.** No refusals and no files the simulator couldn't make, in the last hour:
  `aws --profile bmu-personal --region us-west-2 logs filter-log-events --log-group-name /serena/dev/web --start-time "$(( $(date +%s) - 3600 ))000" --filter-pattern '"refused"' --query 'length(events)'`
  and the same with `--log-group-name /serena/dev/devtools` and `--filter-pattern '"couldn"'`. Expect `0` from each.
  - `0` and `0`: the 1,128 fetches (41 of about 5 MB and one of about 20 MB among them) were all decoded and stored.
- [x] **7. A cold run again.** `./serena aws replay --log $LOG --busiest minute --first-row 10000 --dry-run`: expect
  the fake ETL command to end with `--first-row 10000`. Run it: expect `check_failed` on the delta threshold again
  (every row is new), and override it as in step 3. Then the replay with `--first-row 10000`: expect latencies like
  step 4's again, not step 5's, and `answers` all `served`.
  - `pahma-2026-10-22-2`: 1,128 added, 1,128 removed; overridden. The replay: none late, all 302, p50 0.113 s, p95
    0.284, max 1.367; web CPU average 13.1%, busiest minute 25.1%, highest 41.3%; memory 7.3%.
- [x] **8. Refused where it must be.** Add the line `OPEN_IMAGES=true` to `deploy/environments/personal-dev.local.conf`,
  run `./serena aws replay --log $LOG --busiest minute --dry-run`: expect "'personal-dev' isn't an environment with the
  simulator and closed images: the replay runs only against one (D279)." Remove the line. Then
  `serenade/.venv/bin/python -m serenade.load.replay --log $LOG --busiest minute --url https://example.invalid`:
  expect "The replay sends requests only through ./serena aws replay …" and nothing sent.
  - Both refused as expected; the line removed (`grep -c` printed 0).
- [x] **9. Pause.** `./serena aws pause` (type `yes`).

**After a replay, before `./serena aws test`** (added October 22, 2026, after the AWS tests failed following this
section): the replay leaves Serena's servable list on the replay's records, so the tests' fake ETL refresh (20 rows)
fails on the delta threshold and their sample file gets the unavailable image (T92, T95 to T98). Run
`./serena aws etl pahma`, then override the delta threshold on that refresh on the admin app's Refreshes page
(or override it on the tests' own failed refresh, then run the tests again). Also deploy the checked-out commit first:
T91 checks that the running image is it.

## 33. Daily request counts, personal-dev with the simulator (15 minutes, then 5 minutes the next day; before merging the pull request that adds them)

What it checks: issue #96's daily counts of cache hits, misses and unserved requests, and their backfill from the
log. From this pull request's branch on the Mac, signed in (`aws sso login --profile bmu-personal`):

- [ ] **1. Deploy this branch.** `./serena aws resume`, then `./serena aws deploy`. At the plan, expect a new table
  `serena-dev-request-counts` (or your environment's prefix), the worker's policy with `request-counts` and two
  `RequestCount…` statements, and `SERENA_LOG_GROUP` and `SERENA_LOG_RETENTION_DAYS` in the worker's environment.
- [ ] **2. The backfill.** Within a minute of the worker starting, expect a "requests counted" line per museum in the
  worker's log, with `days` 28 (or fewer, if the worker has counted some days before):
  `aws --profile bmu-personal --region us-west-2 logs filter-log-events --log-group-name /serena/dev/worker --start-time "$(( $(date +%s) - 900 ))000" --filter-pattern '"requests counted"' --query 'events[].message' --output text | tr '\t' '\n'`.
  Expect no "requests not counted" line.
- [ ] **3. The counts match the log.** For a day with requests (the replay's, say, or `./serena aws test`'s), compare
  the stored item with the Past requests page's By day row for that day, with "Last 7 days":
  `aws --profile bmu-personal --region us-west-2 dynamodb get-item --table-name serena-dev-request-counts --key '{"pk":{"S":"pahma"},"sk":{"S":"<YYYY-MM-DD>"}}' --output json | jq '.Item | {hits, misses, unserved}'`.
  Expect hits + misses to equal the page's served count, and the unserved reasons to match.
- [ ] **4. The next day.** An hour or more after the next UTC midnight (5 p.m. or 6 p.m. Pacific), expect one more
  "requests counted" line per museum, with `days` 1, and an item for the day just ended.
- [ ] **5. A restart counts nothing again.** Stop the worker's task (the service starts another). Expect no
  "requests counted" line from the new task: every day is counted already.

## 34. From the cache or CollectionSpace on Past requests, in AWS (15 minutes, after section 33's backfill; before merging the pull request that adds it)

What it checks: issue #96's card and the Served card's split, against the stored counts. On personal-dev or
personal-prod, deployed from this pull request's branch (`./serena aws --env <env> deploy`; at the plan, expect the
web role's policy with a `RequestCountsRead` statement, and the task definitions replaced):

- [ ] **1. The Served card's split.** Open Past requests with "Last 24 hours". Under "by size", expect "from the cache
  <n> · from CollectionSpace <m>", the two adding up to the Served total.
- [ ] **2. Collapsed to start.** Below By day and Most requested, expect "▸ From the cache or CollectionSpace" and one
  line: "Since <the first day counted>: <n> served · from the cache … (…%) · from CollectionSpace … (…%) · unserved
  …", with a bar. No table, no Day / Week / Month / Year switch.
- [ ] **3. Opened.** Click the title. Expect the switch (Day selected) and a table, newest first: today's row first,
  "(today, so far)", then the stored days. Compare yesterday's row with the stored item (section 33, step 3): the
  same hits ("From the cache"), misses ("From CollectionSpace") and unserved count.
- [ ] **4. Week, Month, Year.** Click each. Expect weeks labelled "2026-W44 (Oct 26 – Nov 1)", the current one "(so
  far)", and the first one counted "(from <day>)" when counting began after its Monday; months as "October 2026";
  the address gains `counts=week` (and so on). Change the page's range: the card doesn't reload or change.
- [ ] **5. Remembered.** Reload the page: the card is still open. Collapse it and reload: collapsed.
- [ ] **6. Fresh requests.** Browse a few Thumbnails (some new, some seen before), wait a minute, reload. Expect
  today's row and the totals to have grown by those requests, new ones as "From CollectionSpace".

## 35. A refresh's state as a pill, on the local stack (5 minutes; before merging the pull request that adds it)

What it checks: issue #107. With `./serena up`, run `./serena etl pahma`, then `./serena etl pahma --rows 3` (fewer rows
than the delta threshold allows, so its check fails; `--failed` doesn't call Serena at all), and sign in to PAHMA:

- [ ] **1. Past refreshes.** Expect the failed refresh's State as a red pill, "Servable list check failed", with a
  failure icon before it; the other refresh's as a green "Updated" pill, with no icon.
- [ ] **2. The refresh's page.** Open the failed refresh: expect the same red pill, with its icon, at the start of the
  state line.
- [ ] **3. Overview.** Expect "Newest refresh:" followed by the newest refresh's ID and its pill.
- [ ] **4. A screen reader.** With VoiceOver on the failed row, expect only "Servable list check failed" read out for
  the State cell, not the icon.
## 36. An overridden delta threshold, on the local stack (10 minutes; before merging the pull request that adds it)

What it checks: issue #108. With `./serena up`, run `./serena etl pahma`, then `./serena etl pahma --rows 3` (its check
fails on the delta threshold alone), and sign in to PAHMA:

- [ ] **1. Override.** Open the failed refresh and click "Override the delta threshold". Give a reason and confirm.
  Expect a banner under the state line, in orange with a shield: "Delta threshold overridden by <you> at <time> UTC.",
  then "Reason: <your reason>", then that Serena is checking the same list again. Expect your reason not to be under
  Reasons.
- [ ] **2. While it checks.** If you catch it while the state is "Checking the servable list", expect "Servable list
  check: failed" with an "Overridden" chip, and the threshold problem struck through with "(overridden)".
- [ ] **3. It finishes by itself.** Without reloading, within about 10 seconds expect "Updated", "Servable list check:
  passed" with a "Delta threshold overridden" chip, the check's warning, and the servability update. The banner ends
  "and updated from it. The team was emailed."
- [ ] **4. Past refreshes and Overview.** Expect a shield after the refresh's state on both. Hover over it (or tab to
  it): "Delta threshold overridden by <you> at <time> UTC". With VoiceOver, expect the same words read out.
- [ ] **5. Not activity.** Before step 1, open the browser's developer tools on Network. Expect each GET of the refresh
  the page makes by itself while it checks to carry `X-Serena-Background: 1`, so an open tab still signs out when idle.
