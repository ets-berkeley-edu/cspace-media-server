# serenade: Serena's headless test suite

Automated checks of Serena on the local stack: plain HTTP checks of what Serena serves, and Selenium browser checks of
the admin app, written as the team writes them for BOA (bea), Damien (mrsbaylock) and Diablo (xena): pytest, with a
page object per screen in `pages/` and the tests in `tests/`. The local tests (`tests/`) run only against the local
stack: they sign in, recall files and switch the CollectionSpace simulator's outage on. A second, smaller set in
`aws/` checks a deployed environment ("The AWS tests", below). Neither ever runs against production.

## Running it

```
./serena test                  # starts the test stack afresh, builds the dataset, runs every test (headless)
./serena test -k t3 --headed   # one test, with the browser showing
./serena test-down             # stops the test stack
```

Needs Docker, Python 3.11 and Chrome. The first run makes `serenade/.venv`; Selenium Manager (part of Selenium) finds
the matching chromedriver. A run takes the stack's start-up (a few minutes) plus the tests.

- **Its own stack.** `./serena test` runs the Docker Compose project `serena-test` on its own ports (Serena 8400, the
  admin app 5473, the simulator 8480, moto 9400), so it never touches the stack testers use (`./serena up`). Each run
  starts it afresh, so every run begins from the same data. It's left running afterwards, to look at what a failed
  test saw: the admin app at http://localhost:5473/admin/ (`admin` / `admin`).
- **When a browser test fails,** its screenshot and the page's HTML are saved in `serenade/.run/failures/`, and the
  test's report says so.
- `./serena ui` runs the suite against the stack testers use, as before. The tests that need the dataset skip there
  ("needs the test stack"), so only the sign-in tests run.

## How the tests share one dataset

The goal is the most tests per dataset, with the fewest resets (Richard, October 14, 2026).

- **The dataset** (`dataset.py`) is daily refreshes by the fake ETL, built once per run: PAHMA's, Cinefiles' (for its
  PDFs), and two of UCJEPS's, the second of 3 rows, which fails its servable list check (for the alerts and the
  refreshes); and UCJEPS's servable lists of 20 and 3 rows, for the admin refreshes the refresh tests start. Its CSIDs are the same
  every run, and `dataset.py` checks the run built the records it expects.
- **Records have roles.** A *shared* record may be looked at by any test, never changed. A *reserved* record is set
  aside for the tests that change it, and they put it back where they can. Add a role in `dataset.py` when a test
  needs a record of its own, and say which tests use it.
- **Tests run in groups, by what they change:** looking only first, then changes to one record, then changes that
  affect the whole museum (or every museum), last, each undoing itself (for example in a fixture's `finally`). A
  reset falls only where a change can't be undone.
- **A test that builds on an earlier one** says so with `@pytest.mark.after("test_name")`: if that test didn't pass,
  it's skipped rather than failing for the same reason.
- So the tests run in order, never in parallel or shuffled: each file's tests in file order, and the files in
  `conftest.py`'s `FILE_ORDER`: serving first, then Past requests (which reads the serving tests' lines), then UCJEPS's
  alerts (which no PAHMA test reads), then the refreshes (which change UCJEPS after its alerts are read), the PAHMA
  look up and recall tests, the settings (BAMPFA's, and PAHMA's placeholder image, each put back), the audit log
  (which reads what all of them recorded), the layout and navigation checks (which only look, at the lines and
  entries the others left), sign-in and sessions (T45 signs everyone out of PAHMA), and last, Serena unreachable
  (T47 stops and starts its web service). A new file goes where its changes belong.

## Where the tests come from

`docs/testing-checklist.md` says what to check; the test inventory (`serena-test-inventory.xlsx`, kept by Richard)
lists each automated check, by feature, with the checklist section and step it comes from, whether it's HTTP or a
browser check, its data effect, and whether the backend's own tests already cover it. Each test's name starts with
its inventory ID (`test_t3_…`), and its docstring names the checklist steps.

