# Serena: the new CollectionSpace media server

Serena is the new media server for UC Berkeley's CollectionSpace museums: BAMPFA, the Botanical Garden, Cinefiles,
PAHMA and UCJEPS. It replaces the legacy `imageserver` Django webapp in
[cspace-webapps-common](https://github.com/cspace-deployment/cspace-webapps-common).

It's being built, one pull request at a time. So far it parses the legacy imageserver paths, decides from its records in
DynamoDB whether each file may be served, and takes each day's servable list through its ETL API: its worker
checks it and updates servability from it, and its watchdog raises alerts. On a cache miss it checks the Media record, fetches the file
from CollectionSpace, checks it and stores it; every file is served through a signed CloudFront link, and restricted
PDFs only on a portal's signed link. The design is `docs/design.md`.

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

With Docker installed: `./serena up`, then `./serena etl pahma` to run a daily refresh through the ETL API. The command prints
a few files to open in your browser, at http://localhost:8300. The admin app is at http://localhost:5373/admin/:
sign in as `admin`, password `admin` (the simulator's synthetic account). The stack uses a CollectionSpace simulator and
moto in place of AWS, so it needs no accounts or keys. `docs/testing-checklist.md` walks through the admin app's
pages locally (the Past requests page reads a log file inside the app's container, in place of CloudWatch; the recall
form's lookups and thumbnails, and Media look up's view of CollectionSpace, come from the CollectionSpace simulator). In the admin app, the bell at the top right
opens the alerts and the gear opens the museum's settings. `./serena help` lists the rest.

## License

Copyright ©2026 The Regents of the University of California. Serena carries the same license as UC Berkeley RTL's
other applications, such as BOA: free to use, copy, modify and distribute for educational, research and not-for-profit
purposes; commercial use needs a license from UC Berkeley's Office of Technology Licensing. See `LICENSE`.
