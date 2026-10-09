# FB12 — status

**Unit:** FB12 Dutch (API half). **Written:** 2026-10-09 11:05 UK, by the build agent.

**State:** Shell deployed and checked (0.1.1). Race list and race card pushed
(0.2.0); their live check waits on the service identity switch below, because
the default compute account cannot read the Racing API secrets.

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
