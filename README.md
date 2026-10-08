# Serena: the new CollectionSpace media server

Serena is the new image server for UC Berkeley's CollectionSpace museums: BAMPFA, the Botanical Garden, Cinefiles,
PAHMA and UCJEPS. It replaces the legacy `imageserver` Django webapp in
[cspace-webapps-common](https://github.com/cspace-deployment/cspace-webapps-common).

Nothing is built yet. The design document will be `docs/design.md`; until then, `CLAUDE.md` holds the rules the
design must keep.

## What it will do

- Serve the images that the museums' public portals ([Glimmer](https://github.com/cspace-deployment/glimmer)) show,
  at the same addresses the legacy imageserver uses, so the portals keep working unchanged.
- Serve only what the nightly Solr ETL ([cspace-solr-ucb](https://github.com/cspace-deployment/cspace-solr-ucb)) has
  made public, unless the image has been taken down in Serena. Anything else gets the museum's placeholder image.
- Fetch an image from CollectionSpace the first time it's asked for, keep it in Serena's own private storage, and
  serve it from there through short-lived signed links.
- Add a watermark for the museums that want one.

## Layout

| Path | What |
| --- | --- |
| `docs/testing-checklist.md` | Checks to do by hand |
| `docs/design.md` | The design document (to come) |
| `backend/` | The Python 3.11 app, its tests and its pinned requirements (to come) |
| `deploy/` | The AWS deployment: Terraform and the production image (to come) |
| `.github/workflows/` | CI (`ci.yml`), the weekly dependency audit (`audit.yml`) and the secret scan (`security.yml`) |

## License

Copyright ©2026 The Regents of the University of California. Serena carries the same license as UC Berkeley RTL's
other applications, such as BOA: free to use, copy, modify and distribute for educational, research and not-for-profit
purposes; commercial use needs a license from UC Berkeley's Office of Technology Licensing. See `LICENSE`.
