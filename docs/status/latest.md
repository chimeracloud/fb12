# FB12 — status

**Unit:** FB12 Dutch (API half). **Written:** 2026-10-09 12:55 UK, by the build agent.

**State:** 0.3.0 deployed (revision `fb12-dutch-api-00007-jvd`, build 6886d5db
green) and checked live: `POST /api/calculate` with the cautious version at 2%
returns profit per win 12.37, book 103.03, expected value −2.94, Holguin
0.0555 / 0.0268 / 8.08, Witness Stand 0.0882 / 0.0312, £12.13 after commission,
a £50 loss unchanged. Permission errors now name the identity at fault. Race list and race card are deployed but blocked on the
service identity: it runs as the default compute account, not `fb12-sa`, so the
Racing API secrets cannot be read. Open incident: the Racing API credentials
were pasted into the agent chat at about 12:05 UK; not used, not stored;
rotation outstanding.

**Waiting for (from Charles):**
- Since 10:45 UK: the service identity switched to `fb12-sa@chiops.iam.gserviceaccount.com`
  (Cloud Run → fb12-dutch-api → Edit and deploy new revision → Security → Service account).
  Blocks the live check of the race endpoints, move, pace and paper entries.
- Since 12:05 UK: rotation of the Racing API password (and username if it changes) in
  The Racing API account, then a new version on `racingapi-password` / `racingapi-username`.
- Since 10:45 UK: the `api/**` included-files filter on the Cloud Build trigger.

**Last did:** fixed the one failing test (Starlette 1.7 route internals), watched
build 61535281 go green, ran the step 1 checks: 401 everywhere without a
credential, 200 on every admin endpoint with an operator token, a real
Firestore settings write, the SSE stream's hello event. Recorded the URL in the
README.

**Found and reported, not acted on:**
- Only `cloud@ascotwm.com` is logged in to gcloud here; `admin@chimerasportstrading.com`
  is on the operator list but cannot be exercised from this machine.
- gcloud user ID tokens carry the gcloud client id as audience; FB12 accepts it
  via `extra_audiences`, as Cloud Run's own IAM does.

**Declined:** nothing.
