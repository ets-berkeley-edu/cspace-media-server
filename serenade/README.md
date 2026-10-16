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

- **The dataset** (`dataset.py`) is a PAHMA daily refresh and a Cinefiles one (for its PDFs) by the fake ETL, built
  once per run. Its CSIDs are the same
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
  `conftest.py`'s `FILE_ORDER` (serving first; a new file goes where its changes belong).

## Where the tests come from

`docs/testing-checklist.md` says what to check; the test inventory (`serena-test-inventory.xlsx`, kept by Richard)
lists each automated check, by feature, with the checklist section and step it comes from, whether it's HTTP or a
browser check, its data effect, and whether the backend's own tests already cover it. Each test's name starts with
its inventory ID (`test_t3_…`), and its docstring names the checklist steps.

| Tests | What |
| --- | --- |
| `tests/test_serving.py` | Serving, T1, T7 to T9, T14, T15 (plain HTTP): a served image from the stored copy, Cinefiles' public and restricted PDFs, requests Serena refuses, a catalog card, Media URLs (sections 11, 16, 17, 21, 23) |
| `tests/test_sign_in.py` | Signing in, and an account without the role (checklist section 12) |
| `tests/test_lookup_and_recalls.py` | The pilot, T2 to T6: Media look up, a recall and its cancellation, CollectionSpace unreachable (sections 11, 17, 19). Recalls, T74 to T81: the preview (what Serena finds, paths and URLs, more than 12 CSIDs and a text file, an already recalled record), a missing reason, a recall's row and its files, Past requests and the audit log (sections 17 to 21). Media look up, T65 to T73: every size of a Media CSID, the comparison with CollectionSpace, the page's address, paths it forgives and refuses, an unknown CSID, the sizes box, and a record changed in CollectionSpace (off the web, replaced, soft-deleted), then put back (sections 17, 19 to 21, 23) |

## Packages

Pinned with hashes in `requirements.txt`; change `requirements.in` and run
`pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in`. The HTTP checks use
Python's own `urllib`, so the suite needs nothing beyond pytest and Selenium.