| Tests | What |
| --- | --- |
| `tests/test_serving.py` | Serving, T1, T7 to T9, T14, T15 (plain HTTP): a served image from the stored copy, Cinefiles' public and restricted PDFs, requests Serena refuses, a catalog card, Media URLs (sections 11, 16, 17, 21, 23) |
| `tests/test_requests.py` | Past requests, T54 to T64 and T106 (Refresh, issue #100): the page and its range, the summary boxes, the table's lines and columns (no signed-link parameters), Media URL lines, filters, ranges, the CSV export, another museum's page, opening a file from a line (sections 16, 19 to 21, 23) |
| `tests/test_settings.py` | Settings, T29 to T35 and T86: BAMPFA's page and its default values, a value out of bounds said under the field, a value that isn't a number or a time caught on Save (section 29), a change and the default again (with its audit entry), a change that raises an alert, the audit retention's choices, Save without a reason; PAHMA's placeholder image's Media record (sections 15, 19, 21, 22) |
| `tests/test_audit.py` | Audit log, T37 to T39: UCJEPS's refresh actions and the ETL's calls, BAMPFA's CSV export, PAHMA's By column, links and shortened values (sections 14, 15, 20) |
| `tests/test_layout.py` | Layout and navigation, T48 to T53, on PAHMA: page titles, the menu's groups, the bell and the gear, keeping your place on Past requests (back by the link, by the browser's Back, and in a new tab), back links and none from the menu, the Overview's links, column help by the pointer and the keyboard (sections 15, 16, 18, 20, 21) |
| `tests/test_sign_in.py` | Sign-in and sessions, T40 to T46: the five museums on the sign-in page, signing in and out, an account without the role, two museums at once, the role per museum, the API documentation page (read-only, nothing in the console about the Content-Security-Policy), and, last of the whole run, "Sign everyone out" ending another browser's session (sections 12, 20) |
| `tests/test_unreachable.py` | T47, last of all: with Serena's web service stopped (the test stack's web container), "Sign everyone out" and Media look up say "Serena can't be reached right now. Try again in a minute. (502)", and the dialog stays open; Serena is started again however the test ends (sections 20, 21) |
| `tests/test_alerts.py` | Alerts, T23 to T25, on UCJEPS: a failed check's alert on the bell, the banner and the Alerts page; its text, with its refresh ID as a link; acknowledging (sections 14, 18, 20). T84 and T85, on BAMPFA (two alerts from a setting changed and put back): All · Waiting, the waiting rows' bar, the banner and the bell opening Waiting; Acknowledge all, its dialog's list and links, and none waiting after. T87 to T89 (20 more alerts, raised through the admin API): All held through sorting, paging and Back, Waiting back to page 1, the audit log's link opening All; the dialog's order, Cancel, no reason, only its list scrolling in a short window, a link to another page of the table, one audit entry per alert; and a second browser acknowledging one while the dialog is open (section 28) |
| `tests/test_refreshes.py` | Refreshes, T16 to T21: Past refreshes, Start a refresh's missing fields, and on UCJEPS a failed check's page, overriding the threshold, an admin refresh repairing a failed one, sorting and paging 30 refreshes (sections 11, 14, 15, 21) |
| `tests/test_lookup_and_recalls.py` | The pilot, T2 to T6: Media look up, a recall and its cancellation, CollectionSpace unreachable (sections 11, 17, 19). Recalls, T74 to T81: the preview (what Serena finds, paths and URLs, more than 12 CSIDs and a text file, an already recalled record), a missing reason, a recall's row and its files, Past requests and the audit log, and the recall's alert, T26 (sections 17 to 21). Media look up, T65 to T73: every size of a Media CSID, the comparison with CollectionSpace, the page's address, paths it forgives and refuses, an unknown CSID, the sizes box, and a record changed in CollectionSpace (off the web, replaced, soft-deleted), then put back (sections 17, 19 to 21, 23) |
| `aws/test_deployment.py` | A deployed environment, T90 to T108 ("The AWS tests", below; sections 24, 25, 27, and the shared root's addresses) |
| `qa/test_qa_*.py` | PAHMA QA's synthetic records on ucb-stage2, T109 to T133 ("The synthetic-record tests", below; section 63); `test_qa_records.py`, only with `--check-records`, reports the records' state |

## The AWS tests

`aws/` checks an environment in AWS after `./serena aws deploy` or `./serena aws resume` (D222 to D231, decided
October 21, 2026): T90 to T108, from the checklist's AWS sections (24, 25 and 27, their steps marked "Automated").

```
./serena aws test                  # personal-dev (or --env NAME), signed in with aws sso login
./serena aws test -k t96 --headed  # one test, with the browser showing
```

- **You run it, signed in.** Never in CI and never by Claude (D229). It checks the sign-in and that the environment is
  deployed and running, then passes the tests its address, museum, image tag and the rest (`aws/target.py`). The
  tests refuse any address but the one the environment's last deploy saved in `deploy/environments/<env>.url`
  (D225). In an environment its pipeline deploys, `./serena aws test` saves that file itself, from the Terraform state
  the pipeline applied.
- **What it checks:** `./serena aws status`; `/health` and that the image is the checked-out commit (tagged
  `<commit>-<time>` by a deploy from a laptop, with the commit's first 12 characters by the pipeline); the fake ETL's
  refreshes (`./serena aws etl … --json`); a file request's 302 to a signed address, its delivery and CloudFront's
  cache, bad and missing signatures, the bucket refusing direct requests, the unavailable images; the admin app's
  header, Past refreshes, Past requests (CloudWatch Logs Insights, which can take a few minutes to catch up) and Media
  look up; a recall stopping an address but not a signed one; and last, no permission errors in the logs. The deploy,
  plans, emails, `cdn-key`, a second network, pause and destroy stay in the checklist, by hand.
- **What it changes, it undoes** (D227): with the simulator, the fake ETL's refreshes (the simulator's synthetic
  records) and a recall that T104 cancels, even when T103 failed after making it. Never a setting, key, alarm or
  pause.
- **A real CollectionSpace (QA):** only the tests that look run; those marked `changes` or `simulator` are skipped
  (D224), and the sample image comes from `./serena aws list`. Set `SERENADE_ADMIN_USER` to a museum admin's username;
  `./serena aws test` asks for the password (D228), which isn't shown or saved. With the simulator it's `admin`/`admin`.
- **Read-only AWS calls** (D231) use the AWS CLI with the environment's profile: `logs filter-log-events` for T105.

## The synthetic-record tests

`qa/` automates checklist section 63 (decided November 6, 2026): Serena serving and refusing PAHMA QA's synthetic
records SERENA-TEST-001 to -051 on ucb-stage2, T109 to T133. Unlike the AWS tests, they change things in QA.

```
SERENADE_ADMIN_USER=<a PAHMA admin> SERENADE_CSPACE_BASE=https://<PAHMA QA's host>/cspace-services \
  SERENADE_CSPACE_USER=<the account> SERENADE_TEST_MEDIA_SCRIPT=<absolute path to make-test-media.py> \
  ./serena aws test --env ucb-stage2 --synthetic
```

- **Only ucb-stage2's PAHMA, with PAHMA QA's CollectionSpace,** and only through `./serena aws test --synthetic`, which
  Richard runs, signed in (never Claude or CI, D229). It asks for the admin's password and the CollectionSpace
  account's, neither shown nor saved; the tests hand the second to the script in its environment, never as an
  argument.
- **The records come from make-test-media.py,** which is kept in the team's notes, outside this repository:
  `SERENADE_TEST_MEDIA_SCRIPT` is its absolute path, and the tests read the records' CSIDs from its git-ignored `out/`
  (`qa/records.py`). Nothing here names a test record's CSID (D314); the tests name records by number. Media look up
  doesn't search by identification number, so the CSVs are the only list.
- **What it changes** (an exception to D224 and D227, for this set only): the synthetic records in CollectionSpace,
  through the script (step 16's changes, including 027 deleted for good, for which the test types the script's PURGE,
  and the renewal of 021-032); PAHMA's image size limit, put back however T109 ends; the placeholder image, left on
  record 033 as the checklist leaves it (a run that finds it there sets it back to not set first; it refuses to change
  any other record named there); a recall of 029, cancelled however T130 ends.
- **Every run, and every other day.** The files run in `FILE_ORDER`: `test_qa_look.py` (steps 2 to 13, looking
  only), `test_qa_settings.py` (steps 1 and 14), `test_qa_changes.py` (steps 15 to 22) and `test_qa_next_run.py`
  (steps 23 and 24, then T133 renews 021-032). Each of 021-032 can be changed once (D311), so the changes run only
  while the copies in use are listed and unchanged, and the checks after them only once an ETL run Serena applied
  started after the changes; otherwise they skip, saying why. Run it the day after the copies are listed, before
  21:01, and again the next morning: a cycle every other day.
- **Repeatable without renewing the rest.** Serena stores a Blob's files for good, so a first request misses only
  once: the look-only tests read Media look up first and expect a miss only for a size not stored yet. 008's original
  is never requested except by step 1 (a refusal stores nothing), and step 12 takes the first of 006's, 002's, 010's
  or 020's sizes step 2 doesn't ask for that isn't stored, about 16 runs' worth.
- **Requests first, then the log once.** A phase sends all its requests, then reads the web service's log lines with
  `aws logs filter-log-events` (read-only, D231) until every request has its line: the reason, cache hit or miss, and
  the fetches from CollectionSpace (`qa/harness.py`). The admin API is called with one signed-in browser session.
- **Outcomes the checklist left open** in steps 6, 7, 12 and 20 are pinned since the first run (November 7, 2026);
  step 1's time, steps 8 and 9 if CollectionSpace stores another type, and step 13's email are still noted at the end
  of the run ("noted"). A failure message shows a CloudFront address without its query string (no signature). Step 25 and step 13's alarm email stay by hand.
- A setting reaches every web task within a minute (`settings_cache_seconds`), so T109 and T122 wait 65 seconds after
  each change before asking.
- **Both accounts first** (`qa/logins.py`): before any test, the run signs in to Serena's admin API as
  `SERENADE_ADMIN_USER` and reads `SERENADE_CSPACE_USER`'s own roles from CollectionSpace; if either fails it
  stops ("Nothing ran: …") with the reason, before anything in QA changes. Passwords are `Secret`s
  (`serenade/secret.py`), masked in any traceback.
- **Progress as it goes** (`qa/progress.py`): pytest holds a test's output until it ends, so the long parts (signing
  in, each phase's requests and log wait, the 65-second waits, every line make-test-media.py prints, each record in
  `--check-records`) write a line with the time straight to the terminal. A run that's working prints something at
  least every 15 seconds, except while one CollectionSpace upload is under way.
