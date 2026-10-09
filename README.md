# FB12 Dutch

**Chimera Sports Trading · First Build 12 · graded dutch, paper only.**

Strategy concept: Mark Insley. Architecture and build: Charles Duckitt.

FB12 backs several horses in one race with stakes sized so each horse gives a
chosen result if it wins: a profit (PROFIT), the stake back (BREAK_EVEN), part
of the stake back (PART) or the whole stake lost (OUT). It works out every
outcome at current prices, the expected value at the market's own odds, and the
pacemaker and price movement evidence per runner. It logs paper entries and
settles them against the result. It never places a bet and never connects to
Betfair. Every number comes from The Racing API.

The repo holds both halves: the API in `api/` and the GUI in `web/`. One README
and one CHANGELOG at the root cover both.

## Status

| Part | State | Where |
| --- | --- | --- |
| API shell (admin endpoints, both credential paths) | Pushed to `main`, awaiting Charles's Cloud Run wizard for the first deploy | `api/` |
| **Cloud Run URL** | **Not yet deployed.** Recorded here the moment the first build is green; prompt 2 needs it | — |
| Race list, race card, calculate, move, pace, paper entries | Not started | — |
| GUI | Not started (prompt 2) | `web/` |

Current state in detail: [docs/status/latest.md](docs/status/latest.md).
Incidents: [docs/INCIDENTS.md](docs/INCIDENTS.md).

## Standalone, and the access exception

FB12 is a First Build kept outside the Chimera ecosystem by Charles's decision
of 9 October 2026: no CST portal, no portal proxy, no Pub/Sub, no FSU wiring.
The Bible governs how it is built, not what it connects to.

**Exception to CHI-POL-004 and CHI-POL-006, approved by Charles on 9 October
2026.** FB12's Cloud Run service accepts unauthenticated invocation at the IAM
level and FB12 itself is the gate. Reason: the GUI reaches the API through a
Cloudflare Pages Function carrying a Cloudflare Access token, and Cloudflare
cannot present a Google identity, so an IAM invoker binding cannot be the
boundary. Every `/api` and `/admin` request must carry one of two credentials;
anything else gets `401` with no detail.

## Access

| Path | Header | Checked against | Who uses it |
| --- | --- | --- | --- |
| Cloudflare Access token | `Cf-Access-Jwt-Assertion` | Signature against the team domain's published keys, audience against the FB12 Access application's audience tag, issuer against the team domain, expiry | The GUI's Pages Function (prompt 2) |
| Google ID token | `Authorization: Bearer` | Google's published certificates; audience is FB12's own URL (the host the request was sent to) or the gcloud client id that user tokens carry; email verified and on the operator list | Charles and the build agent, before the GUI exists |

Team domain, audience tag and operator list are non-secret config in
`api/config/fb12.json`. Until the team domain and audience tag are set, the
Cloudflare path rejects everything. `saved_by` on paper entries is the email in
the verified credential. No CORS: the browser never calls FB12 directly.

Operators: `cloud@ascotwm.com`, `admin@chimerasportstrading.com`.

Checking an endpoint with an operator token, from a machine where gcloud is
logged in as an operator:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" https://<cloud-run-url>/admin/health
curl -s -o /dev/null -w "%{http_code}\n" https://<cloud-run-url>/admin/health   # 401
```

## Resources

| Resource | Name |
| --- | --- |
| GCP project | `chiops` |
| Cloud Run service | `fb12-dutch-api`, region `europe-west1` (Belgium) |
| Service account | `fb12-sa@chiops.iam.gserviceaccount.com` |
| Racing API credentials | Secret Manager `racingapi-username`, `racingapi-password` (fb12-sa has `secretAccessor` on these two only) |
| Admin settings | Firestore `(default)`, collection `fsu-admin-settings`, document `fb12` (fb12-sa has `roles/datastore.user`) |
| Paper entries | GCS `gs://chiops-fb12-paper-entries`, `europe-west2` per CHI-POL-009, uniform access (fb12-sa has `objectAdmin`) |
| GitHub | `chimeracloud/fb12`, branch `main` only |

