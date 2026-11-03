# Legacy imageserver access logs: what they mean for Serena

October 16, 2026. A summary of what the legacy imageserver's access logs say about Serena's cache design. It is
input to the design, not part of it: `docs/design.md` is the only current design, and nothing here changes it until
a decision is recorded there.

## Source

The figures come from the spreadsheet **serena-access-log-analytics.xlsx**, built from about 21 months of the
legacy imageserver's access logs (January 1, 2025 to October 7, 2026; October is partial): 25,018,271 imageserver
requests for the five museums. The logs were cleaned before analysis; no client address, email address or user
agent string was kept, and the spreadsheet holds only counts and distributions. Its "Method" sheet describes how it
was made.

The spreadsheet is kept on Google Drive (UC Berkeley accounts with access only):
[serena-access-log-analytics.xlsx](https://drive.google.com/file/d/1APuVg2aMXwgEBSJBpeLgNMQR0XHIva9a/view).

## Is access uniformly random? No

| Measure | Uniform random | Actual |
| --- | --- | --- |
| Share of requests to the top 10% of files | about 16% | 59% |
| Files requested only once | 0.2% | 29% |
| Requests for the most-requested file | 27 | 24,974 |

Browsers alone show the same skew, so crawlers don't cause it.

## What it means for Serena's design

1. **The permanent S3 cache would have cut CollectionSpace traffic sharply.** Over the period, 24.7 million requests
   were served, for 2.93 million distinct files. With Serena's cache, 88% of requests would have been hits. A miss
   costs two calls (the light check and the fetch), so that's about 5.9 million CollectionSpace calls instead of
   24.7 million. In bytes, CollectionSpace would have sent 3.2 TB instead of 16.9 TB.
2. **"Fill on demand, no pre-warming" is right.** The requests touched only 27% of the 10.9 million stored objects and
   15% of the 21 TB. A full mirror would be about 6.5 times what was actually requested. Holding every requested file
   took 3.2 TB, 2.9 TB of it OriginalJpeg.
3. **"Keep forever" matters.** Reuse keeps rising with time: 25% of requests repeat a file requested in the past day,
   48% in the past week, 67% in the past month, and 88% over the whole period. A cache that expired files after a
   week would get barely half the benefit.
4. **The cutover will start cold.** Serena starts with an empty cache. In its first days, expect hit rates near the
   one-day figure (about 25%), climbing toward two-thirds over the first month. The busiest minutes (about 40
   requests a second) were single clients fetching in bulk, mostly crawlers. A crawler like that hitting a cold cache
   is where the concurrency cap and the Lyrasis fetch rate will bite. That's an argument for settling the rate limit
   before cutover and starting with a low-traffic museum, as the migration plan already says.
5. **The CloudFront edge cache will do little.** Only 13.5% of requests repeat a file within an hour, and 25.5% within
   a day. So S3, not the edge, does most of the work, and confirming that the cache key leaves out the signature
   parameters (an open question) matters less than it might.
6. **The WAF thresholds now have data.** Per client per 5 minutes: 99th percentile 21 requests, 99.9th 167, maximum
   8,651. 179 clients ever went over 1,000.

## Other findings that touch design decisions

- **Unused derivatives can be trimmed.** Small and FullHD were essentially never requested (single digits in 21
  months), and UCJEPS never requested an original file. This settles the "revisit each museum's list once the logs
  show which sizes are requested" open question: the lists could be trimmed.
- **Audio and video don't come through the imageserver.** There were no 206 or 304 responses, so nothing streamed
  through it. That narrows the audio and video investigation (D3).
- **One URL form needs a decision.** 14,820 UCJEPS requests have a second URL appended after `|`. They work today only
  because a rewrite rule in front of the imageserver cuts the path at `/content`, and Serena's strict parse would
  refuse them unless that rule stays in front of it.
- **OriginalJpeg dominates by bytes,** at 13.0 of 16.9 TB. Applebot alone took 3.2 TB, 90% of it OriginalJpeg. The
  cache's value comes mostly from originals requested by crawlers.

## Is the period representative?

- **Monthly volume swings about fourfold,** from 409 to 1,948 GB.
- **The bot share rose to 45–51% in August–September 2026.**
- **Some figures may undercount.** Reuse over the whole period is a floor for a cache that keeps files forever: a
  longer period would only raise it. But if crawler coverage keeps growing, the share of distinct files rises too.

The skew and the size of the working set relative to the store are large enough that the conclusions hold well
beyond that variation.

## URL forms, audio and video, and file sizes (November 3, 2026)

A second pass over the same cleaned logs (25,018,271 imageserver requests, January 2025 to October 7, 2026), for
three open questions in `docs/design.md`: the URL forms in use, audio and video, and size limits. Bytes are those
sent for `GET` requests answered 200; a megabyte is 1,000,000 bytes.

### Which sizes are requested

Requests by museum and URL form (all methods; `GET` was 99.6% of them, `HEAD` almost all the rest):

| Museum | Thumbnail | Small | Medium | FullHD | OriginalJpeg | File itself (`/content`) | PDF links |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BAMPFA | 48,372 | 6 | 3,068,878 | 1 | 58 | 10 | |
| Botanical Garden | 37,460 | 0 | 67,272 | 0 | 2,976 | 0 | |
| Cinefiles | 34,447 | 6 | 3,952,404 | 0 | 47,965 | 5,359 | 1,123,245 |
| PAHMA | 1,036,444 | 0 | 6,781,540 | 0 | 3,351,113 | 64,109 | |
| UCJEPS | 2,471,961 | 1 | 1,887,173 | 0 | 1,019,843 | 0 | |

- **Small and FullHD are not used anywhere:** 14 requests in 21 months, all five museums together.
- **UCJEPS and the Botanical Garden never requested a file itself.** BAMPFA's 10 such requests, and its 58 for
  OriginalJpeg, got no file from the legacy imageserver either: neither is on BAMPFA's list.
- **Exact matching of derivative names loses next to nothing.** 1,944 requests spelled a listed name another way
  (`originaljpeg`, `medium`, `thumbnail`), and the legacy imageserver sent none of them a file: its largest answer to
  any of them was 1,669 bytes, an error. Most were browsers; UCJEPS' `originaljpeg` (1,149 requests, 680 of them
  since July 2026) is the only one still in steady use. About 180 more used a name on no museum's list (`Large`,
  `Full`, `Zoom` and a few dozen others); only `Original`, CollectionSpace's own name, got a file (44 requests at
  Cinefiles and PAHMA, in 21 months).
