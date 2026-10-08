# Serena testing to do (checks by hand)

These are things Claude couldn't test, to be checked by hand. The list was started on October 8, 2026, when the
repository was set up. Tick an item when it's done, and note anything odd under it.

Change this file through pull requests, like `docs/design.md`. When a pull request needs checks by hand, add a
section here in the same pull request.

## 1. A replaced image isn't fetched on a cache miss (10 minutes, once the cache-miss path is built)

Serena must never serve an orphaned Blob. A Blob CSID can still be in the museum's public Solr core after its image
was replaced in CollectionSpace (replacing an image creates a new Blob), until the ETL runs again. On a cache miss,
Serena GETs the Media record and checks that its `blobcsid` still matches.

Set up, on a test tenant: pick a Blob CSID that is in the museum's public core and not yet in Serena's cache. After
the ETL has run, replace the image on its Media record in CollectionSpace. Don't wait for the next ETL run.

- [ ] Request the old Blob at its legacy URL (`…/<tenant>/imageserver/blobs/<blob CSID>/derivatives/<size>/content`).
  Expect a redirect to the museum's placeholder image, not the old image and not an error.
- [ ] In Serena's log, expect the Media record check for that Blob and no fetch of the Blob's content from
  CollectionSpace.
- [ ] Expect nothing new in Serena's bucket for that Blob.