## Pipeline

Code is written into this repo and never run locally. A push to `main` is the
only path to production. Charles owns the Cloud Run service, its repository
connection and the Cloud Build trigger; the agent uses gcloud only for the
bucket and IAM bindings, and read-only for build status and logs.

The build is `api/Dockerfile`, context `api/`. Stage `test` runs the suite;
stage `runtime` copies a marker from it, so a failing test fails the build and
nothing deploys. The runtime image carries no tests and no dev dependencies.

Cloud Run wizard settings ("Continuously deploy from a repository"):

| Setting | Value |
| --- | --- |
| Repository | GitHub `chimeracloud/fb12` |
| Branch | `^main$` |
| Build type | Dockerfile |
| Source location (Dockerfile) | `/api/Dockerfile`, build context `api` |
| Included files filter (on the Cloud Build trigger) | `api/**` so GUI pushes do not rebuild the API |
| Service name | `fb12-dutch-api` |
| Region | `europe-west1` (Belgium) |
| Authentication | Allow unauthenticated invocations (FB12 is the gate, see above) |
| Service account | `fb12-sa@chiops.iam.gserviceaccount.com` |
| Container port | `8080` |

No environment variables are set on the service: all non-secret config is in
the committed file, and credentials are read from Secret Manager at runtime.

## Repository layout

```
api/
  main.py              FastAPI app factory; middleware order; routers
  config/fb12.json     committed non-secret config (team domain, audience tag, operators, resource and secret names)
  core/config.py       config loader (Pydantic v2, extra="forbid"); Cloud Run identity env
  core/auth.py         the gate: Cloudflare Access token and Google ID token verification
  core/credentials.py  get_credential(name): Secret Manager behind one interface (CHI-POL-040)
  core/settings.py     admin settings: field definitions, validation, Firestore persistence
  core/logging.py      JSON logging (service_name, trace_id, timestamp, severity) + ring buffer
  core/events.py       event bus for the SSE stream
  core/errors.py       the error envelope
  core/middleware.py   trace id, timing, counters, one log line per request
  routers/admin.py     the seven ADR 010 endpoints
  models/schemas.py    request models
  services/            Racing API client, dutch maths, pace, paper entries (steps 2 to 5)
  tests/               runs inside the Docker build
  Dockerfile           base -> test -> runtime
docs/INCIDENTS.md      incident log (CHI-POL-048)
docs/status/latest.md  where the unit is now (CHI-POL-053)
web/                   the GUI (prompt 2)
```

## Configuration

`api/config/fb12.json` ships with every push. Fields: `unit`, `service_name`,
`gcp_project`, `region`, `firestore` (database, collection, document),
`paper_entries_bucket`, `racing_api.base_url`, `credentials` (logical name to
secret id, names only), `access.cloudflare` (`team_domain`, `audience_tag`),
`access.google` (`operators`, `extra_audiences`).

Settings live in Firestore and are edited through `PUT /admin/settings`. The
stored value governs; the code default only applies until something is stored.

| Key | Default | Meaning |
| --- | --- | --- |
| `commission_rate` | 0.02 | Betfair commission on net market winnings |
| `default_stake` | 100 | Total stake the GUI starts with (£) |
| `default_part_fraction` | 0.5 | Share of the stake a PART runner returns |
| `past_runs` | 5 | Previous runs the pace endpoint reads |
| `regions` | gb, ire | Racing API region codes for the race list |
| `request_rate_per_second` | 3 | FB12's own ceiling (the account allows 5 and may be shared) |
| `retry_on_429_max` | 3 | Retries with backoff on a 429 |
| `cache_race_list_seconds` | 300 | |
| `cache_race_card_seconds` | 60 | |
| `cache_odds_seconds` | 60 | |
| `cache_past_runs_seconds` | 86400 | |
| `pace_led`, `pace_prominent`, `pace_held_up`, `pace_midfield` | the lists in the brief | Matched in that order, first match wins; anything else is UNCLASSIFIED |
| `racing_api_username`, `racing_api_password` | masked | Read only; values never leave the credential module |

