# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Serena, the new image server for UC Berkeley's CollectionSpace museums (BAMPFA, the Botanical Garden, Cinefiles,
PAHMA, UCJEPS), replacing the legacy `imageserver` Django webapp in `cspace-webapps-common`. It serves the images
the museums' public Glimmer portals show, deciding what may be served from the nightly Solr ETL's output. Nothing is
built yet: the design document comes first (`docs/design.md`, in its own pull request). `README.md` describes what it
will do.

## Rules that are not negotiable

- **Serena never reads CollectionSpace's Postgres.** Only the nightly Solr ETL
  (`cspace-deployment/cspace-solr-ucb`) does. Serena uses the CollectionSpace API, with a read-only service account
  per museum: HTTP Basic, its password a secret in AWS Secrets Manager, never stored anywhere else and never logged.
- **The ETL's nightly output is the first source of what may be served.** A Blob CSID is servable only if it appears
  in the museum's public Solr core (`blob_ss`, `card_ss`, the primary image field, and the audio, video and 3D CSID
  fields) and has no active takedown in Serena. Takedowns are the only override. Serena never changes the ETL's
  output.
- **Serena keeps serving the legacy URLs the Glimmer portals use**
  (`…/<tenant>/imageserver/blobs/<blob CSID>/derivatives/<size>/content`). Anything Serena won't serve gets the
  museum's placeholder image.
- **Never serve an orphaned Blob.** On a cache miss, GET the Media record and confirm its `blobcsid` still matches
  the Blob asked for. The Media CSID comes from the ETL (the change in Jira CSW-1027).
- **Cached images are never deleted.** A takedown stops serving them; it doesn't remove them.
- **Never read `.env` files, and never put a login, token, key or personal data in the repo, a test or a chat.**
- **Never commit to `main`.** Work on a feature branch and open a pull request. Before committing to a branch,
  `git fetch` and check whether it was already pushed or merged; never amend or rebase a pushed branch.
- The repository owner runs `git push`, `gh pr create` and every AWS command himself: give him the exact commands
  instead of running them.

## Commands

Nothing to run yet. When the code arrives it follows the BMU (`ets-berkeley-edu/cspace-bulk-media-uploader`): Python
3.11 (`.python-version`) in `backend/`, installed only from hash-pinned requirements files generated from
`backend/pyproject.toml` by `backend/pin-requirements.sh` and never edited by hand.

CI (`.github/workflows/ci.yml`) will run, in `backend/`, `ruff check .`, `mypy` and `pytest -q` (the `backend`
job), and a `dependencies` job: the requirements files are in step and `pip-audit` finds no known vulnerabilities.
Until `backend/pyproject.toml` exists, both jobs report "nothing to check yet" and pass; the pull request that adds
it removes those guard steps (in `audit.yml` too). `.github/workflows/audit.yml` repeats the audit every Monday.

A pull request that changes only documentation (`docs/`, `*.md`, `LICENSE`, issue/PR templates) skips `backend`;
the `changes` job decides, and a skipped job counts as passing. `dependencies` and
`.github/workflows/security.yml` (`gitleaks` over the whole history) run on every pull request and push, whatever
changed: never add a path filter or a docs-only condition to them. A gitleaks match that isn't a secret goes in
`.gitleaksignore`, by fingerprint, with a comment saying why. Actions are pinned by commit SHA with the version in a
comment; Dependabot (`.github/dependabot.yml`, weekly, grouped) moves both. Its pip and Docker entries are
commented out until there are files for them to read.

While working, run only the test files a change affects. Run the full suite once before each commit.

## Documents kept in step with the code

- **Design document** — `docs/design.md` (to come). Change it in the same pull request as the code it describes.
- **Testing checklist** — `docs/testing-checklist.md`: the checks to do by hand. A pull request that needs checks
  by hand adds a section to it.
- **README.md** — what Serena does and the repository's layout.
- Update the documents once per pull request, not alongside each change.

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