- **No Media URLs** (`media/<csid>/blob/…`) appear: every request used a Blob URL.
- **Query strings carry nothing Serena needs:** a few hundred requests in all, with tracking parameters (`fbclid`,
  `utm_source`) and the like.
- **Odd paths are rare.** Apart from UCJEPS' second URL after `|` (above), a few hundred requests had truncated or
  garbled paths, which get the unavailable image today too.

### Who links to the imageserver

From the referrer's host, which is all the cleaned logs keep:

- **The museums' own portals,** current and QA (Hearst Museum, Cinefiles, BAMPFA's collection site) and the legacy
  portals on the webapps hosts: most requests with a referrer.
- **Other sites embedding UCJEPS images:** the Symbiota herbarium portals (CCH2 about 1.15 million requests,
  Pteridoportal about 310,000, the Lichen portal, and Symbiota development hosts), Calflora (about 215,000) and
  African Plants (about 50,000).
- **Search engines,** the ARK resolver (n2t.net), and developers' local copies of the portals (`localhost`).
- **No referrer** for about 10 million requests: crawlers, direct links, and apps.

So the portals are not the only clients: UCJEPS' URLs in particular are embedded in other institutions' sites, which
is why the legacy URLs must keep working (as the design already requires).

### Audio and video

The logs carry no file type, so they can't say which requests were for audio or video. They do bound them:

- Audio and video can only have come as the file itself (`/content`), whole: there were no 206 or 304 responses.
- That's 69,478 requests in 21 months, 0.28% of all: PAHMA 64,109, Cinefiles 5,359, BAMPFA 10. PAHMA's are rising
  (14,226 in 2025, 49,883 in 2026 to October 7), but their largest file was 55 MB, and 99% were under 13 MB.
- Cinefiles' 5,359 were for 279 files, but 4,690 of them for one 54 MB file.

To split these by kind, the logged Blob CSIDs would have to be matched against the audio and video rows of a real
ETL list.

### Largest files, against the starting size limits

| Requests for | Requests | Median | 99.9th percentile | Largest | Distinct files over 100 MB |
| --- | --- | --- | --- | --- | --- |
| PDFs (Cinefiles) | 1,122,091 | 0.26 MB | 70 MB | 234 MB | at least 15 |
| Medium (Cinefiles) | 3,951,909 | 0.09 MB | 0.4 MB | 161 MB | 3 |
| OriginalJpeg (PAHMA) | 3,262,221 | 1.1 MB | 21 MB | 112 MB | 1 |
| File itself (Cinefiles) | 5,303 | 54 MB | 54 MB | 92 MB | 0 |
| File itself (PAHMA) | 63,241 | 1.1 MB | 34 MB | 55 MB | 0 |
| OriginalJpeg (UCJEPS) | 1,018,453 | 4.7 MB | 17 MB | 32 MB | 0 |

Everything else was 32 MB or less (BAMPFA's largest was 2 MB).

- **Images and catalog cards (500 MB):** well inside, at 161 MB at most.
- **PDFs (200 MB):** one Cinefiles PDF, of 234 MB, is over the starting limit; Serena would refuse it as `too_large`
  until the limit is raised. The next largest is 187 MB.
- **3D (1 GB):** nothing in the logs comes near it.
- **Three Cinefiles Medium answers of 147 to 161 MB** are out of line with a median of 0.09 MB. They may be
  derivatives of very large scans, or the legacy imageserver answering for a file that isn't an image; worth a look
  at those records before the Cinefiles cutover.
- **The largest answer was 234 MB, not 92 MB.** The 92 MB in the design's Compute section was the largest file
  itself at Cinefiles.

### What it means for Serena's design

1. **Each museum's list of derivatives can be trimmed** to what's used: Small and FullHD at every museum, and the
   file itself at UCJEPS. Whether to trim, and whether UCJEPS should keep the file itself for other reasons, is for
   the museums to decide.
2. **Keep exact matching of derivative names.** Accepting other spellings would serve requests the legacy
   imageserver never served; the 44 requests for `Original` don't justify a name of their own.
3. **Raise the PDF limit for Cinefiles to at least 250 MB,** or accept that its 234 MB PDF is refused. Image and 3D
   limits need no change.
4. **Audio and video are at most a small, whole-file load.** If Serena serves them, they fit the existing fetch and
   cache path; nothing in the logs calls for streaming.