Credentials: `core/credentials.py` is the one place FB12 reads a credential.
Secret Manager sits behind `get_credential(name)` today (interim, per
CHI-POL-040); values live in memory for the life of the process and are never
logged, stored or returned by an endpoint.

## API contract

JSON throughout. Operational routes under `/api`, admin routes under `/admin`.
Every request needs a valid credential.

Units: money in pounds to two decimals; prices as decimal odds; chances as
fractions from 0 to 1; `book_pct`, `change_pct` and `expected_value_pct` as
percents (for example 103.03); times in ISO 8601 with offset. Tiers: `PROFIT`,
`BREAK_EVEN`, `PART`, `OUT`.

Errors: any failure returns an HTTP error status with
`{"error": {"code": "...", "message": "...", "upstream_status": 429}}`.
Codes: `UPSTREAM_ERROR`, `NOT_FOUND`, `INVALID_INPUT`, `NO_RESULT_YET`. Two more
exist in practice: `UNAUTHENTICATED` (401, body `{"error": {"code":
"UNAUTHENTICATED", "message": "Not authenticated."}}`, no detail) and
`INTERNAL_ERROR` (500, an unexpected exception). The message is written to be
shown as is.

### Operational endpoints (steps 2 to 5; not yet built)

1. `GET /api/races?date=&regions=gb,ire&pattern_only=false` →
   `{"date", "races": [{"race_id", "off_dt", "off_time_uk", "course", "race_name", "pattern", "race_class", "field_size", "region"}]}`
2. `GET /api/races/{race_id}` →
   `{"race": {"race_id", "off_dt", "off_time_uk", "course", "race_name", "pattern", "distance", "going", "field_size"}, "fetched_at", "runners": [{"horse_id", "horse", "number", "draw", "status" (DECLARED, NON_RUNNER or RESERVE), "owner", "owner_id", "trainer", "trainer_id", "jockey", "official_rating", "form", "exchange_price", "exchange_updated", "best_bookmaker_price", "best_bookmaker", "same_owner_as", "same_trainer_too"}]}`.
   `exchange_price` is null when the card has no Betfair Exchange price.
3. `GET /api/races/{race_id}/runners/{horse_id}/move` →
   `{"horse_id", "source" ("Betfair Exchange", "bookmaker median" or null), "first_price", "first_at", "latest_price", "latest_at", "change_pct", "direction" ("shortened", "drifted", "unchanged" or null), "note"}`
4. `GET /api/races/{race_id}/runners/{horse_id}/pace?runs=5` →
   `{"horse_id", "counts": {"LED", "PROMINENT", "MIDFIELD", "HELD_UP", "UNCLASSIFIED"}, "runs": [{"date", "course", "race_name", "position", "class", "comment"}]}`, runs newest first, comment raw.
5. `POST /api/calculate` body `{"stake_total", "commission_rate", "runners": [{"horse_id", "horse", "price", "tier", "part_fraction"}]}` →
   `{"feasible", "message", "profit_per_win", "book_pct", "expected_value_gbp", "expected_value_pct", "runners": [{"horse_id", "horse", "tier", "price", "stake", "return_if_wins", "net_if_wins", "net_after_commission", "market_chance", "break_even_chance", "can_break_even", "wins_wiped_out"}]}`.
   No Racing API call, nothing stored. The only place figures are worked out.
