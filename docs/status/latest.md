# FB12 — status

**Unit:** FB12 Dutch (API half). **Written:** 2026-10-09 13:45 UK, by the build agent.

**State:** 0.4.0 pushed: the recorder, raw passthrough on the race card, one
instance. The service now runs as `fb12-sa` with max instances 1 and a 900 s
timeout (set by the agent with gcloud, 9 October 2026, 12:33 UK). Race list,
race card and calculate are checked live and correct.

**Waiting for (from Charles):**
- Since 13:45 UK: yes to the recordings bucket name `chiops-fb12-racingapi-raw`.
  Then the agent creates it with the paper entries bucket's settings and bindings,
  records one day live, and the backfill can start tonight once the Cloud Scheduler
  jobs exist (settings in the README under The recorder).
- Since 12:05 UK: rotation of the Racing API password. The password in Secret
  Manager version 1 is still the one the API accepts, so it has not been rotated.
- Since 10:45 UK: the `api/**` included-files filter on the Cloud Build trigger.

**Last did:** checked the race list (47 GB and IRE races) and the Challenge Stakes
card live; set the service identity, scaling and timeout; built the recorder with
its tests; recorded the contract changes in the README.

**Next:** move and pace, then paper entries with SP and BSP settlement.

**Found and reported, not acted on:**
- The Racing API's racecards endpoint allows 2 requests a second (the others 5); FB12's
  single budget is 3 a second and the race list is cached 5 minutes, so it stays under.
- Only `cloud@ascotwm.com` is logged in to gcloud here.

**Declined:** nothing.
