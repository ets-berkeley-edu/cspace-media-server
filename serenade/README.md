# serenade: Serena's headless test suite

Automated checks of Serena on the local stack: plain HTTP checks of what Serena serves, and Selenium browser checks of
the admin app, written as the team writes them for BOA (bea), Damien (mrsbaylock) and Diablo (xena): pytest, with a
page object per screen in `pages/` and the tests in `tests/`. Never against QA or production: the tests sign in,
recall files and switch the CollectionSpace simulator's outage on.

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
| `tests/test_requests.py` | Past requests, T54 to T64: the page and its range, the summary boxes, the table's lines and columns (no signed-link parameters), Media URL lines, filters, ranges, the CSV export, another museum's page, opening a file from a line (sections 16, 19 to 21, 23) |
| `tests/test_settings.py` | Settings, T29 to T35: BAMPFA's page and its default values, a value out of bounds, a change and the default again (with its audit entry), a change that raises an alert, the audit retention's choices, Save without a reason; PAHMA's placeholder image's Media record (sections 15, 19, 21, 22) |
| `tests/test_audit.py` | Audit log, T37 to T39: UCJEPS's refresh actions and the ETL's calls, BAMPFA's CSV export, PAHMA's By column, links and shortened values (sections 14, 15, 20) |
| `tests/test_layout.py` | Layout and navigation, T48 to T53, on PAHMA: page titles, the menu's groups, the bell and the gear, keeping your place on Past requests (back by the link, by the browser's Back, and in a new tab), back links and none from the menu, the Overview's links, column help by the pointer and the keyboard (sections 15, 16, 18, 20, 21) |
| `tests/test_sign_in.py` | Sign-in and sessions, T40 to T46: the five museums on the sign-in page, signing in and out, an account without the role, two museums at once, the role per museum, the API documentation page (read-only, nothing in the console about the Content-Security-Policy), and, last of the whole run, "Sign everyone out" ending another browser's session (sections 12, 20) |
| `tests/test_unreachable.py` | T47, last of all: with Serena's web service stopped (the test stack's web container), "Sign everyone out" and Media look up say "Serena can't be reached right now. Try again in a minute. (502)", and the dialog stays open; Serena is started again however the test ends (sections 20, 21) |
| `tests/test_alerts.py` | Alerts, T23 to T25, on UCJEPS: a failed check's alert on the bell, the banner and the Alerts page; its text, with its refresh ID as a link; acknowledging (sections 14, 18, 20). T82 and T83, on BAMPFA (two alerts from a setting changed and put back): All · Waiting, the waiting rows' bar, the banner and the bell opening Waiting; Acknowledge all, its dialog's list and links, and none waiting after (section 28) |
| `tests/test_refreshes.py` | Refreshes, T16 to T21: Past refreshes, Start a refresh's missing fields, and on UCJEPS a failed check's page, overriding the threshold, an admin refresh repairing a failed one, sorting and paging 30 refreshes (sections 11, 14, 15, 21) |
| `tests/test_lookup_and_recalls.py` | The pilot, T2 to T6: Media look up, a recall and its cancellation, CollectionSpace unreachable (sections 11, 17, 19). Recalls, T74 to T81: the preview (what Serena finds, paths and URLs, more than 12 CSIDs and a text file, an already recalled record), a missing reason, a recall's row and its files, Past requests and the audit log, and the recall's alert, T26 (sections 17 to 21). Media look up, T65 to T73: every size of a Media CSID, the comparison with CollectionSpace, the page's address, paths it forgives and refuses, an unknown CSID, the sizes box, and a record changed in CollectionSpace (off the web, replaced, soft-deleted), then put back (sections 17, 19 to 21, 23) |

## Packages

Pinned with hashes in `requirements.txt`; change `requirements.in` and run
`pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in`. The HTTP checks use
Python's own `urllib`, so the suite needs nothing beyond pytest and Selenium.
