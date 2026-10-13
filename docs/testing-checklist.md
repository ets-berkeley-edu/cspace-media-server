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

## 7. Signed URLs through CloudFront, in QA (15 minutes, once CloudFront is set up in pull request 18)

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
  doesn't apply), and sample addresses for an image and a card. Open the image one in a browser: expect a grey
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
  an orange button, "Override the delta threshold". Within a minute, expect the banner, and the Alerts page (the bell), to show
  "A servable list check failed" for that refresh.
- [ ] Click that button. A dialog opens with a Reason box. Its blue button, "Override the delta threshold", is greyed
  out until you type a reason. Type one and click it. Expect:
  - the banner, with "2 alerts: An admin overrode the delta threshold" ("A servable list check failed" stays until
    acknowledged), and the bell's badge showing 2 (or one more, if the deadline alert is still waiting);
  - after reloading the page, the same refresh `Updated`, with no orange button, its reasons naming the override and
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
  and click "Start the refresh" (greyed out until all are done). Expect the new refresh's page, "an admin refresh, with
  the servable list for <today>", and, after reloading the page, `Updated`. On "Past refreshes", expect the `check_failed`
  refresh now `Abandoned`, its reasons naming the admin refresh.
- [ ] Open "Audit log". Expect the override, each acknowledgement and the admin refresh, each with `admin`.
- [ ] In a terminal: `./serena logs --no-follow web | grep threshold_overridden`. Expect the override's alert, logged
  once by the web app, which records it; the worker emails it, and locally there's no email topic. Then
  `./serena logs --no-follow worker | grep '"threshold_overridden": true'`: expect one line, the
  override's "servable list check done".

## 15. Settings, sorting and the audit log in the admin app, locally (20 minutes, before merging a pull request that changes them)

