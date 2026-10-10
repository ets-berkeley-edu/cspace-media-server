# Serena: the new CollectionSpace media server

Serena is the new media server for UC Berkeley's CollectionSpace museums: BAMPFA, the Botanical Garden, Cinefiles,
PAHMA and UCJEPS. It replaces the legacy `imageserver` Django webapp in
[cspace-webapps-common](https://github.com/cspace-deployment/cspace-webapps-common).

It's being built, one pull request at a time. So far it parses the legacy imageserver paths, decides from its
records in DynamoDB whether each file may be served, and takes each night's Blob-to-Media file through its ETL API.
Serving the files themselves comes later. The design is `docs/design.md`.

## What it will do

- Serve the images, 3D files and documents that the museums' public portals
  ([Glimmer](https://github.com/cspace-deployment/glimmer)) and other clients link to, at the same addresses the
  legacy imageserver uses, so they keep working unchanged.
- Serve only what the nightly Solr ETL ([cspace-solr-ucb](https://github.com/cspace-deployment/cspace-solr-ucb))
  lists as public, unless it has been taken down in Serena. Anything else gets the museum's unavailable image.
- Take in each night's ETL output through its ETL API, in step with the public Solr core's load.
- Fetch a file from CollectionSpace the first time it's asked for, keep it in Serena's own private storage, and
  serve it from there through short-lived signed links.
- Add a watermark for the museums that want one.
- Give admins a web app to follow nightly runs and alerts, see why a file is or isn't served, take files down and
  change settings.

## Layout

| Path | What |
| --- | --- |
| `docs/design.md` | The design document |
| `docs/testing-checklist.md` | Checks to do by hand |
| `docs/api/etl-v1.json` | The ETL API's OpenAPI description, generated from the code |
| `backend/` | The Python 3.11 app (`serena/`), its tests and its pinned requirements |
| `backend/serena/static/` | The unavailable image (`unavailable.svg`, the legacy imageserver's `404.svg`) |
| `backend/serena/museums/` | Each museum's configuration: derivatives served, restricted-image Blob, starting settings |
| `admin/` | The admin web app: Vue, TypeScript and Vuetify (to come) |
| `deploy/` | The AWS deployment: Terraform and the production image (to come) |
| `.github/workflows/` | CI (`ci.yml`), the weekly dependency audit (`audit.yml`) and the secret scan (`security.yml`) |

## License

Copyright ©2026 The Regents of the University of California. Serena carries the same license as UC Berkeley RTL's
other applications, such as BOA: free to use, copy, modify and distribute for educational, research and not-for-profit
purposes; commercial use needs a license from UC Berkeley's Office of Technology Licensing. See `LICENSE`.
