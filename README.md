# Serena: the new CollectionSpace media server

Serena is the new media server for UC Berkeley's CollectionSpace museums: BAMPFA, the Botanical Garden, Cinefiles,
PAHMA and UCJEPS. It replaces the legacy `imageserver` Django webapp in
[cspace-webapps-common](https://github.com/cspace-deployment/cspace-webapps-common).

It's being built, one pull request at a time, and runs locally today; the AWS deployment comes next. It answers the
legacy imageserver's addresses (by Blob CSID or by Media CSID) and decides from its records whether each file may be
served. It takes each day's servable list through its ETL API: its worker checks the list and updates servability from
it, and its watchdog raises alerts. On a cache miss it checks the Media record, fetches the file from CollectionSpace,
checks it and stores it; every file is served through a signed CloudFront link, and restricted PDFs only on a portal's
signed link. The admin app follows the daily refreshes and alerts, shows what Serena served and couldn't serve
(Past requests), explains any one file (Media look up), recalls files, and changes each museum's settings, the
placeholder image's Media record among them. Watermarking (the Botanical Garden) is not built yet. The design is
`docs/design.md`.

## What it will do

- Serve the images, 3D files and documents that the museums' public portals
  ([Glimmer](https://github.com/cspace-deployment/glimmer)) and other clients link to, at the same addresses the
  legacy imageserver uses, so they keep working unchanged.
- Serve only what the daily Solr ETL ([cspace-solr-ucb](https://github.com/cspace-deployment/cspace-solr-ucb))
  lists as public, unless it has been recalled in Serena. Anything else gets the museum's unavailable image.
- Take in each daily servable list through its ETL API, in step with the public Solr core's refresh.
- Fetch a file from CollectionSpace the first time it's asked for, keep it in Serena's own private storage, and
  serve it from there through short-lived signed links.
- Add a watermark for the museums that want one.
- Give admins a web app to follow daily refreshes and alerts, see what Serena served and couldn't serve and why, recall
  files and change settings.

## Layout

| Path | What |
| --- | --- |
| `docs/design.md` | The design document |
| `docs/testing-checklist.md` | Checks to do by hand |
| `docs/api/etl-v1.json` | The ETL API's OpenAPI description, generated from the code |
| `backend/` | The Python 3.11 app (`serena/`), its tests and its pinned requirements |
| `backend/serena/static/` | The unavailable image (`unavailable.svg`, the legacy imageserver's `404.svg`) |
| `backend/fakecspace/` | A CollectionSpace simulator for tests and local development, with synthetic files |
| `backend/serena/museums/` | Each museum's configuration: derivatives served, placeholder image, kinds with signed access, starting settings |
| `admin/` | The admin web app: Vue, TypeScript and Vuetify, served under `/admin`, its API under `/admin/v1` |
| `serenade/` | The admin app's Selenium tests (`./serena ui`) |
| `backend/devtools/` | Local-only tools: seeding the AWS stand-in, and a fake ETL |
| `docker-compose.yml`, `serena` | The local stack and its script (`./serena help`) |
| `deploy/` | The AWS deployment: Terraform and the production image (to come) |
| `.github/workflows/` | CI (`ci.yml`), the weekly dependency audit (`audit.yml`) and the secret scan (`security.yml`) |

## Run it locally

You need a Mac (or Linux) with [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and
running, and `git`. Nothing else: the stack uses a CollectionSpace simulator and [moto](https://github.com/getmoto/moto)
in place of AWS, so it needs no accounts, keys or `.env` file, and it never talks to AWS or a real CollectionSpace.

```
git clone https://github.com/ets-berkeley-edu/cspace-media-server.git
cd cspace-media-server
./serena up
./serena etl pahma
```

- `./serena up` builds and starts the stack, which takes a few minutes the first time. It prints the branch and commit
  it built; the admin app shows them in its header.
- `./serena etl pahma` runs a daily refresh for PAHMA through the ETL API, with synthetic records, and prints a few
  file addresses to open in your browser, at http://localhost:8300. Any museum works: `bampfa`, `botgarden`,
  `cinefiles`, `ucjeps`.
- The admin app is at http://localhost:5373/admin/. It's ready about a minute after `./serena up` finishes (its
  container installs its packages first): if the page doesn't load, wait and reload. Sign in with one of the
  simulator's synthetic accounts, each with its name as its password:

  | Account | Password | Serena admin of |
  | --- | --- | --- |
  | `admin` | `admin` | every museum |
  | `pahma-admin` | `pahma-admin` | PAHMA only |
  | `viewer` | `viewer` | none (sign-in is refused) |

  In the admin app, the bell at the top right opens the alerts and the gear opens the museum's settings.
- `./serena down` stops it and forgets everything (moto keeps nothing). `./serena down && ./serena up` starts afresh.
- `./serena help` lists the other commands (`logs`, `status`, `smoke`, `urls`, `ui`).

**If something's in the way.**
- *A port is taken.* The stack uses ports 8300 (Serena), 5373 (the admin app), 8380 (the simulator) and 9300 (moto).
  Set `SERENA_PORT`, `SERENA_ADMIN_PORT`, `SERENA_SIM_PORT` or `SERENA_MOTO_PORT` to move one, for example
  `SERENA_ADMIN_PORT=5374 ./serena up`. It runs beside the BMU's stack.
- *`./serena etl` says the servable list check failed on the delta threshold.* A refresh with different `--rows`
  changed too many rows at once, which is the check doing its job. Start afresh: `./serena down && ./serena up`.
- *It isn't up.* `./serena logs web` (or `worker`, `admin`, `fakecspace`) shows why.
- `./serena ui` (the admin app's Selenium tests) also needs Python 3.11 and Chrome.

## Trying it out

`docs/testing-checklist.md` holds the checks done by hand. Many need the AWS QA environment ("in QA" in their title),
which doesn't exist yet. These run on the local stack and make a tour of what Serena does today; each section says how
to start:

| Section | What |
| --- | --- |
| 11 | The local stack: refreshes for several museums, a PDF, a restricted PDF, a failed refresh (skip its last step, the image digests) |
| 12 | Signing in to the admin app, and the sign-ins it refuses |
| 14 | Refreshes and alerts |
| 15 | Settings, sorting and the audit log |
| 16 | Past requests |
| 17 | Recalls and Media look up |
| 19 | Media look up beside CollectionSpace, and the file dialogs |
| 22 | The placeholder image's Media record |
| 23 | Media URLs |

Sections 18, 20 and 21 check later changes to the same pages, step by step.

**Reporting a problem.** Open a [GitHub issue](https://github.com/ets-berkeley-edu/cspace-media-server/issues) with:
the checklist section and step (or what you were doing), what you expected, what happened, and the branch and commit
from the admin app's header (or `./serena up`'s output). A screenshot helps. The stack holds only synthetic data, so a
screenshot or log lines from it are safe to attach; never attach anything from a real CollectionSpace.

## Changing the code

Each change is a pull request from a feature branch; CI runs the checks below. With Python 3.11 and Node 22:

```
cd backend && python3.11 -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt && pip install --no-deps --no-build-isolation -e .
ruff check . && mypy && pytest -q

cd admin && npm ci && npm run lint && npm run typecheck && npm test
```

A pull request that changes what someone could check by hand adds a section to `docs/testing-checklist.md`, and one
that changes a decision updates `docs/design.md`.

## License

Copyright ©2026 The Regents of the University of California. Serena carries the same license as UC Berkeley RTL's
other applications, such as BOA: free to use, copy, modify and distribute for educational, research and not-for-profit
purposes; commercial use needs a license from UC Berkeley's Office of Technology Licensing. See `LICENSE`.
