# Changelog

All notable changes to FB12, both halves. Dates are UK dates. Newest first.

## [0.5.0] — 2026-10-09 — move and pace

### Added
- `GET /api/races/{race_id}/runners/{horse_id}/move` (`services/move.py`): bookmaker median first, Betfair Exchange only when no bookmaker has history; SP and dash entries skipped; exchange prices outside the minute's bookmaker range dropped; first price at 00:00 UK on race day with evening prices carried forward; `note` explains the figure or its absence.
- `GET /api/races/{race_id}/runners/{horse_id}/pace?runs=` (`services/pace.py`): the horse's own comment in each of its last N runs before race day, matched as whole phrases on word boundaries against the `pace_*` settings in list order; anything else UNCLASSIFIED. Contract addition: each run carries `category`.
- Tests on Holguin's real odds history (Bet365 and Betfair Exchange, 8 and 9 October 2026) and his two real past runs with every runner's real running comment: the median path, the exchange fallback with two prices dropped, no history, unchanged and shortened moves, fourteen real comments classified, list order, the endpoints and their input checks.

## [web 0.1.0] — 2026-10-09 — GUI shell, race list, race page, results panel, admin

### Added
- `web/`: React, Vite and TypeScript app for Cloudflare Pages. Pages Functions for `/api` and `/admin` forward to the API with the Cloudflare Access token, drop browser Authorization headers, and return status and body unchanged; the API URL is a committed constant in `web/functions/_config.ts`.
- Races page: date (UK), GB and IRE toggles, pattern races only; rows open the race. Race page: header with fetch time, stake and commission from FB12's settings, presets, the runner grid (editable exchange price with card price and reset, best bookmaker, owner, trainer, OR, same-owner marker, tier with PART fraction, non runners and reserves locked, an "all fields" drawer per runner and for the race). Results panel: `POST /api/calculate` 300 ms after every change, last figures dimmed while in flight, per-runner and summary figures, break-even and wipe-out for OUT and PART, the API's message when infeasible or a price is missing. Admin page: health, status, settings form from the field definitions (PUT of changed fields, secrets masked), config, logs, live stream.
- Formats: decimal odds to two places, money with losses in brackets, chances as percents, UK times. Errors shown as the API returns them, with a retry.
- Left for their endpoints, with no placeholders: move and pace columns, the paper entries page and "Save as paper entry".

## [0.4.2] — 2026-10-09 — backfill: 7-day BSP rule, once a night, budgeted calls

### Changed
- Completeness: BSP is required only for days in the last `bsp_required_within_days` (7). An older day is complete once its results are stored, with runners lacking BSP listed in the manifest (`results.runners_without_bsp`). Stored results of an older day are not re-fetched.
- The backfill tries an incomplete day at most once a night (UK date of its last attempt), then moves on, so one day can no longer be picked every 3 minutes all night.
- A backfill call keeps recording days, newest first, until it has used `backfill_call_budget_seconds` (150), the day in progress always finishing. Response: `days`, `days_recorded`, `calls`, `elapsed_seconds`, `stopped_because`, `remaining_estimate`.
- The recorder index is loaded at startup so `/admin/status` is right from the first call.

## [0.4.1] — 2026-10-09 — recording live; results back to 2005; rotation without a restart

### Added
- A Racing API 401 makes the client re-read both secrets from Secret Manager once and retry, so a rotated password is picked up without a restart. A second 401 is reported, body as is.
- Recorder: a results page with no races on a day whose card has races is `empty`, the day stays incomplete and the boundary is learned, so the plan's reach is never mistaken for a quiet day.

### Changed
- Racing API error messages carry the upstream body as is (trimmed for length only). A 401 message says it can mean wrong credentials, a plan that does not cover the endpoint, or an overdue invoice.
- Recorder defaults: `results_history_days` 8000 and `backfill_earliest_date` 2005-01-01, because the historical results add-on is active on this account (a live call for 2025-03-17 returned 35 races with BSP on every runner); `recorder_max_attempts` 8 so a late BSP never exhausts a day. Set live the same way.
- README: the removed-fields list corrected (rpr, ts, tsr, spotlight, quotes, stable_tour, betting_forecast; medical and breeder can carry data); the network-edge caps (50 per 10 s, 100 per 10 s lockout); overlap and retry behaviour; rotation.

