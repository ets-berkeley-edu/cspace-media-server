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
