# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Serena, the new media server for UC Berkeley's CollectionSpace museums (BAMPFA, the Botanical Garden, Cinefiles,
PAHMA, UCJEPS), replacing the legacy `imageserver` Django webapp in `cspace-webapps-common`. It serves the images and
documents that the museums' public portals (Glimmer, and any other client of the public Solr cores) link to, deciding
what may be served from the nightly Solr ETL's output, and has an admin web app. It is being built one pull request
at a time, following the plan; the design is `docs/design.md`. `README.md` describes what it does.

## Rules that are not negotiable

- **Serena never reads CollectionSpace's Postgres.** Only the nightly Solr ETL
  (`cspace-deployment/cspace-solr-ucb`) does. Serena uses the CollectionSpace API, with a read-only service account
  per museum: HTTP Basic, its password a secret in AWS Secrets Manager, never stored anywhere else and never logged.
  Every call to CollectionSpace goes through the Media service, by Media CSID.
- **The ETL's nightly output is the first source of what may be served.** Each night the ETL hands Serena, through
  Serena's ETL API, a Blob-to-Media file listing every Blob in the museum's public Solr core (`blob_ss`, `card_ss`,
  the primary image field, the audio, video and 3D CSID fields, and `pdf_ss`) with its Media CSID, kind and access. A
  Blob CSID is servable only if that file lists it as public, its kind is one Serena serves, and its Media record has
  no active takedown in Serena. Takedowns are the only override. Serena never changes the ETL's output, and never
  reads Solr.
- **Serena depends on the public core, not on Glimmer.** Glimmer is one client of the public core; assume there are
  others. Changes on Glimmer's side follow Glimmer's own timeline.
