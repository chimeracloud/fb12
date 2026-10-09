# FB12 — status

**Unit:** FB12 Dutch (API half). **Written:** 2026-10-09 14:40 UK, by the build agent.

**State:** recording. Bucket `gs://chiops-fb12-racingapi-raw` created; 2026-10-08 and
2025-03-17 recorded live; the historical results add-on is confirmed active, so the
backfill runs back to 2005-01-01 (results only before 2023-01-23). Cloud Scheduler
jobs `fb12-record-daily` (07:00 UK) and `fb12-record-backfill` (every 3 minutes,
00:00-06:00 UK) are enabled; the backfill starts tonight. Trigger filter `api/**` set.
0.4.1 pushed: 401 credential reload, body passthrough, empty-results guard.

**Waiting for (from Charles):**
- Since 12:05 UK: rotation of the Racing API password, outside 00:00-07:00 UK, then
  a new version of `racingapi-password` and a word to the agent, which rolls a new
  revision at once (FB12 also re-reads the secrets on the first 401).

**Last did:** everything above, plus the overlap check (one run at a time, 409 at
once while busy) and the retry path (an incomplete daily day is the backfill's
first pick that night).

**Next:** move and pace, then paper entries with SP and BSP settlement.

**Found and reported, not acted on:**
- Cloud Run may briefly run two instances during a deploy; a run on the old one
  and a call on the new one could record the same day. Writes are idempotent raw
  objects; the manifest's `runs` list would show both. Recorded in the README.
- Only `cloud@ascotwm.com` is logged in to gcloud here.

**Declined:** nothing.