- **`--check-records`** (`./serena aws test --env ucb-stage2 --synthetic --check-records`, same settings) runs only
  `test_qa_records.py`, none of the tests: a report, under "dataset", on every record against the plan and the changes
  already made, from Media look up (no image requested, so nothing cached) and from `make-test-media.py --check`
  (read-only, in PAHMA QA). It fails if a record is in a state that would make a step fail or skip for a reason that
  isn't Serena's; a listing the plan leaves "to confirm", or a copy not yet listed, is only a NOTE.

## The access-log replay

`load/replay.py` replays a slice of the legacy imageserver's cleaned access logs against an AWS environment with the
simulator, to measure how big Serena's tasks need to be (D278 to D288, decided October 22, 2026; checklist sections
31 and 32). The logs are on Richard's Mac (`rtl/serena/tools/access-logs/out/clean/<month>.tsv.gz`), never in the
repository.

```
./serena aws replay --log 2026-09.tsv.gz --busiest hour --dry-run   # the slice, and the fake ETL command for it
./serena aws etl pahma --env personal-dev --sizes 100KB:5440,1MB:205,5MB:395,20MB:19   # as the dry run printed it
./serena aws replay --log 2026-09.tsv.gz --busiest hour             # the real rate; --speed 5 for five times
```

(September 2026's busiest hour: 12,588 requests for 6,059 files, with 3 left out.)

- **Only with the simulator** (D279): `./serena aws replay` refuses any environment without the simulated
  CollectionSpace and closed image paths, and the script sends nothing unless `./serena aws replay` started it.
- **What it sends** (D280 to D282, D284): the slice's requests in their order and spacing (the log has whole seconds,
  so each second's requests are spread across it), all to the environment's museum, each keeping its URL form and
  method; Cinefiles' PDF links as the file itself; forms Serena doesn't answer are left out and counted. Each logged
  file is one record, always the same, numbered band by band as the fake ETL's `--sizes` makes them. Redirects aren't
  followed, except one in `--follow N`. A request that fails before any answer on a connection that has already had
  one is sent once more on a new connection: CloudFront closes idle keep-alive connections, and the first busiest-hour
  run in stage 1 lost 653 requests that way, none of which reached Serena (added November 3, 2026).
- **The records come first.** Run the `./serena aws etl … --sizes …` command the dry run prints before replaying; again
  after a deploy, pause or resume (the simulator forgets its records). If its servable list check fails on the delta
  threshold (the last updated refresh had other records), override the threshold on that refresh on the admin app's
  Refreshes page; it's then updated from the same list, and the fake ETL needn't run again.
- **Put it back before `./serena aws test`.** The replay's records stay Serena's servable list, so the AWS tests' own
  refresh (20 rows) fails on the delta threshold. Run `./serena aws etl pahma` and override the threshold on that
  refresh first (checklist section 32, "After a replay").
- **Cold and warm.** Serena's cache is kept by Blob CSID, so the first replay over a set of records is cold (every
  file's first request is a miss, as at a cutover) and a replay over the same records again is warm (only hits). For
  another cold replay, give `--first-row` past the records used so far (say 10000, then 20000): the dry run then
  prints the fake ETL command with the same `--first-row`, which makes new records Serena hasn't cached.
- **What it reports** (D287): requests sent, how many went more than a second late (the Mac or the network couldn't
  keep up), the answers by status and by what Serena did (`served`: a 302 to a stored file; `unavailable`: a 302 to
  the unavailable image, as when the records aren't servable; `no answer`: none, even after one more try), how many
  were sent again on a new connection (`retried`), the latency of all answers and of the served ones,
  then, after 3 minutes, the web and worker services' CPU and memory from CloudWatch, a minute at a time (average,
  busiest minute, highest), as a percentage of the task size. On personal-dev (one web task of 1 vCPU and 2 GB),
  September 2026's busiest minute cold took about 25% CPU in the busiest minute and 7% memory (checklist section 32).
- **Tested** in `backend/tests/test_replay.py` (CI's backend job), with logs made up in the tests.

## Packages

Pinned with hashes in `requirements.txt`; change `requirements.in` and run
`pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in`. The HTTP checks use
Python's own `urllib`, so the suite needs nothing beyond pytest and Selenium.
