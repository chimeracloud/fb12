# FB12 — status

**Unit:** FB12 Dutch (API half). **Written:** 2026-10-09 11:55 UK, by the build agent.

**State:** 0.2.0 deployed (revision `fb12-dutch-api-00005-dk9`, build c11718fb
green). Shell checked. Race list and race card answer `502 UPSTREAM_ERROR`
"could not read secret 'racingapi-username': PermissionDenied" because the
service runs as the default compute account, not `fb12-sa`. Blocked on that
switch for the step 2 live check; calculate (step 3) does not need it and is next.

**Waiting for (from Charles, since 2026-10-09 10:45 UK), not blocking the next step:**
- The service identity switched from the default compute service account to
  `fb12-sa@chiops.iam.gserviceaccount.com`. Without it the Racing API secrets
  cannot be read, so the race list will fail with an upstream error until it is done.
- The `api/**` included-files filter on the Cloud Build trigger.

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