The API's tests cover each setting, its bounds, the alerts, the export and the daily removal of old audit entries. This
checks the pages in Chrome. Start afresh from the pull request's branch (see the top of this file), open
http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`).

- [ ] Open Settings (the gear at the top right, left of the museum menu). Expect the title "PAHMA Settings", and five cards: Watchdog (deadline 08:00), The ETL job (poll
  interval 15, step timeout 1800), Servable list check (delta threshold 5), Size limits (image 500, card 500, 3D 1024,
  pdf 200) and Audit log (90 days), each "default value".
- [ ] Click "Change" beside the step timeout. Type `10` and a reason, and click "Save". Expect a red message that it
  must be greater than or equal to 60, and the value unchanged. Click "Change" again, type `900` and a reason, and save. Expect 900, "changed; default value
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
- [ ] Click "Time" in the header: expect the oldest first; click again for newest first.
- [ ] Choose Outcome "Unserved": expect the two unserved lines. Choose Reason "not listed": still two. Choose Outcome
  "Served": expect your two lines, and the Reason filter cleared and greyed out.
- [ ] With Outcome "Unserved", click "Export CSV". Expect a file `serena-requests-pahma-<today>.csv` with the columns
  time (UTC), outcome, reason, path, kind, cache and signed link, and the two unserved lines only.
- [ ] Click "Last hour", then "Last 7 days": each shows the spinner, then the same counts (everything happened today).
- [ ] Open "Overview": expect "What Serena served and couldn't serve is on the Past requests page; "Media look up" says
  why for any one file."
- [ ] Sign in to BAMPFA as well (the menu at the top, "Sign in to another museum") and open its "Past requests": expect "No
  requests in this range." in both cards and "No requests match." in the table; PAHMA's requests never appear.

## 17. Recalls and Media look up, locally (25 minutes, before merging a pull request that changes them)

The API's tests cover how Serena finds each CSID, CollectionSpace being unreachable, the summary, the recall, every
case of how a recall ends (too early, no longer listed, a new Blob, restricted, still public), Release, the
thumbnails and the lookup. This checks the pages in Chrome. Start afresh from the pull request's branch (see the top of
this file), open http://localhost:5373/admin/ and sign in to PAHMA as `admin` (password `admin`).

- [ ] In a terminal, run `./serena etl pahma`. Among the files it prints, copy the image's URL (it ends
  `/derivatives/Medium/content`) and open it in Chrome: expect a synthetic grey image.
- [ ] In the admin app, open "Media look up" (in the menu, under Media records). Expect the title "PAHMA Media look up".
  Paste the URL and click "Look up". Expect "Served", "Every check passes for the Medium size", and "Serena has a
  stored copy" (you opened it); at the foot, the refresh you just ran named as the last servability update. Open "In
  Serena" Details: expect "Media CSID" then "Blob CSID" (in that order, as in the "In CollectionSpace now" Details),
  and the checks In the servable list, Kind (image), Access (public) and Recall (No recall). Copy the Media CSID.
- [ ] Paste the Media CSID alone and look it up again: expect a row for the original and each of PAHMA's sizes
  (Thumbnail, Small, Medium, FullHD, OriginalJpeg), each served "Yes"; Medium with a stored copy, the others "—".
- [ ] Add a Media record to the simulator that isn't in PAHMA's servable list (a file not published yet; synthetic
  CSIDs):
  ```
  curl -s -X POST http://localhost:8380/_fake/media -H 'Content-Type: application/json' \
    -d '{"csid": "1a2b3c4d-0000-4000-8000-000000000001", "blob": "0f1e2d3c-0000-4000-8000-000000000001"}'
  ```
- [ ] Open "Recalls". Expect the title "PAHMA Recalls", no active recalls, and nothing ended. Click "Recall…".
  In the box, paste the image's Blob CSID (from its URL), its Media CSID, `0f1e2d3c-0000-4000-8000-000000000001` and
  `not-a/csid`, one per line. Click "Show what would be recalled". Expect two Media records:
  - yours, with both CSIDs under "You gave" (they're the same record), kind image, served today "yes", found in Serena;
  - `1a2b3c4d-0000-4000-8000-000000000001`, kind "not known", served today "no", found in "CollectionSpace (not served
    today)";

  each with a thumbnail. Below them, "Not recalled: not-a/csid: Not a CSID."
- [ ] Click your record's thumbnail: expect the full-size image in a window. Close it.
- [ ] Expect "Recall 2 Media records" greyed out until you type a reason. Type one and click it. Expect both in
  "Active recalls", by `admin`, with your reason, and "Waiting for a later refresh". Within a minute, expect the
  bell's badge and the banner, "An admin recalled Media records"; click "Open alerts": expect the alert naming 2 and
  your reason.
- [ ] Reload the image's URL in Chrome (a fresh tab, or after clearing the cache): expect the unavailable image.
  Look it up again: expect "Not served: recalled", with your name and reason, "Open Recalls", and every size served
  "No", why not "recalled".
- [ ] Open "Audit log": expect two "recall" entries, one per Media record, each with your reason.
- [ ] Click "Recall…" again, paste your Media CSID and click "Show what would be recalled": expect it greyed, served
  today "already recalled", and no "Recall" button. Cancel.
- [ ] In the box, paste 13 CSIDs (any text, one per line) and click "Show what would be recalled": expect "More than
  12 CSIDs: use a text file instead." Save the same 13 lines as a `.txt` file, clear the box, choose the file and
  click again: expect the summary, every line "Not found" or "Not a CSID". Cancel.
- [ ] Run `./serena etl pahma` again. It's the same refresh date as your recalls (today, Pacific), so the refresh
  doesn't look at them (a list made before staff could change CollectionSpace): expect both still active, and no new
  alert. (Ending a recall needs a refresh on a later day; the tests cover every case. If you leave the stack running
  until tomorrow, run `./serena etl pahma` then: expect your image's recall kept, "Still public in CollectionSpace"
  with a Release button, the alert "Recalled in Serena, but still public in CollectionSpace", and the other
  recall ended, under "Ended", "Ended by a refresh". Release yours with a reason and expect the image served
  again.)

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
what CollectionSpace says now, last served and first stored, and the dialogs that open a file from Past requests and
Recalls. The API's tests cover each CollectionSpace case; this checks the pages in Chrome. Start afresh from the pull
request's branch, run `./serena etl pahma`, open http://localhost:5373/admin/ and sign in to PAHMA as `admin`
(password `admin`). The simulator's synthetic records are changed with `curl` against http://localhost:8380.

- [ ] Open the image's Medium URL that `./serena etl pahma` printed, in Chrome, twice. In the admin app, open "Media
  look up" and look up that URL. Expect:
  - "Served", with "Serena has a stored copy";
  - under it, "Last served" and "First stored in Serena" with today's date, and in the sizes table the Medium row with
    its stored copy (image/png), Last served and First stored;
  - two panels on the left: "In Serena" with the stored Medium, and "In CollectionSpace now" with CollectionSpace's
    file, "not stored"; each with a collapsed "Details". Open both: In Serena lists the Blob, Media record, kind,
    access and the checks; In CollectionSpace now lists the Media record, State "Exists", the same Blob, "Approved for
    web: Yes" and Last changed;
  - "Serena and CollectionSpace": the Media record, Blob, Access and As of rows, none marked "differs", and "What
    the next refresh will do: Nothing has changed in CollectionSpace since the last refresh."
- [ ] Copy the page's address (it ends `?q=` and the URL) into a new tab: expect the same answer.
- [ ] Take the record off the web in the simulator, with the Media CSID from the page (`<media>` below):
  `curl -s -X POST http://localhost:8380/_fake/approve/<media> -H 'Content-Type: application/json' -d '{"approved": false}'`.
  Look it up again: expect still "Served" (Serena's answer comes from the last refresh), "Approved for web: No", the As
  of row marked "differs", and "The Media record changed in CollectionSpace after the last refresh. The next refresh
  shows whether it's still public."
- [ ] Replace its image: `curl -s -X POST http://localhost:8380/_fake/replace/<media>`. Look it up again: expect the
  Blob row and the Blob in "In CollectionSpace now" marked "differs", a darker picture there than Serena's stored
  copy, and "The Media record has a new Blob in CollectionSpace since the last refresh. The next refresh lists the new
  Blob and drops this one; …".
- [ ] Soft-delete it: `curl -s -X POST http://localhost:8380/_fake/delete/<media>`. Look it up by its Media CSID:
  expect "Served (stored sizes only)", Medium served "Yes", every other size "No", why not "media deleted", State
  "Soft-deleted", and "The Media record is soft-deleted in CollectionSpace. The next refresh drops this Blob; …".
- [ ] Look up `9f9f9f9f-0000-4000-8000-000000000000` (synthetic, unknown): expect "Not served: not in the servable
  list", "Not in CollectionSpace", and "CollectionSpace has no Blob or Media record with this CSID either." Look up
  PAHMA's placeholder image, `59a733dd-d641-4e1a-8552`: expect "Nothing to compare: this file has no Media record".
- [ ] Stop the simulator (`docker compose stop fakecspace`) and look up the URL again: expect Serena's answer, the
  notice "CollectionSpace can't be reached, so there's nothing to compare with", and "CollectionSpace can't be
  reached" in the right-hand panel. Start it again (`docker compose start fakecspace`).
- [ ] Open "Past requests" with "Last hour". Hover over a path: expect it underlined, as a link. Click your image's
  Medium path: expect a dialog with the path, the picture, "This request, <time>: served.", "Media look up" and
  "Dismiss". Click "Media look up": expect Media look up on that path. Back on Past requests, expect the path with a
  bad CSID (if any) not to be a link.
- [ ] On "Recalls", recall your image's Media record (with a reason). Hover over its Media CSID and its Blob CSID in
  "Active recalls": each becomes a link. Click the Blob: expect the dialog with the picture (admins see a recalled
  file), "Media look up" and "Dismiss"; click "Dismiss". Click the Media CSID, then "Media look up": expect "Not
  served: recalled".