### Recorded live (9 October 2026)
- 2026-10-08: 471 calls, 160 s, 46 races, 469 runners' odds, 432 result runners of which 428 with BSP; incomplete until BSP lands, retried by the next run.
- 2025-03-17: 360 calls, 123 s, 35 races, 358 runners' odds, 324 result runners all with BSP; complete.

### Infrastructure (gcloud, 9 October 2026)
- `gcloud storage buckets create gs://chiops-fb12-racingapi-raw --location=europe-west2 --uniform-bucket-level-access`; `add-iam-policy-binding` fb12-sa `roles/storage.objectAdmin`.
- Trigger `rmgpgab-fb12-dutch-api-europe-west1-chimeracloud-fb12--maqsf`: `includedFiles: [api/**]` via `gcloud alpha builds triggers export` / `import` (the GA `update github` command rejected the change).
- `gcloud scheduler jobs create http fb12-record-daily` (`0 7 * * *`, `?date=yesterday`) and `fb12-record-backfill` (`*/3 0-5 * * *`, `?date=backfill`), europe-west1, Europe/London, POST, OIDC as `fb12-recorder-scheduler@chiops.iam.gserviceaccount.com`, audience the service URL, deadline 900 s, retries 0.

## [0.4.0] — 2026-10-09 — the recorder, raw passthrough, one instance

### Added
- `POST /api/record?date=` (operator only): records one day of raw Racing API responses (racecards, every results page, every runner's odds history) into the recordings bucket, gzip, one object per response, with a per-day manifest, an index and learned availability boundaries. Modes `YYYY-MM-DD`, `yesterday` (plus retries of recent incomplete days) and `backfill` (newest incomplete day first, night window only). A day is complete only when every result carries BSP. `409 RECORDER_BUSY` while a run is in progress. Progress in `GET /admin/status` under `recorder`.
- Recorder settings group: `cards_history_from` 2023-01-23, `odds_history_from` 2025-03-17, `results_history_days` 365 (what The Racing API documents for this plan), `backfill_earliest_date`, the backfill window hours, `recorder_retry_days`, `recorder_max_attempts`, `recorder_results_page_size`.
- The Racing API client: `fetch()` returns the body exactly as received; background calls yield to GUI calls and share the same budget; per-call logging is DEBUG for background calls so the recorder does not swamp `/admin/logs`.
- `core/storage.py`: one object store interface (GCS in deployment, memory in tests).
- Contract change, endpoint 2: `raw_race` on the card and `raw` on every runner, exactly as received.
- Committed config: `recordings_bucket` (`chiops-fb12-racingapi-raw`, name awaiting Charles's yes) and the scheduler service account `fb12-recorder-scheduler@chiops.iam.gserviceaccount.com` on the operator list.
- Tests: the recorder end to end over real fixture responses (a real Goodwood results page with BSP on every runner; a real Holguin odds history) into an in-memory store: raw bytes stored untouched, manifests, completeness, retry re-fetching results only, 404 odds as missing, plan-limit learning, backfill window and selection, yesterday-mode retries, the busy lock, operator-only access.

### Changed
- Service settings (gcloud, 9 October 2026): `--max-instances 1 --timeout 900 --service-account fb12-sa@chiops.iam.gserviceaccount.com`. One instance always, because the throttle, cache and recorder lock live in memory. Recorded in the README.
- README records the contract decisions of 9 October 2026 for the next steps: move's source order (bookmaker median first, exchange as fallback, SP and dash entries skipped, exchange prices outside the minute's bookmaker range dropped) and the settlement fields `pnl_at_sp`, `pnl_at_bsp`, `pnl_at_bsp_after_commission`, `bsp_pending` on endpoints 7, 8 and 9.

### Fixed
- A missing or unreadable recordings bucket is reported as `502 UPSTREAM_ERROR` naming the bucket, not as a 500 (found on the first live probe before the bucket existed).

### Infrastructure
- `gcloud iam service-accounts create fb12-recorder-scheduler --display-name "FB12 recorder: Cloud Scheduler caller"` (no roles; Cloud Scheduler mints its OIDC token).

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
