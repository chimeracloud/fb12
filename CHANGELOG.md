# Changelog

All notable changes to FB12, both halves. Dates are UK dates. Newest first.

## [0.3.0] — 2026-10-09 — calculate, and the identity named in permission errors

### Added
- `POST /api/calculate` (`services/dutch.py`): the graded dutch maths as the brief states it, the one code path for figures. Feasibility (no PROFIT runner, or P ≤ 0) returns `feasible: false` with the reason and no forced numbers. A runner without a price leaves the book, market chances and expected value null and is named in `message`. Break-even chance, can-break-even and wins-wiped-out for OUT and PART runners. Full input validation with every problem listed.
- Tests: the brief's eight cases on the 08:12 Betfair Exchange prices of the Challenge Stakes (profit per win 71.22 / 20.16 / 12.37; the stakes; book 103.03; expected value −2.94; Holguin 0.0555 / 0.0268 / 1.40, 4.96, 8.08; Witness Stand 0.0882 / 0.0312; £12.13 after 2% commission; a £50 loss unchanged), the identity EV = T × (1/book − 1), unrounded stakes summing to T for several totals, infeasible cases, missing prices, cannot-break-even, validation, and the endpoint against the function.
- `core/identity.py`: the service account the process runs as, from the metadata server. `GET /admin/status` and `GET /admin/config` show it against the expected `fb12-sa` (new committed config field `service_account`).

### Changed
- A `PermissionDenied` reading a secret now says which identity lacked access and that the Cloud Run service must run as `fb12-sa`, so it cannot be read as a credential problem. See docs/INCIDENTS.md, 2026-10-09.

### Incident
- Racing API username and password pasted into the agent chat while the race endpoints were failing on an identity problem. Not used, not stored. Rotation is Charles's; open until done. Recorded in `docs/INCIDENTS.md`.

## [0.2.0] — 2026-10-09 — race list and race card

### Added
- `GET /api/races` and `GET /api/races/{race_id}` per the contract (`services/races.py`, `routers/api.py`, response models in `models/schemas.py`).
- The Racing API client (`services/racing_api.py`): Basic Auth from the credential module, throttle from `request_rate_per_second`, 429 back-off and retry (`retry_on_429_max`), TTL cache per endpoint kind from the `cache_*_seconds` settings, counters in `/admin/status` under `racing_api`, and the Racing API's own status and detail in every error.
- Tests: mapping against the real Challenge Stakes card of 9 October 2026 (`tests/fixtures/challenge_stakes_card.json`, values exactly as received at 09:53 UK, reduced to the fields read); client behaviour (auth header, caching, repeated `region_codes`, 429 retry, error mapping, network failure, missing credentials) over an httpx MockTransport; both endpoints and their input validation through the app.

### Noted
- The card's odds `updated` time arrives without an offset; FB12 reads it as UK time and returns ISO 8601 with offset.
- The live check of these endpoints needs the service identity switched to `fb12-sa`: the default compute account cannot read the Racing API secrets.

## [0.1.1] — 2026-10-09 — first build fixed

### Fixed
- The first Cloud Build run failed in the test stage: `test_stream_route_is_sse` asserted on Starlette's internal `route.methods`, which Starlette 1.7 (pulled by the build) no longer exposes. Replaced with a test of the endpoint's own behaviour: `/admin/stream` answers a streaming `text/event-stream` response. 48 of 49 tests had passed; the build context (`api`) and every `COPY` were right.

### Deployed
- First green build `61535281-b86b-40ab-ad9e-98b94ff9f106` on commit `a6a69af`; revision `fb12-dutch-api-00003-ztd` at https://fb12-dutch-api-jptjmb2mfq-ew.a.run.app.
- Checked live with an operator token (`cloud@ascotwm.com`): 401 with no credential, a bad token, and on both Cloud Run URLs, for every `/admin` and `/api` path and `/`; 200 on `/admin/health`, `/admin/status`, `/admin/settings`, `/admin/config`, `/admin/logs`; `/admin/stream` opens with the `hello` event; `PUT /admin/settings {"past_runs": 5}` wrote `fsu-admin-settings/fb12` in Firestore (`source: firestore`, `updated_by: cloud@ascotwm.com`); credentials shown masked with their secret names.
- Found, not changed (Charles's to set): the service runs as the default compute service account, not `fb12-sa`; the trigger has no `api/**` path filter.

## [0.1.0] — 2026-10-09 — API shell

### Added
- `api/`: FastAPI shell with the seven CHI-ADR-010 admin endpoints (`/admin/health`, `/admin/status`, `GET` and `PUT /admin/settings`, `/admin/config`, `/admin/logs`, `/admin/stream`).
- The gate: every request needs a Cloudflare Access token (signature, audience, issuer, expiry against the team domain) or a Google ID token (Google's certificates, FB12's own URL or the gcloud client id as audience, verified email on the operator list). Anything else is `401` with no detail.
- Committed non-secret config `api/config/fb12.json`: team domain and audience tag (empty until prompt 2), operators `cloud@ascotwm.com` and `admin@chimerasportstrading.com`, resource and secret names.
- Credential module `core/credentials.py` (`get_credential(name)`, Secret Manager behind it, values in memory only).
- Admin settings with field definitions, validation and Firestore persistence (`fsu-admin-settings/fb12`): commission rate 2%, default stake £100, default PART fraction 0.5, past runs 5, regions GB and IRE, pace keyword lists, cache lifetimes, request rate, retries. Credentials shown masked and read only.
- Structured JSON logging (`service_name`, `trace_id`, `timestamp`, `severity`), an in-memory ring buffer for `/admin/logs`, and an event bus for the SSE stream.
- Error envelope `{"error": {"code", "message", "upstream_status"}}`; `UNAUTHENTICATED` and `INTERNAL_ERROR` added to the contract's four codes and recorded in the README.
- Tests (run as a stage of `api/Dockerfile`): 401 on every `/api` and `/admin` route without a credential or with an invalid one; both credential paths against a local signing key; every admin endpoint 200 with an operator token; settings validation, masking and persistence; logs and stream shape.
- Root: README (status, access exception, resources, pipeline, contract), this CHANGELOG, `docs/INCIDENTS.md`, `docs/status/latest.md`, `.gitignore`.

### Infrastructure (run by the build agent with gcloud, 9 October 2026, project chiops)
- `gcloud iam service-accounts create fb12-sa --display-name "FB12 Dutch API"`
- `gcloud secrets add-iam-policy-binding racingapi-username --member serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor`
- `gcloud secrets add-iam-policy-binding racingapi-password --member serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor`
- `gcloud projects add-iam-policy-binding chiops --member serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role roles/datastore.user`
- `gcloud storage buckets create gs://chiops-fb12-paper-entries --location=europe-west2 --uniform-bucket-level-access`
- `gcloud storage buckets add-iam-policy-binding gs://chiops-fb12-paper-entries --member=serviceAccount:fb12-sa@chiops.iam.gserviceaccount.com --role=roles/storage.objectAdmin`

### Decisions recorded
- Exception to CHI-POL-004 and CHI-POL-006 approved by Charles: IAM-level unauthenticated invocation, FB12 is the gate. See README.
- ADR 010's seven admin endpoints, not CHI-POL-008's thirteen (Charles, 9 October 2026).
- Paper entries bucket in `europe-west2` per CHI-POL-009 although the service runs in `europe-west1`.

## STRATEGY NOTES

No dated notes yet. Only Claude Strategy writes here.

---

*Born from complexity. Engineered for certainty.*
