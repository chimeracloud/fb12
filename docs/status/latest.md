# FB12 — status

**Unit:** FB12 Dutch (API half). **Written:** 2026-10-09 11:25 UK, by the build agent.

**State:** API shell pushed to `main`. Not yet deployed.

**Waiting for:** Charles to run the Cloud Run wizard (service `fb12-dutch-api`,
europe-west1, service account `fb12-sa`, Dockerfile `/api/Dockerfile` with
context `api`, included files `api/**`, allow unauthenticated). Since 2026-10-09
11:25 UK.

**Last did:** created `fb12-sa`, bound `secretAccessor` on `racingapi-username`
and `racingapi-password`, `datastore.user` on chiops, created
`gs://chiops-fb12-paper-entries` with `objectAdmin`; wrote and pushed the shell
with its tests in the Dockerfile.

**Next:** when the first deploy is green, record the Cloud Run URL in the README,
check `401` without a credential and `200` on every admin endpoint with an
operator token, then build the race list and race card.

**Found and reported, not acted on:**
- Only `cloud@ascotwm.com` is logged in to gcloud on this machine; checks run as
  that operator. `admin@chimerasportstrading.com` is on the operator list but
  cannot be exercised from here.
- Cloud Run's own IAM accepts gcloud user tokens whose audience is the gcloud
  client id, not the service URL; FB12 mirrors that by listing that client id in
  `extra_audiences`. Recorded in the README.

**Declined:** nothing.