- **Serena keeps serving the legacy URLs its clients use**
  (`…/<tenant>/imageserver/blobs/<blob CSID>/derivatives/<size>/content`, `…/blobs/<blob CSID>/content`, and
  Cinefiles' PDF links with a `linked_pdf:` or `inline_pdf:` suffix). Anything Serena won't serve gets the museum's
  unavailable image (not to be confused with the restricted-image Blob, a real Blob that Serena serves).
- **The light check on a cache miss.** GET the Media record (its Media CSID comes from the ETL's file) and fetch only
  if it exists and isn't soft-deleted; then fetch through the Media service, which returns the record's current file.
  Never compare the record's `blobCsid` with the Blob asked for.
- **Cached files are never deleted.** A takedown stops serving them; it doesn't remove them.
- **Never read `.env` files, and never put a login, token, key or personal data in the repo, a test or a chat.**
- **No personal data in logs.** The PDF link suffix carries a visitor's email address: strip it before anything is
  logged or recorded, and never forward it. Never log the signature on a signed PDF link, and don't log or record the
  reader's `uid` unless the design says so.
- **The ETL decides what is restricted, per museum.** Never put a museum's rule (an access code, a sensitivity flag)
  in Serena: it acts only on the nightly file's listing and `access` value.
- **Restricted files only with a valid signed link,** for a kind the museum allows signed access to (see "Restricted
  files" in the design). Fail closed: a missing, malformed, expired or unmatched signature gets the unavailable image.
- **Don't describe security weaknesses of the legacy imageserver in this repository** (it's public). Describe Serena's
  own rules instead.
- **Never commit to `main`.** Work on a feature branch and open a pull request. Before committing to a branch,
  `git fetch` and check whether it was already pushed or merged; never amend or rebase a pushed branch.
- The repository owner runs `git push`, `gh pr create` and every AWS command himself: give him the exact commands
  instead of running them.

## Commands

The code follows the BMU (`ets-berkeley-edu/cspace-bulk-media-uploader`): Python 3.11 (`.python-version`) in
`backend/`, the package `serena/` with its tests in `tests/`. Install only from the hash-pinned requirements files,
which `backend/pin-requirements.sh` generates from `backend/pyproject.toml` (and `requirements-tools.in`); never edit
them by hand.

```sh
cd backend
pip install --require-hashes -r requirements-dev.txt
pip install --no-deps --no-build-isolation -e .
ruff check . && mypy && pytest -q          # what CI runs
pytest -q tests/test_logs.py               # one test file
python -m serena.etl_api --openapi > ../docs/api/etl-v1.json   # after changing the ETL API
python -m serena.worker                    # the worker (preflight and apply); same settings as the app
uvicorn fakecspace.app:app --port 8180    # the CollectionSpace simulator (synthetic files and account)
```

To run the app locally before Docker Compose exists (pull request 10), point it at DynamoDB Local, never at AWS:
`SERENA_TENANTS='{"pahma": "http://localhost:8180"}' SERENA_DYNAMODB_ENDPOINT=http://localhost:8000
SERENA_CREATE_TABLES=true uvicorn serena.main:app --no-access-log`. Serena refuses to create tables without a
DynamoDB endpoint.

To change a dependency, edit `pyproject.toml` and run `pin-requirements.sh` with the tools installed
(`pip install --require-hashes -r requirements-tools.txt`). Each museum's configuration is
`backend/serena/museums/<tenant>.yaml`.

The admin web app (Vue, TypeScript, Vuetify) will go in `admin/` (the BMU's `frontend/` is the model), with npm
dependencies pinned by its lockfile and installed with `npm ci`; CI will add its lint, type check, unit tests and
`npm audit`.

CI (`.github/workflows/ci.yml`) runs, in `backend/`, `ruff check .`, `mypy` and `pytest -q` (the `backend`
job), and a `dependencies` job: the requirements files are in step and `pip-audit` finds no known vulnerabilities.
`.github/workflows/audit.yml` repeats the audit every Monday.

A pull request that changes only documentation (`docs/`, `*.md`, `LICENSE`, issue/PR templates) skips `backend`;
the `changes` job decides, and a skipped job counts as passing. `dependencies` and
`.github/workflows/security.yml` (`gitleaks` over the whole history) run on every pull request and push, whatever
changed: never add a path filter or a docs-only condition to them. A gitleaks match that isn't a secret goes in
`.gitleaksignore`, by fingerprint, with a comment saying why. Actions are pinned by commit SHA with the version in a
comment; Dependabot (`.github/dependabot.yml`, weekly, grouped) moves both. Its Docker entry is commented
out until there is a Dockerfile.

While working, run only the test files a change affects. Run the full suite once before each commit.

## Documents kept in step with the code

- **Design document** — `docs/design.md`. Change it in the same pull request as the code it describes.
- **API documentation** — `docs/api/etl-v1.json`: the ETL API's OpenAPI description generated from the code; a test
  (so CI) fails when it isn't current.
- **Testing checklist** — `docs/testing-checklist.md`: the checks to do by hand. A pull request that needs checks
  by hand adds a section to it.
- **README.md** — what Serena does and the repository's layout.
- Update the documents once per pull request, not alongside each change.

### Keeping the design document current

- `docs/design.md` on `main` is the only current design. The earlier Google Drive proposals are history. If notes,
  memory or a conversation disagree with it, the document wins: point out the conflict instead of choosing.
- Before any work, `git fetch` and read the current `docs/design.md`. If the owner edited it, build on his version;
  never overwrite it.
- A decision made before there is code goes in on a docs-only branch once it's settled; small ones can be grouped.
  A code change updates the document in the same pull request.
- A settled open question moves out of "Open questions and findings" into the section it belongs in, with the date it
  was decided (for example "decided October 8, 2026").
- Before a pull request that includes code, check that the document matches the code, and list any differences in
  the pull request description.
- The repository is public: live security problems, hostnames, account details and anything else sensitive stay out
  of the document.

## License

Copyright ©2026 The Regents of the University of California. `LICENSE` is the same license as UC Berkeley RTL's
other applications (BOA, Damien, Diablo, the BMU): free to use, copy, modify and distribute for educational,
research and not-for-profit purposes; commercial use needs a license from UC Berkeley's Office of Technology
Licensing.

- Don't change `LICENSE`'s text. The README's License section refers to it (and so will `license` in
  `backend/pyproject.toml`); keep them in step if it ever changes.
- Source files carry no license header; don't add one.
- Don't copy code into the repo from a source whose license is incompatible (GPL and the like). A new package must
  have a permissive license (MIT, BSD, Apache 2.0, ISC or similar).