6. `POST /api/paper` body `{"race_id", "stake_total", "commission_rate", "runners": [{"horse_id", "price", "card_price", "price_edited", "tier", "part_fraction"}]}` → `201 {"entry_id", "status": "OPEN", "saved_at", "saved_by"}`
7. `GET /api/paper?status=` → `{"entries": [{"entry_id", "race_id", "race_name", "course", "off_dt", "saved_at", "saved_by", "status" (OPEN, SETTLED or NEEDS_REVIEW), "pnl", "pnl_after_commission", "review_reason"}]}`
8. `GET /api/paper/{entry_id}` → the entry without the raw API responses.
9. `POST /api/paper/{entry_id}/settle` → `{"entry_id", "status", "winner", "pnl", "pnl_after_commission", "review_reason"}`; `409 NO_RESULT_YET` when the result is not published.

### Admin endpoints (CHI-ADR-010, live in the shell)

| Endpoint | Returns |
| --- | --- |
| `GET /admin/health` | `{"status": "ok", "service", "unit", "version", "revision", "time", "uptime_seconds", "settings_source"}` |
| `GET /admin/status` | `{"service", "unit", "version", "revision", "mode": "paper", "time", "started_at", "uptime_seconds", "requests": {"total", "errors", "error_rate", "by_status"}, "access": {"accepted": {"cloudflare_access", "google_id_token"}, "rejected", "cloudflare_configured", "operators"}, "settings": {"source", "updated_at", "updated_by", "last_error"}, "credentials": {name: "loaded" or "not loaded"}, "racing_api" (null until step 2), "stream": {"subscribers", "events_published", "events_dropped"}}` |
| `GET /admin/settings` | The form: `{"service", "unit", "storage": {"backend", "path"}, "source", "updated_at", "updated_by", "last_loaded_at", "last_error", "groups": [{"id", "label", "fields": [{"key", "label", "type", "value", "default", "writable", "help", "min", "max", "step"}]}]}`. Field types: `number`, `integer`, `boolean`, `string`, `list`, `secret`. A `secret` field has `value` masked, `writable` false, plus `secret` (the Secret Manager name) and `state`. Read from Firestore on every call. |
| `PUT /admin/settings` | Body `{"values": {key: value}}`. Returns `{"applied": [keys], "rejected": [{"key", "reason"}], "settings": the form}`. Persisted to Firestore before anything is applied in memory; a failed write returns `502 UPSTREAM_ERROR` and changes nothing. `updated_by` is the credential's email. |
| `GET /admin/config` | Deployment reference: project, region, Cloud Run service and revision, Python version, Racing API base URL, bucket, Firestore path, access config (team domain, audience tag, operators, audience rule), credential secret names with masked values, pipeline. |
| `GET /admin/logs?limit=100&before=&severity=` | `{"entries": [...newest first], "count", "limit", "newest_seq", "oldest_seq", "next_before", "buffer_size"}`. Each entry: `timestamp`, `severity`, `service_name`, `trace_id`, `logger`, `message`, `seq`, plus the structured fields of that line. In-memory ring buffer of the last 1000 entries of this instance. |
| `GET /admin/stream` | Server-Sent Events. First event `hello` carries the status snapshot. Then `log` (each log entry, `id` = its seq), `settings` (keys changed, by whom) and a `status` heartbeat every 15 seconds of silence. Every event's data is `{"event", "time", "data"}`. Cloud Run closes long requests at its timeout; the client reconnects. |

## Policies honoured

- CHI-POL-008 Shell First: the shell is the first push; content follows only once the shell is deployed and checked.
- CHI-POL-040: one credential module behind `get_credential(name)`.
- CHI-POL-047: STRATEGY NOTES sections below and in the CHANGELOG; only Claude Strategy writes into them.
- CHI-POL-048: `docs/INCIDENTS.md`.
- CHI-POL-053: `docs/status/latest.md`, overwritten whenever the unit reports.
- CHI-POL-004 / CHI-POL-006: exception recorded above.

## STRATEGY NOTES

No notes yet. Only Claude Strategy writes into this section; the build agent
reads it, acts on it and records what it did in the CHANGELOG.

---

*Born from complexity. Engineered for certainty.*
