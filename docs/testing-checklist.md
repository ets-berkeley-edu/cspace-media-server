# Serena testing to do (checks by hand)

These are things Claude couldn't test, to be checked by hand. The list was started on October 8, 2026, when the
repository was set up. Tick an item when it's done, and note anything odd under it.

Change this file through pull requests, like `docs/design.md`. When a pull request needs checks by hand, add a
section here in the same pull request.

## 1. A replaced image is served on a cache miss (10 minutes, once the cache-miss path is built)

Replacing a Media record's image creates a new Blob. Until the next nightly update, clients still request the old
Blob CSID. On a cache miss Serena checks only that the Media record exists and isn't deleted, then fetches through the
Media service, which returns the record's current image (decided October 9, 2026).

Set up, on a test tenant: pick a Blob CSID that the last applied Blob-to-Media file lists as public and that isn't in
Serena's cache yet. After the nightly update, replace the image on its Media record in CollectionSpace. Don't wait for
the next nightly update.

- [ ] Request the old Blob at its legacy URL (`…/<tenant>/imageserver/blobs/<blob CSID>/derivatives/<size>/content`).
  Expect the new image, not the old one and not an error.
- [ ] In Serena's log, expect the light check for that Media record, then a fetch through the Media service
  (`media/<media CSID>/blob/derivatives/<size>/content`), and no request by the old Blob CSID.
- [ ] After the next nightly update, expect the old Blob's URL to get the museum's unavailable image, and the new
  Blob's URL to get the new image.

## 2. A soft-deleted Media record isn't served on a cache miss (10 minutes, once the cache-miss path is built)

The Media service returns soft-deleted Media records and their files, so Serena's light check must catch them.

Set up, on a test tenant: pick a Blob CSID that the last applied file lists as public and that isn't cached, and
soft-delete its Media record in CollectionSpace.

- [ ] Request the Blob at its legacy URL. Expect the museum's unavailable image.
- [ ] In Serena's log, expect the light check finding the record deleted, the reason recorded, and no fetch.
- [ ] Expect nothing new in Serena's bucket for that Blob.

## 3. A Media record with no image gets the unavailable image (10 minutes, once the cache-miss path is built)

Set up, on a test tenant: pick a Blob CSID that the last applied file lists as public and that isn't cached, and
remove the image from its Media record in CollectionSpace.

- [ ] Request the Blob at its legacy URL. Expect the museum's unavailable image, not an error.
- [ ] In Serena's log, expect the light check to pass and the Media service's fetch to fail, with that reason
  recorded. Note the status CollectionSpace returned.

## 4. The ETL API with each museum's real token (15 minutes, once Serena is deployed to QA)

Serena's tests use tokens made up at run time and moto in place of AWS. These checks need the QA deployment, each
museum's token secret in Secrets Manager, and a call from the ETL server (the only place the load balancer accepts
`/etl/` from).

- [ ] From the ETL server, `GET /etl/v1/ping` with each museum's token. Expect `200` and `{"museum": "<that museum>"}`.
- [ ] With one museum's token on another museum's path (`POST /etl/v1/museums/<other>/runs`), expect `403`.
- [ ] Start a run, then upload a real night's Blob-to-Media file (gzip). Expect `received`, with the row count the ETL
  reports, and the file in the museum's bucket under `blob-media/<run ID>/`, encrypted with the museum's KMS key.
- [ ] Rotate one museum's token (new one in `current`, old one in `previous`). Within 5 minutes both work; after
  `previous` is cleared, only the new one.
- [ ] In CloudWatch, search Serena's logs for the tokens: expect no match.

## 5. A whole night through the worker, in QA (30 minutes, once Serena and the ETL change are in QA)

The tests run whole nights against moto with synthetic files. These checks use a real night's file, DynamoDB and S3.

- [ ] Run one museum's nightly job against QA. Expect the run to go `started`, `received`, `preflighting`, `ready`,
  `solr_loaded`, `applying`, `applied`, and the servability table to hold exactly the file's rows for that museum.
- [ ] Note how long the preflight and the apply took for the largest museum (PAHMA), and the worker's memory.
- [ ] The next night, expect the preflight's added, removed and changed counts to match a diff of the two files.
- [ ] Stop the worker's task while it applies a night; a new task starts. Expect the apply to start again after about
  5 minutes and end `applied`, with the table matching the file.
- [ ] Upload a file with 10% of the rows removed: expect `preflight_failed`, the change as a share, and the table
  unchanged.

## 6. Alerts by email, in QA (15 minutes, once Serena and its SNS topic are in QA)

The tests use moto's SNS. These checks need the real topic and the team's mailing list subscribed to it.

- [ ] Set a museum's deadline a few minutes ahead in the admin app (or its Settings item) and run no night for it.
  Expect one email to the mailing list within 5 minutes after the deadline, naming the museum, the night and what
  to do, and one alert record. Expect no second email on the next passes.
- [ ] Make a night's preflight fail (upload a file with a bad kind). Expect a "preflight failed" email with the run ID
  and the reason.
- [ ] Check the email has no personal data and no link with a token or signature in it.
- [ ] Try to unsubscribe from the email's link without signing in to AWS: expect it to be refused (the subscription
  requires authentication to unsubscribe).

## 7. Signed URLs through CloudFront, in QA (15 minutes, once CloudFront is set up in pull request 18)

The tests check the signature against a key made at run time and serve files through the local stand-in.

- [ ] Request a cached image at its legacy URL. Expect a 302 to `<CloudFront>/<tenant>/objects/<sha256>?Expires=…`,
  with `Cache-Control: private, max-age` of 15 to 30 minutes, and the image from CloudFront.
- [ ] Request the same URL without its query string, and with a changed `Signature`. Expect 403 from CloudFront.
- [ ] Request it again after `Expires`. Expect 403.
- [ ] Two requests in the same 15-minute window get the same URL; the second is served from CloudFront's edge cache
  (`X-Cache: Hit from cloudfront`), which checks that the signature's parameters are left out of the cache key.
- [ ] Take the image's Media record down in the admin app. Expect the legacy URL to get the unavailable image at once,
  and the signed URL already handed out to stop working when it expires.
- [ ] Rotate the CloudFront signing key (new key in the key group and the secret). Within 5 minutes, new URLs use the
  new key pair ID and work.
